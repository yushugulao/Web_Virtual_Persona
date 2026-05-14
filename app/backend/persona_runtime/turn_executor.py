import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import suppress

from app.backend.core.config import Settings, get_settings
from app.backend.core.logging import log_event, new_request_id
from app.backend.followups import FollowUpContext, generate_follow_up_questions
from app.backend.memory.memory_context import (
    ensure_user_memory_framing,
    format_memory_context,
    memory_citations,
)
from app.backend.memory.memory_retrieval import retrieve_approved_memories
from app.backend.persona_runtime.boundary_routes import (
    maybe_build_boundary_fast_path_answer as runtime_maybe_build_boundary_fast_path_answer,
    maybe_build_boundary_followup_response as runtime_maybe_build_boundary_followup_response,
)
from app.backend.persona_runtime.dialogue_routes import (
    maybe_build_dialogue_policy_response as runtime_maybe_build_dialogue_policy_response,
)
from app.backend.persona_runtime.context_builder import (
    GenerationContext,
    build_generation_context,
)
from app.backend.persona_runtime.evidence_plan import (
    apply_evidence_plan_trace_notes as runtime_apply_evidence_plan_trace_notes,
    build_evidence_plan as runtime_build_evidence_plan,
)
from app.backend.persona_runtime.evidence_policy import (
    build_evidence_policy,
    build_evidence_policy_trace_note,
    context_budget_for_policy,
    rank_citations_for_policy,
)
from app.backend.persona_runtime.generation_planner import build_generation_plan
from app.backend.persona_runtime.memory_routes import (
    maybe_build_short_term_memory_response as runtime_maybe_build_short_term_memory_response,
)
from app.backend.persona_runtime.persona_first_runtime import maybe_run_persona_first_turn
from app.backend.persona_runtime.post_persona_alignment import (
    build_post_persona_alignment_trace_note,
    soften_over_literary_persona_answer,
)
from app.backend.persona_runtime.prompt_builder import (
    build_ordinary_task_prompt,
    build_prompt,
)
from app.backend.persona_runtime.response_guards import (
    enforce_contextual_followup_answer,
    enforce_immersive_answer,
    immersive_no_evidence_answer,
    repair_answer_language_if_needed,
    repair_cited_latency_metric_drift,
)
from app.backend.persona_runtime.response_first_alignment import (
    build_response_first_plan,
    build_response_first_retrieval_query,
    build_response_first_trace_note,
    format_response_first_prompt_context,
    generate_response_first_draft,
)
from app.backend.persona_runtime.route_orchestrator import (
    load_conversation_turns,
    load_session_context_bundle,
    maybe_build_long_term_memory_write_response,
)
from app.backend.persona_runtime.trace_builder import (
    add_context_trace_note,
    add_thinking_effort_trace_note,
    apply_citation_budget,
    apply_generation_context_selection,
)
from app.backend.persona_runtime.user_context import RuntimeUserContext
from app.backend.persona_runtime.verification_pipeline import (
    align_answer_after_generation,
    refine_answer_for_effort,
)
from app.backend.schemas.chat import ChatRequest, ChatResponse
from app.backend.schemas.common import TimingBreakdown
from app.backend.services.dialogue_policy import should_use_no_evidence_fallback
from app.backend.services.conversation_memory import ConversationTurn
from app.backend.services.metadata_store import MetadataStore
from app.backend.services.model_diagnostics import (
    active_generation_snapshot,
    current_model_diagnostics,
    model_diagnostic_phase,
)
from app.backend.services.model_service import LocalModelClient
from app.backend.services.persona_service import normalize_persona_id
from app.backend.services.retrieval_service import retrieve
from app.rag.verification.citation_verifier import verify_answer


async def _answer_chat_impl(
    request: ChatRequest,
    user_context: RuntimeUserContext | None = None,
) -> ChatResponse:
    request_id = new_request_id()
    session_id = request.session_id or new_request_id()
    user_context = user_context or RuntimeUserContext.dev()
    settings = get_settings()
    store = MetadataStore(settings.sqlite_path)
    effective_persona_id = normalize_persona_id(request.persona_id)
    conversation_turns = load_conversation_turns(
        request,
        session_id,
        effective_persona_id,
        store,
        user_context=user_context,
    )
    session_context_bundle = load_session_context_bundle(
        request,
        session_id,
        effective_persona_id,
        store,
        user_context=user_context,
    )
    total_start = time.perf_counter()

    long_term_memory_response = maybe_build_long_term_memory_write_response(
        request=request,
        request_id=request_id,
        session_id=session_id,
        persona_id=effective_persona_id,
        user_context=user_context,
        total_ms=(time.perf_counter() - total_start) * 1000,
    )
    if long_term_memory_response is not None:
        long_term_memory_response = _attach_diagnostics(long_term_memory_response)
        long_term_memory_response = await _attach_follow_up_questions(
            long_term_memory_response,
            request=request,
            persona_id=effective_persona_id,
            conversation_turns=conversation_turns,
            settings=settings,
        )
        store.record_chat(request=request, response=long_term_memory_response, user_id=user_context.user_id)
        log_event(
            "chat.completed",
            {
                "request_id": request_id,
                "session_id": session_id,
                "query": request.message,
                "citations": [],
                "timings": long_term_memory_response.timings.model_dump(),
                "model": long_term_memory_response.model,
                "long_term_memory_write": True,
            },
        )
        return long_term_memory_response

    memory_response = runtime_maybe_build_short_term_memory_response(
        request=request,
        request_id=request_id,
        session_id=session_id,
        persona_id=effective_persona_id,
        user_context=user_context,
        turns=conversation_turns,
        total_ms=(time.perf_counter() - total_start) * 1000,
    )
    if memory_response is not None:
        memory_response = _attach_diagnostics(memory_response)
        memory_response = await _attach_follow_up_questions(
            memory_response,
            request=request,
            persona_id=effective_persona_id,
            conversation_turns=conversation_turns,
            settings=settings,
        )
        store.record_chat(request=request, response=memory_response, user_id=user_context.user_id)
        log_event(
            "chat.completed",
            {
                "request_id": request_id,
                "session_id": session_id,
                "query": request.message,
                "citations": [],
                "timings": memory_response.timings.model_dump(),
                "model": memory_response.model,
                "conversation_memory": True,
            },
        )
        return memory_response

    boundary_followup_response = runtime_maybe_build_boundary_followup_response(
        request=request,
        request_id=request_id,
        session_id=session_id,
        persona_id=effective_persona_id,
        turns=conversation_turns,
        total_ms=(time.perf_counter() - total_start) * 1000,
    )
    if boundary_followup_response is not None:
        boundary_followup_response = _attach_diagnostics(boundary_followup_response)
        boundary_followup_response = await _attach_follow_up_questions(
            boundary_followup_response,
            request=request,
            persona_id=effective_persona_id,
            conversation_turns=conversation_turns,
            settings=settings,
        )
        store.record_chat(
            request=request,
            response=boundary_followup_response,
            user_id=user_context.user_id,
        )
        log_event(
            "chat.completed",
            {
                "request_id": request_id,
                "session_id": session_id,
                "query": request.message,
                "citations": [],
                "timings": boundary_followup_response.timings.model_dump(),
                "model": boundary_followup_response.model,
                "conversation_boundary_followup": True,
            },
        )
        return boundary_followup_response

    dialogue_route = runtime_maybe_build_dialogue_policy_response(
        request=request,
        request_id=request_id,
        session_id=session_id,
        persona_id=effective_persona_id,
        total_ms=(time.perf_counter() - total_start) * 1000,
    )
    if dialogue_route is not None:
        response = dialogue_route.response
        response = _attach_diagnostics(response)
        response = await _attach_follow_up_questions(
            response,
            request=request,
            persona_id=effective_persona_id,
            conversation_turns=conversation_turns,
            settings=settings,
        )
        store.record_chat(request=request, response=response, user_id=user_context.user_id)
        log_event(
            "chat.completed",
            {
                "request_id": request_id,
                "session_id": session_id,
                "query": request.message,
                "citations": [],
                "timings": response.timings.model_dump(),
                "model": response.model,
                "dialogue_policy": dialogue_route.reason,
            },
        )
        return response

    persona_first_response = await maybe_run_persona_first_turn(
        request=request,
        request_id=request_id,
        session_id=session_id,
        persona_id=effective_persona_id,
        user_context=user_context,
        conversation_turns=conversation_turns,
        session_context_bundle=session_context_bundle,
        settings=settings,
        total_start=total_start,
    )
    if persona_first_response is not None:
        persona_first_response = _attach_diagnostics(persona_first_response)
        persona_first_response = await _attach_follow_up_questions(
            persona_first_response,
            request=request,
            persona_id=effective_persona_id,
            conversation_turns=conversation_turns,
            settings=settings,
        )
        store.record_chat(request=request, response=persona_first_response, user_id=user_context.user_id)
        log_event(
            "chat.completed",
            {
                "request_id": request_id,
                "session_id": session_id,
                "query": request.message,
                "citations": [item.chunk_id for item in persona_first_response.citations],
                "timings": persona_first_response.timings.model_dump(),
                "model": persona_first_response.model,
                "thinking_effort": request.thinking_effort,
                "persona_first": True,
                "mode": persona_first_response.mode,
            },
        )
        return persona_first_response

    retrieval_start = time.perf_counter()
    evidence_plan = runtime_build_evidence_plan(
        request=request,
        session_id=session_id,
        persona_id=effective_persona_id,
        turns=conversation_turns,
    )
    skip_retrieval = evidence_plan.skip_retrieval
    generation_plan = build_generation_plan(settings, request.thinking_effort)
    generation_timeout_seconds = generation_plan.timeout_seconds
    generation_num_predict = generation_plan.num_predict
    generation_model = generation_plan.model
    generation_think = generation_plan.think
    generation_thinking_budget = generation_plan.thinking_budget
    refinement_passes = generation_plan.refinement_passes
    model_client: LocalModelClient | None = None
    response_first_plan = build_response_first_plan(
        request=request,
        persona_id=effective_persona_id,
        skip_retrieval=skip_retrieval,
    )
    response_first_draft: str | None = None
    if evidence_plan.bypass_response is None and response_first_plan.enabled:
        model_client = LocalModelClient(settings)
        response_first_draft, _ = await generate_response_first_draft(
            client=model_client,
            request=request,
            persona_id=effective_persona_id,
            conversation_turns=conversation_turns,
            session_context_bundle=session_context_bundle,
            timeout_seconds=generation_timeout_seconds,
            num_predict=generation_num_predict,
            model_name=generation_model,
        )
    if evidence_plan.bypass_response is not None:
        retrieval_response = evidence_plan.bypass_response
    else:
        retrieve_request = evidence_plan.to_retrieve_request().model_copy(
            update={"user_id": user_context.user_id}
        )
        if response_first_draft:
            retrieve_request = retrieve_request.model_copy(
                update={
                    "query": build_response_first_retrieval_query(
                        request.message,
                        response_first_draft,
                    )
                }
            )
        retrieval_response = retrieve(retrieve_request)
        retrieval_response.trace.original_query = request.message
        runtime_apply_evidence_plan_trace_notes(retrieval_response, evidence_plan)
    retrieval_ms = (time.perf_counter() - retrieval_start) * 1000
    if response_first_plan.enabled:
        retrieval_response.trace.notes.append(
            build_response_first_trace_note(response_first_plan, response_first_draft)
        )

    boundary_answer = runtime_maybe_build_boundary_fast_path_answer(
        request=request,
        citations=retrieval_response.citations,
        persona_id=retrieval_response.trace.persona_id,
        enabled=settings.boundary_fast_path_enabled,
    )
    approved_memory_items = []
    if boundary_answer is None and not skip_retrieval:
        approved_memory_items = retrieve_approved_memories(
            sqlite_path=settings.sqlite_path,
            user_id=user_context.user_id,
            session_id=session_id,
            persona_id=retrieval_response.trace.persona_id,
            query=request.message,
            limit=5,
            include_user_global=True,
        )
    evidence_policy = build_evidence_policy(
        query=request.message,
        persona_id=retrieval_response.trace.persona_id,
        has_approved_memory=bool(approved_memory_items),
    )
    use_no_evidence_fallback = (
        not retrieval_response.citations
        and not skip_retrieval
        and boundary_answer is None
        and not approved_memory_items
        and should_use_no_evidence_fallback(request.message, retrieval_response.trace.persona_id)
    )
    post_persona_alignment_reason: str | None = None
    if boundary_answer is not None:
        apply_citation_budget(retrieval_response, evidence_plan.intended_evidence_budget)
        context_ms = 0.0
        generation_ms = 0.0
        answer = boundary_answer.answer
        model = f"{settings.generation_model}+boundary_fast_path"
    elif use_no_evidence_fallback:
        context_ms = 0.0
        generation_ms = 0.0
        answer = immersive_no_evidence_answer(request.message, retrieval_response.trace.persona_id)
        model = f"{settings.generation_model}+no_evidence_fallback"
    else:
        context_start = time.perf_counter()
        generation_context: GenerationContext | None = None
        if skip_retrieval:
            prompt = build_ordinary_task_prompt(
                request,
                retrieval_response.trace.persona_id,
                session_context_bundle=session_context_bundle,
            )
        else:
            retrieval_response.citations = rank_citations_for_policy(
                retrieval_response.citations,
                evidence_policy,
            )
            generation_context = build_generation_context(
                retrieval_response.citations,
                context_budget_for_policy(
                    evidence_policy,
                    evidence_plan.intended_evidence_budget,
                ),
            )
            long_term_memory_context = format_memory_context(approved_memory_items)
            if approved_memory_items:
                retrieval_response.trace.notes.append(
                    f"Long-term memory V1: injected {len(approved_memory_items)} approved user memories."
                )
            retrieval_response.trace.notes.append(
                build_evidence_policy_trace_note(evidence_policy, generation_context)
            )
            add_context_trace_note(retrieval_response, generation_context)
            apply_generation_context_selection(retrieval_response, generation_context)
            prompt = build_prompt(
                request,
                retrieval_response.citations,
                persona_id=retrieval_response.trace.persona_id,
                conversation_turns=conversation_turns,
                session_context_bundle=session_context_bundle,
                generation_context=generation_context,
                long_term_memory_context=long_term_memory_context,
                response_first_context=format_response_first_prompt_context(
                    response_first_draft or ""
                ),
            )
        context_ms = (time.perf_counter() - context_start) * 1000

        generation_start = time.perf_counter()
        add_thinking_effort_trace_note(
            retrieval_response,
            request.thinking_effort,
            generation_timeout_seconds,
            generation_num_predict,
            refinement_passes,
            generation_model,
            generation_think,
            generation_thinking_budget,
        )
        model_client = model_client or LocalModelClient(settings)
        answer, model = await model_client.generate(
            prompt,
            timeout_seconds=generation_timeout_seconds,
            num_predict=generation_num_predict,
            model_name=generation_model,
            think=generation_think,
            thinking_budget=generation_thinking_budget,
        )
        answer = enforce_immersive_answer(answer, request.message, retrieval_response.trace.persona_id)
        answer = enforce_contextual_followup_answer(answer, request.message, conversation_turns)
        answer, model = await refine_answer_for_effort(
            client=model_client,
            request=request,
            answer=answer,
            citations=retrieval_response.citations,
            persona_id=retrieval_response.trace.persona_id,
            conversation_turns=conversation_turns,
            session_context_bundle=session_context_bundle,
            timeout_seconds=generation_timeout_seconds,
            num_predict=generation_num_predict,
            refinement_passes=refinement_passes,
            current_model=model,
            model_name=generation_model,
            think=generation_think,
            thinking_budget=generation_thinking_budget,
            generation_context=generation_context,
        )
        answer, model, post_persona_alignment_reason = await align_answer_after_generation(
            client=model_client,
            request=request,
            answer=answer,
            persona_id=retrieval_response.trace.persona_id,
            conversation_turns=conversation_turns,
            session_context_bundle=session_context_bundle,
            timeout_seconds=generation_timeout_seconds,
            num_predict=generation_num_predict,
            current_model=model,
            model_name=generation_model,
            think=generation_think,
            thinking_budget=generation_thinking_budget,
            generation_context=generation_context,
            enabled=settings.post_persona_alignment_enabled,
        )
        if post_persona_alignment_reason:
            retrieval_response.trace.notes.append(
                build_post_persona_alignment_trace_note(post_persona_alignment_reason)
            )
        answer, language_repaired = await repair_answer_language_if_needed(
            client=model_client,
            answer=answer,
            query=request.message,
            timeout_seconds=generation_timeout_seconds,
            num_predict=generation_num_predict,
            model_name=generation_model,
            think=generation_think,
            thinking_budget=generation_thinking_budget,
        )
        if language_repaired:
            model = f"{model}+language_repair"
        generation_ms = (time.perf_counter() - generation_start) * 1000

    confidence = "medium" if retrieval_response.citations or approved_memory_items else "low"
    mode = (
        "evidence_grounded"
        if retrieval_response.citations
        else "memory_grounded"
        if approved_memory_items
        else "no_evidence"
    )
    answer = enforce_immersive_answer(answer, request.message, retrieval_response.trace.persona_id)
    answer = enforce_contextual_followup_answer(answer, request.message, conversation_turns)
    answer = soften_over_literary_persona_answer(
        answer,
        retrieval_response.trace.persona_id,
        request.message,
    )
    answer = repair_cited_latency_metric_drift(answer, retrieval_response.citations)
    answer = ensure_user_memory_framing(answer, approved_memory_items, request.message)

    verification_start = time.perf_counter()
    verification = verify_answer(answer, retrieval_response.citations)
    verification_ms = (time.perf_counter() - verification_start) * 1000
    total_ms = (time.perf_counter() - total_start) * 1000
    timings = TimingBreakdown(
        retrieval_ms=round(retrieval_ms, 2),
        context_ms=round(context_ms, 2),
        generation_ms=round(generation_ms, 2),
        verification_ms=round(verification_ms, 2),
        total_ms=round(total_ms, 2),
    )

    response = ChatResponse(
        answer=answer,
        mode=mode,
        confidence=confidence,
        thinking_effort=request.thinking_effort,
        citations=retrieval_response.citations,
        memory_citations=memory_citations(approved_memory_items),
        retrieval_trace=retrieval_response.trace,
        verification=verification,
        timings=timings,
        model=model,
        request_id=request_id,
        session_id=session_id,
    )
    response = _attach_diagnostics(response)
    response = await _attach_follow_up_questions(
        response,
        request=request,
        persona_id=retrieval_response.trace.persona_id,
        conversation_turns=conversation_turns,
        settings=settings,
    )
    store.record_chat(request=request, response=response, user_id=user_context.user_id)

    log_event(
        "chat.completed",
        {
            "request_id": request_id,
            "session_id": session_id,
            "query": request.message,
            "citations": [item.chunk_id for item in retrieval_response.citations],
            "timings": timings.model_dump(),
            "model": model,
            "boundary_fast_path": boundary_answer.reason if boundary_answer else None,
            "thinking_effort": request.thinking_effort,
            "generation_timeout_seconds": generation_timeout_seconds,
            "generation_num_predict": generation_num_predict,
            "generation_thinking_budget": generation_thinking_budget,
            "refinement_passes": refinement_passes,
            "post_persona_alignment": post_persona_alignment_reason,
        },
    )
    return response


def _stream_stage_event(
    key: str,
    label: str,
    total_start: float,
    detail: str = "",
) -> str:
    payload = {
        "type": "stage",
        "value": {
            "key": key,
            "label": label,
            "elapsed_ms": round((time.perf_counter() - total_start) * 1000, 2),
            "detail": detail,
        },
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _stream_diagnostic_event(payload: dict) -> str:
    return f"data: {json.dumps({'type': 'diagnostic', 'value': payload}, ensure_ascii=False)}\n\n"


async def _stream_diagnostics_until_done(task: asyncio.Task) -> AsyncIterator[str]:
    diagnostics = current_model_diagnostics()
    if diagnostics is None or not diagnostics.enabled or not diagnostics.live_stream:
        return
    last_heartbeat = 0.0
    try:
        while not task.done():
            payload = await diagnostics.next_live_payload()
            if payload is not None:
                yield _stream_diagnostic_event(payload)
                continue
            now = time.perf_counter()
            if now - last_heartbeat >= 5.0:
                snapshot = active_generation_snapshot()
                if snapshot is not None:
                    diagnostics.emit_heartbeat(snapshot)
                    for heartbeat in diagnostics.drain_live_payloads():
                        yield _stream_diagnostic_event(heartbeat)
                    last_heartbeat = now
        for payload in diagnostics.drain_live_payloads():
            yield _stream_diagnostic_event(payload)
    except asyncio.CancelledError:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        raise


def _attach_diagnostics(response: ChatResponse) -> ChatResponse:
    diagnostics = current_model_diagnostics()
    if diagnostics is not None and diagnostics.enabled:
        final_source = diagnostics.ensure_final_answer_visible_source(
            response.answer,
            model=response.model or "runtime",
        )
        diagnostics.mark_final_answer_source(final_source)
        response.diagnostics = diagnostics.to_diagnostics()
    return response


async def _attach_follow_up_questions(
    response: ChatResponse,
    *,
    request: ChatRequest,
    persona_id: str,
    conversation_turns: list[ConversationTurn],
    settings: Settings,
) -> ChatResponse:
    if response.follow_up_questions:
        return response
    if "concise_style_acknowledgement" in (response.model or ""):
        return response
    questions = await generate_follow_up_questions(
        FollowUpContext(
            user_question=request.message,
            assistant_answer=response.answer,
            persona_id=persona_id,
            citations=response.citations,
            conversation_turns=conversation_turns,
        ),
        settings=settings,
    )
    return response.model_copy(update={"follow_up_questions": questions})


async def _stream_chat_impl(
    request: ChatRequest,
    user_context: RuntimeUserContext | None = None,
):
    request_id = new_request_id()
    session_id = request.session_id or new_request_id()
    user_context = user_context or RuntimeUserContext.dev()
    settings = get_settings()
    store = MetadataStore(settings.sqlite_path)
    effective_persona_id = normalize_persona_id(request.persona_id)
    conversation_turns = load_conversation_turns(
        request,
        session_id,
        effective_persona_id,
        store,
        user_context=user_context,
    )
    session_context_bundle = load_session_context_bundle(
        request,
        session_id,
        effective_persona_id,
        store,
        user_context=user_context,
    )
    total_start = time.perf_counter()
    yield _stream_stage_event(
        "route",
        "路由判断",
        total_start,
        f"本轮思考努力={request.thinking_effort}；检查长期记忆、短期追问、边界和人格先行路线。",
    )

    long_term_memory_response = maybe_build_long_term_memory_write_response(
        request=request,
        request_id=request_id,
        session_id=session_id,
        persona_id=effective_persona_id,
        user_context=user_context,
        total_ms=(time.perf_counter() - total_start) * 1000,
    )
    if long_term_memory_response is not None:
        yield _stream_stage_event("memory", "记忆写入", total_start, "处理显式记住/更正规则。")
        long_term_memory_response = _attach_diagnostics(long_term_memory_response)
        long_term_memory_response = await _attach_follow_up_questions(
            long_term_memory_response,
            request=request,
            persona_id=effective_persona_id,
            conversation_turns=conversation_turns,
            settings=settings,
        )
        store.record_chat(request=request, response=long_term_memory_response, user_id=user_context.user_id)
        yield _stream_stage_event("done", "完成", total_start, "记忆写入已完成。")
        yield f"data: {json.dumps({'type': 'final', 'value': long_term_memory_response.model_dump(exclude_none=True)}, ensure_ascii=False)}\n\n"
        return

    memory_response = runtime_maybe_build_short_term_memory_response(
        request=request,
        request_id=request_id,
        session_id=session_id,
        persona_id=effective_persona_id,
        user_context=user_context,
        turns=conversation_turns,
        total_ms=(time.perf_counter() - total_start) * 1000,
    )
    if memory_response is not None:
        yield _stream_stage_event("memory", "会话回忆", total_start, "直接回答上下文追问。")
        yield f"data: {json.dumps({'type': 'token', 'value': memory_response.answer}, ensure_ascii=False)}\n\n"
        memory_response = _attach_diagnostics(memory_response)
        memory_response = await _attach_follow_up_questions(
            memory_response,
            request=request,
            persona_id=effective_persona_id,
            conversation_turns=conversation_turns,
            settings=settings,
        )
        store.record_chat(request=request, response=memory_response, user_id=user_context.user_id)
        log_event(
            "chat.completed",
            {
                "request_id": request_id,
                "session_id": session_id,
                "query": request.message,
                "citations": [],
                "timings": memory_response.timings.model_dump(),
                "model": memory_response.model,
                "stream": True,
                "conversation_memory": True,
            },
        )
        yield _stream_stage_event("done", "完成", total_start, "短期记忆路线已完成。")
        yield f"data: {json.dumps({'type': 'final', 'value': memory_response.model_dump(exclude_none=True)}, ensure_ascii=False)}\n\n"
        return

    boundary_followup_response = runtime_maybe_build_boundary_followup_response(
        request=request,
        request_id=request_id,
        session_id=session_id,
        persona_id=effective_persona_id,
        turns=conversation_turns,
        total_ms=(time.perf_counter() - total_start) * 1000,
    )
    if boundary_followup_response is not None:
        yield _stream_stage_event("boundary", "边界追问", total_start, "处理历史人物时代边界追问。")
        yield f"data: {json.dumps({'type': 'token', 'value': boundary_followup_response.answer}, ensure_ascii=False)}\n\n"
        boundary_followup_response = _attach_diagnostics(boundary_followup_response)
        boundary_followup_response = await _attach_follow_up_questions(
            boundary_followup_response,
            request=request,
            persona_id=effective_persona_id,
            conversation_turns=conversation_turns,
            settings=settings,
        )
        store.record_chat(
            request=request,
            response=boundary_followup_response,
            user_id=user_context.user_id,
        )
        log_event(
            "chat.completed",
            {
                "request_id": request_id,
                "session_id": session_id,
                "query": request.message,
                "citations": [],
                "timings": boundary_followup_response.timings.model_dump(),
                "model": boundary_followup_response.model,
                "stream": True,
                "conversation_boundary_followup": True,
            },
        )
        yield _stream_stage_event("done", "完成", total_start, "边界追问路线已完成。")
        yield f"data: {json.dumps({'type': 'final', 'value': boundary_followup_response.model_dump(exclude_none=True)}, ensure_ascii=False)}\n\n"
        return

    dialogue_route = runtime_maybe_build_dialogue_policy_response(
        request=request,
        request_id=request_id,
        session_id=session_id,
        persona_id=effective_persona_id,
        total_ms=(time.perf_counter() - total_start) * 1000,
    )
    if dialogue_route is not None:
        response = dialogue_route.response
        yield _stream_stage_event("dialogue", "对话策略", total_start, "使用确定性关系/情绪路线。")
        yield f"data: {json.dumps({'type': 'token', 'value': response.answer}, ensure_ascii=False)}\n\n"
        response = _attach_diagnostics(response)
        response = await _attach_follow_up_questions(
            response,
            request=request,
            persona_id=effective_persona_id,
            conversation_turns=conversation_turns,
            settings=settings,
        )
        store.record_chat(request=request, response=response, user_id=user_context.user_id)
        log_event(
            "chat.completed",
            {
                "request_id": request_id,
                "session_id": session_id,
                "query": request.message,
                "citations": [],
                "timings": response.timings.model_dump(),
                "model": response.model,
                "stream": True,
                "dialogue_policy": dialogue_route.reason,
            },
        )
        yield _stream_stage_event("done", "完成", total_start, "对话策略路线已完成。")
        yield f"data: {json.dumps({'type': 'final', 'value': response.model_dump(exclude_none=True)}, ensure_ascii=False)}\n\n"
        return

    persona_first_generation_plan = build_generation_plan(settings, request.thinking_effort)
    yield _stream_stage_event(
        "persona_first_actor",
        "人格路线检查",
        total_start,
        (
            f"{request.thinking_effort} -> {persona_first_generation_plan.model}；"
            f"{persona_first_generation_plan.num_predict} token；"
            f"thinking 预算 {persona_first_generation_plan.thinking_budget or '关闭'}；"
            f"若进入 Persona-first，则先生成自然反应再做事实刹车。"
        ),
    )
    persona_first_task = asyncio.create_task(
        maybe_run_persona_first_turn(
            request=request,
            request_id=request_id,
            session_id=session_id,
            persona_id=effective_persona_id,
            user_context=user_context,
            conversation_turns=conversation_turns,
            session_context_bundle=session_context_bundle,
            settings=settings,
            total_start=total_start,
        )
    )
    async for diagnostic_event in _stream_diagnostics_until_done(persona_first_task):
        yield diagnostic_event
    persona_first_response = await persona_first_task
    if persona_first_response is not None:
        yield _stream_stage_event(
            "editor_fact_brake",
            "事实刹车",
            total_start,
            "保留自然语气，只修正不受支持的事实。",
        )
        yield f"data: {json.dumps({'type': 'token', 'value': persona_first_response.answer}, ensure_ascii=False)}\n\n"
        persona_first_response = _attach_diagnostics(persona_first_response)
        persona_first_response = await _attach_follow_up_questions(
            persona_first_response,
            request=request,
            persona_id=effective_persona_id,
            conversation_turns=conversation_turns,
            settings=settings,
        )
        store.record_chat(request=request, response=persona_first_response, user_id=user_context.user_id)
        log_event(
            "chat.completed",
            {
                "request_id": request_id,
                "session_id": session_id,
                "query": request.message,
                "citations": [item.chunk_id for item in persona_first_response.citations],
                "timings": persona_first_response.timings.model_dump(),
                "model": persona_first_response.model,
                "stream": True,
                "thinking_effort": request.thinking_effort,
                "persona_first": True,
                "mode": persona_first_response.mode,
            },
        )
        yield _stream_stage_event("done", "完成", total_start, "人格先行路线已完成。")
        yield f"data: {json.dumps({'type': 'final', 'value': persona_first_response.model_dump(exclude_none=True)}, ensure_ascii=False)}\n\n"
        return

    retrieval_start = time.perf_counter()
    yield _stream_stage_event("retrieval", "检索", total_start, "从本地档案和向量索引中取候选证据。")
    evidence_plan = runtime_build_evidence_plan(
        request=request,
        session_id=session_id,
        persona_id=effective_persona_id,
        turns=conversation_turns,
    )
    skip_retrieval = evidence_plan.skip_retrieval
    generation_plan = build_generation_plan(settings, request.thinking_effort)
    generation_timeout_seconds = generation_plan.timeout_seconds
    generation_num_predict = generation_plan.num_predict
    generation_model = generation_plan.model
    generation_think = generation_plan.think
    generation_thinking_budget = generation_plan.thinking_budget
    refinement_passes = generation_plan.refinement_passes
    model_client: LocalModelClient | None = None
    response_first_plan = build_response_first_plan(
        request=request,
        persona_id=effective_persona_id,
        skip_retrieval=skip_retrieval,
    )
    yield _stream_stage_event(
        "generation_plan",
        "生成预算",
        total_start,
        (
            f"{request.thinking_effort} -> {generation_model}；"
            f"{generation_num_predict} token；thinking 预算 {generation_thinking_budget or '关闭'}；"
            f"最长 {generation_timeout_seconds:g} 秒。"
        ),
    )
    response_first_draft: str | None = None
    if evidence_plan.bypass_response is None and response_first_plan.enabled:
        yield _stream_stage_event("draft", "自然草稿", total_start, "先生成短草稿，用来辅助检索。")
        model_client = LocalModelClient(settings)
        draft_task = asyncio.create_task(
            generate_response_first_draft(
                client=model_client,
                request=request,
                persona_id=effective_persona_id,
                conversation_turns=conversation_turns,
                session_context_bundle=session_context_bundle,
                timeout_seconds=generation_timeout_seconds,
                num_predict=generation_num_predict,
                model_name=generation_model,
            )
        )
        async for diagnostic_event in _stream_diagnostics_until_done(draft_task):
            yield diagnostic_event
        response_first_draft, _ = await draft_task
    if evidence_plan.bypass_response is not None:
        retrieval_response = evidence_plan.bypass_response
    else:
        retrieve_request = evidence_plan.to_retrieve_request().model_copy(
            update={"user_id": user_context.user_id}
        )
        if response_first_draft:
            retrieve_request = retrieve_request.model_copy(
                update={
                    "query": build_response_first_retrieval_query(
                        request.message,
                        response_first_draft,
                    )
                }
            )
        retrieval_response = retrieve(retrieve_request)
        retrieval_response.trace.original_query = request.message
        runtime_apply_evidence_plan_trace_notes(retrieval_response, evidence_plan)
    retrieval_ms = (time.perf_counter() - retrieval_start) * 1000
    if response_first_plan.enabled:
        retrieval_response.trace.notes.append(
            build_response_first_trace_note(response_first_plan, response_first_draft)
        )

    answer_parts: list[str] = []
    model = settings.generation_model
    boundary_answer = runtime_maybe_build_boundary_fast_path_answer(
        request=request,
        citations=retrieval_response.citations,
        persona_id=retrieval_response.trace.persona_id,
        enabled=settings.boundary_fast_path_enabled,
    )
    approved_memory_items = []
    if boundary_answer is None and not skip_retrieval:
        approved_memory_items = retrieve_approved_memories(
            sqlite_path=settings.sqlite_path,
            user_id=user_context.user_id,
            session_id=session_id,
            persona_id=retrieval_response.trace.persona_id,
            query=request.message,
            limit=5,
            include_user_global=True,
        )
    evidence_policy = build_evidence_policy(
        query=request.message,
        persona_id=retrieval_response.trace.persona_id,
        has_approved_memory=bool(approved_memory_items),
    )
    use_no_evidence_fallback = (
        not retrieval_response.citations
        and not skip_retrieval
        and boundary_answer is None
        and not approved_memory_items
        and should_use_no_evidence_fallback(request.message, retrieval_response.trace.persona_id)
    )
    post_persona_alignment_reason: str | None = None

    if boundary_answer is not None:
        apply_citation_budget(retrieval_response, evidence_plan.intended_evidence_budget)
        context_ms = 0.0
        generation_start = time.perf_counter()
        model = f"{settings.generation_model}+boundary_fast_path"
        answer_parts.append(boundary_answer.answer)
        yield _stream_stage_event("boundary", "边界处理", total_start, "使用快速边界回答。")
        yield f"data: {json.dumps({'type': 'token', 'value': boundary_answer.answer}, ensure_ascii=False)}\n\n"
    elif use_no_evidence_fallback:
        context_ms = 0.0
        generation_start = time.perf_counter()
        model = f"{settings.generation_model}+no_evidence_fallback"
        no_evidence_answer = immersive_no_evidence_answer(
            request.message,
            retrieval_response.trace.persona_id,
        )
        answer_parts.append(no_evidence_answer)
        yield _stream_stage_event("fallback", "无证据回应", total_start, "没有可用档案证据，使用自然保守回答。")
        yield f"data: {json.dumps({'type': 'token', 'value': no_evidence_answer}, ensure_ascii=False)}\n\n"
    else:
        context_start = time.perf_counter()
        yield _stream_stage_event("context", "组织上下文", total_start, "压缩证据、记忆和人物约束。")
        generation_context: GenerationContext | None = None
        if skip_retrieval:
            prompt = build_ordinary_task_prompt(
                request,
                retrieval_response.trace.persona_id,
                session_context_bundle=session_context_bundle,
            )
        else:
            retrieval_response.citations = rank_citations_for_policy(
                retrieval_response.citations,
                evidence_policy,
            )
            generation_context = build_generation_context(
                retrieval_response.citations,
                context_budget_for_policy(
                    evidence_policy,
                    evidence_plan.intended_evidence_budget,
                ),
            )
            long_term_memory_context = format_memory_context(approved_memory_items)
            if approved_memory_items:
                retrieval_response.trace.notes.append(
                    f"Long-term memory V1: injected {len(approved_memory_items)} approved user memories."
                )
            retrieval_response.trace.notes.append(
                build_evidence_policy_trace_note(evidence_policy, generation_context)
            )
            add_context_trace_note(retrieval_response, generation_context)
            apply_generation_context_selection(retrieval_response, generation_context)
            prompt = build_prompt(
                request,
                retrieval_response.citations,
                persona_id=retrieval_response.trace.persona_id,
                conversation_turns=conversation_turns,
                session_context_bundle=session_context_bundle,
                generation_context=generation_context,
                long_term_memory_context=long_term_memory_context,
                response_first_context=format_response_first_prompt_context(
                    response_first_draft or ""
                ),
            )
        context_ms = (time.perf_counter() - context_start) * 1000

        generation_start = time.perf_counter()
        yield _stream_stage_event("generation", "思考生成", total_start, "调用本地模型生成回答。")
        generated_parts: list[str] = []
        add_thinking_effort_trace_note(
            retrieval_response,
            request.thinking_effort,
            generation_timeout_seconds,
            generation_num_predict,
            refinement_passes,
            generation_model,
            generation_think,
            generation_thinking_budget,
        )
        model_client = model_client or LocalModelClient(settings)
        with model_diagnostic_phase("main_generation"):
            async for token, token_model in model_client.stream_generate(
                prompt,
                timeout_seconds=generation_timeout_seconds,
                num_predict=generation_num_predict,
                model_name=generation_model,
                think=generation_think,
                thinking_budget=generation_thinking_budget,
            ):
                model = token_model
                generated_parts.append(token)
                diagnostics = current_model_diagnostics()
                if diagnostics is not None and diagnostics.enabled and diagnostics.live_stream:
                    for payload in diagnostics.drain_live_payloads():
                        yield _stream_diagnostic_event(payload)
        diagnostics = current_model_diagnostics()
        if diagnostics is not None and diagnostics.enabled and diagnostics.live_stream:
            for payload in diagnostics.drain_live_payloads():
                yield _stream_diagnostic_event(payload)
        generated_answer = model_client._clean_response("".join(generated_parts))
        visible_answer = enforce_immersive_answer(
            generated_answer,
            request.message,
            retrieval_response.trace.persona_id,
        )
        visible_answer = enforce_contextual_followup_answer(
            visible_answer,
            request.message,
            conversation_turns,
        )
        if refinement_passes > 0:
            yield _stream_stage_event(
                "quality_refine",
                "本地精修",
                total_start,
                f"追加 {refinement_passes} 轮本地自检改写；hidden thinking 会继续实时进入开发者诊断。",
            )
        refine_task = asyncio.create_task(
            refine_answer_for_effort(
                client=model_client,
                request=request,
                answer=visible_answer,
                citations=retrieval_response.citations,
                persona_id=retrieval_response.trace.persona_id,
                conversation_turns=conversation_turns,
                session_context_bundle=session_context_bundle,
                timeout_seconds=generation_timeout_seconds,
                num_predict=generation_num_predict,
                refinement_passes=refinement_passes,
                current_model=model,
                model_name=generation_model,
                think=generation_think,
                thinking_budget=generation_thinking_budget,
                generation_context=generation_context,
            )
        )
        async for diagnostic_event in _stream_diagnostics_until_done(refine_task):
            yield diagnostic_event
        visible_answer, model = await refine_task
        if settings.post_persona_alignment_enabled:
            yield _stream_stage_event(
                "post_persona_alignment",
                "口吻校准",
                total_start,
                "必要时追加 1 轮本地口吻修正；若触发模型调用，开发者诊断会持续刷新。",
            )
        align_task = asyncio.create_task(
            align_answer_after_generation(
                client=model_client,
                request=request,
                answer=visible_answer,
                persona_id=retrieval_response.trace.persona_id,
                conversation_turns=conversation_turns,
                session_context_bundle=session_context_bundle,
                timeout_seconds=generation_timeout_seconds,
                num_predict=generation_num_predict,
                current_model=model,
                model_name=generation_model,
                think=generation_think,
                thinking_budget=generation_thinking_budget,
                generation_context=generation_context,
                enabled=settings.post_persona_alignment_enabled,
            )
        )
        async for diagnostic_event in _stream_diagnostics_until_done(align_task):
            yield diagnostic_event
        visible_answer, model, post_persona_alignment_reason = await align_task
        if post_persona_alignment_reason:
            retrieval_response.trace.notes.append(
                build_post_persona_alignment_trace_note(post_persona_alignment_reason)
            )
        language_repair_task = asyncio.create_task(
            repair_answer_language_if_needed(
                client=model_client,
                answer=visible_answer,
                query=request.message,
                timeout_seconds=generation_timeout_seconds,
                num_predict=generation_num_predict,
                model_name=generation_model,
                think=generation_think,
                thinking_budget=generation_thinking_budget,
            )
        )
        async for diagnostic_event in _stream_diagnostics_until_done(language_repair_task):
            yield diagnostic_event
        visible_answer, language_repaired = await language_repair_task
        if language_repaired:
            model = f"{model}+language_repair"
        visible_answer = soften_over_literary_persona_answer(
            visible_answer,
            retrieval_response.trace.persona_id,
            request.message,
        )
        answer_parts.append(visible_answer)
        yield f"data: {json.dumps({'type': 'token', 'value': visible_answer}, ensure_ascii=False)}\n\n"

    generation_ms = (time.perf_counter() - generation_start) * 1000
    answer = LocalModelClient(settings)._clean_response("".join(answer_parts))
    answer = enforce_immersive_answer(answer, request.message, retrieval_response.trace.persona_id)
    answer = enforce_contextual_followup_answer(answer, request.message, conversation_turns)
    answer = soften_over_literary_persona_answer(
        answer,
        retrieval_response.trace.persona_id,
        request.message,
    )
    answer = repair_cited_latency_metric_drift(answer, retrieval_response.citations)
    answer = ensure_user_memory_framing(answer, approved_memory_items, request.message)
    verification_start = time.perf_counter()
    yield _stream_stage_event("verification", "核验收尾", total_start, "检查引用支持与最终回答。")
    verification = verify_answer(answer, retrieval_response.citations)
    verification_ms = (time.perf_counter() - verification_start) * 1000
    total_ms = (time.perf_counter() - total_start) * 1000
    timings = TimingBreakdown(
        retrieval_ms=round(retrieval_ms, 2),
        context_ms=round(context_ms, 2),
        generation_ms=round(generation_ms, 2),
        verification_ms=round(verification_ms, 2),
        total_ms=round(total_ms, 2),
    )
    confidence = "medium" if retrieval_response.citations or approved_memory_items else "low"
    mode = (
        "evidence_grounded"
        if retrieval_response.citations
        else "memory_grounded"
        if approved_memory_items
        else "no_evidence"
    )
    response = ChatResponse(
        answer=answer,
        mode=mode,
        confidence=confidence,
        thinking_effort=request.thinking_effort,
        citations=retrieval_response.citations,
        memory_citations=memory_citations(approved_memory_items),
        retrieval_trace=retrieval_response.trace,
        verification=verification,
        timings=timings,
        model=model,
        request_id=request_id,
        session_id=session_id,
    )
    response = _attach_diagnostics(response)
    response = await _attach_follow_up_questions(
        response,
        request=request,
        persona_id=retrieval_response.trace.persona_id,
        conversation_turns=conversation_turns,
        settings=settings,
    )
    store.record_chat(request=request, response=response, user_id=user_context.user_id)
    log_event(
        "chat.completed",
        {
            "request_id": request_id,
            "session_id": session_id,
            "query": request.message,
            "citations": [item.chunk_id for item in retrieval_response.citations],
            "timings": timings.model_dump(),
            "model": model,
            "stream": True,
            "boundary_fast_path": boundary_answer.reason if boundary_answer else None,
            "thinking_effort": request.thinking_effort,
            "generation_timeout_seconds": generation_timeout_seconds,
            "generation_num_predict": generation_num_predict,
            "generation_thinking_budget": generation_thinking_budget,
            "refinement_passes": refinement_passes,
            "post_persona_alignment": post_persona_alignment_reason,
        },
    )
    yield _stream_stage_event("done", "完成", total_start, "回答已生成并记录。")
    yield f"data: {json.dumps({'type': 'final', 'value': response.model_dump(exclude_none=True)}, ensure_ascii=False)}\n\n"







































































































