from fastapi import APIRouter, Depends

from app.backend.auth.dependencies import require_admin
from app.backend.schemas.ingest import IngestRequest, IngestResponse
from app.backend.services.ingest_service import ingest_corpus


router = APIRouter(tags=["ingest"], dependencies=[Depends(require_admin)])


@router.post("/ingest", response_model=IngestResponse)
def ingest(request: IngestRequest | None = None) -> IngestResponse:
    return ingest_corpus(request or IngestRequest())
