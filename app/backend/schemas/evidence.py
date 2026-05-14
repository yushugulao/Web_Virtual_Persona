from __future__ import annotations

from pydantic import BaseModel, Field


class EvidenceCardRecord(BaseModel):
    card_id: str
    persona_id: str
    doc_id: str
    chunk_id: str | None = None
    source_title: str
    source_url: str = ""
    source_locator: str = ""
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    quote_anchor: str = ""
    boundary_note: str = ""
    text: str
    trust_level: str = "inferred"
    source_path: str = ""
    batch_id: str = ""


class EvidenceCardListResponse(BaseModel):
    total: int
    items: list[EvidenceCardRecord]


class EvidenceCardStats(BaseModel):
    total_cards: int
    manifest_total_cards: int | None = None
    manifest_matches_store: bool = False
    by_persona: dict[str, int] = Field(default_factory=dict)
    by_trust_level: dict[str, int] = Field(default_factory=dict)
    source_title_count: int = 0
    audited_sync_events: int = 0
