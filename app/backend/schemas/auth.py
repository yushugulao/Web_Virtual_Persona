from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


UserRole = Literal["admin", "user"]
UserStatus = Literal["pending_verification", "active", "disabled"]
AuthChallengePurpose = Literal["register", "login", "resend_verification"]
UiThemePreference = Literal["black_gray", "klee_bomb"]


class AuthUser(BaseModel):
    id: str
    email: str
    username: str
    role: UserRole
    status: UserStatus
    email_verified: bool
    must_change_password: bool = False
    created_at: str
    updated_at: str
    last_login_at: str | None = None
    theme_preference: UiThemePreference = "black_gray"


class RegisterRequest(BaseModel):
    email: str
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    challenge_id: str | None = None
    challenge_nonce: str | None = None
    challenge_counter: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991)
    challenge_answer: int | None = Field(default=None, ge=0, le=10_000)
    challenge_elapsed_ms: int | None = Field(default=None, ge=0, le=600_000)
    website: str | None = Field(default=None, max_length=256)


class VerifyEmailRequest(BaseModel):
    email: str
    code: str = Field(min_length=6, max_length=6)


class ResendVerificationRequest(BaseModel):
    email: str
    challenge_id: str | None = None
    challenge_nonce: str | None = None
    challenge_counter: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991)
    challenge_answer: int | None = Field(default=None, ge=0, le=10_000)
    challenge_elapsed_ms: int | None = Field(default=None, ge=0, le=600_000)
    website: str | None = Field(default=None, max_length=256)


class LoginRequest(BaseModel):
    login: str
    password: str
    challenge_id: str | None = None
    challenge_nonce: str | None = None
    challenge_counter: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991)
    challenge_answer: int | None = Field(default=None, ge=0, le=10_000)
    challenge_elapsed_ms: int | None = Field(default=None, ge=0, le=600_000)
    website: str | None = Field(default=None, max_length=256)


class AuthChallengeResponse(BaseModel):
    challenge_id: str
    purpose: AuthChallengePurpose
    nonce: str
    algorithm: str = "slider-puzzle-v1"
    difficulty: int
    issued_at: str
    expires_at: str
    min_elapsed_ms: int
    prompt: str
    slider_track_width: int | None = None
    slider_piece_size: int | None = None
    slider_target_x: int | None = None
    slider_target_y: int | None = None
    slider_tolerance: int | None = None
    slider_image_url: str | None = None
    slider_image_label: str | None = None
    slider_decoys: list[dict[str, int]] = Field(default_factory=list)


class LoginResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_at: str
    user: AuthUser


class MessageResponse(BaseModel):
    message: str


class ThemePreferenceRequest(BaseModel):
    theme: UiThemePreference


class ThemePreferenceResponse(BaseModel):
    theme: UiThemePreference
    source: Literal["default", "ip_user", "user"] = "default"


class AdminCreateUserRequest(BaseModel):
    email: str
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = "user"
    status: UserStatus = "active"
    email_verified: bool = True
    send_verification: bool = False
    must_change_password: bool = False


class AdminUpdateUserRequest(BaseModel):
    email: str | None = None
    username: str | None = Field(default=None, min_length=2, max_length=64)
    role: UserRole | None = None
    status: UserStatus | None = None
    email_verified: bool | None = None
    must_change_password: bool | None = None


class AdminResetPasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=128)
    must_change_password: bool = True


class AdminUsersResponse(BaseModel):
    users: list[AuthUser]
