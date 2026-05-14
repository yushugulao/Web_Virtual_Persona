from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.backend.core.config import Settings, get_settings
from app.backend.persona_builder.deepseek_client import DeepSeekClient, DeepSeekClientError
from app.backend.persona_builder.web_research import build_web_sources_for_deepseek
from app.backend.schemas.ingest import IngestRequest
from app.backend.services.ingest_service import ingest_corpus
from app.backend.services.metadata_store import MetadataStore
from app.backend.services.user_persona_upload_service import parsed_file_payload
from app.rag.indexes.memory_store import clear_corpus_cache


REQUIRED_CORPUS_FILES = [
    "profile.md",
    "source_notes.md",
    "timeline.md",
    "thinking_style.md",
    "voice_style.md",
    "quote_anchors.md",
    "qa_seed.md",
    "negative_facts.md",
    "style_boundaries.md",
    "source_expansion_overview.md",
    "source_expansion_dialogue_scenes.md",
]


class PersonaBuildError(RuntimeError):
    """A user-facing build failure."""


class PersonaBuildClient(Protocol):
    model: str

    def complete_json(self, *, system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class BuildStart:
    build: dict[str, Any]
    persona: dict[str, Any]


def start_user_persona_build(
    *,
    owner_user_id: str,
    persona_id: str,
    settings: Settings | None = None,
) -> BuildStart:
    settings = settings or get_settings()
    store = MetadataStore(settings.sqlite_path)
    persona = _owner_persona(store, owner_user_id, persona_id)
    source_bundle = _build_source_bundle(store, owner_user_id, persona, settings=settings)
    if not _has_enough_input(source_bundle):
        raise PersonaBuildError("请先填写分身描述，或上传至少一个可解析文件。")
    build_id = f"build_{uuid.uuid4().hex}"
    artifact_dir = settings.data_dir / "user_personas" / owner_user_id / persona_id / "builds" / build_id
    input_hash = hashlib.sha256(
        json.dumps(source_bundle, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    build = store.create_user_persona_build(
        build_id=build_id,
        persona_id=persona_id,
        owner_user_id=owner_user_id,
        input_hash=input_hash,
        model=settings.deepseek_model,
        artifact_dir=str(artifact_dir),
    )
    return BuildStart(build=build, persona=persona)


def run_user_persona_build(
    *,
    owner_user_id: str,
    persona_id: str,
    build_id: str,
    client: PersonaBuildClient | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    store = MetadataStore(settings.sqlite_path)
    persona = _owner_persona(store, owner_user_id, persona_id)
    build = store.get_user_persona_build(
        owner_user_id=owner_user_id,
        persona_id=persona_id,
        build_id=build_id,
    )
    if build is None:
        raise PersonaBuildError("构建任务不存在。")
    artifact_dir = Path(build["artifact_dir"])
    artifact_dir.mkdir(parents=True, exist_ok=True)
    try:
        _phase(store, build_id, "整理资料", 0.12)
        source_bundle = _build_source_bundle(store, owner_user_id, persona, settings=settings)
        _write_json(artifact_dir / "source_bundle.json", source_bundle)

        _phase(store, build_id, "DeepSeek 信息还原与分类", 0.28)
        client = client or DeepSeekClient.from_settings(settings)
        output = client.complete_json(
            system_prompt=_load_skill_prompt(),
            user_payload={
                "source_bundle": source_bundle,
                "builder_contract": {
                    "required_corpus_files": REQUIRED_CORPUS_FILES,
                    "max_evidence_cards": 3200,
                    "private_corpus_prefix": f"corpus/user_personas/{persona_id}/",
                },
            },
        )

        _phase(store, build_id, "校验输出", 0.48)
        normalized = _normalize_builder_output(persona, output)
        _write_json(artifact_dir / "deepseek_output.json", normalized)

        _phase(store, build_id, "生成 reviewed corpus", 0.65)
        corpus_dir = _write_corpus(settings, persona_id, normalized)

        _phase(store, build_id, "生成证据卡与内核", 0.78)
        _write_evidence_cards(corpus_dir, persona_id, normalized["evidence_cards"])
        _write_json(corpus_dir / "persona_kernel.json", normalized["persona_kernel"])
        _write_json(artifact_dir / "repaired_sources.json", normalized["repaired_sources"])
        _write_json(artifact_dir / "fact_graph.json", normalized["fact_graph"])
        _write_json(artifact_dir / "style_profile.json", normalized["style_profile"])
        _write_json(artifact_dir / "persona_kernel.json", normalized["persona_kernel"])
        _write_markdown_report(artifact_dir / "build_quality_report.md", normalized)

        _phase(store, build_id, "同步检索索引", 0.9)
        clear_corpus_cache()
        ingest_corpus(IngestRequest(rebuild=True))

        evidence_count = len(normalized["evidence_cards"])
        source_depth = normalized["source_depth"]
        quality_summary = normalized["quality_summary"]
        store.update_user_persona_after_build(
            owner_user_id=owner_user_id,
            persona_id=persona_id,
            runtime_status="ready",
            short_description=_short_description(persona, normalized),
            identity_tags=_identity_tags(normalized),
            source_depth=source_depth,
            evidence_card_count=evidence_count,
            corpus_path=str(corpus_dir),
            build_error="",
        )
        final_build = store.update_user_persona_build(
            build_id=build_id,
            status="succeeded",
            phase="创建完成",
            progress=1.0,
            source_depth=source_depth,
            evidence_card_count=evidence_count,
            quality_summary=quality_summary,
            finished=True,
        )
        return final_build or {}
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        store.update_user_persona_after_build(
            owner_user_id=owner_user_id,
            persona_id=persona_id,
            runtime_status="error",
            build_error=message,
        )
        failed = store.update_user_persona_build(
            build_id=build_id,
            status="failed",
            phase="构建失败",
            progress=1.0,
            error=message,
            finished=True,
        )
        if isinstance(exc, PersonaBuildError | DeepSeekClientError):
            return failed or {}
        raise


def latest_build_status(*, owner_user_id: str, persona_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    settings = settings or get_settings()
    return MetadataStore(settings.sqlite_path).latest_user_persona_build(
        owner_user_id=owner_user_id,
        persona_id=persona_id,
    )


def build_artifacts_summary(
    *,
    owner_user_id: str,
    persona_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    build = latest_build_status(owner_user_id=owner_user_id, persona_id=persona_id, settings=settings)
    if build is None:
        raise PersonaBuildError("还没有构建记录。")
    artifact_dir = Path(build["artifact_dir"])
    return {
        "build": build,
        "source_bundle": _read_json(artifact_dir / "source_bundle.json"),
        "quality_summary": build.get("quality_summary") or {},
        "generated_files": _relative_files(artifact_dir),
        "report_markdown": _read_text(artifact_dir / "build_quality_report.md")[:12000],
    }


def _owner_persona(store: MetadataStore, owner_user_id: str, persona_id: str) -> dict[str, Any]:
    persona = store.get_user_persona(persona_id)
    if persona is None or persona["owner_user_id"] != owner_user_id:
        raise PersonaBuildError("虚拟分身不存在或不可访问。")
    return persona


def _build_source_bundle(
    store: MetadataStore,
    owner_user_id: str,
    persona: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    files = store.list_user_persona_files(owner_user_id=owner_user_id, persona_id=persona["persona_id"])
    parsed_files: list[dict[str, Any]] = []
    for row in files:
        if row["parse_status"] in {"queued", "parsing"}:
            continue
        if row["parse_status"] == "failed":
            continue
        payload = parsed_file_payload(row)
        markdown = (payload.get("markdown") or "")[:50000]
        blocks = payload.get("blocks") or []
        diagnostics = payload.get("diagnostics") or []
        parsed_files.append(
            {
                "file_id": row["file_id"],
                "filename": row["original_filename"],
                "mime_type": row["mime_type"],
                "extension": row["extension"],
                "parse_status": row["parse_status"],
                "quality_score": row["quality_score"],
                "warnings": row["warnings"],
                "document_md": markdown,
                "blocks": blocks[:200],
                "provenance": (payload.get("provenance") or [])[:200],
                "diagnostics": diagnostics[:50],
            }
        )
    web_sources: list[dict[str, Any]] = []
    web_research: dict[str, Any] = {"web_research_status": "disabled", "included_source_count": 0}
    if persona.get("web_search_enabled"):
        web_sources, web_research = build_web_sources_for_deepseek(
            owner_user_id=owner_user_id,
            persona_id=persona["persona_id"],
            settings=settings,
            auto_run_if_missing=True,
        )
    return {
        "persona": {
            "persona_id": persona["persona_id"],
            "name": persona["name"],
            "description": persona["description"],
            "web_search_enabled": persona["web_search_enabled"],
        },
        "parsed_files": parsed_files,
        "web_sources": web_sources,
        "web_research": web_research,
        "created_at": time.time(),
    }


def _has_enough_input(source_bundle: dict[str, Any]) -> bool:
    description = str(source_bundle.get("persona", {}).get("description") or "").strip()
    parsed_files = source_bundle.get("parsed_files") or []
    web_sources = source_bundle.get("web_sources") or []
    return bool(description or parsed_files or web_sources)


def _load_skill_prompt() -> str:
    base = Path(__file__).parent / "skills" / "deepseek_v4_pro_persona_creation"
    parts = [
        _read_text(base / "SKILL.md"),
        _read_text(base / "references" / "output_contract.md"),
        _read_text(base / "references" / "source_interpretation.md"),
        _read_text(base / "references" / "persona_quality_rubric.md"),
    ]
    return "\n\n".join(parts)


def _normalize_builder_output(persona: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    source_depth = str(output.get("source_depth") or "limited")
    if source_depth not in {"limited", "moderate", "rich"}:
        source_depth = "limited"
    corpus_files = output.get("corpus_files")
    if not isinstance(corpus_files, dict):
        raise PersonaBuildError("DeepSeek 输出缺少 corpus_files。")
    normalized_corpus: dict[str, str] = {}
    for filename in REQUIRED_CORPUS_FILES:
        content = str(corpus_files.get(filename) or "").strip()
        if not content:
            content = _fallback_corpus_file(persona, filename)
        normalized_corpus[filename] = _ensure_frontmatter(
            persona_id=persona["persona_id"],
            filename=filename,
            content=content,
        )
    evidence_cards = output.get("evidence_cards")
    if not isinstance(evidence_cards, list):
        evidence_cards = []
    clean_cards = [_normalize_card(persona["persona_id"], idx, card) for idx, card in enumerate(evidence_cards, 1)]
    clean_cards = [card for card in clean_cards if card["text"] and card["provenance"]]
    clean_cards = clean_cards[:3200]
    if not clean_cards:
        raise PersonaBuildError("DeepSeek 未生成可追溯证据卡。")
    persona_kernel = output.get("persona_kernel")
    if not isinstance(persona_kernel, dict):
        persona_kernel = {}
    persona_kernel = _runtime_kernel(persona, persona_kernel)
    quality_summary = output.get("quality_summary")
    if not isinstance(quality_summary, dict):
        quality_summary = {}
    quality_summary["source_depth"] = source_depth
    quality_summary["evidence_card_count"] = len(clean_cards)
    return {
        "source_depth": source_depth,
        "repaired_sources": output.get("repaired_sources") if isinstance(output.get("repaired_sources"), list) else [],
        "fact_graph": output.get("fact_graph") if isinstance(output.get("fact_graph"), dict) else {},
        "style_profile": output.get("style_profile") if isinstance(output.get("style_profile"), dict) else {},
        "corpus_files": normalized_corpus,
        "evidence_cards": clean_cards,
        "persona_kernel": persona_kernel,
        "quality_summary": quality_summary,
    }


def _write_corpus(settings: Settings, persona_id: str, normalized: dict[str, Any]) -> Path:
    corpus_dir = settings.corpus_dir / "user_personas" / persona_id
    if corpus_dir.exists():
        shutil.rmtree(corpus_dir)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in normalized["corpus_files"].items():
        (corpus_dir / filename).write_text(content.strip() + "\n", encoding="utf-8")
    return corpus_dir


def _write_evidence_cards(corpus_dir: Path, persona_id: str, cards: list[dict[str, Any]]) -> None:
    shard_size = 100
    for shard_index, start in enumerate(range(0, len(cards), shard_size), 1):
        shard_cards = cards[start : start + shard_size]
        lines = [
            "---",
            f'persona_id: "{persona_id}"',
            'source_type: "evidence_cards"',
            'trust_level: "reviewed"',
            'privacy_level: "private"',
            "---",
            "",
            f"# Evidence Cards {shard_index:03d}",
            "",
        ]
        for card in shard_cards:
            lines.extend(
                [
                    f"## {card['card_id']}",
                    "",
                    f"- source_title: {card['source_title']}",
                    f"- source_locator: {card['source_locator']}",
                    f"- tags: {', '.join(card['tags'])}",
                    f"- keywords: {', '.join(card['keywords'])}",
                    f"- quote_anchor: {card['quote_anchor']}",
                    f"- boundary_note: {card['boundary_note']}",
                    f"- provenance: {json.dumps(card['provenance'], ensure_ascii=False)}",
                    "",
                    card["text"],
                    "",
                ]
            )
        (corpus_dir / f"source_expansion_evidence_cards_{shard_index:03d}.md").write_text(
            "\n".join(lines).strip() + "\n",
            encoding="utf-8",
        )


def _ensure_frontmatter(*, persona_id: str, filename: str, content: str) -> str:
    if content.lstrip().startswith("---"):
        return content
    source_type = {
        "profile.md": "reviewed_profile",
        "timeline.md": "timeline",
        "thinking_style.md": "thinking_style",
        "voice_style.md": "voice_style",
        "quote_anchors.md": "quote_anchor",
        "qa_seed.md": "qa_seed",
        "negative_facts.md": "negative_facts",
        "style_boundaries.md": "style_boundary",
    }.get(filename, "evidence_expansion")
    return "\n".join(
        [
            "---",
            f'persona_id: "{persona_id}"',
            f'source_type: "{source_type}"',
            'trust_level: "reviewed"',
            'privacy_level: "private"',
            "---",
            "",
            content,
        ]
    )


def _fallback_corpus_file(persona: dict[str, Any], filename: str) -> str:
    title = {
        "profile.md": "档案",
        "source_notes.md": "来源说明",
        "timeline.md": "时间线",
        "thinking_style.md": "思维方式",
        "voice_style.md": "说话方式",
        "quote_anchors.md": "短锚点",
        "qa_seed.md": "问答种子",
        "negative_facts.md": "不应编造的内容",
        "style_boundaries.md": "风格边界",
        "source_expansion_overview.md": "资料扩展概览",
        "source_expansion_dialogue_scenes.md": "对话场景",
    }.get(filename, "资料")
    return f"# {persona['name']} {title}\n\n资料不足，保留为待补充章节。"


def _normalize_card(persona_id: str, idx: int, card: Any) -> dict[str, Any]:
    source = card if isinstance(card, dict) else {}
    return {
        "card_id": str(source.get("card_id") or f"{persona_id}_card_{idx:06d}"),
        "source_title": _plain(source.get("source_title"), "用户上传资料"),
        "source_locator": _plain(source.get("source_locator"), "unknown"),
        "tags": _string_list(source.get("tags")),
        "keywords": _string_list(source.get("keywords")),
        "quote_anchor": _plain(source.get("quote_anchor"), ""),
        "text": _plain(source.get("text"), ""),
        "boundary_note": _plain(source.get("boundary_note"), ""),
        "provenance": source.get("provenance") if isinstance(source.get("provenance"), list) else [],
    }


def _short_description(persona: dict[str, Any], normalized: dict[str, Any]) -> str:
    summary = normalized.get("quality_summary", {})
    candidate = ""
    if isinstance(summary, dict):
        candidate = str(summary.get("short_description") or "")
    return candidate.strip()[:120] or persona.get("short_description") or persona.get("description", "")[:80]


def _identity_tags(normalized: dict[str, Any]) -> list[str]:
    graph = normalized.get("fact_graph", {})
    tags = graph.get("identity_tags") if isinstance(graph, dict) else None
    if isinstance(tags, list):
        return [str(tag).strip() for tag in tags if str(tag).strip()][:4]
    kernel = normalized.get("persona_kernel", {})
    principles = kernel.get("conversation_principles") if isinstance(kernel, dict) else None
    if isinstance(principles, list):
        return [str(item).strip()[:12] for item in principles if str(item).strip()][:4]
    return []


def _runtime_kernel(persona: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    def first_text(*keys: str, default: str) -> str:
        for key in keys:
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list) and value:
                return "；".join(str(item).strip() for item in value if str(item).strip())[:240]
        return default

    scenes = raw.get("scenes") if isinstance(raw.get("scenes"), dict) else {}
    typical_scenes = raw.get("typical_scenes") if isinstance(raw.get("typical_scenes"), list) else []
    if "chitchat" not in scenes:
        scenes["chitchat"] = typical_scenes[:3] or ["先自然接住用户的话，再给一个短促、具体的回应。"]
    scenes.setdefault("reflective", ["回应观点时先给判断，再用资料里的价值观或经历补充。"])
    scenes.setdefault("factual", ["事实问题先说可确认部分；资料没有支撑时自然承认不确定。"])
    scenes.setdefault("boundary", ["边界问题保持清楚，但不要套用模板化拒答。"])
    return {
        "persona_id": persona["persona_id"],
        "display_name": str(raw.get("display_name") or persona["name"]),
        "rhythm": first_text("rhythm", "speech_rhythm", default="简洁、自然，像真人对话而不是资料总结。"),
        "emotional_posture": first_text("emotional_posture", default="稳、真诚，先回应人，再回应事。"),
        "boundary_posture": first_text("boundary_posture", default="只把资料支持的内容说成事实，不确定时自然说明。"),
        "conversation_principles": _string_list(
            raw.get("conversation_principles")
            or raw.get("principles")
            or ["先接住用户的话", "避免资料卡片腔", "事实必须有来源支撑"]
        ),
        "overused_themes": _string_list(raw.get("overused_themes") or raw.get("overused_theme_bans")),
        "factual_anchors": _string_list(raw.get("factual_anchors")),
        "scenes": {
            str(scene): [str(item) for item in values] if isinstance(values, list) else [str(values)]
            for scene, values in scenes.items()
        },
    }


def _phase(store: MetadataStore, build_id: str, phase: str, progress: float) -> None:
    store.update_user_persona_build(build_id=build_id, status="running", phase=phase, progress=progress)


def _write_markdown_report(path: Path, normalized: dict[str, Any]) -> None:
    summary = normalized["quality_summary"]
    lines = [
        "# 分身构建质量报告",
        "",
        f"- source_depth: {normalized['source_depth']}",
        f"- evidence_card_count: {len(normalized['evidence_cards'])}",
        f"- provenance_coverage: {summary.get('provenance_coverage', 'unknown')}",
        "",
        "## Warnings",
        "",
    ]
    for warning in summary.get("warnings", []) if isinstance(summary, dict) else []:
        lines.append(f"- {warning}")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _relative_files(path: Path) -> list[str]:
    if not path.exists():
        return []
    return sorted(str(file.relative_to(path)).replace("\\", "/") for file in path.rglob("*") if file.is_file())


def _plain(value: Any, default: str) -> str:
    text = str(value if value is not None else default)
    return re.sub(r"\s+", " ", text).strip()


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()][:12]
    text = str(value or "").strip()
    return [text] if text else []
