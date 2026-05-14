from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryCitation(BaseModel):
    memory_id: str
    user_id: str = "dev-auth-disabled"
    session_id: str = "default-session"
    persona_id: str
    scope: str
    memory_type: str
    content: str
    confidence: float = 1.0


class MemoryItem(BaseModel):
    id: str
    user_id: str = "dev-auth-disabled"
    session_id: str = "default-session"
    persona_id: str
    scope: str = "session"
    memory_type: str = "user_profile"
    status: str = "pending"
    content: str
    sensitivity: str = "normal"
    source: str = "explicit"
    tags: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    created_at: float
    updated_at: float
    expires_at: float | None = None


class MemoryListResponse(BaseModel):
    items: list[MemoryItem] = Field(default_factory=list)


class MemoryStatsResponse(BaseModel):
    total: int = 0
    by_persona: dict[str, int] = Field(default_factory=dict)
    by_session: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
    by_sensitivity: dict[str, int] = Field(default_factory=dict)
    by_persona_status: dict[str, dict[str, int]] = Field(default_factory=dict)
    current_session_total: int = 0
    current_session_approved: int = 0


class MemoryProposeRequest(BaseModel):
    content: str
    persona_id: str = "local_persona"
    session_id: str | None = None
    scope: str = "session"
    memory_type: str | None = None
    tags: list[str] = Field(default_factory=list)


class MemoryActionResponse(BaseModel):
    item: MemoryItem
    message: str
