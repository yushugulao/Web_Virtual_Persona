from fastapi import APIRouter, Depends, HTTPException, Query

from app.backend.auth.dependencies import require_admin, require_user
from app.backend.core.config import get_settings
from app.backend.memory.memory_gate import classify_memory_type, classify_sensitivity
from app.backend.memory.memory_store import (
    DEFAULT_MEMORY_SESSION_ID,
    USER_GLOBAL_MEMORY_PERSONA_ID,
    USER_GLOBAL_MEMORY_SCOPE,
    USER_GLOBAL_MEMORY_SESSION_ID,
    MemoryStore,
)
from app.backend.schemas.auth import AuthUser
from app.backend.schemas.memory import (
    MemoryActionResponse,
    MemoryItem,
    MemoryListResponse,
    MemoryProposeRequest,
    MemoryStatsResponse,
)


router = APIRouter(tags=["memory"], dependencies=[Depends(require_user)])


@router.get("/memory/items", response_model=MemoryListResponse)
def list_memory_items(
    persona_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    scope: str = Query(default="session", pattern="^(session|user_global|all)$"),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthUser = Depends(require_user),
) -> MemoryListResponse:
    store = MemoryStore(get_settings().sqlite_path)
    if scope == "all":
        session_items = store.list_items(
            user_id=user.id,
            session_id=session_id,
            persona_id=persona_id,
            status=status,
            scope="session",
            limit=limit,
        )
        global_items = store.list_items(
            user_id=user.id,
            persona_id=USER_GLOBAL_MEMORY_PERSONA_ID,
            status=status,
            scope=USER_GLOBAL_MEMORY_SCOPE,
            limit=limit,
            only_active_origins=True,
        )
        items = sorted(
            [*session_items, *global_items],
            key=lambda item: item.updated_at,
            reverse=True,
        )[:limit]
        return MemoryListResponse(items=items)
    effective_scope = None if scope == "all" else scope
    effective_session_id = session_id
    effective_persona_id = persona_id
    if scope == USER_GLOBAL_MEMORY_SCOPE:
        effective_session_id = None
        effective_persona_id = USER_GLOBAL_MEMORY_PERSONA_ID
    only_active_origins = scope == USER_GLOBAL_MEMORY_SCOPE
    items = store.list_items(
        user_id=user.id,
        session_id=effective_session_id,
        persona_id=effective_persona_id,
        status=status,
        scope=effective_scope,
        limit=limit,
        only_active_origins=only_active_origins,
    )
    return MemoryListResponse(items=items)


@router.get("/memory/stats", response_model=MemoryStatsResponse)
def memory_stats(
    persona_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    scope: str = Query(default="session", pattern="^(session|user_global|all)$"),
    user: AuthUser = Depends(require_user),
) -> MemoryStatsResponse:
    store = MemoryStore(get_settings().sqlite_path)
    if scope == "all":
        session_stats = store.stats(
            user_id=user.id,
            session_id=session_id,
            persona_id=persona_id,
            scope="session",
        )
        global_stats = store.stats(
            user_id=user.id,
            persona_id=USER_GLOBAL_MEMORY_PERSONA_ID,
            scope=USER_GLOBAL_MEMORY_SCOPE,
            only_active_origins=True,
        )
        merged = dict(session_stats)
        merged["total"] = int(session_stats["total"]) + int(global_stats["total"])
        merged["current_session_total"] = merged["total"]
        merged["current_session_approved"] = int(session_stats["current_session_approved"]) + int(
            global_stats["current_session_approved"]
        )
        return MemoryStatsResponse.model_validate(merged)
    effective_scope = None if scope == "all" else scope
    effective_session_id = session_id
    effective_persona_id = persona_id
    if scope == USER_GLOBAL_MEMORY_SCOPE:
        effective_session_id = None
        effective_persona_id = USER_GLOBAL_MEMORY_PERSONA_ID
    only_active_origins = scope == USER_GLOBAL_MEMORY_SCOPE
    return MemoryStatsResponse.model_validate(
        store.stats(
            user_id=user.id,
            session_id=effective_session_id,
            persona_id=effective_persona_id,
            scope=effective_scope,
            only_active_origins=only_active_origins,
        )
    )


@router.post("/memory/propose", response_model=MemoryActionResponse)
def propose_memory(
    request: MemoryProposeRequest,
    user: AuthUser = Depends(require_user),
) -> MemoryActionResponse:
    sensitivity = classify_sensitivity(request.content)
    scope = request.scope if request.scope in {"session", USER_GLOBAL_MEMORY_SCOPE} else "session"
    session_id = request.session_id or DEFAULT_MEMORY_SESSION_ID
    persona_id = request.persona_id
    status = "pending"
    if scope == USER_GLOBAL_MEMORY_SCOPE:
        session_id = USER_GLOBAL_MEMORY_SESSION_ID
        persona_id = USER_GLOBAL_MEMORY_PERSONA_ID
        status = "approved" if sensitivity == "normal" else "pending"
    store = MemoryStore(get_settings().sqlite_path)
    item = store.propose(
        user_id=user.id,
        session_id=session_id,
        persona_id=persona_id,
        content=request.content.strip(),
        scope=scope,
        memory_type=request.memory_type or classify_memory_type(request.content),
        status=status,
        sensitivity=sensitivity,
        source="manual_panel",
        tags=request.tags,
        actor_user_id=user.id,
    )
    if scope == USER_GLOBAL_MEMORY_SCOPE and request.session_id:
        store.add_origin(
            memory_id=item.id,
            user_id=user.id,
            session_id=request.session_id,
            persona_id=request.persona_id,
        )
    message = (
        "共享用户记忆已保存。"
        if scope == USER_GLOBAL_MEMORY_SCOPE and status == "approved"
        else "记忆已进入待确认队列。"
    )
    return MemoryActionResponse(item=item, message=message)


@router.post("/memory/{memory_id}/approve", response_model=MemoryActionResponse)
def approve_memory(
    memory_id: str,
    session_id: str | None = Query(default=None),
    admin: AuthUser = Depends(require_admin),
) -> MemoryActionResponse:
    return memory_action(
        memory_id,
        status="approved",
        action="approve",
        message="记忆已批准。",
        user=admin,
        session_id=session_id,
    )


@router.post("/memory/{memory_id}/reject", response_model=MemoryActionResponse)
def reject_memory(
    memory_id: str,
    session_id: str | None = Query(default=None),
    admin: AuthUser = Depends(require_admin),
) -> MemoryActionResponse:
    return memory_action(
        memory_id,
        status="rejected",
        action="reject",
        message="记忆已拒绝。",
        user=admin,
        session_id=session_id,
    )


@router.post("/memory/{memory_id}/retract", response_model=MemoryActionResponse)
def retract_memory(
    memory_id: str,
    session_id: str | None = Query(default=None),
    admin: AuthUser = Depends(require_admin),
) -> MemoryActionResponse:
    return memory_action(
        memory_id,
        status="retracted",
        action="retract",
        message="记忆已撤回。",
        user=admin,
        session_id=session_id,
    )


@router.post("/memory/rebuild-index")
def rebuild_memory_index(_admin=Depends(require_admin)) -> dict[str, int]:
    return MemoryStore(get_settings().sqlite_path).rebuild_index()


def memory_action(
    memory_id: str,
    *,
    status: str,
    action: str,
    message: str,
    user: AuthUser,
    session_id: str | None,
) -> MemoryActionResponse:
    try:
        item = MemoryStore(get_settings().sqlite_path).set_status(
            memory_id,
            status,
            action=action,
            user_id=user.id,
            session_id=session_id,
            actor_user_id=user.id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Memory item not found") from exc
    return MemoryActionResponse(item=MemoryItem.model_validate(item), message=message)
