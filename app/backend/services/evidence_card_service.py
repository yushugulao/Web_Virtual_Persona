from __future__ import annotations

import json
import re
from pathlib import Path

from app.backend.schemas.evidence import EvidenceCardRecord, EvidenceCardStats
from app.backend.services.metadata_store import MetadataStore
from app.rag.chunking.markdown import Chunk, parse_frontmatter


CARD_HEADER_RE = re.compile(
    r"^##\s+卡片\s+(?P<card_id>[A-Z]{1,3}-\d{3}-\d{3})\s+\|\s+"
    r"(?P<source_title>[^|]+)\|\s+(?P<tags>.+?)\s*$"
)
PERSONA_LINE_RE = re.compile(r"^- Persona:\s+`?([^`\s]+)`?")
BATCH_LINE_RE = re.compile(r"^- Batch:\s+`?([^`\s]+)`?")
CARD_SHARD_GLOB = "personas/*/source_expansion_evidence_cards_*.md"
MANIFEST_PATH = Path("data/persona_sources/evidence_card_manifest.json")


def rebuild_evidence_cards_from_corpus(
    *,
    corpus_dir: Path,
    store: MetadataStore,
    chunks: list[Chunk] | None = None,
) -> EvidenceCardStats:
    cards = parse_evidence_card_files(corpus_dir, chunks=chunks)
    manifest_total = read_manifest_total_cards(corpus_dir.parent)
    store.sync_evidence_cards(cards, manifest_total=manifest_total)
    return evidence_card_stats(store, manifest_total=manifest_total)


def parse_evidence_card_files(
    corpus_dir: Path,
    *,
    chunks: list[Chunk] | None = None,
) -> list[EvidenceCardRecord]:
    chunk_by_doc_and_card = build_chunk_lookup(chunks or [])
    records: list[EvidenceCardRecord] = []
    for path in sorted(corpus_dir.glob(CARD_SHARD_GLOB)):
        records.extend(parse_evidence_card_file(path, corpus_dir, chunk_by_doc_and_card))
    return records


def parse_evidence_card_file(
    path: Path,
    corpus_dir: Path,
    chunk_by_doc_and_card: dict[tuple[str, str], str],
) -> list[EvidenceCardRecord]:
    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text, path)
    persona_id = infer_persona_id(path, body)
    batch_id = infer_batch_id(body)
    cards: list[EvidenceCardRecord] = []
    current_header: re.Match[str] | None = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_header is None:
            return
        card_id = current_header.group("card_id").strip()
        fields = parse_card_fields(current_lines)
        source_title = fields.get("source_title") or current_header.group("source_title").strip()
        tags = fields.get("tags") or split_terms(current_header.group("tags"))
        record = EvidenceCardRecord(
            card_id=card_id,
            persona_id=persona_id,
            doc_id=meta.doc_id,
            chunk_id=chunk_by_doc_and_card.get((meta.doc_id, card_id)),
            source_title=source_title,
            source_url=fields.get("source_url", ""),
            source_locator=fields.get("source_locator", ""),
            tags=tags,
            keywords=fields.get("keywords", []),
            quote_anchor=fields.get("quote_anchor", ""),
            boundary_note=fields.get("boundary_note", ""),
            text="\n".join(line for line in current_lines if line.strip()).strip(),
            trust_level=meta.trust_level,
            source_path=relative_path(path, corpus_dir),
            batch_id=batch_id,
        )
        cards.append(record)

    for line in body.splitlines():
        header = CARD_HEADER_RE.match(line)
        if header:
            flush()
            current_header = header
            current_lines = [line]
            continue
        if current_header is not None:
            current_lines.append(line)
    flush()
    return cards


def parse_card_fields(lines: list[str]) -> dict[str, str | list[str]]:
    fields: dict[str, str | list[str]] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("- ") or "：" not in stripped:
            continue
        label, raw_value = stripped[2:].split("：", 1)
        value = clean_value(raw_value)
        if "中文检索线索" in label:
            fields["tags"] = split_terms(value)
        elif "来源标题" in label:
            fields["source_title"] = value
        elif "来源 URL" in label:
            fields["source_url"] = value
        elif "来源定位" in label:
            fields["source_locator"] = value
        elif "英文关键词" in label:
            fields["keywords"] = split_terms(value)
        elif "quote anchor" in label:
            fields["quote_anchor"] = value.strip('"“”')
        elif "边界提醒" in label:
            fields["boundary_note"] = value
    return fields


def build_chunk_lookup(chunks: list[Chunk]) -> dict[tuple[str, str], str]:
    lookup: dict[tuple[str, str], str] = {}
    for chunk in chunks:
        if "source_expansion_evidence_cards" not in chunk.doc_id:
            continue
        match = re.search(r"\b[A-Z]{1,3}-\d{3}-\d{3}\b", f"{chunk.section_path}\n{chunk.text}")
        if match:
            lookup[(chunk.doc_id, match.group(0))] = chunk.chunk_id
    return lookup


def evidence_card_stats(
    store: MetadataStore,
    *,
    manifest_total: int | None = None,
) -> EvidenceCardStats:
    stats = store.evidence_card_stats()
    total_cards = int(stats["total_cards"])
    manifest_cards = manifest_total if manifest_total is not None else stats.get("manifest_total_cards")
    return EvidenceCardStats(
        total_cards=total_cards,
        manifest_total_cards=manifest_cards,
        manifest_matches_store=bool(manifest_cards is not None and total_cards == int(manifest_cards)),
        by_persona=stats["by_persona"],
        by_trust_level=stats["by_trust_level"],
        source_title_count=int(stats["source_title_count"]),
        audited_sync_events=int(stats["audited_sync_events"]),
    )


def read_manifest_total_cards(project_root: Path) -> int | None:
    path = project_root / MANIFEST_PATH
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    total = data.get("total_cards")
    return int(total) if isinstance(total, int | float) else None


def infer_persona_id(path: Path, body: str) -> str:
    for line in body.splitlines()[:30]:
        match = PERSONA_LINE_RE.match(line.strip())
        if match:
            return match.group(1)
    return path.parent.name


def infer_batch_id(body: str) -> str:
    for line in body.splitlines()[:30]:
        match = BATCH_LINE_RE.match(line.strip())
        if match:
            return match.group(1)
    return ""


def split_terms(value: str) -> list[str]:
    cleaned = value.strip().strip("。.")
    parts = [part.strip(" `\"“”") for part in re.split(r"[、,，;；/]+", cleaned)]
    return [part for part in parts if part]


def clean_value(value: str) -> str:
    return value.strip().strip("。").strip()


def relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
