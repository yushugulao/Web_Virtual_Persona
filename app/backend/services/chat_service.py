from __future__ import annotations

import asyncio

from app.backend.core.config import get_settings
from app.backend.core.logging import log_event
from app.backend.persona_runtime import TurnRuntime
from app.backend.persona_runtime.response_guards import (
    clean_visible_answer_style,
    enforce_contextual_followup_answer,
    enforce_immersive_answer,
    immersive_no_evidence_answer,
    strip_leading_question_echo,
)
from app.backend.persona_runtime.prompt_builder import (
    build_answer_refinement_prompt,
    build_ordinary_task_prompt,
    build_prompt,
)
from app.backend.persona_runtime.turn_executor import (
    _answer_chat_impl,
    _stream_chat_impl,
)
from app.backend.persona_runtime.user_context import RuntimeUserContext
from app.backend.schemas.chat import ChatRequest, ChatResponse
from app.backend.services.model_diagnostics import ModelDiagnosticsCollector, model_diagnostics_scope
from app.backend.services.model_service import release_runtime_models

__all__ = [
    "answer_chat",
    "build_answer_refinement_prompt",
    "build_ordinary_task_prompt",
    "build_prompt",
    "clean_visible_answer_style",
    "enforce_contextual_followup_answer",
    "enforce_immersive_answer",
    "get_turn_runtime",
    "immersive_no_evidence_answer",
    "stream_chat",
    "strip_leading_question_echo",
]

_turn_runtime: TurnRuntime | None = None


def get_turn_runtime() -> TurnRuntime:
    global _turn_runtime
    if _turn_runtime is None:
        _turn_runtime = TurnRuntime(
            answer_handler=_answer_chat_impl,
            stream_handler=_stream_chat_impl,
        )
    return _turn_runtime


async def answer_chat(
    request: ChatRequest,
    *,
    diagnostics_enabled: bool = False,
    user_context: RuntimeUserContext | None = None,
) -> ChatResponse:
    collector = ModelDiagnosticsCollector(
        enabled=True,
        live_stream=False,
        include_hidden=diagnostics_enabled,
    )
    with model_diagnostics_scope(collector):
        return await get_turn_runtime().answer(request, user_context or RuntimeUserContext.dev())


async def stream_chat(
    request: ChatRequest,
    *,
    diagnostics_enabled: bool = False,
    user_context: RuntimeUserContext | None = None,
):
    collector = ModelDiagnosticsCollector(
        enabled=True,
        live_stream=True,
        include_hidden=diagnostics_enabled,
    )
    try:
        with model_diagnostics_scope(collector):
            async for event in get_turn_runtime().stream(
                request,
                user_context or RuntimeUserContext.dev(),
            ):
                yield event
    except asyncio.CancelledError:
        try:
            await asyncio.shield(_release_cancelled_effort_model(request))
        except Exception:
            pass
        raise


async def _release_cancelled_effort_model(request: ChatRequest) -> None:
    settings = get_settings()
    release_result = await release_runtime_models(
        settings,
        thinking_effort=request.thinking_effort,
        include_embedding=False,
        include_all_generation_models=False,
    )
    log_event(
        "chat.cancelled",
        {
            "session_id": request.session_id,
            "persona_id": request.persona_id,
            "thinking_effort": request.thinking_effort,
            "released_models": release_result["released_models"],
            "still_loaded_models": release_result["still_loaded_models"],
            "released": release_result["ok"],
        },
    )
