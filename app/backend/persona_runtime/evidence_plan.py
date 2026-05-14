"""Evidence planning for retrieval-backed persona turns."""

from __future__ import annotations

from dataclasses import dataclass

from app.backend.schemas.chat import ChatRequest
from app.backend.schemas.retrieval import RetrieveRequest, RetrieveResponse
from app.backend.services.conversation_memory import ConversationTurn

from .ordinary_routes import plan_ordinary_retrieval_route


FOLLOWUP_RETRIEVAL_TRACE_NOTE = (
    "会话追问检索补充：已把上一问并入本轮检索查询，仅用于解析省略、澄清、补充和代词。"
)
CONTEXT_CANDIDATE_MULTIPLIER = 2
CONTEXT_CANDIDATE_CEILING = 12


@dataclass(frozen=True)
class EvidencePlan:
    retrieval_query: str
    requested_persona_id: str
    effective_persona_id: str
    top_k: int
    include_private: bool
    session_id: str | None
    skip_retrieval: bool = False
    intended_evidence_budget: int = 0
    trace_notes: tuple[str, ...] = ()
    bypass_response: RetrieveResponse | None = None

    def to_retrieve_request(self) -> RetrieveRequest:
        return RetrieveRequest(
            query=self.retrieval_query,
            top_k=self.top_k,
            include_private=self.include_private,
            session_id=self.session_id,
            persona_id=self.requested_persona_id,
        )


def build_evidence_plan(
    *,
    request: ChatRequest,
    session_id: str,
    persona_id: str,
    turns: list[ConversationTurn],
) -> EvidencePlan:
    """Plan retrieval without executing it."""

    ordinary_route = plan_ordinary_retrieval_route(
        request=request,
        persona_id=persona_id,
        turns=turns,
    )
    trace_notes: tuple[str, ...] = ()
    if ordinary_route.retrieval_query != request.message:
        trace_notes = (FOLLOWUP_RETRIEVAL_TRACE_NOTE,)
    retrieval_top_k = context_candidate_top_k(request.top_k)
    if retrieval_top_k != request.top_k:
        trace_notes = (
            *trace_notes,
            (
                "证据规划："
                f"检索候选池最多 {retrieval_top_k} 个片段，"
                f"提示词预算保留 {request.top_k} 个片段，用于证据族多样性选择。"
            ),
        )
    return EvidencePlan(
        retrieval_query=ordinary_route.retrieval_query,
        requested_persona_id=request.persona_id,
        effective_persona_id=persona_id,
        top_k=retrieval_top_k,
        include_private=request.include_private,
        session_id=session_id,
        skip_retrieval=ordinary_route.skip_retrieval,
        intended_evidence_budget=request.top_k,
        trace_notes=trace_notes,
        bypass_response=ordinary_route.bypass_response,
    )


def apply_evidence_plan_trace_notes(
    retrieval_response: RetrieveResponse,
    plan: EvidencePlan,
) -> None:
    """Apply plan-level trace notes after retrieval preserves existing ordering."""

    for note in reversed(plan.trace_notes):
        retrieval_response.trace.notes.insert(0, note)


def context_candidate_top_k(request_top_k: int) -> int:
    if request_top_k <= 0:
        return 0
    return min(
        CONTEXT_CANDIDATE_CEILING,
        max(request_top_k, request_top_k * CONTEXT_CANDIDATE_MULTIPLIER),
    )
