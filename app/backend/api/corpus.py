from fastapi import APIRouter, Depends, HTTPException

from app.backend.auth.dependencies import require_admin
from app.backend.schemas.corpus import ChunkRecord, DocumentRecord
from app.backend.services.corpus_service import get_chunk, list_chunks, list_documents


router = APIRouter(tags=["corpus"], dependencies=[Depends(require_admin)])


@router.get("/documents", response_model=list[DocumentRecord])
def documents() -> list[DocumentRecord]:
    return list_documents()


@router.get("/chunks", response_model=list[ChunkRecord])
def chunks() -> list[ChunkRecord]:
    return list_chunks()


@router.get("/chunks/{chunk_id}", response_model=ChunkRecord)
def chunk(chunk_id: str) -> ChunkRecord:
    record = get_chunk(chunk_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到片段：{chunk_id}")
    return record
