from __future__ import annotations

from app.backend.persona_runtime.context_builder import GenerationContext
from app.backend.persona_runtime.post_persona_alignment import (
    adjacent_answer_similarity,
    build_adjacent_repetition_repair_prompt,
    build_post_persona_alignment_plan,
    build_post_persona_alignment_prompt,
    needs_adjacent_repetition_repair,
    soften_over_literary_persona_answer,
)
from app.backend.persona_runtime.prompt_builder import build_answer_refinement_prompt
from app.backend.persona_runtime.response_guards import (
    enforce_contextual_followup_answer,
    enforce_immersive_answer,
)
from app.backend.schemas.chat import ChatRequest
from app.backend.services.conversation_memory import ConversationTurn, SessionContextBundle
from app.backend.services.model_diagnostics import model_diagnostic_phase
from app.backend.services.model_service import LocalModelClient
from app.backend.services.persona_service import normalize_persona_id


async def refine_answer_for_effort(
    *,
    client: LocalModelClient,
    request: ChatRequest,
    answer: str,
    citations,
    persona_id: str | None,
    conversation_turns: list[ConversationTurn],
    timeout_seconds: float,
    num_predict: int,
    refinement_passes: int,
    current_model: str,
    session_context_bundle: SessionContextBundle | None = None,
    model_name: str | None = None,
    think: bool | None = None,
    thinking_budget: int | None = None,
    generation_context: GenerationContext | None = None,
) -> tuple[str, str]:
    if refinement_passes <= 0 or not answer.strip() or current_model == "fallback":
        return answer, current_model

    refined_answer = answer.strip()
    final_model = current_model
    effective_persona_id = normalize_persona_id(persona_id or request.persona_id)
    for pass_index in range(1, refinement_passes + 1):
        prompt = build_answer_refinement_prompt(
            request=request,
            draft_answer=refined_answer,
            citations=citations,
            persona_id=effective_persona_id,
            conversation_turns=conversation_turns,
            session_context_bundle=session_context_bundle,
            pass_index=pass_index,
            total_passes=refinement_passes,
            generation_context=generation_context,
        )
        with model_diagnostic_phase(f"quality_refine_{pass_index}"):
            candidate, candidate_model = await client.generate(
                prompt,
                timeout_seconds=timeout_seconds,
                num_predict=num_predict,
                model_name=model_name,
                think=think,
                thinking_budget=thinking_budget,
            )
        if candidate_model == "fallback":
            break
        candidate = client._clean_response(candidate)
        if not candidate.strip():
            continue
        candidate = enforce_immersive_answer(candidate, request.message, effective_persona_id)
        candidate = enforce_contextual_followup_answer(candidate, request.message, conversation_turns)
        refined_answer = candidate.strip()
        final_model = f"{candidate_model}+quality_refine_{pass_index}of{refinement_passes}"
    return refined_answer, final_model

async def align_answer_after_generation(
    *,
    client: LocalModelClient,
    request: ChatRequest,
    answer: str,
    persona_id: str | None,
    conversation_turns: list[ConversationTurn],
    timeout_seconds: float,
    num_predict: int,
    current_model: str,
    session_context_bundle: SessionContextBundle | None = None,
    model_name: str | None = None,
    think: bool | None = None,
    thinking_budget: int | None = None,
    generation_context: GenerationContext | None = None,
    enabled: bool = True,
) -> tuple[str, str, str | None]:
    if current_model == "fallback":
        return answer, current_model, None
    effective_persona_id = normalize_persona_id(persona_id or request.persona_id)
    plan = build_post_persona_alignment_plan(
        request=request,
        draft_answer=answer,
        persona_id=effective_persona_id,
        generation_context=generation_context,
        enabled=enabled,
    )
    if not plan.should_align or generation_context is None:
        return answer, current_model, None
    prompt = build_post_persona_alignment_prompt(
        request=request,
        draft_answer=answer,
        persona_id=effective_persona_id,
        generation_context=generation_context,
        conversation_turns=conversation_turns,
        session_context_bundle=session_context_bundle,
        reason=plan.reason,
    )
    try:
        with model_diagnostic_phase("post_persona_alignment"):
            candidate, candidate_model = await client.generate(
                prompt,
                timeout_seconds=timeout_seconds,
                num_predict=max(384, min(num_predict, 1536)),
                model_name=model_name,
                think=think,
                thinking_budget=thinking_budget,
            )
    except Exception:
        return answer, current_model, None
    if candidate_model == "fallback":
        return answer, current_model, None
    candidate = client._clean_response(candidate)
    if not candidate.strip():
        return answer, current_model, None
    candidate = enforce_immersive_answer(candidate, request.message, effective_persona_id)
    candidate = enforce_contextual_followup_answer(candidate, request.message, conversation_turns)
    candidate = soften_over_literary_persona_answer(candidate, effective_persona_id, request.message)
    aligned_answer = candidate.strip()
    aligned_model = f"{current_model}+post_persona_alignment"
    aligned_reason = plan.reason

    previous_answer = conversation_turns[-1].answer if conversation_turns else ""
    if previous_answer and needs_adjacent_repetition_repair(previous_answer, aligned_answer):
        repair_prompt = build_adjacent_repetition_repair_prompt(
            request=request,
            previous_answer=previous_answer,
            draft_answer=aligned_answer,
            persona_id=effective_persona_id,
            generation_context=generation_context,
            conversation_turns=conversation_turns,
            session_context_bundle=session_context_bundle,
            reason=aligned_reason,
        )
        try:
            with model_diagnostic_phase("post_persona_alignment_repair"):
                repaired, repair_model = await client.generate(
                    repair_prompt,
                    timeout_seconds=timeout_seconds,
                    num_predict=max(384, min(num_predict, 1536)),
                    model_name=model_name,
                    think=think,
                    thinking_budget=thinking_budget,
                )
        except Exception:
            return aligned_answer, aligned_model, aligned_reason
        if repair_model != "fallback":
            repaired = client._clean_response(repaired)
            if repaired.strip():
                repaired = enforce_immersive_answer(repaired, request.message, effective_persona_id)
                repaired = enforce_contextual_followup_answer(repaired, request.message, conversation_turns)
                repaired = soften_over_literary_persona_answer(repaired, effective_persona_id, request.message)
                repaired = repaired.strip()
                current_similarity = adjacent_answer_similarity(previous_answer, aligned_answer)
                repaired_similarity = adjacent_answer_similarity(previous_answer, repaired)
                if repaired_similarity + 0.03 < current_similarity:
                    return (
                        repaired,
                        f"{aligned_model}+adjacent_repetition_repair",
                        f"{aligned_reason}+adjacent_repetition_repair",
                    )

    return aligned_answer, aligned_model, aligned_reason
