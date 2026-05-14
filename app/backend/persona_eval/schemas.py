from __future__ import annotations

from pydantic import BaseModel, Field


JUDGE_DIMENSIONS = (
    "persona_consistency",
    "era_consistency",
    "evidence_faithfulness",
    "over_refusal",
    "relationship_boundary",
    "naturalness",
    "cardiness",
    "lecture_rate",
    "human_turn",
    "emotional_fit",
    "repetition",
    "contradiction_risk",
)


class JudgeVerdict(BaseModel):
    scores: dict[str, float] = Field(default_factory=dict)
    overall: float = 0.0
    passed: bool = False
    failures: list[str] = Field(default_factory=list)
    feedback: str = ""

    @property
    def weakest_dimension(self) -> str | None:
        if not self.scores:
            return None
        return min(self.scores, key=self.scores.get)
