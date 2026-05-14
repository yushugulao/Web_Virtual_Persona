from pydantic import BaseModel, Field


class PersonaProfile(BaseModel):
    id: str
    name: str
    subtitle: str
    description: str
    avatar_label: str = Field(min_length=1, max_length=4)
    avatar_url: str | None = None
    identity_tags: list[str] = Field(default_factory=list)
    source_note: str
    boundary_note: str
    corpus_paths: list[str]
    retrieval_prefixes: list[str] = Field(default_factory=list)
    raw_source_paths: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    suggested_questions: list[str]


class PersonaMaterialDocument(BaseModel):
    doc_id: str
    title: str
    source_path: str
    source_type: str
    trust_level: str
    privacy_level: str
    chunk_count: int
    sections: list[str]
    preview: str


class PersonaMaterialsResponse(BaseModel):
    persona_id: str
    requested_persona_id: str | None = None
    corpus_paths: list[str]
    retrieval_prefixes: list[str]
    raw_source_paths: list[str]
    source_urls: list[str]
    documents: list[PersonaMaterialDocument]
