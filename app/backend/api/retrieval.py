from fastapi import APIRouter, Depends, HTTPException, status

from app.backend.auth.dependencies import require_admin, require_user
from app.backend.schemas.auth import AuthUser
from app.backend.schemas.retrieval import RetrieveRequest, RetrieveResponse
from app.backend.services.persona_catalog_service import resolve_chat_persona_id
from app.backend.services.public_persona_policy import (
    public_user_persona_is_readonly_for_user,
    sanitize_retrieve_response_for_public_persona,
)
from app.backend.services.retrieval_service import retrieve


router = APIRouter(tags=["retrieval"], dependencies=[Depends(require_user)])


@router.post("/retrieve", response_model=RetrieveResponse)
def retrieve_endpoint(
    request: RetrieveRequest,
    user: AuthUser = Depends(require_user),
) -> RetrieveResponse:
    effective_persona_id = resolve_chat_persona_id(persona_id=request.persona_id, user_id=user.id)
    if effective_persona_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="虚拟分身不存在、尚未准备好，或当前账号无权访问。",
        )
    response = retrieve(
        request.model_copy(
            update={
                "user_id": user.id,
                "persona_id": effective_persona_id,
                "include_private": request.include_private or effective_persona_id.startswith("user_persona_"),
            }
        )
    )
    if public_user_persona_is_readonly_for_user(persona_id=effective_persona_id, user_id=user.id):
        return sanitize_retrieve_response_for_public_persona(response)
    return response


@router.post("/debug/retrieve", response_model=RetrieveResponse)
def debug_retrieve_endpoint(
    request: RetrieveRequest,
    admin: AuthUser = Depends(require_admin),
) -> RetrieveResponse:
    effective_persona_id = resolve_chat_persona_id(persona_id=request.persona_id, user_id=admin.id)
    if effective_persona_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="虚拟分身不存在、尚未准备好，或当前账号无权访问。",
        )
    return retrieve(
        request.model_copy(
            update={
                "user_id": admin.id,
                "persona_id": effective_persona_id,
                "include_private": request.include_private or effective_persona_id.startswith("user_persona_"),
            }
        )
    )
