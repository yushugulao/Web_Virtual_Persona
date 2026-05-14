from collections import Counter

from app.backend.core.config import get_settings
from app.backend.schemas.corpus import ChunkRecord, DocumentRecord
from app.rag.indexes.memory_store import document_to_dict, load_corpus


def list_documents() -> list[DocumentRecord]:
    settings = get_settings()
    documents, chunks = load_corpus(str(settings.corpus_dir))
    counts = Counter(chunk.doc_id for chunk in chunks)
    return [DocumentRecord(**document_to_dict(doc, counts[doc.doc_id])) for doc in documents]


def list_chunks() -> list[ChunkRecord]:
    settings = get_settings()
    _, chunks = load_corpus(str(settings.corpus_dir))
    return [ChunkRecord(**chunk.__dict__) for chunk in chunks]


def get_chunk(chunk_id: str) -> ChunkRecord | None:
    for chunk in list_chunks():
        if chunk.chunk_id == chunk_id:
            return chunk
    return None

