from fastapi import APIRouter, Depends

from app.backend.auth.dependencies import require_admin, require_user
from app.backend.schemas.auth import AuthUser
from app.backend.schemas.retrieval import RetrieveRequest, RetrieveResponse
from app.backend.services.retrieval_service import retrieve


router = APIRouter(tags=["retrieval"], dependencies=[Depends(require_user)])


@router.post("/retrieve", response_model=RetrieveResponse)
def retrieve_endpoint(
    request: RetrieveRequest,
    user: AuthUser = Depends(require_user),
) -> RetrieveResponse:
    return retrieve(request.model_copy(update={"user_id": user.id}))


@router.post("/debug/retrieve", response_model=RetrieveResponse)
def debug_retrieve_endpoint(
    request: RetrieveRequest,
    admin: AuthUser = Depends(require_admin),
) -> RetrieveResponse:
    return retrieve(request.model_copy(update={"user_id": admin.id}))
