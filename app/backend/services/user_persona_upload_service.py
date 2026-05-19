from __future__ import annotations

import re
import shutil
import uuid
import json
from pathlib import Path

from fastapi import UploadFile

from app.backend.core.config import get_settings
from app.backend.document_reader import SUPPORTED_EXTENSIONS, read_document
from app.backend.document_reader.reader import sha256_file
from app.backend.services.metadata_store import MetadataStore


MAX_PERSONA_FILES = 20
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024


def metadata_store() -> MetadataStore:
    return MetadataStore(get_settings().sqlite_path)


def create_draft_persona(
    *,
    user_id: str,
    name: str,
    description: str,
    web_search_enabled: bool,
) -> dict:
    store = metadata_store()
    clean_name = re.sub(r"\s+", " ", name).strip()
    if not clean_name:
        raise ValueError("请填写分身名称。")
    clean_description = description.strip()
    tags = _tags_from_description(clean_description)
    return store.create_user_persona(
        owner_user_id=user_id,
        name=clean_name,
        avatar_label=clean_name[:1],
        short_description=_short_description(clean_description),
        description=clean_description,
        identity_tags=tags,
        web_search_enabled=web_search_enabled,
        runtime_status="draft",
        is_public=False,
    )


def ensure_persona_owner(*, persona_id: str, user_id: str) -> dict:
    row = metadata_store().get_user_persona(persona_id)
    if row is None or row["owner_user_id"] != user_id:
        raise PermissionError("分身不存在或不属于当前用户。")
    return row


def list_files(*, user_id: str, persona_id: str) -> list[dict]:
    ensure_persona_owner(persona_id=persona_id, user_id=user_id)
    return metadata_store().list_user_persona_files(owner_user_id=user_id, persona_id=persona_id)


def get_file(*, user_id: str, persona_id: str, file_id: str) -> dict | None:
    ensure_persona_owner(persona_id=persona_id, user_id=user_id)
    return metadata_store().get_user_persona_file(
        owner_user_id=user_id,
        persona_id=persona_id,
        file_id=file_id,
    )


def delete_file(*, user_id: str, persona_id: str, file_id: str) -> bool:
    ensure_persona_owner(persona_id=persona_id, user_id=user_id)
    row = metadata_store().delete_user_persona_file(
        owner_user_id=user_id,
        persona_id=persona_id,
        file_id=file_id,
    )
    if row is None:
        return False
    raw_path = Path(row["raw_path"])
    base_dir = raw_path.parent.parent if raw_path.parent.name == "raw" else raw_path.parent
    shutil.rmtree(base_dir, ignore_errors=True)
    return True


async def save_upload_file(
    *,
    user_id: str,
    persona_id: str,
    upload: UploadFile,
) -> dict:
    ensure_persona_owner(persona_id=persona_id, user_id=user_id)
    filename = sanitize_filename(upload.filename or "uploaded_file")
    extension = extension_from_filename(filename)
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"不支持的文件格式：.{extension}")
    store = metadata_store()
    if store.count_user_persona_files(owner_user_id=user_id, persona_id=persona_id) >= MAX_PERSONA_FILES:
        raise ValueError(f"每个分身最多上传 {MAX_PERSONA_FILES} 个文件。")

    file_id = uuid.uuid4().hex
    base_dir = _upload_base_dir(user_id, persona_id, file_id)
    raw_dir = base_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / filename
    size = await _write_limited_upload(upload, raw_path)
    digest = sha256_file(raw_path)
    row = store.create_user_persona_file(
        file_id=file_id,
        persona_id=persona_id,
        owner_user_id=user_id,
        original_filename=upload.filename or filename,
        stored_filename=filename,
        mime_type=upload.content_type or "",
        extension=extension,
        size_bytes=size,
        sha256=digest,
        raw_path=str(raw_path),
    )
    return row


def parse_uploaded_file(*, file_id: str) -> None:
    store = metadata_store()
    store.set_user_persona_file_parse_status(file_id=file_id, parse_status="parsing")
    row = _get_file_by_id(file_id)
    if row is None:
        return
    raw_path = Path(row["raw_path"])
    output_dir = raw_path.parent.parent / "parsed"
    try:
        result = read_document(
            raw_path,
            output_dir,
            original_filename=row["original_filename"],
            mime_type=row["mime_type"],
            file_id=file_id,
        )
    except Exception as exc:
        store.update_user_persona_file_parse_result(
            file_id=file_id,
            parse_status="failed",
            error_message=str(exc),
        )
        return
    if _get_file_by_id(file_id) is None:
        return
    if result.quality_summary.needs_ocr_backend:
        status = "needs_ocr_backend"
    elif result.quality_score >= 0.5:
        status = "parsed"
    else:
        status = "parsed_low_quality"
    store.update_user_persona_file_parse_result(
        file_id=file_id,
        parse_status=status,
        parser_chain=result.parser_chain,
        quality_score=result.quality_score,
        warnings=result.warnings,
        parsed_markdown_path=result.markdown_path,
        blocks_path=result.blocks_path,
        provenance_path=result.provenance_path,
        diagnostics_path=result.diagnostics_path,
        page_count=result.page_count,
    )


def save_generated_markdown_file(
    *,
    user_id: str,
    persona_id: str,
    filename: str,
    markdown: str,
    parser_chain: list[str],
    quality_score: float = 0.85,
    warnings: list[str] | None = None,
) -> dict:
    ensure_persona_owner(persona_id=persona_id, user_id=user_id)
    clean_filename = sanitize_filename(filename)
    if extension_from_filename(clean_filename) != "md":
        clean_filename = f"{clean_filename}.md"
    store = metadata_store()
    if store.count_user_persona_files(owner_user_id=user_id, persona_id=persona_id) >= MAX_PERSONA_FILES:
        raise ValueError(f"每个分身最多上传 {MAX_PERSONA_FILES} 个文件。")

    file_id = uuid.uuid4().hex
    base_dir = _upload_base_dir(user_id, persona_id, file_id)
    raw_dir = base_dir / "raw"
    parsed_dir = base_dir / "parsed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    parsed_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / clean_filename
    raw_path.write_text(markdown, encoding="utf-8")
    digest = sha256_file(raw_path)
    row = store.create_user_persona_file(
        file_id=file_id,
        persona_id=persona_id,
        owner_user_id=user_id,
        original_filename=clean_filename,
        stored_filename=clean_filename,
        mime_type="text/markdown",
        extension="md",
        size_bytes=raw_path.stat().st_size,
        sha256=digest,
        raw_path=str(raw_path),
        parse_status="parsed",
    )
    markdown_path = parsed_dir / "document.md"
    blocks_path = parsed_dir / "blocks.json"
    provenance_path = parsed_dir / "provenance.json"
    diagnostics_path = parsed_dir / "diagnostics.json"
    markdown_path.write_text(markdown, encoding="utf-8")
    blocks_path.write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "text": markdown[:5000],
                    "source": clean_filename,
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    provenance_path.write_text(
        json.dumps([{"source": clean_filename, "kind": "generated_markdown"}], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    diagnostics_path.write_text(
        json.dumps(
            {
                "pages": [],
                "parser_candidates": [],
                "quality_summary": {"generated_source": True, "filename": clean_filename},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    updated = store.update_user_persona_file_parse_result(
        file_id=file_id,
        parse_status="parsed",
        parser_chain=parser_chain,
        quality_score=quality_score,
        warnings=warnings or [],
        parsed_markdown_path=str(markdown_path),
        blocks_path=str(blocks_path),
        provenance_path=str(provenance_path),
        diagnostics_path=str(diagnostics_path),
        page_count=None,
    )
    return updated or row


def parsed_file_payload(row: dict) -> dict:
    markdown = ""
    blocks: list[dict] = []
    provenance: list[dict] = []
    diagnostics: list[dict] = []
    parser_candidates: list[dict] = []
    quality_summary: dict = {}
    if row.get("parsed_markdown_path"):
        path = Path(row["parsed_markdown_path"])
        if path.exists():
            markdown = path.read_text(encoding="utf-8")
    if row.get("blocks_path"):
        path = Path(row["blocks_path"])
        if path.exists():
            blocks = json.loads(path.read_text(encoding="utf-8"))
    if row.get("provenance_path"):
        path = Path(row["provenance_path"])
        if path.exists():
            provenance = json.loads(path.read_text(encoding="utf-8"))
    if row.get("diagnostics_path"):
        path = Path(row["diagnostics_path"])
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                diagnostics = payload
            elif isinstance(payload, dict):
                diagnostics = payload.get("pages", [])
                parser_candidates = payload.get("parser_candidates", [])
                quality_summary = payload.get("quality_summary", {})
    return {
        "file": row,
        "markdown": markdown,
        "blocks": blocks,
        "provenance": provenance,
        "diagnostics": diagnostics,
        "parser_candidates": parser_candidates,
        "quality_summary": quality_summary,
    }


def _get_file_by_id(file_id: str) -> dict | None:
    store = metadata_store()
    store.initialize()
    with store._connect() as conn:  # noqa: SLF001 - local metadata helper for background parse.
        row = conn.execute("SELECT * FROM user_persona_files WHERE file_id = ?", (file_id,)).fetchone()
    return store._user_persona_file_row(row) if row is not None else None  # noqa: SLF001


async def _write_limited_upload(upload: UploadFile, raw_path: Path) -> int:
    total = 0
    try:
        with raw_path.open("wb") as handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_FILE_SIZE_BYTES:
                    handle.close()
                    raw_path.unlink(missing_ok=True)
                    raise ValueError("单个文件不能超过 50MB。")
                handle.write(chunk)
    except Exception:
        if raw_path.exists():
            raw_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return total


def _upload_base_dir(user_id: str, persona_id: str, file_id: str) -> Path:
    safe_user = _safe_path_part(user_id)
    safe_persona = _safe_path_part(persona_id)
    safe_file = _safe_path_part(file_id)
    return get_settings().data_dir / "user_personas" / safe_user / safe_persona / "uploads" / safe_file


def sanitize_filename(filename: str) -> str:
    name = Path(filename).name.strip().replace("\\", "_").replace("/", "_")
    name = re.sub(r"[\x00-\x1f]", "_", name)
    if not name or name in {".", ".."}:
        name = "uploaded_file"
    return name[:180]


def extension_from_filename(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def _safe_path_part(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", value)[:120] or "unknown"


def _short_description(description: str) -> str:
    clean = re.sub(r"\s+", " ", description).strip()
    return clean[:80]


def _tags_from_description(description: str) -> list[str]:
    parts = re.split(r"[,，、;；\s]+", description.strip())
    tags = [part for part in parts if 1 <= len(part) <= 12]
    return tags[:4]


def remove_upload_tree(*, user_id: str, persona_id: str) -> None:
    base = get_settings().data_dir / "user_personas" / _safe_path_part(user_id) / _safe_path_part(persona_id)
    shutil.rmtree(base, ignore_errors=True)
