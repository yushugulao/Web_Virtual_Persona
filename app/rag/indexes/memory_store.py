from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from app.rag.chunking.markdown import Chunk, DocumentMeta, chunk_markdown
from app.rag.ingest.loader import iter_markdown_files, read_markdown


@lru_cache(maxsize=4)
def load_corpus(corpus_dir_str: str) -> tuple[list[DocumentMeta], list[Chunk]]:
    corpus_dir = Path(corpus_dir_str)
    documents: list[DocumentMeta] = []
    chunks: list[Chunk] = []
    for path in iter_markdown_files(corpus_dir):
        meta, doc_chunks = chunk_markdown(path, read_markdown(path))
        documents.append(meta)
        chunks.extend(doc_chunks)
    return documents, chunks


def clear_corpus_cache() -> None:
    load_corpus.cache_clear()


def chunk_to_dict(chunk: Chunk) -> dict:
    return asdict(chunk)


def document_to_dict(document: DocumentMeta, chunk_count: int) -> dict:
    data = asdict(document)
    data["chunk_count"] = chunk_count
    return data

