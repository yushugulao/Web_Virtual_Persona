from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable

from app.backend.persona_runtime.turn_context import TurnContext
from app.backend.persona_runtime.user_context import RuntimeUserContext
from app.backend.schemas.chat import ChatRequest, ChatResponse


AnswerHandler = Callable[[ChatRequest, RuntimeUserContext], Awaitable[ChatResponse]]
StreamHandler = Callable[[ChatRequest, RuntimeUserContext], AsyncIterator[str]]


class TurnRuntime:
    """Entry point for one persona chat turn.

    Phase 1A intentionally keeps this as a transparent facade over the existing implementation.
    Later phases will move routing, evidence planning, memory resolution, and generation behind
    this boundary while keeping FastAPI and eval callers stable.
    """

    def __init__(
        self,
        *,
        answer_handler: AnswerHandler,
        stream_handler: StreamHandler,
    ) -> None:
        self._answer_handler = answer_handler
        self._stream_handler = stream_handler

    async def answer(
        self,
        request: ChatRequest,
        user_context: RuntimeUserContext | None = None,
    ) -> ChatResponse:
        TurnContext.from_request(request)
        return await self._answer_handler(request, user_context or RuntimeUserContext.dev())

    async def stream(
        self,
        request: ChatRequest,
        user_context: RuntimeUserContext | None = None,
    ) -> AsyncIterator[str]:
        TurnContext.from_request(request)
        async for event in self._stream_handler(request, user_context or RuntimeUserContext.dev()):
            yield event
