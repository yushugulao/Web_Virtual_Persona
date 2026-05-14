from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials

from app.backend.auth.auth_store import AuthChallengeFailed, AuthStore, LoginIpLimitExceeded
from app.backend.auth.client_ip import client_ip_from_request
from app.backend.auth.dependencies import bearer_scheme, get_auth_store, require_user
from app.backend.auth.email import EmailConfigurationError, send_verification_email
from app.backend.core.config import get_settings
from app.backend.schemas.auth import (
    AuthChallengePurpose,
    AuthChallengeResponse,
    AuthUser,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    RegisterRequest,
    ResendVerificationRequest,
    ThemePreferenceRequest,
    ThemePreferenceResponse,
    VerifyEmailRequest,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def _validate_email(email: str) -> str:
    normalized = email.strip().lower()
    if "@" not in normalized or "." not in normalized.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="邮箱格式不正确。")
    return normalized


def _request_ip(request: Request) -> str:
    settings = get_settings()
    return client_ip_from_request(request, trust_proxy_headers=settings.auth_trust_proxy_headers)


def _verify_auth_challenge(
    payload: RegisterRequest | LoginRequest | ResendVerificationRequest,
    *,
    purpose: AuthChallengePurpose,
    request: Request,
    store: AuthStore,
) -> None:
    settings = get_settings()
    if not settings.auth_challenge_required:
        return
    if (payload.website or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="人机校验失败，请刷新后重试。")
    try:
        store.verify_challenge(
            purpose=purpose,
            challenge_id=payload.challenge_id,
            nonce=payload.challenge_nonce,
            counter=payload.challenge_counter,
            answer=payload.challenge_answer,
            client_ip=_request_ip(request),
            min_elapsed_ms=settings.auth_challenge_min_elapsed_ms,
        )
    except AuthChallengeFailed as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="人机校验失败，请刷新后重试。") from exc


@router.get("/challenge", response_model=AuthChallengeResponse)
def auth_challenge(
    request: Request,
    purpose: AuthChallengePurpose = "login",
    store: AuthStore = Depends(get_auth_store),
) -> AuthChallengeResponse:
    settings = get_settings()
    challenge = store.create_challenge(
        purpose=purpose,
        client_ip=_request_ip(request),
        user_agent=request.headers.get("user-agent", ""),
        difficulty=settings.auth_challenge_difficulty,
        ttl_seconds=settings.auth_challenge_ttl_seconds,
        min_elapsed_ms=settings.auth_challenge_min_elapsed_ms,
        mode=settings.auth_challenge_mode,
    )
    return AuthChallengeResponse(
        challenge_id=challenge.challenge_id,
        purpose=purpose,
        nonce=challenge.nonce,
        algorithm=challenge.algorithm,
        difficulty=challenge.difficulty,
        issued_at=challenge.issued_at,
        expires_at=challenge.expires_at,
        min_elapsed_ms=challenge.min_elapsed_ms,
        prompt="按住滑块拖动，松开后自动校验。",
        slider_track_width=challenge.slider_track_width,
        slider_piece_size=challenge.slider_piece_size,
        slider_target_x=challenge.slider_target_x,
        slider_target_y=challenge.slider_target_y,
        slider_tolerance=challenge.slider_tolerance,
        slider_image_url=challenge.slider_image_url,
        slider_image_label=challenge.slider_image_label,
        slider_decoys=challenge.slider_decoys or [],
    )


@router.get("/theme-preference", response_model=ThemePreferenceResponse)
def theme_preference(
    request: Request,
    store: AuthStore = Depends(get_auth_store),
) -> ThemePreferenceResponse:
    theme, source = store.theme_for_ip(_request_ip(request))
    return ThemePreferenceResponse(theme=theme, source=source)


@router.post("/register", response_model=MessageResponse)
def register(
    payload: RegisterRequest,
    request: Request,
    store: AuthStore = Depends(get_auth_store),
) -> MessageResponse:
    settings = get_settings()
    _verify_auth_challenge(payload, purpose="register", request=request, store=store)
    email = _validate_email(payload.email)
    try:
        user = store.create_user(
            email=email,
            username=payload.username,
            password=payload.password,
            role="user",
            status="pending_verification",
            email_verified=False,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邮箱或用户名已存在。") from exc
    code = store.create_email_code(
        user.id,
        purpose="register",
        ttl_minutes=settings.email_verification_ttl_minutes,
    )
    try:
        send_verification_email(settings, user.email, code)
    except EmailConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"验证码邮件发送失败：{exc}") from exc
    return MessageResponse(message="验证码已发送，请查收邮箱并完成激活。")


@router.post("/verify-email", response_model=AuthUser)
def verify_email(payload: VerifyEmailRequest, store: AuthStore = Depends(get_auth_store)) -> AuthUser:
    user = store.verify_email_code(email=_validate_email(payload.email), code=payload.code, purpose="register")
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误、已过期或已使用。")
    return user


@router.post("/resend-verification", response_model=MessageResponse)
def resend_verification(
    payload: ResendVerificationRequest,
    request: Request,
    store: AuthStore = Depends(get_auth_store),
) -> MessageResponse:
    settings = get_settings()
    _verify_auth_challenge(payload, purpose="resend_verification", request=request, store=store)
    user = store.get_user_by_login(_validate_email(payload.email))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在。")
    if user.email_verified and user.status == "active":
        return MessageResponse(message="账号已经激活，可以直接登录。")
    code = store.create_email_code(
        user.id,
        purpose="register",
        ttl_minutes=settings.email_verification_ttl_minutes,
    )
    try:
        send_verification_email(settings, user.email, code)
    except EmailConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"验证码邮件发送失败：{exc}") from exc
    return MessageResponse(message="新的验证码已发送。")


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    store: AuthStore = Depends(get_auth_store),
) -> LoginResponse:
    settings = get_settings()
    _verify_auth_challenge(payload, purpose="login", request=request, store=store)
    user = store.authenticate(payload.login, payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误。")
    if user.status == "disabled":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用。")
    if user.status != "active" or not user.email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号尚未通过邮箱验证。")
    client_ip = _request_ip(request)
    user_agent = request.headers.get("user-agent", "")
    try:
        session = store.create_session(
            user.id,
            ttl_hours=settings.auth_token_ttl_hours,
            client_ip=client_ip,
            user_agent=user_agent,
            max_active_login_ips=settings.auth_max_active_login_ips,
        )
    except LoginIpLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="当前登录 IP 数已达上限，请稍后再试或联系管理员。",
        ) from exc
    return LoginResponse(token=session.token, expires_at=session.expires_at, user=session.user)


@router.put("/theme-preference", response_model=ThemePreferenceResponse)
def update_theme_preference(
    payload: ThemePreferenceRequest,
    request: Request,
    store: AuthStore = Depends(get_auth_store),
    user: AuthUser = Depends(require_user),
) -> ThemePreferenceResponse:
    updated_user = store.update_theme_preference(user.id, payload.theme, client_ip=_request_ip(request))
    return ThemePreferenceResponse(theme=updated_user.theme_preference, source="user")


@router.post("/logout", response_model=MessageResponse)
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    store: AuthStore = Depends(get_auth_store),
    _user: AuthUser = Depends(require_user),
) -> MessageResponse:
    if credentials is not None and credentials.credentials:
        store.revoke_token(credentials.credentials)
    return MessageResponse(message="已退出登录。")


@router.get("/me", response_model=AuthUser)
def me(user: AuthUser = Depends(require_user)) -> AuthUser:
    return user
