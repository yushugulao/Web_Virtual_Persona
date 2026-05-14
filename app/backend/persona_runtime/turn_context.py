from __future__ import annotations

from dataclasses import dataclass

from app.backend.schemas.chat import ChatRequest, ThinkingEffort
from app.backend.services.persona_service import normalize_persona_id
from app.backend.services.response_language import ResponseLanguage, detect_response_language


@dataclass(frozen=True)
class TurnContext:
    """Side-effect-free view of a chat turn.

    The current runtime still delegates behavior to the legacy chat implementation. This object is
    the stable carrier for later extraction of routing, evidence planning, memory, and generation.
    """

    request: ChatRequest
    message: str
    requested_session_id: str | None
    requested_persona_id: str
    effective_persona_id: str
    response_language: ResponseLanguage
    thinking_effort: ThinkingEffort
    top_k: int
    include_private: bool
    debug: bool

    @classmethod
    def from_request(cls, request: ChatRequest) -> "TurnContext":
        return cls(
            request=request,
            message=request.message,
            requested_session_id=request.session_id,
            requested_persona_id=request.persona_id,
            effective_persona_id=normalize_persona_id(request.persona_id),
            response_language=detect_response_language(request.message),
            thinking_effort=request.thinking_effort,
            top_k=request.top_k,
            include_private=request.include_private,
            debug=request.debug,
        )
