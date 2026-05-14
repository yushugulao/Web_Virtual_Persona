from typing import Any

from pydantic import BaseModel, Field


class StoreCounts(BaseModel):
    documents: int
    chunks: int
    sessions: int
    retrieval_events: int
    chat_events: int
    eval_runs: int
    eval_case_results: int
    evidence_cards: int = 0
    evidence_card_audit: int = 0


class TraceListResponse(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
