from __future__ import annotations

from dataclasses import dataclass

from app.backend.schemas.auth import AuthUser


DEV_USER_ID = "dev-auth-disabled"


@dataclass(frozen=True)
class RuntimeUserContext:
    user_id: str
    username: str = "developer"
    role: str = "admin"

    @classmethod
    def dev(cls) -> "RuntimeUserContext":
        return cls(user_id=DEV_USER_ID)

    @classmethod
    def from_auth_user(cls, user: AuthUser) -> "RuntimeUserContext":
        return cls(user_id=user.id, username=user.username, role=user.role)
