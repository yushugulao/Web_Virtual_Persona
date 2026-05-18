from __future__ import annotations

from collections import Counter
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from app.backend.memory.memory_store import (
    USER_GLOBAL_MEMORY_PERSONA_ID,
    USER_GLOBAL_MEMORY_SCOPE,
    USER_GLOBAL_MEMORY_SESSION_ID,
    MemoryStore,
)
from app.backend.memory.user_global_extractor import extract_user_global_memories
from app.backend.schemas.chat import ChatDiagnostics, ChatRequest, ChatResponse
from app.backend.schemas.evals import EvalCaseResult, EvalRunResponse
from app.backend.schemas.retrieval import RetrieveRequest, RetrieveResponse
from app.backend.services.conversation_memory import ConversationTurn, serialize_session_context_summary
from app.rag.chunking.markdown import Chunk, DocumentMeta


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  source_path TEXT NOT NULL,
  source_type TEXT NOT NULL,
  trust_level TEXT NOT NULL,
  privacy_level TEXT NOT NULL,
  chunk_count INTEGER NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
  chunk_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  title TEXT NOT NULL,
  source_path TEXT NOT NULL,
  section_path TEXT NOT NULL,
  text TEXT NOT NULL,
  source_type TEXT NOT NULL,
  trust_level TEXT NOT NULL,
  privacy_level TEXT NOT NULL,
  token_estimate INTEGER NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY(doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_privacy ON chunks(privacy_level);

CREATE TABLE IF NOT EXISTS chat_sessions (
  session_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL DEFAULT 'legacy-user',
  persona_id TEXT NOT NULL DEFAULT 'local_persona',
  title TEXT NOT NULL DEFAULT '',
  message_count INTEGER NOT NULL DEFAULT 0,
  last_message_preview TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  last_seen_at REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  archived_at REAL,
  deleted_at REAL,
  summary_json TEXT,
  summary_message_count INTEGER NOT NULL DEFAULT 0,
  summary_updated_at REAL
);

CREATE TABLE IF NOT EXISTS user_personas (
  persona_id TEXT PRIMARY KEY,
  owner_user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  avatar_url TEXT NOT NULL DEFAULT '',
  avatar_label TEXT NOT NULL DEFAULT '分',
  short_description TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  identity_tags_json TEXT NOT NULL DEFAULT '[]',
  web_search_enabled INTEGER NOT NULL DEFAULT 0,
  runtime_status TEXT NOT NULL DEFAULT 'draft',
  is_public INTEGER NOT NULL DEFAULT 0,
  score INTEGER NOT NULL DEFAULT 0,
  build_id TEXT NOT NULL DEFAULT '',
  build_artifact_dir TEXT NOT NULL DEFAULT '',
  corpus_path TEXT NOT NULL DEFAULT '',
  source_depth TEXT NOT NULL DEFAULT '',
  evidence_card_count INTEGER NOT NULL DEFAULT 0,
  build_error TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  published_at REAL
);

CREATE INDEX IF NOT EXISTS idx_user_personas_owner ON user_personas(owner_user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_user_personas_public_score
ON user_personas(is_public, runtime_status, score, published_at);

CREATE TABLE IF NOT EXISTS user_persona_files (
  file_id TEXT PRIMARY KEY,
  persona_id TEXT NOT NULL,
  owner_user_id TEXT NOT NULL,
  original_filename TEXT NOT NULL,
  stored_filename TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  extension TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  upload_status TEXT NOT NULL,
  parse_status TEXT NOT NULL,
  parser_chain_json TEXT NOT NULL DEFAULT '[]',
  quality_score REAL NOT NULL DEFAULT 0,
  warnings_json TEXT NOT NULL DEFAULT '[]',
  error_message TEXT NOT NULL DEFAULT '',
  raw_path TEXT NOT NULL,
  parsed_markdown_path TEXT NOT NULL DEFAULT '',
  blocks_path TEXT NOT NULL DEFAULT '',
  provenance_path TEXT NOT NULL DEFAULT '',
  diagnostics_path TEXT NOT NULL DEFAULT '',
  page_count INTEGER,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY(persona_id) REFERENCES user_personas(persona_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_persona_files_owner_persona
ON user_persona_files(owner_user_id, persona_id, created_at);

CREATE INDEX IF NOT EXISTS idx_user_persona_files_hash
ON user_persona_files(owner_user_id, persona_id, sha256);

CREATE TABLE IF NOT EXISTS user_persona_builds (
  build_id TEXT PRIMARY KEY,
  persona_id TEXT NOT NULL,
  owner_user_id TEXT NOT NULL,
  status TEXT NOT NULL,
  phase TEXT NOT NULL,
  progress REAL NOT NULL DEFAULT 0,
  input_hash TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  artifact_dir TEXT NOT NULL DEFAULT '',
  source_depth TEXT NOT NULL DEFAULT '',
  evidence_card_count INTEGER NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT '',
  quality_summary_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  finished_at REAL,
  FOREIGN KEY(persona_id) REFERENCES user_personas(persona_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_persona_builds_owner_persona
ON user_persona_builds(owner_user_id, persona_id, created_at);

CREATE TABLE IF NOT EXISTS user_persona_web_research_runs (
  run_id TEXT PRIMARY KEY,
  persona_id TEXT NOT NULL,
  owner_user_id TEXT NOT NULL,
  status TEXT NOT NULL,
  phase TEXT NOT NULL,
  progress REAL NOT NULL DEFAULT 0,
  provider TEXT NOT NULL DEFAULT '',
  artifact_dir TEXT NOT NULL DEFAULT '',
  query_count INTEGER NOT NULL DEFAULT 0,
  source_count INTEGER NOT NULL DEFAULT 0,
  included_source_count INTEGER NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT '',
  quality_summary_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  finished_at REAL,
  FOREIGN KEY(persona_id) REFERENCES user_personas(persona_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_persona_web_runs_owner_persona
ON user_persona_web_research_runs(owner_user_id, persona_id, created_at);

CREATE TABLE IF NOT EXISTS user_persona_web_sources (
  source_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  persona_id TEXT NOT NULL,
  owner_user_id TEXT NOT NULL,
  url TEXT NOT NULL,
  canonical_url TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  source_family TEXT NOT NULL DEFAULT '',
  channel TEXT NOT NULL DEFAULT '',
  trust_level TEXT NOT NULL DEFAULT '',
  score REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'candidate',
  content_hash TEXT NOT NULL DEFAULT '',
  artifact_path TEXT NOT NULL DEFAULT '',
  locator TEXT NOT NULL DEFAULT '',
  warning TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY(run_id) REFERENCES user_persona_web_research_runs(run_id) ON DELETE CASCADE,
  FOREIGN KEY(persona_id) REFERENCES user_personas(persona_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_persona_web_sources_run
ON user_persona_web_sources(run_id, status, score);

CREATE TABLE IF NOT EXISTS persona_score_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  persona_id TEXT NOT NULL,
  issue TEXT NOT NULL,
  score_delta INTEGER NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(user_id, request_id, persona_id)
);

CREATE INDEX IF NOT EXISTS idx_persona_score_events_persona
ON persona_score_events(persona_id, created_at);

CREATE TABLE IF NOT EXISTS retrieval_events (
  retrieval_id TEXT PRIMARY KEY,
  ts REAL NOT NULL,
  user_id TEXT NOT NULL DEFAULT 'legacy-user',
  session_id TEXT,
  query TEXT NOT NULL,
  top_k INTEGER NOT NULL,
  include_private INTEGER NOT NULL,
  mode TEXT NOT NULL,
  selected_chunk_ids_json TEXT NOT NULL,
  citations_json TEXT NOT NULL,
  trace_json TEXT NOT NULL,
  timings_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_retrieval_events_ts ON retrieval_events(ts);
CREATE INDEX IF NOT EXISTS idx_retrieval_events_session ON retrieval_events(session_id);

CREATE TABLE IF NOT EXISTS chat_events (
  request_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL DEFAULT 'legacy-user',
  session_id TEXT NOT NULL,
  persona_id TEXT NOT NULL DEFAULT 'local_persona',
  ts REAL NOT NULL,
  message TEXT NOT NULL,
  answer TEXT NOT NULL,
  model TEXT NOT NULL,
  mode TEXT NOT NULL,
  confidence TEXT NOT NULL,
  citation_ids_json TEXT NOT NULL,
  retrieval_trace_json TEXT NOT NULL,
  timings_json TEXT NOT NULL,
  diagnostics_json TEXT,
  follow_up_questions_json TEXT,
  FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chat_events_ts ON chat_events(ts);
CREATE INDEX IF NOT EXISTS idx_chat_events_session ON chat_events(session_id);

CREATE TABLE IF NOT EXISTS eval_runs (
  run_id TEXT PRIMARY KEY,
  ts REAL NOT NULL,
  status TEXT NOT NULL,
  mode TEXT NOT NULL,
  question_count INTEGER NOT NULL,
  passed_count INTEGER NOT NULL,
  failed_count INTEGER NOT NULL,
  metrics_json TEXT NOT NULL,
  message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_case_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  case_id TEXT NOT NULL,
  ts REAL NOT NULL,
  passed INTEGER NOT NULL,
  question TEXT NOT NULL,
  expected_sources_json TEXT NOT NULL,
  retrieved_doc_ids_json TEXT NOT NULL,
  selected_chunk_ids_json TEXT NOT NULL,
  answer TEXT,
  metrics_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES eval_runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_eval_runs_ts ON eval_runs(ts);
CREATE INDEX IF NOT EXISTS idx_eval_case_results_run ON eval_case_results(run_id);

CREATE TABLE IF NOT EXISTS evidence_cards (
  card_id TEXT PRIMARY KEY,
  persona_id TEXT NOT NULL,
  doc_id TEXT NOT NULL,
  chunk_id TEXT,
  source_title TEXT NOT NULL,
  source_url TEXT NOT NULL,
  source_locator TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  keywords_json TEXT NOT NULL,
  quote_anchor TEXT NOT NULL,
  boundary_note TEXT NOT NULL,
  text TEXT NOT NULL,
  trust_level TEXT NOT NULL,
  source_path TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  updated_at REAL NOT NULL,
  FOREIGN KEY(doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_evidence_cards_persona ON evidence_cards(persona_id);
CREATE INDEX IF NOT EXISTS idx_evidence_cards_doc ON evidence_cards(doc_id);
CREATE INDEX IF NOT EXISTS idx_evidence_cards_chunk ON evidence_cards(chunk_id);
CREATE INDEX IF NOT EXISTS idx_evidence_cards_source_title ON evidence_cards(source_title);

CREATE TABLE IF NOT EXISTS evidence_card_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  action TEXT NOT NULL,
  card_id TEXT NOT NULL,
  persona_id TEXT NOT NULL,
  doc_id TEXT NOT NULL,
  detail_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_card_audit_ts ON evidence_card_audit(ts);
"""


class MetadataStore:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._ensure_column(
                conn,
                table="chat_events",
                column="persona_id",
                definition="TEXT NOT NULL DEFAULT 'local_persona'",
            )
            self._ensure_column(
                conn,
                table="chat_sessions",
                column="user_id",
                definition="TEXT NOT NULL DEFAULT 'legacy-user'",
            )
            self._ensure_column(
                conn,
                table="chat_sessions",
                column="persona_id",
                definition="TEXT NOT NULL DEFAULT 'local_persona'",
            )
            self._ensure_column(
                conn,
                table="chat_sessions",
                column="title",
                definition="TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                table="chat_sessions",
                column="message_count",
                definition="INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                conn,
                table="chat_sessions",
                column="last_message_preview",
                definition="TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                table="chat_sessions",
                column="status",
                definition="TEXT NOT NULL DEFAULT 'active'",
            )
            self._ensure_column(
                conn,
                table="chat_sessions",
                column="archived_at",
                definition="REAL",
            )
            self._ensure_column(
                conn,
                table="chat_sessions",
                column="deleted_at",
                definition="REAL",
            )
            self._ensure_column(
                conn,
                table="chat_sessions",
                column="summary_json",
                definition="TEXT",
            )
            self._ensure_column(
                conn,
                table="chat_sessions",
                column="summary_message_count",
                definition="INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                conn,
                table="chat_sessions",
                column="summary_updated_at",
                definition="REAL",
            )
            self._ensure_column(
                conn,
                table="retrieval_events",
                column="user_id",
                definition="TEXT NOT NULL DEFAULT 'legacy-user'",
            )
            self._ensure_column(
                conn,
                table="chat_events",
                column="user_id",
                definition="TEXT NOT NULL DEFAULT 'legacy-user'",
            )
            self._ensure_column(
                conn,
                table="chat_events",
                column="diagnostics_json",
                definition="TEXT",
            )
            self._ensure_column(
                conn,
                table="chat_events",
                column="follow_up_questions_json",
                definition="TEXT",
            )
            self._ensure_column(
                conn,
                table="user_personas",
                column="avatar_url",
                definition="TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                table="user_personas",
                column="avatar_label",
                definition="TEXT NOT NULL DEFAULT '分'",
            )
            self._ensure_column(
                conn,
                table="user_personas",
                column="short_description",
                definition="TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                table="user_personas",
                column="description",
                definition="TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                table="user_personas",
                column="identity_tags_json",
                definition="TEXT NOT NULL DEFAULT '[]'",
            )
            self._ensure_column(
                conn,
                table="user_personas",
                column="web_search_enabled",
                definition="INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                conn,
                table="user_personas",
                column="runtime_status",
                definition="TEXT NOT NULL DEFAULT 'draft'",
            )
            self._ensure_column(
                conn,
                table="user_personas",
                column="is_public",
                definition="INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                conn,
                table="user_personas",
                column="score",
                definition="INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                conn,
                table="user_personas",
                column="published_at",
                definition="REAL",
            )
            self._ensure_column(
                conn,
                table="user_personas",
                column="build_id",
                definition="TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                table="user_personas",
                column="build_artifact_dir",
                definition="TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                table="user_personas",
                column="corpus_path",
                definition="TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                table="user_personas",
                column="source_depth",
                definition="TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                table="user_personas",
                column="evidence_card_count",
                definition="INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                conn,
                table="user_personas",
                column="build_error",
                definition="TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                conn,
                table="user_persona_files",
                column="diagnostics_path",
                definition="TEXT NOT NULL DEFAULT ''",
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_events_persona "
                "ON chat_events(session_id, persona_id, ts)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_events_owner_session "
                "ON chat_events(user_id, session_id, persona_id, ts)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_sessions_owner_seen "
                "ON chat_sessions(user_id, last_seen_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_sessions_owner_persona "
                "ON chat_sessions(user_id, persona_id, last_seen_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_sessions_owner_status_seen "
                "ON chat_sessions(user_id, status, last_seen_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_retrieval_events_owner_session "
                "ON retrieval_events(user_id, session_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_personas_owner "
                "ON user_personas(owner_user_id, updated_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_personas_public_score "
                "ON user_personas(is_public, runtime_status, score, published_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_persona_files_owner_persona "
                "ON user_persona_files(owner_user_id, persona_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_persona_files_hash "
                "ON user_persona_files(owner_user_id, persona_id, sha256)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_persona_score_events_persona "
                "ON persona_score_events(persona_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_persona_builds_owner_persona "
                "ON user_persona_builds(owner_user_id, persona_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_persona_web_runs_owner_persona "
                "ON user_persona_web_research_runs(owner_user_id, persona_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_persona_web_sources_run "
                "ON user_persona_web_sources(run_id, status, score)"
            )
            self._migrate_chat_session_metadata(conn)

    def upsert_corpus(self, documents: list[DocumentMeta], chunks: list[Chunk]) -> None:
        self.initialize()
        now = time.time()
        chunk_counts = Counter(chunk.doc_id for chunk in chunks)
        current_doc_ids = [doc.doc_id for doc in documents]
        current_chunk_ids = [chunk.chunk_id for chunk in chunks]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO documents (
                  doc_id, title, source_path, source_type, trust_level, privacy_level,
                  chunk_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                  title=excluded.title,
                  source_path=excluded.source_path,
                  source_type=excluded.source_type,
                  trust_level=excluded.trust_level,
                  privacy_level=excluded.privacy_level,
                  chunk_count=excluded.chunk_count,
                  updated_at=excluded.updated_at
                """,
                [
                    (
                        doc.doc_id,
                        doc.title,
                        doc.source_path,
                        doc.source_type,
                        doc.trust_level,
                        doc.privacy_level,
                        chunk_counts[doc.doc_id],
                        now,
                    )
                    for doc in documents
                ],
            )
            conn.executemany(
                """
                INSERT INTO chunks (
                  chunk_id, doc_id, title, source_path, section_path, text, source_type,
                  trust_level, privacy_level, token_estimate, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                  doc_id=excluded.doc_id,
                  title=excluded.title,
                  source_path=excluded.source_path,
                  section_path=excluded.section_path,
                  text=excluded.text,
                  source_type=excluded.source_type,
                  trust_level=excluded.trust_level,
                  privacy_level=excluded.privacy_level,
                  token_estimate=excluded.token_estimate,
                  updated_at=excluded.updated_at
                """,
                [
                    (
                        chunk.chunk_id,
                        chunk.doc_id,
                        chunk.title,
                        chunk.source_path,
                        chunk.section_path,
                        chunk.text,
                        chunk.source_type,
                        chunk.trust_level,
                        chunk.privacy_level,
                        chunk.token_estimate,
                        now,
                    )
                    for chunk in chunks
                ],
            )
            self._delete_stale_rows(conn, "chunks", "chunk_id", current_chunk_ids)
            self._delete_stale_rows(conn, "documents", "doc_id", current_doc_ids)

    def touch_session(
        self,
        session_id: str,
        *,
        user_id: str = "dev-auth-disabled",
        persona_id: str = "local_persona",
        title: str | None = None,
    ) -> None:
        self.initialize()
        now = time.time()
        clean_title = normalize_session_title(title or "")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (
                  session_id, user_id, persona_id, title, message_count,
                  last_message_preview, created_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, 0, '', ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  title=CASE
                    WHEN chat_sessions.title IN ('', '未命名会话', '未命名对话') AND excluded.title != '' THEN excluded.title
                    ELSE chat_sessions.title
                  END,
                  last_seen_at=excluded.last_seen_at
                """,
                (session_id, user_id, persona_id, clean_title, now, now),
            )

    def create_chat_session(
        self,
        *,
        user_id: str,
        persona_id: str,
        title: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        now = time.time()
        created_session_id = session_id or uuid.uuid4().hex
        clean_title = normalize_session_title(title or "") or "未命名会话"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (
                  session_id, user_id, persona_id, title, message_count,
                  last_message_preview, created_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, 0, '', ?, ?)
                """,
                (created_session_id, user_id, persona_id, clean_title, now, now),
            )
            row = conn.execute(
                "SELECT * FROM chat_sessions WHERE session_id = ?",
                (created_session_id,),
            ).fetchone()
        return self._session_row(row)

    def get_chat_session(self, session_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chat_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._session_row(row) if row is not None else None

    def ensure_chat_session(
        self,
        *,
        session_id: str,
        user_id: str,
        persona_id: str,
        first_message: str | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        now = time.time()
        title = title_from_user_message(first_message or "")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chat_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO chat_sessions (
                      session_id, user_id, persona_id, title, message_count,
                      last_message_preview, created_at, last_seen_at
                    )
                    VALUES (?, ?, ?, ?, 0, '', ?, ?)
                    """,
                    (session_id, user_id, persona_id, title, now, now),
                )
            else:
                conn.execute(
                    """
                    UPDATE chat_sessions
                    SET last_seen_at = ?,
                        title = CASE
                          WHEN title IN ('', '未命名会话', '未命名对话') THEN ?
                          ELSE title
                        END
                    WHERE session_id = ?
                    """,
                    (now, title, session_id),
                )
            updated = conn.execute(
                "SELECT * FROM chat_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._session_row(updated)

    def list_chat_sessions(
        self,
        *,
        user_id: str,
        sort: str = "recent",
        status: str = "active",
    ) -> list[dict[str, Any]]:
        self.initialize()
        order_by = "last_seen_at DESC, created_at DESC"
        if sort == "persona":
            order_by = "persona_id ASC, last_seen_at DESC, created_at DESC"
        where = "user_id = ? AND status = ?"
        params: list[Any] = [user_id, status]
        if status == "all":
            where = "user_id = ? AND status IN ('active', 'archived')"
            params = [user_id]
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM chat_sessions
                WHERE {where}
                ORDER BY {order_by}
                """,
                params,
            ).fetchall()
        return [self._session_row(row) for row in rows]

    def archive_chat_session(self, *, user_id: str, session_id: str) -> dict[str, Any] | None:
        self.initialize()
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chat_sessions WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            ).fetchone()
            if row is None or row["status"] == "deleted":
                return None
            if row["status"] != "archived":
                conn.execute(
                    """
                    UPDATE chat_sessions
                    SET status = 'archived', archived_at = ?, last_seen_at = ?
                    WHERE user_id = ? AND session_id = ?
                    """,
                    (now, now, user_id, session_id),
                )
            updated = conn.execute(
                "SELECT * FROM chat_sessions WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            ).fetchone()
        return self._session_row(updated) if updated is not None else None

    def restore_chat_session(self, *, user_id: str, session_id: str) -> dict[str, Any] | None:
        self.initialize()
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chat_sessions WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            ).fetchone()
            if row is None or row["status"] == "deleted":
                return None
            conn.execute(
                """
                UPDATE chat_sessions
                SET status = 'active', archived_at = NULL, deleted_at = NULL, last_seen_at = ?
                WHERE user_id = ? AND session_id = ?
                """,
                (now, user_id, session_id),
            )
            updated = conn.execute(
                "SELECT * FROM chat_sessions WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            ).fetchone()
        return self._session_row(updated) if updated is not None else None

    def delete_archived_chat_session(self, *, user_id: str, session_id: str) -> bool:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chat_sessions WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            ).fetchone()
        if row is None or row["status"] != "archived":
            return False
        MemoryStore(self.path).delete_session_scope(user_id=user_id, session_id=session_id)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM retrieval_events WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            )
            conn.execute(
                "DELETE FROM chat_events WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            )
            conn.execute(
                "DELETE FROM chat_sessions WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            )
        return True

    def chat_session_messages(
        self,
        *,
        user_id: str,
        session_id: str,
        include_diagnostics: bool = False,
    ) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT request_id, user_id, session_id, persona_id, ts, message, answer,
                       model, mode, confidence, diagnostics_json, follow_up_questions_json
                FROM chat_events
                WHERE user_id = ? AND session_id = ?
                ORDER BY ts ASC
                """,
                (user_id, session_id),
            ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            base = {
                "request_id": row["request_id"],
                "session_id": row["session_id"],
                "persona_id": row["persona_id"],
                "ts": row["ts"],
                "model": row["model"],
                "mode": row["mode"],
                "confidence": row["confidence"],
            }
            messages.append(
                {
                    **base,
                    "id": f"{row['request_id']}:user",
                    "role": "user",
                    "content": row["message"],
                }
            )
            assistant_message = {
                **base,
                "id": f"{row['request_id']}:assistant",
                "role": "assistant",
                "content": row["answer"],
                "follow_up_questions": self._parse_follow_up_questions(
                    row["follow_up_questions_json"]
                ),
            }
            if include_diagnostics:
                diagnostics = self._parse_chat_diagnostics(row["diagnostics_json"])
                if diagnostics is not None:
                    assistant_message["diagnostics"] = diagnostics.model_dump(mode="json")
            messages.append(assistant_message)
        return messages

    def update_chat_follow_up_questions(
        self,
        *,
        user_id: str,
        session_id: str,
        request_id: str,
        questions: list[str],
    ) -> bool:
        self.initialize()
        cleaned = [question.strip() for question in questions if question.strip()][:3]
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE chat_events
                SET follow_up_questions_json = ?
                WHERE user_id = ? AND session_id = ? AND request_id = ?
                """,
                (dumps(cleaned), user_id, session_id, request_id),
            )
        return cursor.rowcount > 0

    def record_retrieval(
        self,
        *,
        retrieval_id: str,
        request: RetrieveRequest,
        response: RetrieveResponse,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        self.initialize()
        event_user_id = user_id or request.user_id or "dev-auth-disabled"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO retrieval_events (
                  retrieval_id, ts, user_id, session_id, query, top_k, include_private, mode,
                  selected_chunk_ids_json, citations_json, trace_json, timings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    retrieval_id,
                    time.time(),
                    event_user_id,
                    session_id,
                    request.query,
                    request.top_k,
                    int(request.include_private),
                    response.trace.notes[0] if response.trace.notes else "unknown",
                    dumps(response.trace.selected_chunk_ids),
                    dumps([citation.model_dump() for citation in response.citations]),
                    dumps(response.trace.model_dump()),
                    dumps(response.timings.model_dump()),
                ),
            )

    def record_chat(
        self,
        *,
        request: ChatRequest,
        response: ChatResponse,
        user_id: str = "dev-auth-disabled",
    ) -> None:
        persona_id = response.retrieval_trace.persona_id
        now = time.time()
        title = title_from_user_message(request.message)
        preview = preview_from_user_message(request.message)
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (
                  session_id, user_id, persona_id, title, message_count,
                  last_message_preview, created_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, 0, '', ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  title=CASE
                    WHEN chat_sessions.title IN ('', '未命名会话', '未命名对话') THEN excluded.title
                    ELSE chat_sessions.title
                  END,
                  last_seen_at=excluded.last_seen_at
                """,
                (response.session_id, user_id, persona_id, title, now, now),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO chat_events (
                  request_id, user_id, session_id, persona_id, ts, message, answer, model, mode, confidence,
                  citation_ids_json, retrieval_trace_json, timings_json, diagnostics_json,
                  follow_up_questions_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    response.request_id,
                    user_id,
                    response.session_id,
                    persona_id,
                    now,
                    request.message,
                    response.answer,
                    response.model,
                    response.mode,
                    response.confidence,
                    dumps([citation.chunk_id for citation in response.citations]),
                    dumps(response.retrieval_trace.model_dump()),
                    dumps(response.timings.model_dump()),
                    self._chat_diagnostics_json(response.diagnostics),
                    dumps(response.follow_up_questions),
                ),
            )
            message_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM chat_events
                WHERE user_id = ? AND session_id = ?
                """,
                (user_id, response.session_id),
            ).fetchone()["count"]
            conn.execute(
                """
                UPDATE chat_sessions
                SET persona_id = ?,
                    message_count = ?,
                    last_message_preview = ?,
                    last_seen_at = ?
                WHERE session_id = ?
                """,
                (persona_id, int(message_count), preview, now, response.session_id),
            )
            self._refresh_session_context_summary(
                conn,
                user_id=user_id,
                session_id=response.session_id,
                persona_id=persona_id,
                now=now,
            )
        self._record_auto_user_global_memories(
            user_id=user_id,
            source_session_id=response.session_id,
            source_persona_id=persona_id,
            message=request.message,
        )

    def _refresh_session_context_summary(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        session_id: str,
        persona_id: str,
        now: float,
    ) -> None:
        rows = conn.execute(
            """
            SELECT ts, persona_id, message, answer
            FROM chat_events
            WHERE user_id = ?
              AND session_id = ?
              AND persona_id = ?
            ORDER BY ts ASC
            """,
            (user_id, session_id, persona_id),
        ).fetchall()
        turns = [
            ConversationTurn(
                message=row["message"],
                answer=row["answer"],
                ts=row["ts"],
                persona_id=row["persona_id"],
            )
            for row in rows
        ]
        if len(turns) <= 8:
            summary_json = None
            summary_message_count = 0
        else:
            summary = serialize_session_context_summary(
                turns,
                summarized_message_count=len(turns),
                updated_at=now,
            )
            summary_json = dumps(summary)
            summary_message_count = len(turns)
        conn.execute(
            """
            UPDATE chat_sessions
            SET summary_json = ?,
                summary_message_count = ?,
                summary_updated_at = ?
            WHERE user_id = ? AND session_id = ? AND persona_id = ?
            """,
            (summary_json, summary_message_count, now, user_id, session_id, persona_id),
        )

    @staticmethod
    def _chat_diagnostics_json(diagnostics: ChatDiagnostics | None) -> str | None:
        if diagnostics is None:
            return None
        return dumps(diagnostics.model_dump(mode="json"))

    @staticmethod
    def _parse_chat_diagnostics(value: str | None) -> ChatDiagnostics | None:
        if not value:
            return None
        try:
            return ChatDiagnostics.model_validate(loads(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_follow_up_questions(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            parsed = loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(parsed, list):
            return []
        questions: list[str] = []
        for item in parsed:
            if not isinstance(item, str):
                continue
            question = item.strip()
            if question:
                questions.append(question)
        return questions[:3]

    def _record_auto_user_global_memories(
        self,
        *,
        user_id: str,
        source_session_id: str,
        source_persona_id: str,
        message: str,
    ) -> None:
        extracted = extract_user_global_memories(message)
        if not extracted:
            return
        store = MemoryStore(self.path)
        existing = {
            item.content: item
            for item in store.list_items(
                user_id=user_id,
                scope=USER_GLOBAL_MEMORY_SCOPE,
                limit=500,
            )
        }
        for item in extracted:
            if item.content in existing:
                store.add_origin(
                    memory_id=existing[item.content].id,
                    user_id=user_id,
                    session_id=source_session_id,
                    persona_id=source_persona_id,
                )
                continue
            memory_item = store.propose(
                user_id=user_id,
                session_id=USER_GLOBAL_MEMORY_SESSION_ID,
                persona_id=USER_GLOBAL_MEMORY_PERSONA_ID,
                content=item.content,
                scope=USER_GLOBAL_MEMORY_SCOPE,
                memory_type=item.memory_type,
                status="approved",
                sensitivity="normal",
                source=f"auto_user_global:{source_persona_id}:{source_session_id}",
                tags=item.tags,
                confidence=item.confidence,
                actor_user_id=user_id,
            )
            store.add_origin(
                memory_id=memory_item.id,
                user_id=user_id,
                session_id=source_session_id,
                persona_id=source_persona_id,
            )
            existing[item.content] = memory_item

    def record_eval_run(self, response: EvalRunResponse) -> None:
        self.initialize()
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO eval_runs (
                  run_id, ts, status, mode, question_count, passed_count, failed_count,
                  metrics_json, message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    response.run_id,
                    now,
                    response.status,
                    response.mode,
                    response.question_count,
                    response.passed_count,
                    response.failed_count,
                    dumps(response.metrics.model_dump()),
                    response.message,
                ),
            )
            conn.execute("DELETE FROM eval_case_results WHERE run_id = ?", (response.run_id,))
            conn.executemany(
                """
                INSERT INTO eval_case_results (
                  run_id, case_id, ts, passed, question, expected_sources_json,
                  retrieved_doc_ids_json, selected_chunk_ids_json, answer, metrics_json,
                  result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    self._eval_case_row(response.run_id, now, result)
                    for result in response.results
                ],
            )

    def counts(self) -> dict[str, int]:
        self.initialize()
        with self._connect() as conn:
            return {
                "documents": self._count(conn, "documents"),
                "chunks": self._count(conn, "chunks"),
                "sessions": self._count(conn, "chat_sessions"),
                "retrieval_events": self._count(conn, "retrieval_events"),
                "chat_events": self._count(conn, "chat_events"),
                "eval_runs": self._count(conn, "eval_runs"),
                "eval_case_results": self._count(conn, "eval_case_results"),
                "evidence_cards": self._count(conn, "evidence_cards"),
                "evidence_card_audit": self._count(conn, "evidence_card_audit"),
            }

    def sync_evidence_cards(self, cards: list[Any], *, manifest_total: int | None = None) -> None:
        self.initialize()
        now = time.time()
        with self._connect() as conn:
            conn.execute("DELETE FROM evidence_cards")
            conn.executemany(
                """
                INSERT INTO evidence_cards (
                  card_id, persona_id, doc_id, chunk_id, source_title, source_url,
                  source_locator, tags_json, keywords_json, quote_anchor, boundary_note,
                  text, trust_level, source_path, batch_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        card.card_id,
                        card.persona_id,
                        card.doc_id,
                        card.chunk_id,
                        card.source_title,
                        card.source_url,
                        card.source_locator,
                        dumps(card.tags),
                        dumps(card.keywords),
                        card.quote_anchor,
                        card.boundary_note,
                        card.text,
                        card.trust_level,
                        card.source_path,
                        card.batch_id,
                        now,
                    )
                    for card in cards
                ],
            )
            persona_counts = Counter(card.persona_id for card in cards)
            conn.execute(
                """
                INSERT INTO evidence_card_audit (
                  ts, action, card_id, persona_id, doc_id, detail_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    "sync",
                    "*",
                    "*",
                    "*",
                    dumps(
                        {
                            "card_count": len(cards),
                            "manifest_total": manifest_total,
                            "persona_counts": dict(persona_counts),
                        }
                    ),
                ),
            )

    def list_evidence_cards(
        self,
        *,
        persona_id: str | None = None,
        source_title: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        self.initialize()
        clauses: list[str] = []
        params: list[Any] = []
        if persona_id:
            clauses.append("persona_id = ?")
            params.append(persona_id)
        if source_title:
            clauses.append("source_title LIKE ?")
            params.append(f"%{source_title}%")
        if tag:
            clauses.append("(tags_json LIKE ? OR keywords_json LIKE ?)")
            params.extend([f"%{tag}%", f"%{tag}%"])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS count FROM evidence_cards {where}",
                params,
            ).fetchone()
            rows = conn.execute(
                f"""
                SELECT card_id, persona_id, doc_id, chunk_id, source_title, source_url,
                       source_locator, tags_json, keywords_json, quote_anchor,
                       boundary_note, text, trust_level, source_path, batch_id
                FROM evidence_cards
                {where}
                ORDER BY persona_id, card_id
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        return {
            "total": int(total_row["count"] if total_row else 0),
            "items": [self._evidence_card_row(row) for row in rows],
        }

    def evidence_card_stats(self) -> dict[str, Any]:
        self.initialize()
        with self._connect() as conn:
            total_cards = self._count(conn, "evidence_cards")
            persona_rows = conn.execute(
                """
                SELECT persona_id, COUNT(*) AS count
                FROM evidence_cards
                GROUP BY persona_id
                ORDER BY persona_id
                """
            ).fetchall()
            trust_rows = conn.execute(
                """
                SELECT trust_level, COUNT(*) AS count
                FROM evidence_cards
                GROUP BY trust_level
                ORDER BY trust_level
                """
            ).fetchall()
            source_title_count = conn.execute(
                "SELECT COUNT(DISTINCT source_title) AS count FROM evidence_cards"
            ).fetchone()
            audit_count = conn.execute(
                "SELECT COUNT(*) AS count FROM evidence_card_audit WHERE action = 'sync'"
            ).fetchone()
        return {
            "total_cards": total_cards,
            "by_persona": {row["persona_id"]: int(row["count"]) for row in persona_rows},
            "by_trust_level": {row["trust_level"]: int(row["count"]) for row in trust_rows},
            "source_title_count": int(source_title_count["count"] if source_title_count else 0),
            "audited_sync_events": int(audit_count["count"] if audit_count else 0),
        }

    def evidence_cards_for_chunk_ids(self, chunk_ids: list[str]) -> list[dict[str, Any]]:
        if not chunk_ids:
            return []
        self.initialize()
        placeholders = ",".join("?" for _ in chunk_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT card_id, persona_id, doc_id, chunk_id, source_title, source_locator,
                       tags_json, keywords_json, quote_anchor, boundary_note, trust_level
                FROM evidence_cards
                WHERE chunk_id IN ({placeholders})
                ORDER BY persona_id, card_id
                """,
                chunk_ids,
            ).fetchall()
        return [
            {
                "card_id": row["card_id"],
                "persona_id": row["persona_id"],
                "doc_id": row["doc_id"],
                "chunk_id": row["chunk_id"],
                "source_title": row["source_title"],
                "source_locator": row["source_locator"],
                "tags": loads(row["tags_json"]),
                "keywords": loads(row["keywords_json"]),
                "quote_anchor": row["quote_anchor"],
                "boundary_note": row["boundary_note"],
                "trust_level": row["trust_level"],
            }
            for row in rows
        ]

    def post_persona_alignment_stats(self) -> dict[str, Any]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT model, retrieval_trace_json
                FROM chat_events
                WHERE model LIKE '%post_persona_alignment%'
                   OR retrieval_trace_json LIKE '%浜烘牸鍚庡榻?'
                """
            ).fetchall()
        reason_counts: Counter[str] = Counter()
        event_rows = 0
        for row in rows:
            reasons = post_persona_alignment_reasons(
                model=row["model"],
                retrieval_trace=loads(row["retrieval_trace_json"]),
            )
            if not reasons:
                continue
            event_rows += 1
            reason_counts.update(reasons)
        return {
            "event_rows": event_rows,
            "reason_counts": dict(reason_counts),
        }

    def persona_first_stats(self) -> dict[str, Any]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT mode
                FROM chat_events
                WHERE mode LIKE 'persona_first%'
                """
            ).fetchall()
        mode_counts = Counter(str(row["mode"]) for row in rows)
        return {
            "event_rows": sum(mode_counts.values()),
            "mode_counts": dict(mode_counts),
        }

    def recent_retrievals(self, limit: int = 20) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT retrieval_id, ts, session_id, query, top_k, include_private, mode,
                       selected_chunk_ids_json, timings_json
                FROM retrieval_events
                ORDER BY ts DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "retrieval_id": row["retrieval_id"],
                "ts": row["ts"],
                "session_id": row["session_id"],
                "query": row["query"],
                "top_k": row["top_k"],
                "include_private": bool(row["include_private"]),
                "mode": row["mode"],
                "selected_chunk_ids": loads(row["selected_chunk_ids_json"]),
                "timings": loads(row["timings_json"]),
            }
            for row in rows
        ]

    def recent_eval_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, ts, status, mode, question_count, passed_count, failed_count,
                       metrics_json, message
                FROM eval_runs
                ORDER BY ts DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "ts": row["ts"],
                "status": row["status"],
                "mode": row["mode"],
                "question_count": row["question_count"],
                "passed_count": row["passed_count"],
                "failed_count": row["failed_count"],
                "metrics": loads(row["metrics_json"]),
                "message": row["message"],
            }
            for row in rows
        ]

    def eval_run(self, run_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT run_id, ts, status, mode, question_count, passed_count, failed_count,
                       metrics_json, message
                FROM eval_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "ts": row["ts"],
            "status": row["status"],
            "mode": row["mode"],
            "question_count": row["question_count"],
            "passed_count": row["passed_count"],
            "failed_count": row["failed_count"],
            "metrics": loads(row["metrics_json"]),
            "message": row["message"],
        }

    def eval_results(self, run_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT result_json
                FROM eval_case_results
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        return [loads(row["result_json"]) for row in rows]

    def recent_chats(self, limit: int = 20) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT request_id, session_id, persona_id, ts, message, answer, model, mode, confidence,
                       citation_ids_json, timings_json
                FROM chat_events
                ORDER BY ts DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "request_id": row["request_id"],
                "session_id": row["session_id"],
                "persona_id": row["persona_id"],
                "ts": row["ts"],
                "message": row["message"],
                "answer": row["answer"],
                "model": row["model"],
                "mode": row["mode"],
                "confidence": row["confidence"],
                "citation_ids": loads(row["citation_ids_json"]),
                "timings": loads(row["timings_json"]),
            }
            for row in rows
        ]

    def recent_chat_turns(
        self,
        *,
        user_id: str = "dev-auth-disabled",
        session_id: str,
        persona_id: str | None = None,
        limit: int = 6,
    ) -> list[ConversationTurn]:
        self.initialize()
        params: list[Any] = [user_id, session_id]
        persona_filter = ""
        if persona_id:
            persona_filter = "AND persona_id = ?"
            params.append(persona_id)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT ts, persona_id, message, answer
                FROM chat_events
                WHERE user_id = ?
                  AND session_id = ?
                {persona_filter}
                ORDER BY ts DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            ConversationTurn(
                message=row["message"],
                answer=row["answer"],
                ts=row["ts"],
                persona_id=row["persona_id"],
            )
            for row in reversed(rows)
        ]

    def chat_session_summary(
        self,
        *,
        user_id: str = "dev-auth-disabled",
        session_id: str,
        persona_id: str,
    ) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT summary_json, summary_message_count, summary_updated_at
                FROM chat_sessions
                WHERE user_id = ?
                  AND session_id = ?
                  AND persona_id = ?
                  AND status = 'active'
                """,
                (user_id, session_id, persona_id),
            ).fetchone()
        if row is None or not row["summary_json"]:
            return None
        try:
            parsed = loads(row["summary_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(parsed, dict):
            return None
        parsed.setdefault("summarized_message_count", int(row["summary_message_count"] or 0))
        parsed.setdefault("updated_at", float(row["summary_updated_at"] or 0.0))
        return parsed

    def create_user_persona(
        self,
        *,
        owner_user_id: str,
        name: str,
        persona_id: str | None = None,
        avatar_url: str = "",
        avatar_label: str | None = None,
        short_description: str = "",
        description: str = "",
        identity_tags: list[str] | None = None,
        web_search_enabled: bool = False,
        runtime_status: str = "draft",
        is_public: bool = False,
    ) -> dict[str, Any]:
        self.initialize()
        now = time.time()
        created_persona_id = persona_id or f"user_persona_{uuid.uuid4().hex}"
        clean_name = re.sub(r"\s+", " ", name).strip() or "未命名分身"
        label = (avatar_label or clean_name[:1] or "分")[:4]
        published_at = now if is_public else None
        with self._connect() as conn:
            conn.execute(
                """
                  INSERT INTO user_personas (
                    persona_id, owner_user_id, name, avatar_url, avatar_label,
                    short_description, description, identity_tags_json, runtime_status,
                    web_search_enabled, is_public, score, created_at, updated_at, published_at
                  )
                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                  """,
                  (
                      created_persona_id,
                      owner_user_id,
                      clean_name,
                    avatar_url.strip(),
                    label,
                      short_description.strip(),
                      description.strip(),
                      dumps(identity_tags or []),
                      runtime_status,
                      int(web_search_enabled),
                      int(is_public),
                      now,
                      now,
                    published_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM user_personas WHERE persona_id = ?",
                (created_persona_id,),
            ).fetchone()
        return self._user_persona_row(row)

    def get_user_persona(self, persona_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_personas WHERE persona_id = ?",
                (persona_id,),
            ).fetchone()
        return self._user_persona_row(row) if row is not None else None

    def list_user_personas(self, *, owner_user_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM user_personas
                WHERE owner_user_id = ?
                ORDER BY updated_at DESC, created_at DESC
                """,
                (owner_user_id,),
            ).fetchall()
        return [self._user_persona_row(row) for row in rows]

    def search_public_user_personas(
        self,
        *,
        query: str = "",
        current_user_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        self.initialize()
        clean_query = re.sub(r"\s+", " ", query).strip().lower()
        clauses = ["is_public = 1", "runtime_status = 'ready'"]
        params: list[Any] = []
        if clean_query:
            like = f"%{clean_query}%"
            clauses.append(
                "(LOWER(name) LIKE ? OR LOWER(short_description) LIKE ? "
                "OR LOWER(description) LIKE ? OR LOWER(identity_tags_json) LIKE ?)"
            )
            params.extend([like, like, like, like])
        where = " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM user_personas
                WHERE {where}
                ORDER BY score DESC, COALESCE(published_at, updated_at) DESC, updated_at DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
        personas = [self._user_persona_row(row) for row in rows]
        if current_user_id:
            return [persona for persona in personas if persona["owner_user_id"] != current_user_id]
        return personas

    def count_public_user_personas(self, *, query: str = "") -> int:
        self.initialize()
        clean_query = re.sub(r"\s+", " ", query).strip().lower()
        clauses, params = self._public_user_persona_search_clauses(clean_query)
        where = " AND ".join(clauses)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM user_personas
                WHERE {where}
                """,
                params,
            ).fetchone()
        return int(row["count"] if row else 0)

    def list_public_user_personas(
        self,
        *,
        query: str = "",
        limit: int = 24,
        offset: int = 0,
        sort: str = "published_at",
    ) -> list[dict[str, Any]]:
        self.initialize()
        clean_query = re.sub(r"\s+", " ", query).strip().lower()
        clauses, params = self._public_user_persona_search_clauses(clean_query)
        where = " AND ".join(clauses)
        order_by = (
            "score DESC, COALESCE(published_at, updated_at) DESC, updated_at DESC"
            if sort == "score"
            else "COALESCE(published_at, updated_at) DESC, score DESC, updated_at DESC"
        )
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM user_personas
                WHERE {where}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        return [self._user_persona_row(row) for row in rows]

    def top_public_user_personas(
        self,
        *,
        current_user_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = []
        owner_clause = ""
        if current_user_id:
            owner_clause = "AND owner_user_id != ?"
            params.append(current_user_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM user_personas
                WHERE is_public = 1
                  AND runtime_status = 'ready'
                  {owner_clause}
                ORDER BY score DESC, COALESCE(published_at, updated_at) DESC, updated_at DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
        return [self._user_persona_row(row) for row in rows]

    def publish_user_persona(self, *, owner_user_id: str, persona_id: str) -> dict[str, Any] | None:
        self.initialize()
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_personas WHERE owner_user_id = ? AND persona_id = ?",
                (owner_user_id, persona_id),
            ).fetchone()
            if row is None:
                return None
            if row["runtime_status"] != "ready":
                return self._user_persona_row(row)
            conn.execute(
                """
                UPDATE user_personas
                SET is_public = 1,
                    published_at = COALESCE(published_at, ?),
                    updated_at = ?
                WHERE owner_user_id = ? AND persona_id = ?
                """,
                (now, now, owner_user_id, persona_id),
            )
            updated = conn.execute(
                "SELECT * FROM user_personas WHERE owner_user_id = ? AND persona_id = ?",
                (owner_user_id, persona_id),
            ).fetchone()
        return self._user_persona_row(updated) if updated is not None else None

    def unpublish_user_persona(self, *, owner_user_id: str, persona_id: str) -> dict[str, Any] | None:
        self.initialize()
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_personas WHERE owner_user_id = ? AND persona_id = ?",
                (owner_user_id, persona_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE user_personas
                SET is_public = 0,
                    updated_at = ?
                WHERE owner_user_id = ? AND persona_id = ?
                """,
                (now, owner_user_id, persona_id),
            )
            updated = conn.execute(
                "SELECT * FROM user_personas WHERE owner_user_id = ? AND persona_id = ?",
                (owner_user_id, persona_id),
            ).fetchone()
        return self._user_persona_row(updated) if updated is not None else None

    def _public_user_persona_search_clauses(self, clean_query: str) -> tuple[list[str], list[Any]]:
        clauses = ["is_public = 1", "runtime_status = 'ready'"]
        params: list[Any] = []
        if clean_query:
            like = f"%{clean_query}%"
            clauses.append(
                "(LOWER(name) LIKE ? OR LOWER(short_description) LIKE ? "
                "OR LOWER(description) LIKE ? OR LOWER(identity_tags_json) LIKE ?)"
            )
            params.extend([like, like, like, like])
        return clauses, params

    def create_user_persona_build(
        self,
        *,
        build_id: str,
        persona_id: str,
        owner_user_id: str,
        input_hash: str,
        model: str,
        artifact_dir: str,
    ) -> dict[str, Any]:
        self.initialize()
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_persona_builds (
                  build_id, persona_id, owner_user_id, status, phase, progress,
                  input_hash, model, artifact_dir, created_at, updated_at
                )
                VALUES (?, ?, ?, 'queued', 'queued', 0, ?, ?, ?, ?, ?)
                """,
                (build_id, persona_id, owner_user_id, input_hash, model, artifact_dir, now, now),
            )
            conn.execute(
                """
                UPDATE user_personas
                SET runtime_status = 'building',
                    build_id = ?,
                    build_artifact_dir = ?,
                    build_error = '',
                    updated_at = ?
                WHERE owner_user_id = ? AND persona_id = ?
                """,
                (build_id, artifact_dir, now, owner_user_id, persona_id),
            )
            row = conn.execute(
                "SELECT * FROM user_persona_builds WHERE build_id = ?",
                (build_id,),
            ).fetchone()
        return self._user_persona_build_row(row)

    def update_user_persona_build(
        self,
        *,
        build_id: str,
        status: str | None = None,
        phase: str | None = None,
        progress: float | None = None,
        artifact_dir: str | None = None,
        source_depth: str | None = None,
        evidence_card_count: int | None = None,
        error: str | None = None,
        quality_summary: dict[str, Any] | None = None,
        finished: bool = False,
    ) -> dict[str, Any] | None:
        self.initialize()
        updates: list[str] = ["updated_at = ?"]
        now = time.time()
        params: list[Any] = [now]
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if phase is not None:
            updates.append("phase = ?")
            params.append(phase)
        if progress is not None:
            updates.append("progress = ?")
            params.append(max(0.0, min(1.0, float(progress))))
        if artifact_dir is not None:
            updates.append("artifact_dir = ?")
            params.append(artifact_dir)
        if source_depth is not None:
            updates.append("source_depth = ?")
            params.append(source_depth)
        if evidence_card_count is not None:
            updates.append("evidence_card_count = ?")
            params.append(int(evidence_card_count))
        if error is not None:
            updates.append("error = ?")
            params.append(error)
        if quality_summary is not None:
            updates.append("quality_summary_json = ?")
            params.append(dumps(quality_summary))
        if finished:
            updates.append("finished_at = ?")
            params.append(now)
        params.append(build_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE user_persona_builds SET {', '.join(updates)} WHERE build_id = ?",
                params,
            )
            row = conn.execute(
                "SELECT * FROM user_persona_builds WHERE build_id = ?",
                (build_id,),
            ).fetchone()
        return self._user_persona_build_row(row) if row is not None else None

    def latest_user_persona_build(
        self,
        *,
        owner_user_id: str,
        persona_id: str,
    ) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM user_persona_builds
                WHERE owner_user_id = ? AND persona_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (owner_user_id, persona_id),
            ).fetchone()
        return self._user_persona_build_row(row) if row is not None else None

    def get_user_persona_build(
        self,
        *,
        owner_user_id: str,
        persona_id: str,
        build_id: str,
    ) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM user_persona_builds
                WHERE owner_user_id = ? AND persona_id = ? AND build_id = ?
                """,
                (owner_user_id, persona_id, build_id),
            ).fetchone()
        return self._user_persona_build_row(row) if row is not None else None

    def update_user_persona_after_build(
        self,
        *,
        owner_user_id: str,
        persona_id: str,
        runtime_status: str,
        short_description: str = "",
        identity_tags: list[str] | None = None,
        source_depth: str = "",
        evidence_card_count: int = 0,
        corpus_path: str = "",
        build_error: str = "",
    ) -> dict[str, Any] | None:
        self.initialize()
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_personas WHERE owner_user_id = ? AND persona_id = ?",
                (owner_user_id, persona_id),
            ).fetchone()
            if row is None:
                return None
            next_short_description = short_description.strip() or row["short_description"] or ""
            next_identity_tags = identity_tags if identity_tags is not None else loads(row["identity_tags_json"] or "[]")
            conn.execute(
                """
                UPDATE user_personas
                SET runtime_status = ?,
                    short_description = ?,
                    identity_tags_json = ?,
                    source_depth = ?,
                    evidence_card_count = ?,
                    corpus_path = ?,
                    build_error = ?,
                    updated_at = ?
                WHERE owner_user_id = ? AND persona_id = ?
                """,
                (
                    runtime_status,
                    next_short_description,
                    dumps(next_identity_tags),
                    source_depth,
                    int(evidence_card_count),
                    corpus_path,
                    build_error,
                    now,
                    owner_user_id,
                    persona_id,
                ),
            )
            updated = conn.execute(
                "SELECT * FROM user_personas WHERE owner_user_id = ? AND persona_id = ?",
                (owner_user_id, persona_id),
            ).fetchone()
        return self._user_persona_row(updated) if updated is not None else None

    def create_user_persona_web_research_run(
        self,
        *,
        run_id: str,
        owner_user_id: str,
        persona_id: str,
        provider: str,
        artifact_dir: str,
    ) -> dict[str, Any]:
        self.initialize()
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_persona_web_research_runs (
                  run_id, persona_id, owner_user_id, status, phase, progress,
                  provider, artifact_dir, created_at, updated_at
                )
                VALUES (?, ?, ?, 'queued', 'queued', 0, ?, ?, ?, ?)
                """,
                (run_id, persona_id, owner_user_id, provider, artifact_dir, now, now),
            )
            row = conn.execute(
                "SELECT * FROM user_persona_web_research_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return self._user_persona_web_research_run_row(row)

    def update_user_persona_web_research_run(
        self,
        *,
        run_id: str,
        status: str | None = None,
        phase: str | None = None,
        progress: float | None = None,
        query_count: int | None = None,
        source_count: int | None = None,
        included_source_count: int | None = None,
        error: str | None = None,
        quality_summary: dict[str, Any] | None = None,
        finished: bool = False,
    ) -> dict[str, Any] | None:
        self.initialize()
        updates: list[str] = ["updated_at = ?"]
        now = time.time()
        params: list[Any] = [now]
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if phase is not None:
            updates.append("phase = ?")
            params.append(phase)
        if progress is not None:
            updates.append("progress = ?")
            params.append(max(0.0, min(1.0, float(progress))))
        if query_count is not None:
            updates.append("query_count = ?")
            params.append(int(query_count))
        if source_count is not None:
            updates.append("source_count = ?")
            params.append(int(source_count))
        if included_source_count is not None:
            updates.append("included_source_count = ?")
            params.append(int(included_source_count))
        if error is not None:
            updates.append("error = ?")
            params.append(error)
        if quality_summary is not None:
            updates.append("quality_summary_json = ?")
            params.append(dumps(quality_summary))
        if finished:
            updates.append("finished_at = ?")
            params.append(now)
        params.append(run_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE user_persona_web_research_runs SET {', '.join(updates)} WHERE run_id = ?",
                params,
            )
            row = conn.execute(
                "SELECT * FROM user_persona_web_research_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return self._user_persona_web_research_run_row(row) if row is not None else None

    def latest_user_persona_web_research_run(
        self,
        *,
        owner_user_id: str,
        persona_id: str,
        succeeded_only: bool = False,
    ) -> dict[str, Any] | None:
        self.initialize()
        status_clause = "AND status = 'succeeded'" if succeeded_only else ""
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT *
                FROM user_persona_web_research_runs
                WHERE owner_user_id = ? AND persona_id = ?
                  {status_clause}
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (owner_user_id, persona_id),
            ).fetchone()
        return self._user_persona_web_research_run_row(row) if row is not None else None

    def get_user_persona_web_research_run(
        self,
        *,
        owner_user_id: str,
        persona_id: str,
        run_id: str,
    ) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM user_persona_web_research_runs
                WHERE owner_user_id = ? AND persona_id = ? AND run_id = ?
                """,
                (owner_user_id, persona_id, run_id),
            ).fetchone()
        return self._user_persona_web_research_run_row(row) if row is not None else None

    def replace_user_persona_web_sources(
        self,
        *,
        run_id: str,
        sources: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self.initialize()
        now = time.time()
        with self._connect() as conn:
            conn.execute("DELETE FROM user_persona_web_sources WHERE run_id = ?", (run_id,))
            conn.executemany(
                """
                INSERT INTO user_persona_web_sources (
                  source_id, run_id, persona_id, owner_user_id, url, canonical_url,
                  title, source_family, channel, trust_level, score, status,
                  content_hash, artifact_path, locator, warning, metadata_json,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        source["source_id"],
                        run_id,
                        source["persona_id"],
                        source["owner_user_id"],
                        source["url"],
                        source.get("canonical_url") or "",
                        source.get("title") or "",
                        source.get("source_family") or "",
                        source.get("channel") or "",
                        source.get("trust_level") or "",
                        float(source.get("score") or 0),
                        source.get("status") or "candidate",
                        source.get("content_hash") or "",
                        source.get("artifact_path") or "",
                        source.get("locator") or "",
                        source.get("warning") or "",
                        dumps(source.get("metadata") or {}),
                        now,
                        now,
                    )
                    for source in sources
                ],
            )
            rows = conn.execute(
                "SELECT * FROM user_persona_web_sources WHERE run_id = ? ORDER BY score DESC",
                (run_id,),
            ).fetchall()
        return [self._user_persona_web_source_row(row) for row in rows]

    def list_user_persona_web_sources(
        self,
        *,
        owner_user_id: str,
        persona_id: str,
        run_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        self.initialize()
        clauses = ["owner_user_id = ?", "persona_id = ?"]
        params: list[Any] = [owner_user_id, persona_id]
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM user_persona_web_sources
                WHERE {' AND '.join(clauses)}
                ORDER BY score DESC, created_at ASC
                """,
                params,
            ).fetchall()
        return [self._user_persona_web_source_row(row) for row in rows]

    def set_user_persona_web_source_status(
        self,
        *,
        owner_user_id: str,
        persona_id: str,
        source_id: str,
        status: str,
    ) -> dict[str, Any] | None:
        self.initialize()
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM user_persona_web_sources
                WHERE owner_user_id = ? AND persona_id = ? AND source_id = ?
                """,
                (owner_user_id, persona_id, source_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE user_persona_web_sources
                SET status = ?, updated_at = ?
                WHERE owner_user_id = ? AND persona_id = ? AND source_id = ?
                """,
                (status, now, owner_user_id, persona_id, source_id),
            )
            updated = conn.execute(
                "SELECT * FROM user_persona_web_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        return self._user_persona_web_source_row(updated) if updated is not None else None

    def count_user_persona_files(self, *, owner_user_id: str, persona_id: str) -> int:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM user_persona_files
                WHERE owner_user_id = ? AND persona_id = ?
                """,
                (owner_user_id, persona_id),
            ).fetchone()
        return int(row["count"] if row else 0)

    def create_user_persona_file(
        self,
        *,
        file_id: str,
        persona_id: str,
        owner_user_id: str,
        original_filename: str,
        stored_filename: str,
        mime_type: str,
        extension: str,
        size_bytes: int,
        sha256: str,
        raw_path: str,
        upload_status: str = "uploaded",
        parse_status: str = "queued",
    ) -> dict[str, Any]:
        self.initialize()
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_persona_files (
                  file_id, persona_id, owner_user_id, original_filename, stored_filename,
                  mime_type, extension, size_bytes, sha256, upload_status, parse_status,
                  raw_path, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    persona_id,
                    owner_user_id,
                    original_filename,
                    stored_filename,
                    mime_type,
                    extension,
                    size_bytes,
                    sha256,
                    upload_status,
                    parse_status,
                    raw_path,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM user_persona_files WHERE file_id = ?",
                (file_id,),
            ).fetchone()
        return self._user_persona_file_row(row)

    def update_user_persona_file_parse_result(
        self,
        *,
        file_id: str,
        parse_status: str,
        parser_chain: list[str] | None = None,
        quality_score: float | None = None,
        warnings: list[str] | None = None,
        error_message: str = "",
        parsed_markdown_path: str = "",
        blocks_path: str = "",
        provenance_path: str = "",
        diagnostics_path: str = "",
        page_count: int | None = None,
    ) -> dict[str, Any] | None:
        self.initialize()
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE user_persona_files
                SET parse_status = ?,
                    parser_chain_json = ?,
                    quality_score = ?,
                    warnings_json = ?,
                    error_message = ?,
                    parsed_markdown_path = ?,
                    blocks_path = ?,
                    provenance_path = ?,
                    diagnostics_path = ?,
                    page_count = ?,
                    updated_at = ?
                WHERE file_id = ?
                """,
                (
                    parse_status,
                    dumps(parser_chain or []),
                    quality_score if quality_score is not None else 0.0,
                    dumps(warnings or []),
                    error_message,
                    parsed_markdown_path,
                    blocks_path,
                    provenance_path,
                    diagnostics_path,
                    page_count,
                    now,
                    file_id,
                ),
            )
            row = conn.execute(
                "SELECT * FROM user_persona_files WHERE file_id = ?",
                (file_id,),
            ).fetchone()
        return self._user_persona_file_row(row) if row is not None else None

    def set_user_persona_file_parse_status(
        self,
        *,
        file_id: str,
        parse_status: str,
        error_message: str = "",
    ) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE user_persona_files
                SET parse_status = ?, error_message = ?, updated_at = ?
                WHERE file_id = ?
                """,
                (parse_status, error_message, time.time(), file_id),
            )

    def list_user_persona_files(
        self,
        *,
        owner_user_id: str,
        persona_id: str,
    ) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM user_persona_files
                WHERE owner_user_id = ? AND persona_id = ?
                ORDER BY created_at ASC
                """,
                (owner_user_id, persona_id),
            ).fetchall()
        return [self._user_persona_file_row(row) for row in rows]

    def get_user_persona_file(
        self,
        *,
        owner_user_id: str,
        persona_id: str,
        file_id: str,
    ) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM user_persona_files
                WHERE owner_user_id = ? AND persona_id = ? AND file_id = ?
                """,
                (owner_user_id, persona_id, file_id),
            ).fetchone()
        return self._user_persona_file_row(row) if row is not None else None

    def delete_user_persona_file(
        self,
        *,
        owner_user_id: str,
        persona_id: str,
        file_id: str,
    ) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM user_persona_files
                WHERE owner_user_id = ? AND persona_id = ? AND file_id = ?
                """,
                (owner_user_id, persona_id, file_id),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                DELETE FROM user_persona_files
                WHERE owner_user_id = ? AND persona_id = ? AND file_id = ?
                """,
                (owner_user_id, persona_id, file_id),
            )
        return self._user_persona_file_row(row)

    def record_persona_score_event(
        self,
        *,
        user_id: str,
        request_id: str,
        persona_id: str,
        issue: str,
    ) -> int:
        score_delta = 2 if issue == "good" else -1 if issue == "other" else 0
        if score_delta == 0:
            return 0
        self.initialize()
        now = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO persona_score_events (
                  user_id, request_id, persona_id, issue, score_delta, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, request_id, persona_id, issue, score_delta, now),
            )
            if cursor.rowcount != 1:
                return 0
            conn.execute(
                """
                UPDATE user_personas
                SET score = score + ?,
                    updated_at = updated_at
                WHERE persona_id = ?
                """,
                (score_delta, persona_id),
            )
        return score_delta

    def persona_score(self, persona_id: str) -> int:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(score_delta), 0) AS score
                FROM persona_score_events
                WHERE persona_id = ?
                """,
                (persona_id,),
            ).fetchone()
        return int(row["score"] if row else 0)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _count(self, conn: sqlite3.Connection, table: str) -> int:
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        return int(row["count"])

    def _eval_case_row(self, run_id: str, ts: float, result: EvalCaseResult) -> tuple[Any, ...]:
        return (
            run_id,
            result.case.id,
            ts,
            int(result.metrics.passed),
            result.case.question,
            dumps(result.case.expected_sources),
            dumps(result.retrieved_doc_ids),
            dumps(result.selected_chunk_ids),
            result.answer,
            dumps(result.metrics.model_dump()),
            dumps(result.model_dump()),
        )

    def _evidence_card_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "card_id": row["card_id"],
            "persona_id": row["persona_id"],
            "doc_id": row["doc_id"],
            "chunk_id": row["chunk_id"],
            "source_title": row["source_title"],
            "source_url": row["source_url"],
            "source_locator": row["source_locator"],
            "tags": loads(row["tags_json"]),
            "keywords": loads(row["keywords_json"]),
            "quote_anchor": row["quote_anchor"],
            "boundary_note": row["boundary_note"],
            "text": row["text"],
            "trust_level": row["trust_level"],
            "source_path": row["source_path"],
            "batch_id": row["batch_id"],
        }

    def _session_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "session_id": row["session_id"],
            "user_id": row["user_id"],
            "persona_id": row["persona_id"],
            "title": row["title"] or "未命名会话",
            "created_at": float(row["created_at"]),
            "last_seen_at": float(row["last_seen_at"]),
            "message_count": int(row["message_count"]),
            "last_message_preview": row["last_message_preview"] or "",
            "status": row["status"] or "active",
            "archived_at": float(row["archived_at"]) if row["archived_at"] is not None else None,
            "deleted_at": float(row["deleted_at"]) if row["deleted_at"] is not None else None,
        }

    def _user_persona_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "persona_id": row["persona_id"],
            "owner_user_id": row["owner_user_id"],
            "name": row["name"],
            "avatar_url": row["avatar_url"] or None,
            "avatar_label": row["avatar_label"] or "分",
            "short_description": row["short_description"] or "",
            "description": row["description"] or "",
            "identity_tags": loads(row["identity_tags_json"] or "[]"),
            "web_search_enabled": bool(row["web_search_enabled"]) if "web_search_enabled" in row.keys() else False,
            "runtime_status": row["runtime_status"] or "draft",
            "is_public": bool(row["is_public"]),
            "score": int(row["score"] or 0),
            "build_id": row["build_id"] or "",
            "build_artifact_dir": row["build_artifact_dir"] or "",
            "corpus_path": row["corpus_path"] or "",
            "source_depth": row["source_depth"] or "",
            "evidence_card_count": int(row["evidence_card_count"] or 0),
            "build_error": row["build_error"] or "",
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "published_at": float(row["published_at"]) if row["published_at"] is not None else None,
        }

    def _user_persona_build_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "build_id": row["build_id"],
            "persona_id": row["persona_id"],
            "owner_user_id": row["owner_user_id"],
            "status": row["status"],
            "phase": row["phase"],
            "progress": float(row["progress"] or 0),
            "input_hash": row["input_hash"] or "",
            "model": row["model"] or "",
            "artifact_dir": row["artifact_dir"] or "",
            "source_depth": row["source_depth"] or "",
            "evidence_card_count": int(row["evidence_card_count"] or 0),
            "error": row["error"] or "",
            "quality_summary": loads(row["quality_summary_json"] or "{}"),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "finished_at": float(row["finished_at"]) if row["finished_at"] is not None else None,
        }

    def _user_persona_web_research_run_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "persona_id": row["persona_id"],
            "owner_user_id": row["owner_user_id"],
            "status": row["status"],
            "phase": row["phase"],
            "progress": float(row["progress"] or 0),
            "provider": row["provider"] or "",
            "artifact_dir": row["artifact_dir"] or "",
            "query_count": int(row["query_count"] or 0),
            "source_count": int(row["source_count"] or 0),
            "included_source_count": int(row["included_source_count"] or 0),
            "error": row["error"] or "",
            "quality_summary": loads(row["quality_summary_json"] or "{}"),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "finished_at": float(row["finished_at"]) if row["finished_at"] is not None else None,
        }

    def _user_persona_web_source_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "source_id": row["source_id"],
            "run_id": row["run_id"],
            "persona_id": row["persona_id"],
            "owner_user_id": row["owner_user_id"],
            "url": row["url"],
            "canonical_url": row["canonical_url"] or "",
            "title": row["title"] or "",
            "source_family": row["source_family"] or "",
            "channel": row["channel"] or "",
            "trust_level": row["trust_level"] or "",
            "score": float(row["score"] or 0),
            "status": row["status"] or "candidate",
            "content_hash": row["content_hash"] or "",
            "artifact_path": row["artifact_path"] or "",
            "locator": row["locator"] or "",
            "warning": row["warning"] or "",
            "metadata": loads(row["metadata_json"] or "{}"),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    def _user_persona_file_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "file_id": row["file_id"],
            "persona_id": row["persona_id"],
            "owner_user_id": row["owner_user_id"],
            "original_filename": row["original_filename"],
            "stored_filename": row["stored_filename"],
            "mime_type": row["mime_type"],
            "extension": row["extension"],
            "size_bytes": int(row["size_bytes"]),
            "sha256": row["sha256"],
            "upload_status": row["upload_status"],
            "parse_status": row["parse_status"],
            "parser_chain": loads(row["parser_chain_json"] or "[]"),
            "quality_score": float(row["quality_score"] or 0),
            "warnings": loads(row["warnings_json"] or "[]"),
            "error_message": row["error_message"] or "",
            "raw_path": row["raw_path"],
            "parsed_markdown_path": row["parsed_markdown_path"] or "",
            "blocks_path": row["blocks_path"] or "",
            "provenance_path": row["provenance_path"] or "",
            "diagnostics_path": row["diagnostics_path"] or "",
            "page_count": int(row["page_count"]) if row["page_count"] is not None else None,
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    def _migrate_chat_session_metadata(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT session_id, user_id, persona_id, title, message_count, last_message_preview
            FROM chat_sessions
            """
        ).fetchall()
        for row in rows:
            needs_backfill = (
                not row["persona_id"]
                or row["persona_id"] == "local_persona"
                or not row["title"]
                or int(row["message_count"] or 0) == 0
                or not row["last_message_preview"]
            )
            if not needs_backfill:
                continue
            events = conn.execute(
                """
                SELECT persona_id, message, ts
                FROM chat_events
                WHERE session_id = ? AND user_id = ?
                ORDER BY ts ASC
                """,
                (row["session_id"], row["user_id"]),
            ).fetchall()
            if not events:
                continue
            first_event = events[0]
            last_event = events[-1]
            conn.execute(
                """
                UPDATE chat_sessions
                SET persona_id = ?,
                    title = ?,
                    message_count = ?,
                    last_message_preview = ?,
                    last_seen_at = MAX(last_seen_at, ?)
                WHERE session_id = ?
                """,
                (
                    first_event["persona_id"] or row["persona_id"] or "local_persona",
                    row["title"] or title_from_user_message(first_event["message"]),
                    len(events),
                    preview_from_user_message(last_event["message"]),
                    float(last_event["ts"]),
                    row["session_id"],
                ),
            )

    def _delete_stale_rows(
        self,
        conn: sqlite3.Connection,
        table: str,
        key_column: str,
        current_ids: list[str],
    ) -> None:
        if not current_ids:
            conn.execute(f"DELETE FROM {table}")
            return
        placeholders = ",".join("?" for _ in current_ids)
        conn.execute(
            f"DELETE FROM {table} WHERE {key_column} NOT IN ({placeholders})",
            current_ids,
        )

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        *,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value: str) -> Any:
    return json.loads(value)


def post_persona_alignment_reasons(*, model: str, retrieval_trace: dict[str, Any]) -> list[str]:
    notes = retrieval_trace.get("notes", []) if isinstance(retrieval_trace, dict) else []
    reasons: list[str] = []
    for note in notes:
        if not isinstance(note, str):
            continue
        if "post_persona_alignment" not in note and "人格后对齐" not in note:
            continue
        match = re.search(r"[（(]([^）)]+)[）)]", note)
        reasons.append(match.group(1) if match else "unknown")
    if not reasons and "post_persona_alignment" in model:
        reasons.append("unknown")
    return reasons


def normalize_session_title(text: str, *, limit: int = 34) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return ""
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def title_from_user_message(message: str) -> str:
    return normalize_session_title(message) or "未命名会话"


def is_placeholder_session_title(title: str | None) -> bool:
    return not (title or "").strip() or title in {"未命名会话", "未命名对话"}


def preview_from_user_message(message: str, *, limit: int = 72) -> str:
    clean = re.sub(r"\s+", " ", message).strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"
