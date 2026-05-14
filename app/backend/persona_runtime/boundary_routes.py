"""Deterministic boundary routes for persona turns."""

from __future__ import annotations

from app.backend.schemas.chat import ChatRequest, ChatResponse
from app.backend.schemas.common import Citation
from app.backend.services.boundary_answer import BoundaryAnswer, maybe_build_boundary_answer
from app.backend.services.conversation_memory import ConversationTurn, maybe_build_boundary_followup_answer

from .memory_routes import build_conversation_memory_response


def maybe_build_boundary_followup_response(
    *,
    request: ChatRequest,
    request_id: str,
    session_id: str,
    persona_id: str,
    turns: list[ConversationTurn],
    total_ms: float,
) -> ChatResponse | None:
    """Answer immediate follow-ups about a previous boundary answer."""

    answer = maybe_build_boundary_followup_answer(
        request.message,
        turns,
        persona_id=persona_id,
    )
    if answer is None:
        return None
    return build_boundary_followup_response(
        request=request,
        request_id=request_id,
        session_id=session_id,
        persona_id=persona_id,
        answer=answer,
        total_ms=total_ms,
    )


def build_boundary_followup_response(
    *,
    request: ChatRequest,
    request_id: str,
    session_id: str,
    persona_id: str,
    answer: str,
    total_ms: float,
) -> ChatResponse:
    """Wrap a deterministic boundary-follow-up answer in the chat schema."""

    return build_conversation_memory_response(
        request=request,
        request_id=request_id,
        session_id=session_id,
        persona_id=persona_id,
        answer=answer,
        total_ms=total_ms,
        note="短期对话记忆：本次回答解释上一轮边界回答，未写入长期人物记忆。",
        model_suffix="conversation_boundary_followup",
        confidence="high",
    )


def maybe_build_boundary_fast_path_answer(
    *,
    request: ChatRequest,
    citations: list[Citation],
    persona_id: str,
    enabled: bool,
) -> BoundaryAnswer | None:
    """Build a post-retrieval deterministic boundary answer when configured."""

    if not enabled:
        return None
    return maybe_build_boundary_answer(
        request.message,
        citations,
        persona_id,
    )
