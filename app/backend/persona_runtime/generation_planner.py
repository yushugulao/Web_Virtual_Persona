from __future__ import annotations

from dataclasses import dataclass

from app.backend.core.config import Settings
from app.backend.schemas.chat import RetrievalTrace
from app.backend.services.model_service import (
    model_for_effort,
    num_predict_for_effort,
    refinement_passes_for_request,
    think_for_effort,
    thinking_budget_for_effort,
    timeout_seconds_for_effort,
)


@dataclass(frozen=True)
class GenerationPlan:
    """Resolved local-generation budget for one chat turn."""

    effort: str
    model: str
    timeout_seconds: float
    num_predict: int
    think: bool
    thinking_budget: int | None
    refinement_passes: int

    @property
    def trace_note(self) -> str:
        return (
            "Generation effort: "
            f"{self.effort}; model={self.model}; timeout={self.timeout_seconds:g}s; "
            f"num_predict={self.num_predict}; think={self.think}; "
            f"thinking_budget={self.thinking_budget or 'off'}; "
            f"refinement_passes={self.refinement_passes}."
        )


def build_generation_plan(settings: Settings, thinking_effort: str) -> GenerationPlan:
    """Centralize model choice, local timeout, token budget, and refinement passes."""

    return GenerationPlan(
        effort=thinking_effort,
        model=model_for_effort(settings, thinking_effort),
        timeout_seconds=timeout_seconds_for_effort(
            settings.model_timeout_seconds,
            thinking_effort,
        ),
        num_predict=num_predict_for_effort(settings.model_num_predict, thinking_effort),
        think=think_for_effort(settings, thinking_effort),
        thinking_budget=thinking_budget_for_effort(settings, thinking_effort),
        refinement_passes=refinement_passes_for_request(settings, thinking_effort),
    )


def add_thinking_effort_trace_note(trace: RetrievalTrace, plan: GenerationPlan) -> None:
    """Record the resolved local generation budget without exposing hidden reasoning."""

    trace.notes.append(plan.trace_note)
