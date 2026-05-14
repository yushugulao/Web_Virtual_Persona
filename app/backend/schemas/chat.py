from typing import Literal

from pydantic import BaseModel, Field

from app.backend.schemas.common import Citation, TimingBreakdown, VerificationResult
from app.backend.schemas.memory import MemoryCitation
from app.backend.schemas.retrieval import RetrievalTrace


class ChatMessage(BaseModel):
    role: str
    content: str


ThinkingEffort = Literal["low", "medium", "high"]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: list[ChatMessage] = Field(default_factory=list)
    session_id: str | None = None
    persona_id: str = "local_persona"
    thinking_effort: ThinkingEffort = "low"
    top_k: int = Field(default=6, ge=1, le=20)
    include_private: bool = False
    debug: bool = True


class HiddenThinkingEvent(BaseModel):
    event_id: str
    phase: str
    model: str
    provider: str
    source: str
    content: str
    elapsed_ms: float = 0.0
    sequence: int = 0


class VisibleAnswerSource(BaseModel):
    phase: str
    source: str
    model: str
    preview: str = ""
    elapsed_ms: float = 0.0


class ChatDiagnostics(BaseModel):
    enabled: bool = False
    hidden_thinking_events: list[HiddenThinkingEvent] = Field(default_factory=list)
    final_answer_source: str | None = None
    visible_answer_sources: list[VisibleAnswerSource] = Field(default_factory=list)
    thinking_budget: int | None = None
    thinking_tokens_observed: int | None = None
    thinking_budget_ratio: float | None = None
    thinking_budget_stop_reason: str | None = None
    thinking_budget_overshoot_tokens: int | None = None


class ChatResponse(BaseModel):
    answer: str
    mode: str
    confidence: str
    thinking_effort: ThinkingEffort = "low"
    follow_up_questions: list[str] = Field(default_factory=list)
    citations: list[Citation]
    memory_citations: list[MemoryCitation] = Field(default_factory=list)
    retrieval_trace: RetrievalTrace
    verification: VerificationResult = Field(default_factory=VerificationResult)
    timings: TimingBreakdown
    model: str
    request_id: str
    session_id: str
    diagnostics: ChatDiagnostics | None = None


class ChatSessionSummary(BaseModel):
    session_id: str
    user_id: str | None = None
    persona_id: str
    persona_name: str | None = None
    title: str
    created_at: float
    last_seen_at: float
    message_count: int = 0
    last_message_preview: str = ""
    status: Literal["active", "archived", "deleted"] = "active"
    archived_at: float | None = None
    deleted_at: float | None = None
    opening_message: str | None = None


class ChatSessionCreateRequest(BaseModel):
    persona_id: str = "local_persona"
    title: str | None = None


class ChatSessionMessage(BaseModel):
    id: str
    request_id: str
    session_id: str
    persona_id: str
    role: Literal["user", "assistant"]
    content: str
    ts: float
    model: str | None = None
    mode: str | None = None
    confidence: str | None = None
    diagnostics: ChatDiagnostics | None = None
    follow_up_questions: list[str] = Field(default_factory=list)


class ChatSessionMessagesResponse(BaseModel):
    session: ChatSessionSummary
    messages: list[ChatSessionMessage] = Field(default_factory=list)
