from fastapi import APIRouter, Depends, Query

from app.backend.auth.dependencies import require_admin
from app.backend.core.config import get_settings
from app.backend.schemas.traces import StoreCounts, TraceListResponse
from app.backend.services.metadata_store import MetadataStore


router = APIRouter(tags=["traces"], dependencies=[Depends(require_admin)])


@router.get("/traces/counts", response_model=StoreCounts)
def trace_counts() -> StoreCounts:
    return StoreCounts(**MetadataStore(get_settings().sqlite_path).counts())


@router.get("/traces/retrievals", response_model=TraceListResponse)
def recent_retrievals(limit: int = Query(default=20, ge=1, le=100)) -> TraceListResponse:
    rows = MetadataStore(get_settings().sqlite_path).recent_retrievals(limit=limit)
    return TraceListResponse(rows=rows)


@router.get("/traces/chats", response_model=TraceListResponse)
def recent_chats(limit: int = Query(default=20, ge=1, le=100)) -> TraceListResponse:
    rows = MetadataStore(get_settings().sqlite_path).recent_chats(limit=limit)
    return TraceListResponse(rows=rows)
