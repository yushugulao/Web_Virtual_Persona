from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from app.backend.schemas.memory import MemoryItem


DEFAULT_MEMORY_USER_ID = "dev-auth-disabled"
DEFAULT_MEMORY_SESSION_ID = "default-session"
LEGACY_MEMORY_USER_ID = "legacy-user"
LEGACY_MEMORY_SESSION_ID = "legacy-session"
USER_GLOBAL_MEMORY_SCOPE = "user_global"
USER_GLOBAL_MEMORY_SESSION_ID = "__user_global__"
USER_GLOBAL_MEMORY_PERSONA_ID = "__user_global__"
MEMORY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "do",
    "for",
    "i",
    "is",
    "it",
    "like",
    "me",
    "my",
    "of",
    "or",
    "remember",
    "that",
    "the",
    "to",
    "you",
}

PERSONAL_MEMORY_QUERY_MARKERS = (
    "对我的了解",
    "了解我",
    "关于我的信息",
    "我的信息",
    "我的偏好",
    "我偏好",
    "我的回答偏好",
    "怎么称呼我",
    "称呼我",
    "叫我",
    "我的名字",
    "我叫什么",
    "我的习惯",
)

USER_PROFILE_MEMORY_MARKERS = (
    "用户希望被称呼为",
    "用户喜欢或偏好",
    "用户希望互动方式",
    "用户的长期背景",
    "用户不喜欢",
)


MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_items (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL DEFAULT 'legacy-user',
  session_id TEXT NOT NULL DEFAULT 'legacy-session',
  persona_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  memory_type TEXT NOT NULL,
  status TEXT NOT NULL,
  content TEXT NOT NULL,
  sensitivity TEXT NOT NULL,
  source TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  confidence REAL NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  expires_at REAL
);

CREATE INDEX IF NOT EXISTS idx_memory_items_persona_status ON memory_items(persona_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_items_scope ON memory_items(scope);

CREATE TABLE IF NOT EXISTS memory_audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  memory_id TEXT NOT NULL,
  action TEXT NOT NULL,
  actor TEXT NOT NULL,
  actor_user_id TEXT NOT NULL DEFAULT 'legacy-user',
  user_id TEXT NOT NULL DEFAULT 'legacy-user',
  session_id TEXT NOT NULL DEFAULT 'legacy-session',
  persona_id TEXT NOT NULL DEFAULT 'legacy-persona',
  detail_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_audit_memory ON memory_audit_events(memory_id);

CREATE TABLE IF NOT EXISTS memory_origin_sessions (
  memory_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  persona_id TEXT NOT NULL,
  created_at REAL NOT NULL,
  PRIMARY KEY(memory_id, user_id, session_id),
  FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_origin_user_session
  ON memory_origin_sessions(user_id, session_id);
CREATE INDEX IF NOT EXISTS idx_memory_origin_memory
  ON memory_origin_sessions(memory_id);
"""


class MemoryStore:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(MEMORY_SCHEMA)
            self._ensure_column(
                conn,
                table="memory_items",
                column="user_id",
                definition=f"TEXT NOT NULL DEFAULT '{LEGACY_MEMORY_USER_ID}'",
            )
            self._ensure_column(
                conn,
                table="memory_items",
                column="session_id",
                definition=f"TEXT NOT NULL DEFAULT '{LEGACY_MEMORY_SESSION_ID}'",
            )
            self._ensure_column(
                conn,
                table="memory_audit_events",
                column="actor_user_id",
                definition=f"TEXT NOT NULL DEFAULT '{LEGACY_MEMORY_USER_ID}'",
            )
            self._ensure_column(
                conn,
                table="memory_audit_events",
                column="user_id",
                definition=f"TEXT NOT NULL DEFAULT '{LEGACY_MEMORY_USER_ID}'",
            )
            self._ensure_column(
                conn,
                table="memory_audit_events",
                column="session_id",
                definition=f"TEXT NOT NULL DEFAULT '{LEGACY_MEMORY_SESSION_ID}'",
            )
            self._ensure_column(
                conn,
                table="memory_audit_events",
                column="persona_id",
                definition="TEXT NOT NULL DEFAULT 'legacy-persona'",
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_items_owner_session_persona "
                "ON memory_items(user_id, session_id, persona_id, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_items_owner_scope "
                "ON memory_items(user_id, scope, status, updated_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_audit_owner "
                "ON memory_audit_events(user_id, session_id, persona_id)"
            )
            self._migrate_user_global_origins(conn)

    def propose(
        self,
        *,
        user_id: str = DEFAULT_MEMORY_USER_ID,
        session_id: str = DEFAULT_MEMORY_SESSION_ID,
        persona_id: str,
        content: str,
        scope: str = "session",
        memory_type: str = "user_profile",
        status: str = "pending",
        sensitivity: str = "normal",
        source: str = "explicit",
        tags: list[str] | None = None,
        confidence: float = 1.0,
        actor_user_id: str | None = None,
    ) -> MemoryItem:
        self.initialize()
        now = time.time()
        item = MemoryItem(
            id=uuid.uuid4().hex,
            user_id=user_id,
            session_id=session_id,
            persona_id=persona_id,
            scope=scope,
            memory_type=memory_type,
            status=status,
            content=content,
            sensitivity=sensitivity,
            source=source,
            tags=tags or [],
            confidence=confidence,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_items (
                  id, user_id, session_id, persona_id, scope, memory_type, status, content, sensitivity,
                  source, tags_json, confidence, created_at, updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._item_row(item),
            )
            self._audit(
                conn,
                item,
                "propose",
                {"status": status, "sensitivity": sensitivity},
                actor_user_id=actor_user_id or user_id,
            )
            if item.status == "approved" and item.memory_type == "correction":
                self._apply_correction(conn, item, actor_user_id=actor_user_id or user_id)
        return item

    def add_origin(
        self,
        *,
        memory_id: str,
        user_id: str,
        session_id: str,
        persona_id: str,
    ) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_origin_sessions (
                  memory_id, user_id, session_id, persona_id, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (memory_id, user_id, session_id, persona_id, time.time()),
            )

    def delete_session_scope(self, *, user_id: str, session_id: str) -> None:
        self.initialize()
        with self._connect() as conn:
            session_memory_rows = conn.execute(
                """
                SELECT id
                FROM memory_items
                WHERE user_id = ? AND session_id = ? AND scope = 'session'
                """,
                (user_id, session_id),
            ).fetchall()
            origin_rows = conn.execute(
                """
                SELECT DISTINCT memory_id
                FROM memory_origin_sessions
                WHERE user_id = ? AND session_id = ?
                """,
                (user_id, session_id),
            ).fetchall()
            conn.execute(
                "DELETE FROM memory_origin_sessions WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            )
            origin_memory_ids = [row["memory_id"] for row in origin_rows]
            orphan_global_ids: list[str] = []
            if origin_memory_ids:
                placeholders = ",".join("?" for _ in origin_memory_ids)
                orphan_rows = conn.execute(
                    f"""
                    SELECT id
                    FROM memory_items
                    WHERE user_id = ?
                      AND scope = ?
                      AND id IN ({placeholders})
                      AND NOT EXISTS (
                        SELECT 1
                        FROM memory_origin_sessions
                        WHERE memory_origin_sessions.memory_id = memory_items.id
                      )
                    """,
                    [user_id, USER_GLOBAL_MEMORY_SCOPE, *origin_memory_ids],
                ).fetchall()
                orphan_global_ids = [row["id"] for row in orphan_rows]
            memory_ids = [row["id"] for row in session_memory_rows] + orphan_global_ids
            if memory_ids:
                placeholders = ",".join("?" for _ in memory_ids)
                conn.execute(f"DELETE FROM memory_audit_events WHERE memory_id IN ({placeholders})", memory_ids)
                conn.execute(f"DELETE FROM memory_items WHERE id IN ({placeholders})", memory_ids)

    def list_items(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        persona_id: str | None = None,
        status: str | None = None,
        scope: str | None = None,
        limit: int = 100,
        only_active_origins: bool = False,
    ) -> list[MemoryItem]:
        self.initialize()
        clauses: list[str] = []
        params: list[Any] = []
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if persona_id:
            clauses.append("persona_id = ?")
            params.append(persona_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        with self._connect() as conn:
            effective_clauses = list(clauses)
            if only_active_origins:
                if self._table_exists(conn, "chat_sessions"):
                    effective_clauses.append(
                        """
                        EXISTS (
                          SELECT 1
                          FROM memory_origin_sessions AS mos
                          JOIN chat_sessions AS cs
                            ON cs.user_id = mos.user_id
                           AND cs.session_id = mos.session_id
                          WHERE mos.memory_id = memory_items.id
                            AND mos.user_id = memory_items.user_id
                            AND cs.status = 'active'
                        )
                        """
                    )
                else:
                    effective_clauses.append("0 = 1")
            where = f"WHERE {' AND '.join(effective_clauses)}" if effective_clauses else ""
            rows = conn.execute(
                f"""
                SELECT *
                FROM memory_items
                {where}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def retrieve_approved(
        self,
        *,
        user_id: str = DEFAULT_MEMORY_USER_ID,
        session_id: str = DEFAULT_MEMORY_SESSION_ID,
        persona_id: str,
        query: str,
        limit: int = 5,
        include_user_global: bool = False,
    ) -> list[MemoryItem]:
        candidates = self.list_items(
            user_id=user_id,
            session_id=session_id,
            persona_id=persona_id,
            status="approved",
            scope="session",
            limit=200,
        )
        if include_user_global:
            candidates.extend(
                self.list_items(
                    user_id=user_id,
                    status="approved",
                    scope=USER_GLOBAL_MEMORY_SCOPE,
                    limit=200,
                    only_active_origins=True,
                )
            )
        scored = [
            (score_memory(item.content, query), item)
            for item in candidates
            if item.user_id == user_id
            and (
                (
                    item.scope == "session"
                    and item.session_id == session_id
                    and item.persona_id == persona_id
                )
                or item.scope == USER_GLOBAL_MEMORY_SCOPE
            )
        ]
        scored = [(score, item) for score, item in scored if score > 0]
        scored.sort(key=lambda pair: (pair[0], pair[1].updated_at), reverse=True)
        return [item for _, item in scored[:limit]]

    def set_status(
        self,
        memory_id: str,
        status: str,
        *,
        action: str,
        user_id: str | None = None,
        session_id: str | None = None,
        actor_user_id: str = DEFAULT_MEMORY_USER_ID,
    ) -> MemoryItem:
        self.initialize()
        now = time.time()
        with self._connect() as conn:
            clauses = ["id = ?"]
            params: list[Any] = [memory_id]
            if user_id:
                clauses.append("user_id = ?")
                params.append(user_id)
            if session_id:
                clauses.append("session_id = ?")
                params.append(session_id)
            row = conn.execute(
                f"SELECT * FROM memory_items WHERE {' AND '.join(clauses)}",
                params,
            ).fetchone()
            if row is None:
                raise KeyError(memory_id)
            current_item = self._row_to_item(row)
            conn.execute(
                "UPDATE memory_items SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, memory_id),
            )
            self._audit(
                conn,
                current_item,
                action,
                {"status": status},
                actor_user_id=actor_user_id,
            )
            updated = conn.execute("SELECT * FROM memory_items WHERE id = ?", (memory_id,)).fetchone()
            item = self._row_to_item(updated)
            if item.status == "approved" and item.memory_type == "correction":
                self._apply_correction(conn, item, actor_user_id=actor_user_id)
        return item

    def stats(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        persona_id: str | None = None,
        scope: str | None = None,
        only_active_origins: bool = False,
    ) -> dict[str, Any]:
        self.initialize()
        clauses: list[str] = []
        params: list[Any] = []
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if persona_id:
            clauses.append("persona_id = ?")
            params.append(persona_id)
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        with self._connect() as conn:
            effective_clauses = list(clauses)
            if only_active_origins:
                if self._table_exists(conn, "chat_sessions"):
                    effective_clauses.append(
                        """
                        EXISTS (
                          SELECT 1
                          FROM memory_origin_sessions AS mos
                          JOIN chat_sessions AS cs
                            ON cs.user_id = mos.user_id
                           AND cs.session_id = mos.session_id
                          WHERE mos.memory_id = memory_items.id
                            AND mos.user_id = memory_items.user_id
                            AND cs.status = 'active'
                        )
                        """
                    )
                else:
                    effective_clauses.append("0 = 1")
            where = f"WHERE {' AND '.join(effective_clauses)}" if effective_clauses else ""
            total = conn.execute(
                f"SELECT COUNT(*) AS count FROM memory_items {where}",
                params,
            ).fetchone()["count"]
            by_persona = grouped_counts(conn, "persona_id", where=where, params=params)
            by_session = grouped_counts(conn, "session_id", where=where, params=params)
            by_status = grouped_counts(conn, "status", where=where, params=params)
            by_type = grouped_counts(conn, "memory_type", where=where, params=params)
            by_sensitivity = grouped_counts(conn, "sensitivity", where=where, params=params)
            rows = conn.execute(
                f"""
                SELECT persona_id, status, COUNT(*) AS count
                FROM memory_items
                {where}
                GROUP BY persona_id, status
                """,
                params,
            ).fetchall()
            approved = conn.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM memory_items
                {where + (' AND ' if where else 'WHERE ')}status = 'approved'
                """,
                params,
            ).fetchone()["count"]
        by_persona_status: dict[str, dict[str, int]] = {}
        for row in rows:
            by_persona_status.setdefault(row["persona_id"], {})[row["status"]] = int(row["count"])
        return {
            "total": int(total),
            "by_persona": by_persona,
            "by_session": by_session,
            "by_status": by_status,
            "by_type": by_type,
            "by_sensitivity": by_sensitivity,
            "by_persona_status": by_persona_status,
            "current_session_total": int(total),
            "current_session_approved": int(approved),
        }

    def rebuild_index(self) -> dict[str, int]:
        self.initialize()
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS count FROM memory_items").fetchone()["count"]
            approved = conn.execute(
                "SELECT COUNT(*) AS count FROM memory_items WHERE status = 'approved'"
            ).fetchone()["count"]
        return {"total": int(total), "approved": int(approved)}

    def counts(self) -> dict[str, int]:
        self.initialize()
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS count FROM memory_items").fetchone()["count"]
            audit = conn.execute(
                "SELECT COUNT(*) AS count FROM memory_audit_events"
            ).fetchone()["count"]
        return {"memory_items": int(total), "memory_audit_events": int(audit)}

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _item_row(self, item: MemoryItem) -> tuple[Any, ...]:
        return (
            item.id,
            item.user_id,
            item.session_id,
            item.persona_id,
            item.scope,
            item.memory_type,
            item.status,
            item.content,
            item.sensitivity,
            item.source,
            json.dumps(item.tags, ensure_ascii=False),
            item.confidence,
            item.created_at,
            item.updated_at,
            item.expires_at,
        )

    def _row_to_item(self, row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            id=row["id"],
            user_id=row["user_id"],
            session_id=row["session_id"],
            persona_id=row["persona_id"],
            scope=row["scope"],
            memory_type=row["memory_type"],
            status=row["status"],
            content=row["content"],
            sensitivity=row["sensitivity"],
            source=row["source"],
            tags=json.loads(row["tags_json"]),
            confidence=float(row["confidence"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            expires_at=row["expires_at"],
        )

    def _audit(
        self,
        conn: sqlite3.Connection,
        item: MemoryItem,
        action: str,
        detail: dict[str, Any],
        *,
        actor_user_id: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO memory_audit_events (
              ts, memory_id, action, actor, actor_user_id, user_id, session_id, persona_id, detail_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                time.time(),
                item.id,
                action,
                actor_user_id,
                actor_user_id,
                item.user_id,
                item.session_id,
                item.persona_id,
                json.dumps(detail, ensure_ascii=False),
            ),
        )

    def _apply_correction(
        self,
        conn: sqlite3.Connection,
        correction: MemoryItem,
        *,
        actor_user_id: str,
    ) -> None:
        rows = conn.execute(
            """
            SELECT *
            FROM memory_items
            WHERE user_id = ?
              AND session_id = ?
              AND persona_id = ?
              AND status = 'approved'
              AND memory_type != 'correction'
              AND id != ?
            """,
            (correction.user_id, correction.session_id, correction.persona_id, correction.id),
        ).fetchall()
        now = time.time()
        for row in rows:
            item = self._row_to_item(row)
            if not lexical_correction_conflict(item.content, correction.content):
                continue
            conn.execute(
                "UPDATE memory_items SET status = 'retracted', updated_at = ? WHERE id = ?",
                (now, item.id),
            )
            self._audit(
                conn,
                item,
                "superseded_by_correction",
                {"correction_id": correction.id},
                actor_user_id=actor_user_id,
            )

    def _migrate_user_global_origins(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT id, user_id, source
            FROM memory_items
            WHERE scope = ?
              AND source LIKE 'auto_user_global:%'
            """,
            (USER_GLOBAL_MEMORY_SCOPE,),
        ).fetchall()
        for row in rows:
            parts = str(row["source"]).split(":", 2)
            if len(parts) != 3:
                continue
            _, persona_id, session_id = parts
            if not session_id:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_origin_sessions (
                  memory_id, user_id, session_id, persona_id, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (row["id"], row["user_id"], session_id, persona_id, time.time()),
            )

    def _table_exists(self, conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        *,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def score_memory(content: str, query: str) -> float:
    if is_personal_memory_query(query) and is_user_profile_memory(content):
        return 0.75
    content_terms = set(tokenize_memory_text(content))
    query_terms = set(tokenize_memory_text(query))
    if not content_terms or not query_terms:
        return 0.1 if len(content) < 160 else 0.0
    overlap = len(content_terms & query_terms)
    if overlap:
        return overlap / max(1, len(query_terms))
    return 0.0


def is_personal_memory_query(query: str) -> bool:
    compact = re.sub(r"\s+", "", query)
    return any(marker in compact for marker in PERSONAL_MEMORY_QUERY_MARKERS)


def is_user_profile_memory(content: str) -> bool:
    return any(marker in content for marker in USER_PROFILE_MEMORY_MARKERS)


def tokenize_memory_text(text: str) -> list[str]:
    latin = [
        token
        for token in re.findall(r"[A-Za-z0-9_]{2,}", text.lower())
        if token not in MEMORY_STOPWORDS
    ]
    cjk_segments = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    cjk = cjk_segments + cjk_bigrams(text)
    return latin + cjk


def lexical_correction_conflict(old_content: str, correction_content: str) -> bool:
    old_terms = set(tokenize_memory_text(old_content)) | set(cjk_bigrams(old_content))
    correction_terms = set(tokenize_memory_text(correction_content)) | set(
        cjk_bigrams(correction_content)
    )
    if not old_terms or not correction_terms:
        return False
    return bool(old_terms & correction_terms)


def cjk_bigrams(text: str) -> list[str]:
    bigrams: list[str] = []
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        bigrams.extend(segment[index : index + 2] for index in range(len(segment) - 1))
    return bigrams


def grouped_counts(
    conn: sqlite3.Connection,
    column: str,
    *,
    where: str = "",
    params: list[Any] | None = None,
) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT {column} AS label, COUNT(*) AS count FROM memory_items {where} GROUP BY {column}",
        params or [],
    ).fetchall()
    return {row["label"]: int(row["count"]) for row in rows}
