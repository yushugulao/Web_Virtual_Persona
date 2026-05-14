from __future__ import annotations

from pydantic import BaseModel, Field


class BrowserAcceptancePersona(BaseModel):
    persona_id: str
    display_name: str


class BrowserAcceptanceCategory(BaseModel):
    category_id: str
    label: str
    acceptance_focus: list[str] = Field(default_factory=list)
    feedback_labels: list[str] = Field(default_factory=list)
    promotion_target: str


class BrowserAcceptanceCase(BaseModel):
    case_id: str
    persona_id: str
    category_id: str
    prompt: str
    expected_behavior: str
    watch_for: list[str] = Field(default_factory=list)


class BrowserAcceptanceCaseFeedback(BaseModel):
    matched_feedback_count: int = 0
    negative_feedback_count: int = 0
    positive_feedback_count: int = 0
    issue_counts: dict[str, int] = Field(default_factory=dict)
    latest_feedback_id: str | None = None
    latest_issue: str | None = None
    latest_severity: str | None = None
    latest_created_at: str | None = None


class BrowserAcceptanceMatrixResponse(BaseModel):
    schema_version: str
    description: str
    default_thinking_effort: str
    personas: list[BrowserAcceptancePersona]
    categories: list[BrowserAcceptanceCategory]
    cases: list[BrowserAcceptanceCase]
    total_cases: int
    filtered_cases: int
    by_persona: dict[str, int]
    by_category: dict[str, int]
    matched_feedback_records: int = 0
    tested_cases: int = 0
    negative_cases: int = 0
    positive_cases: int = 0
    case_feedback: dict[str, BrowserAcceptanceCaseFeedback] = Field(default_factory=dict)
