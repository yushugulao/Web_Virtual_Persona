"""Ordinary-task retrieval routing for persona turns."""

from __future__ import annotations

from dataclasses import dataclass

from app.backend.core.logging import new_request_id
from app.backend.schemas.chat import ChatRequest
from app.backend.schemas.common import TimingBreakdown
from app.backend.schemas.retrieval import RetrievalTrace, RetrieveResponse
from app.backend.services.conversation_memory import ConversationTurn, maybe_build_conversation_retrieval_query
from app.backend.services.dialogue_policy import should_skip_retrieval_for_ordinary_query


@dataclass(frozen=True)
class OrdinaryRetrievalRoute:
    skip_retrieval: bool
    retrieval_query: str
    bypass_response: RetrieveResponse | None = None


def plan_ordinary_retrieval_route(
    *,
    request: ChatRequest,
    persona_id: str,
    turns: list[ConversationTurn],
) -> OrdinaryRetrievalRoute:
    """Decide whether the turn should bypass persona-document retrieval."""

    skip_retrieval = should_skip_retrieval_for_ordinary_query(request.message, persona_id)
    retrieval_query = (
        request.message
        if skip_retrieval
        else maybe_build_conversation_retrieval_query(request.message, turns) or request.message
    )
    if not skip_retrieval:
        return OrdinaryRetrievalRoute(skip_retrieval=False, retrieval_query=retrieval_query)
    return OrdinaryRetrievalRoute(
        skip_retrieval=True,
        retrieval_query=retrieval_query,
        bypass_response=build_ordinary_retrieval_bypass_response(
            retrieval_query,
            requested_persona_id=request.persona_id,
            persona_id=persona_id,
        ),
    )


def build_ordinary_retrieval_bypass_response(
    query: str,
    requested_persona_id: str | None,
    persona_id: str,
) -> RetrieveResponse:
    """Return an empty retrieval result for standalone ordinary tasks."""

    trace = RetrievalTrace(
        original_query=query,
        persona_id=persona_id,
        requested_persona_id=requested_persona_id,
        notes=["普通算术、语言或常识任务绕过档案检索，避免无关人物片段污染回答。"],
    )
    return RetrieveResponse(
        retrieval_id=new_request_id(),
        query=query,
        citations=[],
        trace=trace,
        timings=TimingBreakdown(
            retrieval_ms=0.0,
            context_ms=0.0,
            generation_ms=0.0,
            verification_ms=0.0,
            total_ms=0.0,
        ),
    )
