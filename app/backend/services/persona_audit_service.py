from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from urllib.parse import urlparse

from app.backend.schemas.personas import PersonaProfile
from app.backend.services.persona_service import (
    DEFAULT_PERSONA_ID,
    PERSONA_CONFIG_PATH,
    ensure_persona_registry_is_valid,
    normalize_prefix,
)
from app.rag.chunking.markdown import chunk_markdown


REQUIRED_FRONTMATTER_KEYS = {"doc_id", "title", "source_type", "trust_level", "privacy_level"}
REQUIRED_NAMED_PERSONA_FILES = {
    "profile.md": "profile",
    "thinking_style.md": "thinking_style",
    "qa_seed.md": "qa_seed",
    "negative_facts.md": "negative_fact",
}
ALLOWED_SOURCE_TYPES = {
    "profile",
    "resume",
    "project",
    "timeline",
    "values",
    "thinking_style",
    "colleague",
    "qa_seed",
    "negative_fact",
    "memory",
    "converted_pdf",
    "safety_policy",
}
ALLOWED_TRUST_LEVELS = {"verified", "synthetic", "inferred", "user_memory"}
ALLOWED_PRIVACY_LEVELS = {"public", "private", "sensitive"}


@dataclass
class PersonaAuditReport:
    persona_count: int
    checked_files: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def audit_persona_materials(project_root: Path | None = None) -> PersonaAuditReport:
    root = (project_root or Path(".")).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    checked_markdown: set[Path] = set()

    personas = _load_personas(root, errors)
    if not personas:
        return PersonaAuditReport(
            persona_count=0,
            checked_files=0,
            errors=errors,
            warnings=warnings,
        )

    _audit_registry_paths(root, personas, checked_markdown, errors, warnings)
    _audit_named_persona_contracts(root, personas, checked_markdown, errors, warnings)
    _audit_named_prefix_overlap(personas, errors)
    _audit_markdown_files(root, checked_markdown, errors, warnings)

    return PersonaAuditReport(
        persona_count=len(personas),
        checked_files=len(checked_markdown),
        errors=errors,
        warnings=warnings,
    )


def _load_personas(root: Path, errors: list[str]) -> list[PersonaProfile]:
    config_path = root / PERSONA_CONFIG_PATH
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        personas = [PersonaProfile.model_validate(item) for item in raw]
        ensure_persona_registry_is_valid(personas)
        return personas
    except Exception as exc:  # noqa: BLE001 - audit should report all registry failures.
        errors.append(f"Could not load {PERSONA_CONFIG_PATH}: {exc}")
        return []


def _audit_registry_paths(
    root: Path,
    personas: list[PersonaProfile],
    checked_markdown: set[Path],
    errors: list[str],
    warnings: list[str],
) -> None:
    for persona in personas:
        if not persona.corpus_paths:
            errors.append(f"Persona {persona.id} must define corpus_paths.")
        for pattern in persona.corpus_paths:
            matches = _glob_relative(root, pattern, errors, f"{persona.id} corpus path")
            markdown_matches = [
                path
                for path in matches
                if path.suffix.lower() == ".md" and not _is_private_user_persona_corpus(path, root)
            ]
            if not markdown_matches:
                errors.append(f"Persona {persona.id} corpus path matched no Markdown: {pattern}")
            checked_markdown.update(markdown_matches)

        for prefix in _effective_retrieval_prefixes(persona):
            prefix_path = _resolve_relative(root, prefix.rstrip("/"), errors, f"{persona.id} prefix")
            if prefix_path is None:
                continue
            if not prefix_path.exists():
                errors.append(f"Persona {persona.id} retrieval prefix is missing: {prefix}")
                continue
            if not prefix_path.is_dir():
                errors.append(f"Persona {persona.id} retrieval prefix is not a directory: {prefix}")
                continue
            prefix_markdown = [
                path
                for path in sorted(prefix_path.rglob("*.md"))
                if not _is_private_user_persona_corpus(path, root)
            ]
            if not prefix_markdown:
                errors.append(f"Persona {persona.id} retrieval prefix has no Markdown: {prefix}")
            checked_markdown.update(prefix_markdown)

        if persona.id == DEFAULT_PERSONA_ID:
            continue

        if not persona.raw_source_paths:
            errors.append(f"Persona {persona.id} must define at least one raw source path.")
        for raw_path in persona.raw_source_paths:
            source_path = _resolve_relative(root, raw_path, errors, f"{persona.id} raw source")
            if source_path is None:
                continue
            if not source_path.exists():
                errors.append(f"Persona {persona.id} raw source is missing: {raw_path}")
            elif source_path.stat().st_size == 0:
                errors.append(f"Persona {persona.id} raw source is empty: {raw_path}")

        if not persona.source_urls:
            errors.append(f"Persona {persona.id} must define at least one source URL.")
        for url in persona.source_urls:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors.append(f"Persona {persona.id} has an invalid source URL: {url}")

        if len(persona.suggested_questions) < 2:
            warnings.append(f"Persona {persona.id} has fewer than two suggested questions.")


def _audit_named_persona_contracts(
    root: Path,
    personas: list[PersonaProfile],
    checked_markdown: set[Path],
    errors: list[str],
    warnings: list[str],
) -> None:
    for persona in personas:
        if persona.id == DEFAULT_PERSONA_ID:
            continue
        expected_dir = root / "corpus" / "personas" / persona.id
        if not expected_dir.exists():
            errors.append(f"Named persona {persona.id} is missing reviewed corpus dir: {expected_dir}")
            continue
        if not any(
            normalize_prefix(prefix) == normalize_prefix(f"corpus/personas/{persona.id}/")
            for prefix in persona.retrieval_prefixes
        ):
            warnings.append(
                f"Named persona {persona.id} does not use the standard corpus/personas/{persona.id}/ prefix."
            )

        for filename, expected_source_type in REQUIRED_NAMED_PERSONA_FILES.items():
            path = expected_dir / filename
            checked_markdown.add(path)
            if not path.exists():
                errors.append(f"Named persona {persona.id} is missing required file: {path}")
                continue
            try:
                meta, chunks = chunk_markdown(_relative_path(path, root), path.read_text("utf-8"))
            except Exception as exc:  # noqa: BLE001 - audit should continue after file failures.
                errors.append(f"Could not parse required persona file {path}: {exc}")
                continue
            if meta.source_type != expected_source_type:
                errors.append(
                    f"{path} has source_type={meta.source_type}; expected {expected_source_type}."
                )
            if not chunks:
                errors.append(f"{path} produced no retrievable chunks.")

        if not (expected_dir / "negative_facts.md").exists():
            warnings.append(f"Named persona {persona.id} has no explicit negative facts file.")


def _audit_named_prefix_overlap(personas: list[PersonaProfile], errors: list[str]) -> None:
    named_prefixes: list[tuple[str, str]] = []
    for persona in personas:
        if persona.id == DEFAULT_PERSONA_ID:
            continue
        for prefix in _effective_retrieval_prefixes(persona):
            named_prefixes.append((persona.id, normalize_prefix(prefix)))

    for index, (left_id, left_prefix) in enumerate(named_prefixes):
        for right_id, right_prefix in named_prefixes[index + 1 :]:
            if left_id == right_id:
                continue
            if left_prefix.startswith(right_prefix) or right_prefix.startswith(left_prefix):
                errors.append(
                    "Named persona retrieval prefixes overlap: "
                    f"{left_id}={left_prefix}, {right_id}={right_prefix}"
                )


def _audit_markdown_files(
    root: Path,
    files: set[Path],
    errors: list[str],
    warnings: list[str],
) -> None:
    doc_ids: dict[str, Path] = {}
    for path in sorted(files):
        if not path.exists():
            errors.append(f"Referenced Markdown file is missing: {path}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
            frontmatter_keys = _frontmatter_keys(text)
            missing_keys = REQUIRED_FRONTMATTER_KEYS - frontmatter_keys
            if missing_keys:
                errors.append(
                    f"{_relative_path(path, root)} is missing frontmatter keys: "
                    f"{sorted(missing_keys)}"
                )

            meta, chunks = chunk_markdown(_relative_path(path, root), text)
        except UnicodeDecodeError as exc:
            errors.append(f"{_relative_path(path, root)} is not valid UTF-8: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - audit should report all corpus issues.
            errors.append(f"Could not parse {_relative_path(path, root)}: {exc}")
            continue

        if meta.doc_id in doc_ids:
            errors.append(
                f"Duplicate doc_id {meta.doc_id}: {_relative_path(path, root)} and "
                f"{_relative_path(doc_ids[meta.doc_id], root)}"
            )
        doc_ids[meta.doc_id] = path

        if meta.source_type not in ALLOWED_SOURCE_TYPES:
            errors.append(f"{_relative_path(path, root)} has unsupported source_type {meta.source_type}.")
        if meta.trust_level not in ALLOWED_TRUST_LEVELS:
            errors.append(f"{_relative_path(path, root)} has unsupported trust_level {meta.trust_level}.")
        if meta.privacy_level not in ALLOWED_PRIVACY_LEVELS:
            errors.append(
                f"{_relative_path(path, root)} has unsupported privacy_level {meta.privacy_level}."
            )
        if not chunks:
            errors.append(f"{_relative_path(path, root)} produced no retrievable chunks.")

        persona_id = _named_persona_id_for_path(path, root)
        if persona_id and not meta.doc_id.startswith(f"{persona_id}_"):
            warnings.append(
                f"{_relative_path(path, root)} doc_id should usually start with {persona_id}_"
            )


def _effective_retrieval_prefixes(persona: PersonaProfile) -> list[str]:
    if persona.retrieval_prefixes:
        return [normalize_prefix(prefix) for prefix in persona.retrieval_prefixes]
    if persona.id == DEFAULT_PERSONA_ID:
        return ["corpus/"]
    return [f"corpus/personas/{persona.id}/"]


def _glob_relative(
    root: Path,
    pattern: str,
    errors: list[str],
    context: str,
) -> list[Path]:
    normalized = pattern.replace("\\", "/")
    if Path(normalized).is_absolute() or ".." in Path(normalized).parts:
        errors.append(f"{context} must stay inside the project root: {pattern}")
        return []
    return sorted(path.resolve() for path in root.glob(normalized))


def _resolve_relative(
    root: Path,
    relative_path: str,
    errors: list[str],
    context: str,
) -> Path | None:
    candidate = Path(relative_path.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts:
        errors.append(f"{context} must stay inside the project root: {relative_path}")
        return None
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        errors.append(f"{context} escapes the project root: {relative_path}")
        return None
    return resolved


def _relative_path(path: Path, root: Path) -> Path:
    try:
        return path.resolve().relative_to(root)
    except ValueError:
        return path


def _is_private_user_persona_corpus(path: Path, root: Path) -> bool:
    try:
        parts = path.resolve().relative_to(root).parts
    except ValueError:
        return False
    return len(parts) >= 2 and parts[0] == "corpus" and parts[1] == "user_personas"


def _frontmatter_keys(text: str) -> set[str]:
    if not text.startswith("---\n"):
        return set()
    end = text.find("\n---", 4)
    if end == -1:
        return set()
    keys: set[str] = set()
    for line in text[4:end].strip().splitlines():
        if ":" not in line:
            continue
        key, _value = line.split(":", 1)
        keys.add(key.strip())
    return keys


def _named_persona_id_for_path(path: Path, root: Path) -> str | None:
    try:
        parts = path.resolve().relative_to(root).parts
    except ValueError:
        return None
    if len(parts) >= 3 and parts[0] == "corpus" and parts[1] == "personas":
        return parts[2]
    return None
