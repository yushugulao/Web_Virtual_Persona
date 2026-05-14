from pydantic import BaseModel, Field


class TimingBreakdown(BaseModel):
    ingest_ms: float = 0
    retrieval_ms: float = 0
    rerank_ms: float = 0
    context_ms: float = 0
    generation_ms: float = 0
    verification_ms: float = 0
    total_ms: float = 0


class Citation(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    source_path: str
    section_path: str
    preview: str
    score: float
    trust_level: str
    privacy_level: str


class VerificationClaim(BaseModel):
    text: str
    support_score: float = 0.0
    supported: bool = False
    best_citation_ids: list[str] = Field(default_factory=list)


class VerificationResult(BaseModel):
    claim_count: int = 0
    supported_claim_count: int = 0
    unsupported_claim_count: int = 0
    claim_support_rate: float = 0.0
    unsupported_claims: list[str] = Field(default_factory=list)
    claims: list[VerificationClaim] = Field(default_factory=list)
