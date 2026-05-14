from fastapi import APIRouter, Depends, Query

from app.backend.auth.dependencies import require_admin, require_user
from app.backend.core.config import get_settings
from app.backend.schemas.auth import AuthUser
from app.backend.schemas.browser_acceptance import BrowserAcceptanceMatrixResponse
from app.backend.schemas.feedback import (
    PersonaTurnFeedbackListResponse,
    PersonaTurnFeedbackRequest,
    PersonaTurnFeedbackResponse,
    PersonaTurnFeedbackStatsResponse,
)
from app.backend.services.browser_acceptance_service import load_browser_acceptance_matrix
from app.backend.services.feedback_service import (
    list_persona_turn_feedback,
    summarize_persona_turn_feedback,
    write_persona_turn_feedback,
)
from app.backend.services.metadata_store import MetadataStore


router = APIRouter(tags=["feedback"], dependencies=[Depends(require_user)])


@router.post("/feedback/persona-turn", response_model=PersonaTurnFeedbackResponse)
def create_persona_turn_feedback(
    request: PersonaTurnFeedbackRequest,
    user: AuthUser = Depends(require_user),
) -> PersonaTurnFeedbackResponse:
    settings = get_settings()
    record = write_persona_turn_feedback(request, data_dir=settings.data_dir)
    sqlite_path = getattr(settings, "sqlite_path", None)
    if sqlite_path is not None:
        MetadataStore(sqlite_path).record_persona_score_event(
            user_id=user.id,
            request_id=request.request_id,
            persona_id=request.persona_id,
            issue=request.issue,
        )
    return PersonaTurnFeedbackResponse(
        feedback_id=record.feedback_id,
        message="反馈已保存到本地验收样本。",
        record=record,
    )


@router.get("/feedback/persona-turns", response_model=PersonaTurnFeedbackListResponse)
def recent_persona_turn_feedback(
    _admin=Depends(require_admin),
    limit: int = Query(default=50, ge=1, le=200),
    persona_id: str | None = Query(default=None),
    issue: str | None = Query(default=None),
) -> PersonaTurnFeedbackListResponse:
    records = list_persona_turn_feedback(
        data_dir=get_settings().data_dir,
        limit=limit,
        persona_id=persona_id,
        issue=issue,
    )
    return PersonaTurnFeedbackListResponse(records=records)


@router.get("/feedback/stats", response_model=PersonaTurnFeedbackStatsResponse)
def persona_turn_feedback_stats(
    _admin=Depends(require_admin),
    recent_limit: int = Query(default=5, ge=0, le=50),
) -> PersonaTurnFeedbackStatsResponse:
    return summarize_persona_turn_feedback(
        data_dir=get_settings().data_dir,
        recent_limit=recent_limit,
    )


@router.get("/feedback/browser-acceptance-matrix", response_model=BrowserAcceptanceMatrixResponse)
def browser_acceptance_matrix(
    _admin=Depends(require_admin),
    persona_id: str | None = Query(default=None),
    category_id: str | None = Query(default=None),
) -> BrowserAcceptanceMatrixResponse:
    return load_browser_acceptance_matrix(
        data_dir=get_settings().data_dir,
        persona_id=persona_id,
        category_id=category_id,
    )
