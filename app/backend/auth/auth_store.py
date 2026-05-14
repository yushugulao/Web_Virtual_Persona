from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator

from app.backend.auth.passwords import (
    hash_password,
    hash_token,
    hash_verification_code,
    new_token,
    new_verification_code,
    verify_password,
)
from app.backend.schemas.auth import AuthUser, UserRole, UserStatus

DEFAULT_UI_THEME = "black_gray"
VALID_UI_THEMES = {"black_gray", "klee_bomb"}
MAX_THEME_IPS_PER_USER = 10


AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
  status TEXT NOT NULL CHECK(status IN ('pending_verification', 'active', 'disabled')),
  email_verified INTEGER NOT NULL DEFAULT 0,
  must_change_password INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_login_at TEXT,
  theme_preference TEXT NOT NULL DEFAULT 'black_gray'
);

CREATE TABLE IF NOT EXISTS auth_sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  client_ip TEXT,
  user_agent TEXT,
  last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS auth_email_codes (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
  purpose TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT
);

CREATE TABLE IF NOT EXISTS auth_audit_events (
  id TEXT PRIMARY KEY,
  actor_user_id TEXT,
  target_user_id TEXT,
  action TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_challenges (
  id TEXT PRIMARY KEY,
  purpose TEXT NOT NULL,
  nonce TEXT NOT NULL,
  algorithm TEXT NOT NULL DEFAULT 'sha256-prefix-zero',
  difficulty INTEGER NOT NULL,
  slider_target_x INTEGER,
  slider_target_y INTEGER,
  slider_tolerance INTEGER,
  slider_track_width INTEGER,
  slider_piece_size INTEGER,
  slider_image_url TEXT,
  slider_image_label TEXT,
  slider_decoys_json TEXT,
  client_ip TEXT NOT NULL,
  user_agent TEXT,
  issued_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT
);

CREATE TABLE IF NOT EXISTS auth_user_theme_ips (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
  client_ip TEXT NOT NULL,
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE(user_id, client_ip)
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_token_hash ON auth_sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_codes_user_purpose ON auth_email_codes(user_id, purpose, expires_at);
CREATE INDEX IF NOT EXISTS idx_auth_challenges_purpose ON auth_challenges(purpose, expires_at, used_at);
CREATE INDEX IF NOT EXISTS idx_auth_user_theme_ips_ip ON auth_user_theme_ips(client_ip, last_seen_at);
CREATE INDEX IF NOT EXISTS idx_auth_user_theme_ips_user ON auth_user_theme_ips(user_id, last_seen_at);
"""


@dataclass(slots=True)
class SessionToken:
    token: str
    expires_at: str
    user: AuthUser


@dataclass(slots=True)
class AuthChallenge:
    challenge_id: str
    purpose: str
    nonce: str
    difficulty: int
    issued_at: str
    expires_at: str
    min_elapsed_ms: int
    algorithm: str = "sha256-prefix-zero"
    slider_target_x: int | None = None
    slider_target_y: int | None = None
    slider_tolerance: int | None = None
    slider_track_width: int | None = None
    slider_piece_size: int | None = None
    slider_image_url: str | None = None
    slider_image_label: str | None = None
    slider_decoys: list[dict[str, int]] | None = None


SLIDER_PUZZLE_IMAGES: tuple[tuple[str, str], ...] = (
    ("/auth_captcha/notebook-paper.jpg", "纹理照片 01"),
    ("/auth_captcha/city-alley.jpg", "纹理照片 02"),
    ("/auth_captcha/forest-path.jpg", "纹理照片 03"),
    ("/auth_captcha/market-texture.jpg", "纹理照片 04"),
    ("/auth_captcha/books-shelf.jpg", "纹理照片 05"),
    ("/auth_captcha/mountain-river.jpg", "纹理照片 06"),
)


class LoginIpLimitExceeded(ValueError):
    pass


class AuthChallengeFailed(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat()


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _normalize_username(username: str) -> str:
    return username.strip()


def _row_to_user(row: sqlite3.Row) -> AuthUser:
    theme_preference = row["theme_preference"] if "theme_preference" in row.keys() else DEFAULT_UI_THEME
    if theme_preference not in VALID_UI_THEMES:
        theme_preference = DEFAULT_UI_THEME
    return AuthUser(
        id=row["id"],
        email=row["email"],
        username=row["username"],
        role=row["role"],
        status=row["status"],
        email_verified=bool(row["email_verified"]),
        must_change_password=bool(row["must_change_password"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_login_at=row["last_login_at"],
        theme_preference=theme_preference,
    )


def _slider_decoy_positions(
    *,
    target_x: int,
    target_y: int,
    min_x: int,
    max_x: int,
    min_y: int,
    max_y: int,
    piece_size: int,
) -> list[dict[str, int]]:
    decoys: list[dict[str, int]] = []
    attempts = 0
    while len(decoys) < 2 and attempts < 80:
        attempts += 1
        x = secrets.randbelow(max_x - min_x + 1) + min_x
        y = secrets.randbelow(max_y - min_y + 1) + min_y
        if abs(x - target_x) < piece_size + 14 and abs(y - target_y) < piece_size:
            continue
        if any(abs(x - decoy["x"]) < piece_size and abs(y - decoy["y"]) < piece_size for decoy in decoys):
            continue
        decoys.append({"x": x, "y": y})
    fallback_candidates = [
        {"x": min_x, "y": max_y},
        {"x": max_x, "y": min_y},
    ]
    for candidate in fallback_candidates:
        if len(decoys) >= 2:
            break
        if abs(candidate["x"] - target_x) >= piece_size or abs(candidate["y"] - target_y) >= piece_size // 2:
            decoys.append(candidate)
    return decoys[:2]


class AuthStore:
    def __init__(self, sqlite_path: str | Path):
        self.sqlite_path = Path(sqlite_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.sqlite_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(AUTH_SCHEMA)
            self._ensure_auth_user_theme_columns(connection)
            self._ensure_auth_user_theme_ip_table(connection)
            self._ensure_auth_session_security_columns(connection)
            self._ensure_auth_challenge_columns(connection)

    def bootstrap_admin(self, *, username: str, email: str, password: str) -> AuthUser:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM auth_users WHERE role = 'admin' LIMIT 1").fetchone()
            if row is not None:
                return _row_to_user(row)
            now = _iso()
            user_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO auth_users (
                  id, email, username, password_hash, role, status, email_verified,
                  must_change_password, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 'admin', 'active', 1, 1, ?, ?)
                """,
                (
                    user_id,
                    _normalize_email(email),
                    _normalize_username(username),
                    hash_password(password),
                    now,
                    now,
                ),
            )
            self._audit(connection, None, user_id, "bootstrap_admin", "initial local administrator")
            row = connection.execute("SELECT * FROM auth_users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise RuntimeError("管理员账号初始化失败")
            return _row_to_user(row)

    def create_user(
        self,
        *,
        email: str,
        username: str,
        password: str,
        role: UserRole = "user",
        status: UserStatus = "pending_verification",
        email_verified: bool = False,
        must_change_password: bool = False,
        actor_user_id: str | None = None,
    ) -> AuthUser:
        self.initialize()
        user_id = str(uuid.uuid4())
        now = _iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO auth_users (
                  id, email, username, password_hash, role, status, email_verified,
                  must_change_password, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    _normalize_email(email),
                    _normalize_username(username),
                    hash_password(password),
                    role,
                    status,
                    int(email_verified),
                    int(must_change_password),
                    now,
                    now,
                ),
            )
            self._audit(connection, actor_user_id, user_id, "create_user", f"role={role}; status={status}")
        user = self.get_user_by_id(user_id)
        if user is None:
            raise RuntimeError("用户创建后读取失败")
        return user

    def get_user_by_id(self, user_id: str) -> AuthUser | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM auth_users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row) if row else None

    def get_user_by_login(self, login: str) -> AuthUser | None:
        normalized = login.strip().lower()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM auth_users WHERE lower(email) = ? OR lower(username) = ?",
                (normalized, normalized),
            ).fetchone()
        return _row_to_user(row) if row else None

    def list_users(self) -> list[AuthUser]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM auth_users ORDER BY created_at DESC").fetchall()
        return [_row_to_user(row) for row in rows]

    def delete_user(self, user_id: str, *, actor_user_id: str | None = None) -> None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM auth_users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise KeyError(user_id)
            if actor_user_id == user_id:
                raise ValueError("cannot_delete_self")
            if row["role"] == "admin":
                admin_count = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM auth_users
                    WHERE role = 'admin' AND status = 'active' AND email_verified = 1
                    """
                ).fetchone()["count"]
                if int(admin_count) <= 1:
                    raise ValueError("cannot_delete_last_admin")
            detail = f"email={row['email']}; username={row['username']}; role={row['role']}; status={row['status']}"
            self._audit(connection, actor_user_id, user_id, "delete_user", detail)
            self._delete_owned_project_data(connection, user_id)
            connection.execute("DELETE FROM auth_users WHERE id = ?", (user_id,))

    def authenticate(self, login: str, password: str) -> AuthUser | None:
        normalized = login.strip().lower()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM auth_users WHERE lower(email) = ? OR lower(username) = ?",
                (normalized, normalized),
            ).fetchone()
            if row is None or not verify_password(password, row["password_hash"]):
                return None
            user = _row_to_user(row)
            if user.status != "active" or not user.email_verified:
                return user
            now = _iso()
            connection.execute("UPDATE auth_users SET last_login_at = ?, updated_at = ? WHERE id = ?", (now, now, user.id))
        return self.get_user_by_id(user.id)

    def create_session(
        self,
        user_id: str,
        *,
        ttl_hours: float,
        client_ip: str | None = None,
        user_agent: str | None = None,
        max_active_login_ips: int = 3,
    ) -> SessionToken:
        token = new_token()
        expires_at_dt = _now() + timedelta(hours=ttl_hours)
        now = _iso()
        clean_client_ip = (client_ip or "unknown").strip() or "unknown"
        clean_user_agent = (user_agent or "").strip()[:512] or None
        with self._connect() as connection:
            self._revoke_same_user_other_ip_sessions(connection, user_id, clean_client_ip, now)
            if not self._active_ip_has_capacity(connection, clean_client_ip, max_active_login_ips, now):
                self._audit(
                    connection,
                    user_id,
                    user_id,
                    "login_ip_limit_rejected",
                    f"client_ip={clean_client_ip}; max_active_login_ips={max_active_login_ips}",
                )
                raise LoginIpLimitExceeded(clean_client_ip)
            connection.execute(
                """
                INSERT INTO auth_sessions (
                  id, user_id, token_hash, created_at, expires_at, revoked_at,
                  client_ip, user_agent, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    user_id,
                    hash_token(token),
                    now,
                    _iso(expires_at_dt),
                    clean_client_ip,
                    clean_user_agent,
                    now,
                ),
            )
            self._bind_theme_ip(connection, user_id=user_id, client_ip=clean_client_ip, now=now)
            self._audit(connection, user_id, user_id, "login_session_created", f"client_ip={clean_client_ip}")
        user = self.get_user_by_id(user_id)
        if user is None:
            raise RuntimeError("创建会话后用户不存在")
        return SessionToken(token=token, expires_at=_iso(expires_at_dt), user=user)

    def theme_for_ip(self, client_ip: str | None) -> tuple[str, str]:
        self.initialize()
        clean_client_ip = (client_ip or "").strip()
        if not clean_client_ip:
            return DEFAULT_UI_THEME, "default"
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT u.theme_preference
                FROM auth_user_theme_ips ip
                JOIN auth_users u ON u.id = ip.user_id
                WHERE ip.client_ip = ?
                  AND u.status = 'active'
                ORDER BY ip.last_seen_at DESC, ip.created_at DESC
                LIMIT 1
                """,
                (clean_client_ip,),
            ).fetchone()
        if row is None:
            return DEFAULT_UI_THEME, "default"
        theme = row["theme_preference"]
        return (theme if theme in VALID_UI_THEMES else DEFAULT_UI_THEME), "ip_user"

    def update_theme_preference(
        self,
        user_id: str,
        theme: str,
        *,
        client_ip: str | None = None,
    ) -> AuthUser:
        self.initialize()
        if theme not in VALID_UI_THEMES:
            raise ValueError("invalid_theme")
        now = _iso()
        clean_client_ip = (client_ip or "").strip()
        with self._connect() as connection:
            connection.execute(
                "UPDATE auth_users SET theme_preference = ?, updated_at = ? WHERE id = ?",
                (theme, now, user_id),
            )
            if clean_client_ip:
                self._bind_theme_ip(connection, user_id=user_id, client_ip=clean_client_ip, now=now)
            self._audit(connection, user_id, user_id, "theme_preference_updated", f"theme={theme}")
        user = self.get_user_by_id(user_id)
        if user is None:
            raise KeyError(user_id)
        return user

    def create_challenge(
        self,
        *,
        purpose: str,
        client_ip: str,
        user_agent: str | None,
        difficulty: int,
        ttl_seconds: int,
        min_elapsed_ms: int,
        mode: str = "slider",
    ) -> AuthChallenge:
        self.initialize()
        now_dt = _now()
        expires_at_dt = now_dt + timedelta(seconds=ttl_seconds)
        algorithm = "sha256-prefix-zero" if mode == "pow" else "slider-puzzle-v1"
        track_width = 320
        stage_height = 150
        piece_size = 46
        tolerance = 8
        min_target = piece_size + 18
        max_target = track_width - piece_size - 18
        min_target_y = 18
        max_target_y = stage_height - piece_size - 18
        slider_target_x = (
            secrets.randbelow(max_target - min_target + 1) + min_target
            if algorithm == "slider-puzzle-v1"
            else None
        )
        slider_target_y = (
            secrets.randbelow(max_target_y - min_target_y + 1) + min_target_y
            if algorithm == "slider-puzzle-v1"
            else None
        )
        slider_image_url: str | None = None
        slider_image_label: str | None = None
        if algorithm == "slider-puzzle-v1":
            slider_image_url, slider_image_label = secrets.choice(SLIDER_PUZZLE_IMAGES)
        slider_decoys = (
            _slider_decoy_positions(
                target_x=slider_target_x,
                target_y=slider_target_y,
                min_x=min_target,
                max_x=max_target,
                min_y=min_target_y,
                max_y=max_target_y,
                piece_size=piece_size,
            )
            if algorithm == "slider-puzzle-v1" and slider_target_x is not None and slider_target_y is not None
            else []
        )
        challenge = AuthChallenge(
            challenge_id=uuid.uuid4().hex,
            purpose=purpose,
            nonce=secrets.token_urlsafe(24),
            difficulty=max(1, min(difficulty, 6)),
            issued_at=_iso(now_dt),
            expires_at=_iso(expires_at_dt),
            min_elapsed_ms=max(0, min_elapsed_ms),
            algorithm=algorithm,
            slider_target_x=slider_target_x,
            slider_target_y=slider_target_y,
            slider_tolerance=tolerance if algorithm == "slider-puzzle-v1" else None,
            slider_track_width=track_width if algorithm == "slider-puzzle-v1" else None,
            slider_piece_size=piece_size if algorithm == "slider-puzzle-v1" else None,
            slider_image_url=slider_image_url,
            slider_image_label=slider_image_label,
            slider_decoys=slider_decoys,
        )
        clean_user_agent = (user_agent or "").strip()[:512] or None
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO auth_challenges (
                  id, purpose, nonce, algorithm, difficulty,
                  slider_target_x, slider_target_y, slider_tolerance,
                  slider_track_width, slider_piece_size, slider_image_url, slider_image_label,
                  slider_decoys_json,
                  client_ip, user_agent, issued_at, expires_at, used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    challenge.challenge_id,
                    challenge.purpose,
                    challenge.nonce,
                    challenge.algorithm,
                    challenge.difficulty,
                    challenge.slider_target_x,
                    challenge.slider_target_y,
                    challenge.slider_tolerance,
                    challenge.slider_track_width,
                    challenge.slider_piece_size,
                    challenge.slider_image_url,
                    challenge.slider_image_label,
                    json.dumps(challenge.slider_decoys or [], ensure_ascii=False),
                    client_ip,
                    clean_user_agent,
                    challenge.issued_at,
                    challenge.expires_at,
                ),
            )
            connection.execute(
                """
                DELETE FROM auth_challenges
                WHERE expires_at <= ? OR used_at IS NOT NULL
                """,
                (_iso(now_dt - timedelta(minutes=5)),),
            )
        return challenge

    def verify_challenge(
        self,
        *,
        purpose: str,
        challenge_id: str | None,
        nonce: str | None,
        counter: int | None,
        answer: int | None,
        client_ip: str,
        min_elapsed_ms: int,
    ) -> None:
        if not challenge_id or not nonce:
            raise AuthChallengeFailed("missing_challenge")
        now_dt = _now()
        now = _iso(now_dt)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM auth_challenges
                WHERE id = ?
                  AND purpose = ?
                  AND used_at IS NULL
                  AND expires_at > ?
                """,
                (challenge_id, purpose, now),
            ).fetchone()
            if row is None:
                self._audit(connection, None, None, "auth_challenge_failed", f"purpose={purpose}; reason=missing_or_used")
                raise AuthChallengeFailed("missing_or_used")
            if row["nonce"] != nonce:
                self._audit(connection, None, None, "auth_challenge_failed", f"purpose={purpose}; reason=nonce_mismatch")
                raise AuthChallengeFailed("nonce_mismatch")
            if row["client_ip"] != client_ip:
                self._audit(connection, None, None, "auth_challenge_failed", f"purpose={purpose}; reason=ip_mismatch")
                raise AuthChallengeFailed("ip_mismatch")
            issued_at = datetime.fromisoformat(row["issued_at"])
            observed_elapsed_ms = int((now_dt - issued_at).total_seconds() * 1000)
            if observed_elapsed_ms < max(0, min_elapsed_ms):
                self._audit(
                    connection,
                    None,
                    None,
                    "auth_challenge_failed",
                    f"purpose={purpose}; reason=too_fast; elapsed_ms={observed_elapsed_ms}",
                )
                raise AuthChallengeFailed("too_fast")
            algorithm = row["algorithm"] or "sha256-prefix-zero"
            if algorithm == "slider-puzzle-v1":
                target_x = row["slider_target_x"]
                tolerance = int(row["slider_tolerance"] or 8)
                if target_x is None or answer is None:
                    self._audit(connection, None, None, "auth_challenge_failed", f"purpose={purpose}; reason=missing_slider_answer")
                    raise AuthChallengeFailed("missing_slider_answer")
                if abs(int(answer) - int(target_x)) > tolerance:
                    self._audit(connection, None, None, "auth_challenge_failed", f"purpose={purpose}; reason=bad_slider_answer")
                    raise AuthChallengeFailed("bad_slider_answer")
            else:
                if counter is None:
                    raise AuthChallengeFailed("missing_pow_counter")
                digest = hashlib.sha256(f"{challenge_id}:{nonce}:{counter}".encode("utf-8")).hexdigest()
                if not digest.startswith("0" * int(row["difficulty"])):
                    self._audit(connection, None, None, "auth_challenge_failed", f"purpose={purpose}; reason=bad_pow")
                    raise AuthChallengeFailed("bad_pow")
            connection.execute("UPDATE auth_challenges SET used_at = ? WHERE id = ?", (now, challenge_id))
            self._audit(connection, None, None, "auth_challenge_verified", f"purpose={purpose}; client_ip={client_ip}")

    def get_user_by_token(self, token: str, *, client_ip: str | None = None) -> AuthUser | None:
        token_digest = hash_token(token)
        clean_client_ip = (client_ip or "").strip()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                  u.*,
                  s.id AS session_id,
                  s.client_ip AS session_client_ip
                FROM auth_sessions s
                JOIN auth_users u ON u.id = s.user_id
                WHERE s.token_hash = ?
                  AND s.revoked_at IS NULL
                  AND s.expires_at > ?
                """,
                (token_digest, _iso()),
            ).fetchone()
            if row is None:
                return None
            session_id = row["session_id"]
            session_client_ip = (row["session_client_ip"] or "").strip()
            now = _iso()
            if clean_client_ip:
                if session_client_ip and session_client_ip != clean_client_ip:
                    connection.execute(
                        "UPDATE auth_sessions SET revoked_at = ?, last_seen_at = ? WHERE id = ? AND revoked_at IS NULL",
                        (now, now, session_id),
                    )
                    self._audit(
                        connection,
                        row["id"],
                        row["id"],
                        "session_ip_mismatch_revoked",
                        f"expected={session_client_ip}; observed={clean_client_ip}",
                    )
                    return None
                if not session_client_ip:
                    connection.execute(
                        "UPDATE auth_sessions SET client_ip = ?, last_seen_at = ? WHERE id = ?",
                        (clean_client_ip, now, session_id),
                    )
                else:
                    connection.execute("UPDATE auth_sessions SET last_seen_at = ? WHERE id = ?", (now, session_id))
            else:
                connection.execute("UPDATE auth_sessions SET last_seen_at = ? WHERE id = ?", (now, session_id))
        return _row_to_user(row) if row else None

    def revoke_token(self, token: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (_iso(), hash_token(token)),
            )

    def create_email_code(self, user_id: str, *, purpose: str, ttl_minutes: int) -> str:
        code = new_verification_code()
        now_dt = _now()
        expires_at = now_dt + timedelta(minutes=ttl_minutes)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE auth_email_codes
                SET used_at = ?
                WHERE user_id = ? AND purpose = ? AND used_at IS NULL
                """,
                (_iso(now_dt), user_id, purpose),
            )
            connection.execute(
                """
                INSERT INTO auth_email_codes (id, user_id, purpose, code_hash, created_at, expires_at, used_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    str(uuid.uuid4()),
                    user_id,
                    purpose,
                    hash_verification_code(user_id, code),
                    _iso(now_dt),
                    _iso(expires_at),
                ),
            )
            self._audit(connection, None, user_id, f"create_{purpose}_code", "email verification")
        return code

    def verify_email_code(self, *, email: str, code: str, purpose: str = "register") -> AuthUser | None:
        user = self.get_user_by_login(email)
        if user is None:
            return None
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM auth_email_codes
                WHERE user_id = ?
                  AND purpose = ?
                  AND code_hash = ?
                  AND used_at IS NULL
                  AND expires_at > ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user.id, purpose, hash_verification_code(user.id, code), _iso()),
            ).fetchone()
            if row is None:
                return None
            now = _iso()
            connection.execute("UPDATE auth_email_codes SET used_at = ? WHERE id = ?", (now, row["id"]))
            connection.execute(
                """
                UPDATE auth_users
                SET status = 'active', email_verified = 1, updated_at = ?
                WHERE id = ?
                """,
                (now, user.id),
            )
            self._audit(connection, user.id, user.id, "verify_email", purpose)
        return self.get_user_by_id(user.id)

    def update_user(self, user_id: str, updates: dict[str, object], *, actor_user_id: str | None = None) -> AuthUser:
        allowed = {"email", "username", "role", "status", "email_verified", "must_change_password"}
        clean_updates = {key: value for key, value in updates.items() if key in allowed and value is not None}
        if not clean_updates:
            user = self.get_user_by_id(user_id)
            if user is None:
                raise KeyError(user_id)
            return user
        if "email" in clean_updates:
            clean_updates["email"] = _normalize_email(str(clean_updates["email"]))
        if "username" in clean_updates:
            clean_updates["username"] = _normalize_username(str(clean_updates["username"]))
        clean_updates["updated_at"] = _iso()
        assignments = ", ".join(f"{key} = ?" for key in clean_updates)
        values = [int(value) if isinstance(value, bool) else value for value in clean_updates.values()]
        values.append(user_id)
        with self._connect() as connection:
            cursor = connection.execute(f"UPDATE auth_users SET {assignments} WHERE id = ?", values)
            if cursor.rowcount == 0:
                raise KeyError(user_id)
            self._audit(connection, actor_user_id, user_id, "update_user", ",".join(sorted(clean_updates)))
        user = self.get_user_by_id(user_id)
        if user is None:
            raise KeyError(user_id)
        return user

    def set_user_status(self, user_id: str, status: UserStatus, *, actor_user_id: str | None = None) -> AuthUser:
        return self.update_user(user_id, {"status": status}, actor_user_id=actor_user_id)

    def reset_password(
        self,
        user_id: str,
        password: str,
        *,
        must_change_password: bool = True,
        actor_user_id: str | None = None,
    ) -> AuthUser:
        now = _iso()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE auth_users
                SET password_hash = ?, must_change_password = ?, updated_at = ?
                WHERE id = ?
                """,
                (hash_password(password), int(must_change_password), now, user_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(user_id)
            connection.execute("UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (now, user_id))
            self._audit(connection, actor_user_id, user_id, "reset_password", "sessions revoked")
        user = self.get_user_by_id(user_id)
        if user is None:
            raise KeyError(user_id)
        return user

    def _audit(
        self,
        connection: sqlite3.Connection,
        actor_user_id: str | None,
        target_user_id: str | None,
        action: str,
        detail: str | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO auth_audit_events (id, actor_user_id, target_user_id, action, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), actor_user_id, target_user_id, action, detail, _iso()),
        )

    def _ensure_auth_session_security_columns(self, connection: sqlite3.Connection) -> None:
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(auth_sessions)").fetchall()
        }
        additions = {
            "client_ip": "TEXT",
            "user_agent": "TEXT",
            "last_seen_at": "TEXT",
        }
        for column, column_type in additions.items():
            if column not in existing_columns:
                connection.execute(f"ALTER TABLE auth_sessions ADD COLUMN {column} {column_type}")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_client_ip ON auth_sessions(client_ip)")

    def _ensure_auth_user_theme_columns(self, connection: sqlite3.Connection) -> None:
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(auth_users)").fetchall()
        }
        if "theme_preference" not in existing_columns:
            connection.execute(
                "ALTER TABLE auth_users ADD COLUMN theme_preference TEXT NOT NULL DEFAULT 'black_gray'"
            )

    def _ensure_auth_user_theme_ip_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_user_theme_ips (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
              client_ip TEXT NOT NULL,
              created_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              UNIQUE(user_id, client_ip)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_user_theme_ips_ip ON auth_user_theme_ips(client_ip, last_seen_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_user_theme_ips_user ON auth_user_theme_ips(user_id, last_seen_at)"
        )

    def _ensure_auth_challenge_columns(self, connection: sqlite3.Connection) -> None:
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(auth_challenges)").fetchall()
        }
        additions = {
            "algorithm": "TEXT NOT NULL DEFAULT 'sha256-prefix-zero'",
            "slider_target_x": "INTEGER",
            "slider_target_y": "INTEGER",
            "slider_tolerance": "INTEGER",
            "slider_track_width": "INTEGER",
            "slider_piece_size": "INTEGER",
            "slider_image_url": "TEXT",
            "slider_image_label": "TEXT",
            "slider_decoys_json": "TEXT",
        }
        for column, column_type in additions.items():
            if column not in existing_columns:
                connection.execute(f"ALTER TABLE auth_challenges ADD COLUMN {column} {column_type}")

    def _revoke_same_user_other_ip_sessions(
        self,
        connection: sqlite3.Connection,
        user_id: str,
        client_ip: str,
        now: str,
    ) -> None:
        connection.execute(
            """
            UPDATE auth_sessions
            SET revoked_at = ?, last_seen_at = ?
            WHERE user_id = ?
              AND revoked_at IS NULL
              AND expires_at > ?
              AND COALESCE(client_ip, '') <> ?
            """,
            (now, now, user_id, now, client_ip),
        )

    def _bind_theme_ip(
        self,
        connection: sqlite3.Connection,
        *,
        user_id: str,
        client_ip: str,
        now: str,
    ) -> None:
        clean_client_ip = client_ip.strip()
        if not clean_client_ip or clean_client_ip == "unknown":
            return
        existing = connection.execute(
            "SELECT id, created_at FROM auth_user_theme_ips WHERE user_id = ? AND client_ip = ?",
            (user_id, clean_client_ip),
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO auth_user_theme_ips (id, user_id, client_ip, created_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), user_id, clean_client_ip, now, now),
            )
        else:
            connection.execute(
                "UPDATE auth_user_theme_ips SET last_seen_at = ? WHERE id = ?",
                (now, existing["id"]),
            )
        connection.execute(
            """
            DELETE FROM auth_user_theme_ips
            WHERE user_id = ?
              AND id NOT IN (
                SELECT id
                FROM auth_user_theme_ips
                WHERE user_id = ?
                ORDER BY last_seen_at DESC, created_at DESC
                LIMIT ?
              )
            """,
            (user_id, user_id, MAX_THEME_IPS_PER_USER),
        )

    def _active_ip_has_capacity(
        self,
        connection: sqlite3.Connection,
        client_ip: str,
        max_active_login_ips: int,
        now: str,
    ) -> bool:
        if max_active_login_ips <= 0:
            return True
        active_current_ip = connection.execute(
            """
            SELECT 1
            FROM auth_sessions
            WHERE revoked_at IS NULL
              AND expires_at > ?
              AND COALESCE(client_ip, '') = ?
            LIMIT 1
            """,
            (now, client_ip),
        ).fetchone()
        if active_current_ip is not None:
            return True
        row = connection.execute(
            """
            SELECT COUNT(DISTINCT COALESCE(client_ip, 'unknown')) AS active_ip_count
            FROM auth_sessions
            WHERE revoked_at IS NULL
              AND expires_at > ?
            """,
            (now,),
        ).fetchone()
        active_ip_count = int(row["active_ip_count"] if row is not None else 0)
        return active_ip_count < max_active_login_ips

    def _delete_owned_project_data(self, connection: sqlite3.Connection, user_id: str) -> None:
        if self._table_has_column(connection, "memory_origin_sessions", "user_id"):
            connection.execute("DELETE FROM memory_origin_sessions WHERE user_id = ?", (user_id,))
        for table in ("chat_events", "retrieval_events", "chat_sessions", "memory_items"):
            if self._table_has_column(connection, table, "user_id"):
                connection.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        if self._table_has_column(connection, "memory_audit_events", "user_id"):
            connection.execute(
                """
                DELETE FROM memory_audit_events
                WHERE user_id = ? OR actor_user_id = ?
                """,
                (user_id, user_id),
            )

    def _table_has_column(self, connection: sqlite3.Connection, table: str, column: str) -> bool:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if exists is None:
            return False
        return column in {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
