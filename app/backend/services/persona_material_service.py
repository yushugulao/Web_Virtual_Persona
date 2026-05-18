from __future__ import annotations

from pathlib import Path
import re

from app.backend.schemas.personas import PersonaMaterialDocument, PersonaMaterialsResponse
from app.backend.core.config import get_settings
from app.backend.services.metadata_store import MetadataStore
from app.backend.services.persona_service import (
    is_known_persona_id,
    normalize_persona_id,
    persona_retrieval_prefixes,
    get_persona,
)
from app.rag.chunking.markdown import chunk_markdown


MAX_PREVIEW_CHARS = 320
MAX_SECTIONS = 6


def get_persona_materials(
    persona_id: str | None,
    project_root: Path | None = None,
    *,
    user_id: str | None = None,
    store: MetadataStore | None = None,
) -> PersonaMaterialsResponse:
    root = (project_root or Path(".")).resolve()
    access = _user_persona_material_access(persona_id, user_id=user_id, store=store)
    if access == "not_found":
        raise FileNotFoundError("虚拟分身不存在或不可访问。")
    if access == "restricted_public":
        effective_persona_id = str(persona_id or "")
        return PersonaMaterialsResponse(
            persona_id=effective_persona_id,
            requested_persona_id=None,
            corpus_paths=[],
            retrieval_prefixes=[],
            raw_source_paths=[],
            source_urls=[],
            documents=[],
        )

    effective_persona_id = normalize_persona_id(persona_id)
    requested_persona_id = persona_id if persona_id and not is_known_persona_id(persona_id) else None
    persona = get_persona(effective_persona_id)
    documents: list[PersonaMaterialDocument] = []
    seen_paths: set[Path] = set()

    for pattern in persona.corpus_paths:
        for path in _glob_relative(root, pattern):
            if path in seen_paths or path.suffix.lower() != ".md":
                continue
            seen_paths.add(path)
            material = _material_from_path(path, root)
            if material is not None:
                documents.append(material)

    documents.sort(key=lambda item: (_source_type_order(item.source_type), item.source_path))
    return PersonaMaterialsResponse(
        persona_id=effective_persona_id,
        requested_persona_id=requested_persona_id,
        corpus_paths=persona.corpus_paths,
        retrieval_prefixes=persona_retrieval_prefixes(effective_persona_id),
        raw_source_paths=persona.raw_source_paths,
        source_urls=persona.source_urls,
        documents=documents,
    )


def _user_persona_material_access(
    persona_id: str | None,
    *,
    user_id: str | None,
    store: MetadataStore | None,
) -> str:
    candidate = (persona_id or "").strip()
    if not candidate.startswith("user_persona_"):
        return "owner_or_system"
    active_store = store or MetadataStore(get_settings().sqlite_path)
    row = active_store.get_user_persona(candidate)
    if row is None or row["runtime_status"] != "ready":
        return "not_found"
    if user_id and row["owner_user_id"] == user_id:
        return "owner_or_system"
    if row["is_public"]:
        return "restricted_public"
    return "not_found"


def _material_from_path(path: Path, root: Path) -> PersonaMaterialDocument | None:
    try:
        relative_path = path.resolve().relative_to(root)
        text = path.read_text(encoding="utf-8")
        meta, chunks = chunk_markdown(relative_path, text)
    except (OSError, UnicodeDecodeError):
        return None

    sections: list[str] = []
    for chunk in chunks:
        if chunk.section_path not in sections:
            sections.append(chunk.section_path)
        if len(sections) >= MAX_SECTIONS:
            break

    preview = _preview_from_chunks([chunk.text for chunk in chunks])
    return PersonaMaterialDocument(
        doc_id=meta.doc_id,
        title=meta.title,
        source_path=meta.source_path,
        source_type=meta.source_type,
        trust_level=meta.trust_level,
        privacy_level=meta.privacy_level,
        chunk_count=len(chunks),
        sections=sections,
        preview=preview,
    )


def _glob_relative(root: Path, pattern: str) -> list[Path]:
    normalized = pattern.replace("\\", "/")
    candidate = Path(normalized)
    if candidate.is_absolute() or ".." in candidate.parts:
        return []
    return sorted(path.resolve() for path in root.glob(normalized))


def _preview_from_chunks(texts: list[str]) -> str:
    joined = "\n\n".join(text for text in texts if text.strip())
    cleaned = re.sub(r"^#+\s*", "", joined, flags=re.MULTILINE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= MAX_PREVIEW_CHARS:
        return cleaned
    return f"{cleaned[:MAX_PREVIEW_CHARS].rstrip()}..."


def _source_type_order(source_type: str) -> int:
    order = {
        "profile": 0,
        "resume": 1,
        "timeline": 2,
        "thinking_style": 3,
        "values": 4,
        "qa_seed": 5,
        "negative_fact": 6,
        "project": 7,
        "colleague": 8,
        "safety_policy": 9,
    }
    return order.get(source_type, 50)
