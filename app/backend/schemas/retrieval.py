from pydantic import BaseModel, Field

from app.backend.schemas.common import Citation, TimingBreakdown


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=6, ge=1, le=20)
    include_private: bool = False
    session_id: str | None = None
    user_id: str | None = None
    persona_id: str = "local_persona"


class RetrievalTrace(BaseModel):
    original_query: str
    persona_id: str = "local_persona"
    requested_persona_id: str | None = None
    rewritten_queries: list[str] = []
    candidates: list[Citation] = []
    selected_chunk_ids: list[str] = []
    notes: list[str] = []


class RetrieveResponse(BaseModel):
    retrieval_id: str
    query: str
    citations: list[Citation]
    trace: RetrievalTrace
    timings: TimingBreakdown
