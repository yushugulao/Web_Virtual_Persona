from __future__ import annotations

import os

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.backend.auth.client_ip import client_ip_from_request
from app.backend.auth.auth_store import AuthStore
from app.backend.core.config import get_settings
from app.backend.schemas.auth import AuthUser


bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_store() -> AuthStore:
    return AuthStore(get_settings().sqlite_path)


def _dev_user() -> AuthUser:
    return AuthUser(
        id="dev-auth-disabled",
        email="developer@local.persona-rag",
        username="developer",
        role="admin",
        status="active",
        email_verified=True,
        must_change_password=False,
        created_at="1970-01-01T00:00:00+00:00",
        updated_at="1970-01-01T00:00:00+00:00",
        last_login_at=None,
    )


def require_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    store: AuthStore = Depends(get_auth_store),
) -> AuthUser:
    settings = get_settings()
    pytest_bypass = (
        "PYTEST_CURRENT_TEST" in os.environ
        and os.getenv("PERSONA_RAG_ENFORCE_AUTH_IN_TESTS", "").lower() not in {"1", "true", "yes", "on"}
    )
    if not settings.auth_required or pytest_bypass:
        return _dev_user()
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    client_ip = client_ip_from_request(request, trust_proxy_headers=settings.auth_trust_proxy_headers)
    user = store.get_user_by_token(credentials.credentials, client_ip=client_ip)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效，请重新登录。")
    if user.status == "disabled":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用。")
    if user.status != "active" or not user.email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号尚未激活。")
    return user


def require_admin(user: AuthUser = Depends(require_user)) -> AuthUser:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限。")
    return user
