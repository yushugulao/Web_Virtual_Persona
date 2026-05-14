from typing import Literal

from pydantic import BaseModel, Field


PersonaCardKind = Literal["system", "user"]
UserPersonaStatus = Literal["draft", "building", "ready", "error"]
UserPersonaBuildStatus = Literal["queued", "running", "succeeded", "failed"]
UserPersonaWebResearchStatus = Literal["queued", "running", "succeeded", "failed"]
UserPersonaWebSourceStatus = Literal["candidate", "included", "excluded"]


class PersonaCatalogCard(BaseModel):
    id: str
    name: str
    avatar_url: str | None = None
    avatar_label: str = Field(default="分", min_length=1, max_length=4)
    identity_tags: list[str] = Field(default_factory=list)
    short_description: str = ""
    kind: PersonaCardKind
    runtime_status: UserPersonaStatus = "ready"
    score: int = 0
    is_owner: bool = False


class UserPersonaDetail(PersonaCatalogCard):
    owner_user_id: str
    description: str = ""
    is_public: bool = False
    web_search_enabled: bool = False
    source_depth: str = ""
    evidence_card_count: int = 0
    build_error: str = ""
    created_at: float
    updated_at: float
    published_at: float | None = None


class PersonaCatalogSearchResponse(BaseModel):
    query: str = ""
    results: list[PersonaCatalogCard] = Field(default_factory=list)


class PersonaCatalogRecommendedResponse(BaseModel):
    candidates_considered: int = 0
    results: list[PersonaCatalogCard] = Field(default_factory=list)


class UserPersonaListResponse(BaseModel):
    personas: list[UserPersonaDetail] = Field(default_factory=list)


class UserPersonaDraftCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    web_search_enabled: bool = False


class UserPersonaFileItem(BaseModel):
    file_id: str
    persona_id: str
    original_filename: str
    mime_type: str = ""
    extension: str
    size_bytes: int
    sha256: str
    upload_status: str
    parse_status: str
    parser_chain: list[str] = Field(default_factory=list)
    quality_score: float = 0
    warnings: list[str] = Field(default_factory=list)
    error_message: str = ""
    page_count: int | None = None
    diagnostics_path: str = Field(default="", exclude=True)
    created_at: float
    updated_at: float


class UserPersonaFileListResponse(BaseModel):
    files: list[UserPersonaFileItem] = Field(default_factory=list)
    max_files: int
    max_file_size_bytes: int
    supported_extensions: list[str] = Field(default_factory=list)


class UserPersonaParsedFileResponse(BaseModel):
    file: UserPersonaFileItem
    markdown: str = ""
    blocks: list[dict] = Field(default_factory=list)
    provenance: list[dict] = Field(default_factory=list)
    diagnostics: list[dict] = Field(default_factory=list)
    parser_candidates: list[dict] = Field(default_factory=list)
    quality_summary: dict = Field(default_factory=dict)


class UserPersonaBuildStatusResponse(BaseModel):
    build_id: str
    persona_id: str
    status: UserPersonaBuildStatus
    phase: str = "queued"
    progress: float = Field(default=0, ge=0, le=1)
    model: str = ""
    artifact_dir: str = ""
    source_depth: str = ""
    evidence_card_count: int = 0
    error: str = ""
    quality_summary: dict = Field(default_factory=dict)
    created_at: float
    updated_at: float
    finished_at: float | None = None
    persona: UserPersonaDetail | None = None


class UserPersonaBuildArtifactsResponse(BaseModel):
    build: UserPersonaBuildStatusResponse
    source_bundle: dict = Field(default_factory=dict)
    quality_summary: dict = Field(default_factory=dict)
    generated_files: list[str] = Field(default_factory=list)
    report_markdown: str = ""


class UserPersonaWebSourceItem(BaseModel):
    source_id: str
    run_id: str
    persona_id: str
    url: str
    canonical_url: str = ""
    title: str = ""
    source_family: str = ""
    channel: str = ""
    trust_level: str = ""
    score: float = 0
    status: UserPersonaWebSourceStatus = "candidate"
    content_hash: str = ""
    locator: str = ""
    warning: str = ""
    metadata: dict = Field(default_factory=dict)
    created_at: float
    updated_at: float


class UserPersonaWebResearchStatusResponse(BaseModel):
    run_id: str = ""
    persona_id: str
    status: UserPersonaWebResearchStatus | Literal["not_started"] = "not_started"
    phase: str = ""
    progress: float = Field(default=0, ge=0, le=1)
    provider: str = ""
    query_count: int = 0
    source_count: int = 0
    included_source_count: int = 0
    error: str = ""
    quality_summary: dict = Field(default_factory=dict)
    created_at: float | None = None
    updated_at: float | None = None
    finished_at: float | None = None
    sources: list[UserPersonaWebSourceItem] = Field(default_factory=list)
