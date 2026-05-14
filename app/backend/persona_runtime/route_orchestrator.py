from __future__ import annotations

from app.backend.core.config import get_settings
from app.backend.memory.memory_gate import detect_explicit_memory_write
from app.backend.memory.memory_store import MemoryStore
from app.backend.memory.memory_context import memory_citations
from app.backend.persona_runtime.user_context import RuntimeUserContext
from app.backend.schemas.chat import ChatRequest, ChatResponse
from app.backend.schemas.common import TimingBreakdown, VerificationResult
from app.backend.schemas.retrieval import RetrievalTrace
from app.backend.services.conversation_memory import (
    ConversationTurn,
    SessionContextBundle,
    build_session_context_bundle,
    turns_from_request_history,
)
from app.backend.services.metadata_store import MetadataStore


SHORT_TERM_TURN_LIMIT = 40
SESSION_CONTEXT_TURN_LIMIT = 48


def load_conversation_turns(
    request: ChatRequest,
    session_id: str,
    persona_id: str,
    store: MetadataStore,
    user_context: RuntimeUserContext | None = None,
) -> list[ConversationTurn]:
    stored_turns = store.recent_chat_turns(
        user_id=(user_context or RuntimeUserContext.dev()).user_id,
        session_id=session_id,
        persona_id=persona_id,
        limit=SHORT_TERM_TURN_LIMIT,
    )
    if stored_turns:
        return stored_turns
    return turns_from_request_history(request.history, persona_id=persona_id)


def load_session_context_bundle(
    request: ChatRequest,
    session_id: str,
    persona_id: str,
    store: MetadataStore,
    user_context: RuntimeUserContext | None = None,
) -> SessionContextBundle:
    effective_user = (user_context or RuntimeUserContext.dev()).user_id
    stored_turns = store.recent_chat_turns(
        user_id=effective_user,
        session_id=session_id,
        persona_id=persona_id,
        limit=SESSION_CONTEXT_TURN_LIMIT,
    )
    if not stored_turns:
        stored_turns = turns_from_request_history(request.history, persona_id=persona_id)
    summary = store.chat_session_summary(
        user_id=effective_user,
        session_id=session_id,
        persona_id=persona_id,
    )
    return build_session_context_bundle(stored_turns, summary)

def maybe_build_long_term_memory_write_response(
    *,
    request: ChatRequest,
    request_id: str,
    session_id: str,
    persona_id: str,
    user_context: RuntimeUserContext | None = None,
    total_ms: float,
) -> ChatResponse | None:
    decision = detect_explicit_memory_write(request.message)
    if decision is None:
        return None
    user_context = user_context or RuntimeUserContext.dev()
    item = MemoryStore(get_settings().sqlite_path).propose(
        user_id=user_context.user_id,
        session_id=session_id,
        persona_id=persona_id,
        content=decision.content,
        scope="session",
        memory_type=decision.memory_type,
        status=decision.status,
        sensitivity=decision.sensitivity,
        source=decision.reason,
        actor_user_id=user_context.user_id,
    )
    if item.status == "approved":
        answer = f"我记住了：你先前告诉我，{item.content}"
        confidence = "high"
    else:
        answer = (
            f"这条内容我先放入待确认记忆：{item.content}。"
            "等你在记忆面板批准后，我才会在后续对话中使用它。"
        )
        confidence = "medium"
    return ChatResponse(
        answer=answer,
        mode="long_term_memory_write",
        confidence=confidence,
        thinking_effort=request.thinking_effort,
        citations=[],
        memory_citations=memory_citations([item]),
        retrieval_trace=RetrievalTrace(
            original_query=request.message,
            persona_id=persona_id,
            requested_persona_id=request.persona_id,
            rewritten_queries=[],
            candidates=[],
            selected_chunk_ids=[],
            notes=[
                "Long-term memory V1: explicit write gate handled this turn; "
                f"status={item.status}; sensitivity={item.sensitivity}; no archive retrieval.",
            ],
        ),
        verification=VerificationResult(),
        timings=TimingBreakdown(total_ms=round(total_ms, 2)),
        model=f"{get_settings().generation_model}+long_term_memory",
        request_id=request_id,
        session_id=session_id,
    )
