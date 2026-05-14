from app.backend.core.config import get_settings
from app.backend.schemas.ingest import IngestRequest, IngestResponse
from app.backend.services.evidence_card_service import rebuild_evidence_cards_from_corpus
from app.backend.services.metadata_store import MetadataStore
from app.rag.indexes.memory_store import clear_corpus_cache, load_corpus


def ingest_corpus(request: IngestRequest) -> IngestResponse:
    settings = get_settings()
    if request.rebuild:
        clear_corpus_cache()
    documents, chunks = load_corpus(str(settings.corpus_dir))
    store = MetadataStore(settings.sqlite_path)
    store.upsert_corpus(documents, chunks)
    rebuild_evidence_cards_from_corpus(
        corpus_dir=settings.corpus_dir,
        store=store,
        chunks=chunks,
    )
    return IngestResponse(
        status="ready" if documents else "empty",
        document_count=len(documents),
        chunk_count=len(chunks),
        message="档案已载入内存，并同步到 SQLite 元数据存储。",
    )
