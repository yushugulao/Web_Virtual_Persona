"""Deterministic short-term conversation memory routes."""

from __future__ import annotations

from app.backend.core.config import get_settings
from app.backend.memory.memory_context import memory_citations
from app.backend.memory.memory_retrieval import retrieve_approved_memories
from app.backend.memory.memory_store import cjk_bigrams, tokenize_memory_text
from app.backend.persona_runtime.user_context import RuntimeUserContext
from app.backend.schemas.chat import ChatRequest, ChatResponse
from app.backend.schemas.common import TimingBreakdown, VerificationResult
from app.backend.schemas.memory import MemoryItem
from app.backend.schemas.retrieval import RetrievalTrace
from app.backend.services.conversation_memory import (
    ConversationTurn,
    build_conversation_recall_answer,
    build_conversation_user_request_recall_answer,
    is_all_question_recall_query,
    is_answer_only_recall_query,
    is_conversation_recall_query,
    is_conversation_user_request_recall_query,
    is_except_first_question_recall_query,
    is_first_question_recall_query,
    is_latest_only_recall_query,
    maybe_build_conversation_answer_recall_answer,
    maybe_build_conversation_social_answer,
    maybe_build_conversation_topic_recap_answer,
    maybe_build_conversation_user_recall_answer,
    question_recall_count,
    question_recall_index,
)
from app.backend.services.response_language import detect_response_language


LONG_TERM_MEMORY_RECALL_MARKERS = (
    "你记得我",
    "还记得我",
    "记得我",
    "我的偏好",
    "我偏好",
    "answer from memory",
    "from memory",
    "did i say",
    "do you remember my",
    "remember my",
    "what drink did i say",
)

SHORT_TERM_RECALL_CUES = (
    "刚才",
    "刚刚",
    "前面问",
    "上一条",
    "上一句",
    "上一轮",
    "last message",
    "previous message",
    "previous sentence",
    "just ask",
    "just asked",
)

GENERIC_MEMORY_FEATURES = {
    "我",
    "你",
    "我喜",
    "喜欢",
    "我偏",
    "偏好",
    "记得",
    "得我",
    "你记",
    "什么",
    "方式",
    "tell",
    "told",
    "previously",
    "earlier",
    "remember",
    "memory",
    "answer",
    "from",
    "did",
    "say",
    "like",
    "my",
    "you",
}


def maybe_build_short_term_memory_response(
    *,
    request: ChatRequest,
    request_id: str,
    session_id: str,
    persona_id: str,
    user_context: RuntimeUserContext | None = None,
    turns: list[ConversationTurn],
    total_ms: float,
) -> ChatResponse | None:
    """Answer current-session memory questions before retrieval/generation."""

    if is_conversation_recall_query(request.message):
        return build_conversation_recall_response(
            request=request,
            request_id=request_id,
            session_id=session_id,
            persona_id=persona_id,
            turns=turns,
            total_ms=total_ms,
        )

    if is_conversation_user_request_recall_query(request.message):
        user_request_recall = build_conversation_user_request_recall_answer(
            turns,
            persona_id=persona_id,
            language=detect_response_language(request.message),
            answer_only=is_answer_only_recall_query(request.message),
        )
        return build_conversation_memory_response(
            request=request,
            request_id=request_id,
            session_id=session_id,
            persona_id=persona_id,
            answer=user_request_recall,
            total_ms=total_ms,
            note="短期对话记忆：本次回答回忆用户上一轮给出的请求，未检索、未生成、未写入长期人物记忆。",
            model_suffix="conversation_user_request_recall",
            confidence="high" if turns else "low",
        )

    user_recall = maybe_build_conversation_user_recall_answer(
        request.message,
        turns,
        persona_id=persona_id,
    )
    if user_recall is not None:
        return build_conversation_memory_response(
            request=request,
            request_id=request_id,
            session_id=session_id,
            persona_id=persona_id,
            answer=user_recall,
            total_ms=total_ms,
            note="短期对话记忆：本次回答回忆用户上一轮说法，未检索、未生成、未写入长期人物记忆。",
            model_suffix="conversation_user_recall",
            confidence="high" if turns else "low",
        )

    answer_recall = maybe_build_conversation_answer_recall_answer(
        request.message,
        turns,
        persona_id=persona_id,
    )
    if answer_recall is not None:
        return build_conversation_memory_response(
            request=request,
            request_id=request_id,
            session_id=session_id,
            persona_id=persona_id,
            answer=answer_recall,
            total_ms=total_ms,
            note="短期对话记忆：本次回答回忆上一轮答复，未写入长期人物记忆。",
            model_suffix="conversation_answer_recall",
            confidence="high" if turns else "low",
        )

    topic_recap = maybe_build_conversation_topic_recap_answer(
        request.message,
        turns,
        persona_id=persona_id,
    )
    if topic_recap is not None:
        return build_conversation_memory_response(
            request=request,
            request_id=request_id,
            session_id=session_id,
            persona_id=persona_id,
            answer=topic_recap,
            total_ms=total_ms,
            note="短期对话记忆：本次回答回顾上一轮话题，未写入长期人物记忆。",
            model_suffix="conversation_topic_recap",
            confidence="high" if turns else "low",
        )

    long_term_recall = maybe_build_long_term_memory_recall_response(
        request=request,
        request_id=request_id,
        session_id=session_id,
        persona_id=persona_id,
        user_context=user_context or RuntimeUserContext.dev(),
        total_ms=total_ms,
    )
    if long_term_recall is not None:
        return long_term_recall

    social_answer = maybe_build_conversation_social_answer(
        request.message,
        persona_id=persona_id,
    )
    if social_answer is not None:
        return build_conversation_memory_response(
            request=request,
            request_id=request_id,
            session_id=session_id,
            persona_id=persona_id,
            answer=social_answer,
            total_ms=total_ms,
            note="短期对话礼貌回合：本次回答处理寒暄、确认或告别，未检索、未生成、未写入长期人物记忆。",
            model_suffix="conversation_social",
            confidence="high",
        )

    return None


def maybe_build_long_term_memory_recall_response(
    *,
    request: ChatRequest,
    request_id: str,
    session_id: str,
    persona_id: str,
    user_context: RuntimeUserContext | None = None,
    total_ms: float,
) -> ChatResponse | None:
    """Deterministically answer explicit long-term memory recall questions."""

    if not is_long_term_memory_recall_query(request.message):
        return None
    settings = get_settings()
    user_context = user_context or RuntimeUserContext.dev()
    approved_items = retrieve_approved_memories(
        sqlite_path=settings.sqlite_path,
        user_id=user_context.user_id,
        session_id=session_id,
        persona_id=persona_id,
        query=request.message,
        limit=8,
        include_user_global=True,
    )
    relevant_items = [
        item
        for item in approved_items
        if is_memory_item_relevant_to_query(item.content, request.message)
    ][:3]
    language = detect_response_language(request.message)
    if relevant_items:
        answer = build_approved_memory_recall_answer(relevant_items, language=language)
        confidence = "high"
        note = "长期记忆读取：只引用同 persona 下已批准且与问题相关的用户记忆，未检索人物档案。"
    else:
        answer = build_no_approved_memory_recall_answer(language=language)
        confidence = "medium"
        note = "长期记忆读取：没有找到同 persona 下已批准且与问题相关的用户记忆，未检索人物档案。"
    return build_conversation_memory_response(
        request=request,
        request_id=request_id,
        session_id=session_id,
        persona_id=persona_id,
        answer=answer,
        total_ms=total_ms,
        note=note,
        model_suffix="long_term_memory_recall",
        confidence=confidence,
        memory_items=relevant_items,
    )


def is_long_term_memory_recall_query(query: str) -> bool:
    normalized = query.lower()
    compact = "".join(normalized.split())
    if any(cue in normalized or cue in compact for cue in SHORT_TERM_RECALL_CUES):
        return False
    has_recall_marker = any(marker in normalized for marker in LONG_TERM_MEMORY_RECALL_MARKERS)
    if not has_recall_marker:
        return False
    return "?" in query or "？" in query or "吗" in query or "memory" in normalized


def is_memory_item_relevant_to_query(content: str, query: str) -> bool:
    content_features = memory_match_features(content)
    query_features = memory_match_features(query)
    return bool(content_features & query_features)


def memory_match_features(text: str) -> set[str]:
    features = set(tokenize_memory_text(text)) | set(cjk_bigrams(text))
    return {
        feature.lower()
        for feature in features
        if len(feature.strip()) >= 2 and feature.lower() not in GENERIC_MEMORY_FEATURES
    }


def build_approved_memory_recall_answer(
    items: list[MemoryItem],
    *,
    language: str,
) -> str:
    contents = [item.content.strip() for item in items if item.content.strip()]
    if not contents:
        return build_no_approved_memory_recall_answer(language=language)
    if language == "en":
        return "You previously told me: " + "; ".join(contents) + "."
    return "你先前告诉我：" + "；".join(contents) + "。"


def build_no_approved_memory_recall_answer(*, language: str) -> str:
    if language == "en":
        return "I am not certain you have approved that memory for me in this persona."
    return "我不确定你是否把这件事明确告诉过我，或者它还没有被批准为这个分身可用的记忆。"


def build_conversation_recall_response(
    *,
    request: ChatRequest,
    request_id: str,
    session_id: str,
    persona_id: str,
    turns: list[ConversationTurn],
    total_ms: float,
) -> ChatResponse:
    """Build a deterministic answer for question-recall requests."""

    skip_first = is_except_first_question_recall_query(request.message)
    recall_index = question_recall_index(request.message)
    recall_count = question_recall_count(request.message)
    if skip_first:
        max_questions = 8
        recall_position = "recent"
    elif recall_index is not None:
        max_questions = 1
        recall_position = "recent"
    elif recall_count is not None:
        max_questions = recall_count
        recall_position = "recent"
    elif is_first_question_recall_query(request.message):
        max_questions = 1
        recall_position = "first"
    elif is_latest_only_recall_query(request.message):
        max_questions = 1
        recall_position = "recent"
    elif is_all_question_recall_query(request.message):
        max_questions = 8
        recall_position = "recent"
    else:
        max_questions = 3
        recall_position = "recent"
    answer = build_conversation_recall_answer(
        turns,
        persona_id=persona_id,
        max_questions=max_questions,
        language=detect_response_language(request.message),
        recall_position=recall_position,
        answer_only=is_answer_only_recall_query(request.message),
        recall_index=recall_index,
        include_recall_queries=skip_first or recall_index is not None or recall_count is not None,
        skip_first=skip_first,
    )
    return build_conversation_memory_response(
        request=request,
        request_id=request_id,
        session_id=session_id,
        persona_id=persona_id,
        answer=answer,
        total_ms=total_ms,
        note="短期对话记忆：本次回答使用同一会话内最近几轮用户问题，未写入长期人物记忆。",
        model_suffix="conversation_memory",
        confidence="high" if turns else "low",
    )


def build_conversation_memory_response(
    *,
    request: ChatRequest,
    request_id: str,
    session_id: str,
    persona_id: str,
    answer: str,
    total_ms: float,
    note: str,
    model_suffix: str,
    confidence: str,
    memory_items: list[MemoryItem] | None = None,
) -> ChatResponse:
    """Wrap a deterministic memory/policy answer in the normal chat schema."""

    timings = TimingBreakdown(total_ms=round(total_ms, 2))
    trace = RetrievalTrace(
        original_query=request.message,
        persona_id=persona_id,
        requested_persona_id=request.persona_id,
        notes=[note],
    )
    return ChatResponse(
        answer=answer,
        mode="conversation_memory",
        confidence=confidence,
        thinking_effort=request.thinking_effort,
        citations=[],
        memory_citations=memory_citations(memory_items or []),
        retrieval_trace=trace,
        verification=VerificationResult(),
        timings=timings,
        model=f"{get_settings().generation_model}+{model_suffix}",
        request_id=request_id,
        session_id=session_id,
    )
