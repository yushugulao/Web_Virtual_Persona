from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


DOCUMENT_EXTENSIONS = {
    "pdf",
    "docx",
    "doc",
    "pptx",
    "ppt",
    "xlsx",
    "xls",
    "csv",
    "tsv",
    "txt",
    "md",
    "html",
    "htm",
    "rtf",
}

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "tif", "tiff", "bmp"}

CODE_EXTENSIONS = {
    "py",
    "js",
    "ts",
    "tsx",
    "jsx",
    "java",
    "cpp",
    "c",
    "h",
    "cs",
    "go",
    "rs",
    "php",
    "rb",
    "swift",
    "kt",
    "sql",
    "json",
    "jsonl",
    "yaml",
    "yml",
    "xml",
    "ini",
    "toml",
    "log",
}

SUPPORTED_EXTENSIONS = DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS | CODE_EXTENSIONS

BlockType = Literal[
    "title",
    "heading",
    "paragraph",
    "table",
    "image",
    "code",
    "formula",
    "warning",
]


class DocumentRegion(BaseModel):
    page: int | None = None
    bbox: list[float] | None = None


class DocumentBlock(BaseModel):
    block_id: str
    block_type: BlockType
    text: str = ""
    page: int | None = None
    region: DocumentRegion | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProvenanceEntry(BaseModel):
    block_id: str
    file_id: str | None = None
    filename: str
    parser: str
    page: int | None = None
    region: DocumentRegion | None = None
    confidence: float | None = None
    note: str = ""


ParserCandidateStatus = Literal["selected", "candidate", "disabled", "failed", "fallback"]


class ParserCandidate(BaseModel):
    parser: str
    status: ParserCandidateStatus
    page: int | None = None
    block_count: int = 0
    text_chars: int = 0
    quality_score: float = 0
    confidence: float | None = None
    warnings: list[str] = Field(default_factory=list)
    reason: str = ""
    features: list[str] = Field(default_factory=list)


class DocumentPageDiagnostic(BaseModel):
    page: int
    route: str
    selected_parser: str
    quality_score: float = 0
    needs_ocr: bool = False
    requires_review: bool = False
    warnings: list[str] = Field(default_factory=list)
    candidates: list[ParserCandidate] = Field(default_factory=list)
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentQualitySummary(BaseModel):
    overall_score: float = 0
    low_quality_pages: int = 0
    ocr_pages: int = 0
    table_blocks: int = 0
    image_blocks: int = 0
    formula_blocks: int = 0
    warning_blocks: int = 0
    mojibake_warnings: int = 0
    needs_review: bool = False
    needs_ocr_backend: bool = False


class DocumentReadResult(BaseModel):
    sha256: str
    mime_type: str
    extension: str
    page_count: int | None = None
    parser_chain: list[str] = Field(default_factory=list)
    quality_score: float = 0
    warnings: list[str] = Field(default_factory=list)
    markdown_path: str
    blocks_path: str
    provenance_path: str
    diagnostics_path: str = ""
    blocks: list[DocumentBlock] = Field(default_factory=list)
    provenance: list[ProvenanceEntry] = Field(default_factory=list)
    diagnostics: list[DocumentPageDiagnostic] = Field(default_factory=list)
    parser_candidates: list[ParserCandidate] = Field(default_factory=list)
    quality_summary: DocumentQualitySummary = Field(default_factory=DocumentQualitySummary)
