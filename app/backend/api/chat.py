from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.backend.auth.dependencies import require_user
from app.backend.core.config import get_settings
from app.backend.followups import FollowUpContext, local_follow_up_questions
from app.backend.persona_runtime.user_context import RuntimeUserContext
from app.backend.schemas.auth import AuthUser
from app.backend.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatSessionCreateRequest,
    ChatSessionMessagesResponse,
    ChatSessionSummary,
    ThinkingEffort,
)
from app.backend.services.chat_service import answer_chat, stream_chat
from app.backend.services.metadata_store import MetadataStore
from app.backend.services.model_service import release_model_for_effort, release_runtime_models
from app.backend.services.persona_catalog_service import persona_display_name, resolve_chat_persona_id
from app.backend.services.persona_service import get_persona
from app.backend.services.session_opening import generate_session_opening


router = APIRouter(tags=["chat"])


class ReleaseEffortModelRequest(BaseModel):
    thinking_effort: ThinkingEffort


class ReleaseEffortModelResponse(BaseModel):
    released: bool
    model: str


class ReleaseRuntimeModelsRequest(BaseModel):
    thinking_effort: ThinkingEffort | None = None
    include_embedding: bool = False
    include_all_generation_models: bool = False


class ReleaseRuntimeModelsResponse(BaseModel):
    released_models: list[str]
    still_loaded_models: list[str]
    attempted_models: list[str]
    elapsed_ms: float
    ok: bool


def _diagnostics_enabled(request: ChatRequest, user: AuthUser) -> bool:
    settings = get_settings()
    return bool(
        request.debug
        and user.role == "admin"
        and (settings.auth_required or user.id != "dev-auth-disabled")
    )


def _metadata_store() -> MetadataStore:
    return MetadataStore(get_settings().sqlite_path)


def _session_summary(row: dict) -> ChatSessionSummary:
    return ChatSessionSummary(
        session_id=row["session_id"],
        user_id=row.get("user_id"),
        persona_id=row["persona_id"],
        persona_name=persona_display_name(row["persona_id"]),
        title=row["title"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
        message_count=row["message_count"],
        last_message_preview=row["last_message_preview"],
        status=row.get("status", "active"),
        archived_at=row.get("archived_at"),
        deleted_at=row.get("deleted_at"),
        opening_message=row.get("opening_message"),
    )


def _validate_request_session(request: ChatRequest, user: AuthUser) -> ChatRequest:
    effective_persona_id = resolve_chat_persona_id(persona_id=request.persona_id, user_id=user.id)
    if effective_persona_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="虚拟分身不存在、尚未准备好，或当前账号无权访问。",
        )
    request_updates: dict[str, object] = {"persona_id": effective_persona_id}
    if effective_persona_id.startswith("user_persona_"):
        request_updates["include_private"] = True
    session_id = request.session_id
    if not session_id:
        return request.model_copy(update=request_updates)
    store = _metadata_store()
    existing = store.get_chat_session(session_id)
    if existing is None:
        store.ensure_chat_session(
            session_id=session_id,
            user_id=user.id,
            persona_id=effective_persona_id,
            first_message=request.message,
        )
        return request.model_copy(update=request_updates)
    if existing["user_id"] != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该会话不属于当前用户。",
        )
    if existing.get("status") == "archived":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该会话已归档，请先在设置中恢复，或新建对话。",
        )
    if existing.get("status") == "deleted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该会话已删除，无法继续，请新建对话。",
        )
    if existing["persona_id"] != effective_persona_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该会话已经绑定到另一个虚拟分身，请从会话列表恢复或新建对话。",
        )
    store.ensure_chat_session(
        session_id=session_id,
        user_id=user.id,
        persona_id=effective_persona_id,
        first_message=request.message,
    )
    return request.model_copy(update=request_updates)


@router.get("/chat/sessions", response_model=list[ChatSessionSummary])
def list_chat_sessions(
    sort: str = Query(default="recent", pattern="^(recent|persona)$"),
    session_status: str = Query(default="active", alias="status", pattern="^(active|archived|all)$"),
    user: AuthUser = Depends(require_user),
) -> list[ChatSessionSummary]:
    sessions = _metadata_store().list_chat_sessions(user_id=user.id, sort=sort, status=session_status)
    return [_session_summary(row) for row in sessions]


@router.post("/chat/sessions", response_model=ChatSessionSummary)
async def create_chat_session(
    request: ChatSessionCreateRequest,
    user: AuthUser = Depends(require_user),
) -> ChatSessionSummary:
    persona_id = resolve_chat_persona_id(persona_id=request.persona_id, user_id=user.id)
    if persona_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="虚拟分身不存在、尚未准备好，或当前账号无权访问。",
        )
    persona = get_persona(persona_id)
    row = _metadata_store().create_chat_session(
        user_id=user.id,
        persona_id=persona_id,
        title=request.title,
    )
    summary = _session_summary(row)
    summary.opening_message = await generate_session_opening(persona)
    return summary


@router.post("/chat/sessions/{session_id}/archive", response_model=ChatSessionSummary)
def archive_chat_session(
    session_id: str,
    user: AuthUser = Depends(require_user),
) -> ChatSessionSummary:
    row = _metadata_store().archive_chat_session(user_id=user.id, session_id=session_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在。")
    return _session_summary(row)


@router.post("/chat/sessions/{session_id}/restore", response_model=ChatSessionSummary)
def restore_archived_chat_session(
    session_id: str,
    user: AuthUser = Depends(require_user),
) -> ChatSessionSummary:
    row = _metadata_store().restore_chat_session(user_id=user.id, session_id=session_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在。")
    return _session_summary(row)


@router.delete("/chat/sessions/{session_id}")
def delete_archived_chat_session(
    session_id: str,
    user: AuthUser = Depends(require_user),
) -> dict[str, str]:
    store = _metadata_store()
    existing = store.get_chat_session(session_id)
    if existing is None or existing["user_id"] != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在。")
    if existing.get("status") != "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="请先归档会话，再永久删除。")
    deleted = store.delete_archived_chat_session(user_id=user.id, session_id=session_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在。")
    return {"message": "会话已永久删除。"}


@router.get("/chat/sessions/{session_id}/messages", response_model=ChatSessionMessagesResponse)
def get_chat_session_messages(
    session_id: str,
    user: AuthUser = Depends(require_user),
) -> ChatSessionMessagesResponse:
    store = _metadata_store()
    session = store.get_chat_session(session_id)
    if session is None or session["user_id"] != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在。")
    messages = store.chat_session_messages(
        user_id=user.id,
        session_id=session_id,
        include_diagnostics=user.role == "admin",
    )
    previous_user_message = ""
    for message in messages:
        if message["role"] == "user":
            previous_user_message = message["content"]
            continue
        if message.get("follow_up_questions"):
            continue
        questions = local_follow_up_questions(
            FollowUpContext(
                user_question=previous_user_message,
                assistant_answer=message["content"],
                persona_id=message["persona_id"],
                citations=[],
                conversation_turns=[],
            )
        )
        message["follow_up_questions"] = questions
        if questions:
            store.update_chat_follow_up_questions(
                user_id=user.id,
                session_id=session_id,
                request_id=message["request_id"],
                questions=questions,
            )
    return ChatSessionMessagesResponse(
        session=_session_summary(session),
        messages=messages,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user: AuthUser = Depends(require_user)) -> ChatResponse:
    request = _validate_request_session(request, user)
    return await answer_chat(
        request,
        diagnostics_enabled=_diagnostics_enabled(request, user),
        user_context=RuntimeUserContext.from_auth_user(user),
    )


@router.post("/chat/release-effort-model", response_model=ReleaseEffortModelResponse)
async def release_effort_model(
    request: ReleaseEffortModelRequest,
    _user: AuthUser = Depends(require_user),
) -> ReleaseEffortModelResponse:
    released, model_name = await release_model_for_effort(get_settings(), request.thinking_effort)
    return ReleaseEffortModelResponse(released=released, model=model_name)


@router.post("/chat/release-runtime-models", response_model=ReleaseRuntimeModelsResponse)
async def release_runtime_model_endpoint(
    request: ReleaseRuntimeModelsRequest,
    _user: AuthUser = Depends(require_user),
) -> ReleaseRuntimeModelsResponse:
    result = await release_runtime_models(
        get_settings(),
        thinking_effort=request.thinking_effort,
        include_embedding=request.include_embedding,
        include_all_generation_models=request.include_all_generation_models,
    )
    return ReleaseRuntimeModelsResponse(**result)


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, user: AuthUser = Depends(require_user)) -> StreamingResponse:
    request = _validate_request_session(request, user)
    return StreamingResponse(
        stream_chat(
            request,
            diagnostics_enabled=_diagnostics_enabled(request, user),
            user_context=RuntimeUserContext.from_auth_user(user),
        ),
        media_type="text/event-stream",
    )
