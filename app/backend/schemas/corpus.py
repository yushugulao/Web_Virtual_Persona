from pydantic import BaseModel, Field


class DocumentRecord(BaseModel):
    doc_id: str
    title: str
    source_path: str
    source_type: str
    trust_level: str
    privacy_level: str
    chunk_count: int = 0


class ChunkRecord(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    source_path: str
    section_path: str
    text: str
    source_type: str
    trust_level: str
    privacy_level: str
    token_estimate: int = Field(ge=0)

