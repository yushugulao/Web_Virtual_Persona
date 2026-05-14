from pydantic import BaseModel, Field
from pathlib import Path
from typing import Literal

from app.backend.schemas.common import Citation


class EvalCase(BaseModel):
    id: str
    question: str
    category: str = "general"
    persona_id: str = "local_persona"
    expected_persona_id: str | None = None
    expected_sources: list[str] = Field(default_factory=list)
    expected_source_prefixes: list[str] = Field(default_factory=list)
    forbidden_sources: list[str] = Field(default_factory=list)
    forbidden_source_prefixes: list[str] = Field(default_factory=list)
    expected_keywords: list[str] = Field(default_factory=list)
    forbidden_keywords: list[str] = Field(default_factory=list)
    min_source_recall: float = Field(default=1.0, ge=0.0, le=1.0)
    min_citation_precision: float = Field(default=0.0, ge=0.0, le=1.0)
    require_top1_source_hit: bool = False
    min_keyword_coverage: float = Field(default=0.5, ge=0.0, le=1.0)
    min_evidence_overlap: float = Field(default=0.05, ge=0.0, le=1.0)
    expected_language: str | None = None
    should_abstain: bool = False
    notes: str = ""


class EvalRunRequest(BaseModel):
    questions: list[str] = Field(default_factory=list)
    case_ids: list[str] = Field(default_factory=list)
    questions_path: Path | None = None
    mode: str = "retrieval"
    top_k: int = Field(default=6, ge=1, le=20)
    include_private: bool = False
    include_results: bool = True
    thinking_effort: Literal["low", "medium", "high"] = "low"


class EvalCaseMetrics(BaseModel):
    source_recall: float = 0.0
    citation_precision: float = 0.0
    top1_source_hit: bool = False
    reciprocal_rank: float = 0.0
    ndcg: float = 0.0
    expected_source_hit_count: int = 0
    expected_source_count: int = 0
    retrieved_count: int = 0
    keyword_coverage: float = 0.0
    evidence_overlap: float = 0.0
    claim_support_rate: float = 0.0
    unsupported_claim_count: int = 0
    abstention_correct: bool | None = None
    language_match: bool | None = None
    forbidden_keyword_hits: list[str] = Field(default_factory=list)
    judge_scores: dict[str, float] = Field(default_factory=dict)
    judge_score: float = 0.0
    judge_passed: bool | None = None
    judge_failures: list[str] = Field(default_factory=list)
    weakest_judge_dimension: str | None = None
    latency_ms: float = 0.0
    passed: bool = False
    failures: list[str] = Field(default_factory=list)


class EvalCaseResult(BaseModel):
    case: EvalCase
    retrieved_doc_ids: list[str]
    selected_chunk_ids: list[str]
    citations: list[Citation]
    answer: str | None = None
    trace_notes: list[str] = Field(default_factory=list)
    metrics: EvalCaseMetrics


class EvalRunMetrics(BaseModel):
    pass_rate: float = 0.0
    mean_source_recall: float = 0.0
    mean_citation_precision: float = 0.0
    top1_accuracy: float = 0.0
    mean_mrr: float = 0.0
    mean_ndcg: float = 0.0
    mean_keyword_coverage: float = 0.0
    mean_evidence_overlap: float = 0.0
    mean_claim_support_rate: float = 0.0
    unsupported_claim_rate: float = 0.0
    abstention_accuracy: float = 0.0
    language_match_rate: float = 0.0
    forbidden_keyword_violation_rate: float = 0.0
    judge_pass_rate: float = 0.0
    mean_judge_score: float = 0.0
    weakest_judge_dimension: str | None = None
    weakest_judge_score: float = 0.0
    mean_latency_ms: float = 0.0


class EvalRunResponse(BaseModel):
    run_id: str
    status: str
    message: str
    mode: str
    question_count: int
    passed_count: int
    failed_count: int
    metrics: EvalRunMetrics
    results: list[EvalCaseResult] = Field(default_factory=list)
    report_path: str | None = None
    report_json_path: str | None = None


class EvalRunListItem(BaseModel):
    run_id: str
    ts: float
    status: str
    mode: str
    question_count: int
    passed_count: int
    failed_count: int
    metrics: EvalRunMetrics
