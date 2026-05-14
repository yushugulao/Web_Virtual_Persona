from pydantic import BaseModel


class IngestRequest(BaseModel):
    rebuild: bool = False


class IngestResponse(BaseModel):
    status: str
    document_count: int
    chunk_count: int
    message: str

