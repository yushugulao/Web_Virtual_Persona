from __future__ import annotations

from pathlib import Path

from app.backend.memory.memory_store import MemoryStore
from app.backend.schemas.memory import MemoryItem


def retrieve_approved_memories(
    *,
    sqlite_path: Path,
    user_id: str = "dev-auth-disabled",
    session_id: str = "default-session",
    persona_id: str,
    query: str,
    limit: int = 5,
    include_user_global: bool = False,
) -> list[MemoryItem]:
    return MemoryStore(sqlite_path).retrieve_approved(
        user_id=user_id,
        session_id=session_id,
        persona_id=persona_id,
        query=query,
        limit=limit,
        include_user_global=include_user_global,
    )
