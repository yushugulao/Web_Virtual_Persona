"""Deterministic dialogue-policy routes for persona turns."""

from __future__ import annotations

from dataclasses import dataclass

from app.backend.schemas.chat import ChatRequest, ChatResponse
from app.backend.services.dialogue_policy import maybe_build_dialogue_policy_answer

from .memory_routes import build_conversation_memory_response


@dataclass(frozen=True)
class DialogueRouteResult:
    response: ChatResponse
    reason: str


def maybe_build_dialogue_policy_response(
    *,
    request: ChatRequest,
    request_id: str,
    session_id: str,
    persona_id: str,
    total_ms: float,
) -> DialogueRouteResult | None:
    """Answer deterministic interpersonal and era-epistemic policy turns."""

    policy_answer = maybe_build_dialogue_policy_answer(
        request.message,
        persona_id=persona_id,
    )
    if policy_answer is None:
        return None
    response = build_conversation_memory_response(
        request=request,
        request_id=request_id,
        session_id=session_id,
        persona_id=persona_id,
        answer=policy_answer.answer,
        total_ms=total_ms,
        note=f"对话策略：本次回答处理关系、情绪或亲密边界（{policy_answer.reason}），未检索、未生成、未写入长期人物记忆。",
        model_suffix=f"conversation_dialogue_{policy_answer.reason}",
        confidence="high",
    )
    return DialogueRouteResult(response=response, reason=policy_answer.reason)
