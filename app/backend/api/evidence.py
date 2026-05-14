from fastapi import APIRouter, Depends, Query

from app.backend.auth.dependencies import require_admin, require_user
from app.backend.core.config import get_settings
from app.backend.schemas.evidence import EvidenceCardListResponse, EvidenceCardRecord, EvidenceCardStats
from app.backend.services.evidence_card_service import (
    evidence_card_stats,
    read_manifest_total_cards,
    rebuild_evidence_cards_from_corpus,
)
from app.backend.services.metadata_store import MetadataStore
from app.rag.indexes.memory_store import load_corpus


router = APIRouter(tags=["evidence"], dependencies=[Depends(require_user)])


@router.get("/evidence/cards", response_model=EvidenceCardListResponse)
def list_evidence_cards(
    persona_id: str | None = Query(default=None),
    source_title: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> EvidenceCardListResponse:
    store = MetadataStore(get_settings().sqlite_path)
    result = store.list_evidence_cards(
        persona_id=persona_id,
        source_title=source_title,
        tag=tag,
        limit=limit,
        offset=offset,
    )
    return EvidenceCardListResponse(
        total=result["total"],
        items=[EvidenceCardRecord(**item) for item in result["items"]],
    )


@router.get("/evidence/stats", response_model=EvidenceCardStats)
def get_evidence_stats() -> EvidenceCardStats:
    settings = get_settings()
    return evidence_card_stats(
        MetadataStore(settings.sqlite_path),
        manifest_total=read_manifest_total_cards(settings.corpus_dir.parent),
    )


@router.post("/evidence/rebuild", response_model=EvidenceCardStats)
def rebuild_evidence_cards(_admin=Depends(require_admin)) -> EvidenceCardStats:
    settings = get_settings()
    documents, chunks = load_corpus(str(settings.corpus_dir))
    store = MetadataStore(settings.sqlite_path)
    store.upsert_corpus(documents, chunks)
    return rebuild_evidence_cards_from_corpus(
        corpus_dir=settings.corpus_dir,
        store=store,
        chunks=chunks,
    )
