from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from app.backend.auth.auth_store import AuthStore
from app.backend.auth.dependencies import get_auth_store, require_admin
from app.backend.auth.email import EmailConfigurationError, send_verification_email
from app.backend.core.config import get_settings
from app.backend.schemas.auth import (
    AdminCreateUserRequest,
    AdminResetPasswordRequest,
    AdminUpdateUserRequest,
    AdminUsersResponse,
    AuthUser,
    MessageResponse,
)


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=AdminUsersResponse)
def list_users(
    _admin: AuthUser = Depends(require_admin),
    store: AuthStore = Depends(get_auth_store),
) -> AdminUsersResponse:
    return AdminUsersResponse(users=store.list_users())


@router.post("/users", response_model=AuthUser)
def create_user(
    payload: AdminCreateUserRequest,
    admin: AuthUser = Depends(require_admin),
    store: AuthStore = Depends(get_auth_store),
) -> AuthUser:
    try:
        user = store.create_user(
            email=payload.email,
            username=payload.username,
            password=payload.password,
            role=payload.role,
            status=payload.status,
            email_verified=payload.email_verified,
            must_change_password=payload.must_change_password,
            actor_user_id=admin.id,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邮箱或用户名已存在。") from exc
    if payload.send_verification:
        settings = get_settings()
        code = store.create_email_code(
            user.id,
            purpose="register",
            ttl_minutes=settings.email_verification_ttl_minutes,
        )
        try:
            send_verification_email(settings, user.email, code)
        except (EmailConfigurationError, OSError) as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"用户已创建，但邮件发送失败：{exc}") from exc
    return user


@router.patch("/users/{user_id}", response_model=AuthUser)
def update_user(
    user_id: str,
    payload: AdminUpdateUserRequest,
    admin: AuthUser = Depends(require_admin),
    store: AuthStore = Depends(get_auth_store),
) -> AuthUser:
    try:
        return store.update_user(
            user_id,
            payload.model_dump(exclude_unset=True),
            actor_user_id=admin.id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。") from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邮箱或用户名已存在。") from exc


@router.post("/users/{user_id}/disable", response_model=AuthUser)
def disable_user(
    user_id: str,
    admin: AuthUser = Depends(require_admin),
    store: AuthStore = Depends(get_auth_store),
) -> AuthUser:
    try:
        return store.set_user_status(user_id, "disabled", actor_user_id=admin.id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。") from exc


@router.post("/users/{user_id}/enable", response_model=AuthUser)
def enable_user(
    user_id: str,
    admin: AuthUser = Depends(require_admin),
    store: AuthStore = Depends(get_auth_store),
) -> AuthUser:
    try:
        return store.set_user_status(user_id, "active", actor_user_id=admin.id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。") from exc


@router.delete("/users/{user_id}", response_model=MessageResponse)
def delete_user(
    user_id: str,
    admin: AuthUser = Depends(require_admin),
    store: AuthStore = Depends(get_auth_store),
) -> MessageResponse:
    try:
        store.delete_user(user_id, actor_user_id=admin.id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。") from exc
    except ValueError as exc:
        if str(exc) == "cannot_delete_self":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="管理员不能删除自己的账号。",
            ) from exc
        if str(exc) == "cannot_delete_last_admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="至少需要保留一个已激活的管理员账号。",
            ) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户删除失败。") from exc
    return MessageResponse(message="用户已删除。")


@router.post("/users/{user_id}/reset-password", response_model=AuthUser)
def reset_password(
    user_id: str,
    payload: AdminResetPasswordRequest,
    admin: AuthUser = Depends(require_admin),
    store: AuthStore = Depends(get_auth_store),
) -> AuthUser:
    try:
        return store.reset_password(
            user_id,
            payload.password,
            must_change_password=payload.must_change_password,
            actor_user_id=admin.id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。") from exc


@router.post("/users/{user_id}/resend-verification", response_model=MessageResponse)
def resend_user_verification(
    user_id: str,
    _admin: AuthUser = Depends(require_admin),
    store: AuthStore = Depends(get_auth_store),
) -> MessageResponse:
    user = store.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。")
    if user.email_verified and user.status == "active":
        return MessageResponse(message="账号已经激活。")
    settings = get_settings()
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
    return MessageResponse(message="验证码已重新发送。")
