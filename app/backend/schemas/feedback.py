from typing import Literal

from pydantic import BaseModel, Field


FeedbackIssue = Literal[
    "cardiness",
    "lecture",
    "too_long",
    "unnatural",
    "memory_error",
    "era_boundary_error",
    "fact_error",
    "good",
    "other",
]

FeedbackSeverity = Literal["low", "medium", "high"]


class PersonaTurnFeedbackRequest(BaseModel):
    persona_id: str = Field(min_length=1)
    persona_name: str | None = None
    session_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    acceptance_case_id: str | None = Field(default=None, max_length=120)
    user_message: str = Field(min_length=1, max_length=4000)
    assistant_answer: str = Field(min_length=1, max_length=8000)
    issue: FeedbackIssue
    severity: FeedbackSeverity = "medium"
    note: str = Field(default="", max_length=1000)
    thinking_effort: str | None = None
    mode: str | None = None
    model: str | None = None
    trace_notes: list[str] = Field(default_factory=list)
    citation_doc_ids: list[str] = Field(default_factory=list)
    citation_titles: list[str] = Field(default_factory=list)
    frontend_url: str | None = None


class PersonaTurnFeedbackRecord(PersonaTurnFeedbackRequest):
    feedback_id: str
    created_at: str


class PersonaTurnFeedbackResponse(BaseModel):
    feedback_id: str
    message: str
    record: PersonaTurnFeedbackRecord


class PersonaTurnFeedbackListResponse(BaseModel):
    records: list[PersonaTurnFeedbackRecord]


class PersonaTurnFeedbackStatsResponse(BaseModel):
    total: int
    negative_total: int
    positive_total: int
    invalid_line_count: int = 0
    by_issue: dict[str, int]
    by_persona: dict[str, int]
    by_severity: dict[str, int]
    by_persona_issue: dict[str, dict[str, int]]
    latest_records: list[PersonaTurnFeedbackRecord]
