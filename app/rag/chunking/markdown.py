from dataclasses import dataclass
import hashlib
import re
from pathlib import Path


HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$")


@dataclass(frozen=True)
class DocumentMeta:
    doc_id: str
    title: str
    source_path: str
    source_type: str
    trust_level: str
    privacy_level: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    source_path: str
    section_path: str
    text: str
    source_type: str
    trust_level: str
    privacy_level: str
    token_estimate: int


def parse_frontmatter(text: str, path: Path) -> tuple[DocumentMeta, str]:
    metadata: dict[str, str] = {}
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            raw_meta = text[4:end].strip()
            body = text[end + 4 :].lstrip()
            for line in raw_meta.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip().strip('"')

    title = metadata.get("title") or path.stem.replace("_", " ").title()
    doc_id = metadata.get("doc_id") or slugify(path.stem)
    return (
        DocumentMeta(
            doc_id=doc_id,
            title=title,
            source_path=str(path.as_posix()),
            source_type=metadata.get("source_type", "profile"),
            trust_level=metadata.get("trust_level", "synthetic"),
            privacy_level=metadata.get("privacy_level", "public"),
        ),
        body,
    )


def chunk_markdown(path: Path, text: str, max_chars: int = 1400) -> tuple[DocumentMeta, list[Chunk]]:
    meta, body = parse_frontmatter(text, path)
    sections: list[tuple[str, list[str]]] = []
    section_stack: list[str] = []
    current_lines: list[str] = []

    def flush() -> None:
        if current_lines:
            section = " / ".join(section_stack) if section_stack else meta.title
            sections.append((section, current_lines.copy()))
            current_lines.clear()

    for line in body.splitlines():
        header = HEADER_RE.match(line)
        if header:
            flush()
            level = len(header.group(1))
            section_stack[:] = section_stack[: level - 1]
            section_stack.append(header.group(2).strip())
        current_lines.append(line)
    flush()

    chunks: list[Chunk] = []
    for section_path, lines in sections:
        text_block = "\n".join(lines).strip()
        if not text_block:
            continue
        for part_index, part in enumerate(split_text(text_block, max_chars=max_chars), 1):
            chunk_id = stable_chunk_id(meta.doc_id, section_path, part_index, part)
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    doc_id=meta.doc_id,
                    title=meta.title,
                    source_path=meta.source_path,
                    section_path=section_path,
                    text=part,
                    source_type=meta.source_type,
                    trust_level=meta.trust_level,
                    privacy_level=meta.privacy_level,
                    token_estimate=estimate_tokens(part),
                )
            )
    return meta, chunks


def split_text(text: str, max_chars: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    parts: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if not current:
            current = paragraph
        elif len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}"
        else:
            parts.append(current)
            current = paragraph
    if current:
        parts.append(current)
    return parts


def stable_chunk_id(doc_id: str, section_path: str, part_index: int, text: str) -> str:
    digest = hashlib.sha1(f"{doc_id}|{section_path}|{part_index}|{text}".encode("utf-8")).hexdigest()
    return f"{doc_id}:{digest[:10]}"


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "document"


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 2)

