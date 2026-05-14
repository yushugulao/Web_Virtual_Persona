from fastapi import APIRouter, Depends

from app.backend.auth.dependencies import require_user
from app.backend.core.config import get_settings
from app.backend.schemas.status import HealthResponse, StatusResponse
from app.backend.services.status_service import build_status


router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/status", response_model=StatusResponse)
def status(_user=Depends(require_user)) -> StatusResponse:
    return build_status(get_settings())
