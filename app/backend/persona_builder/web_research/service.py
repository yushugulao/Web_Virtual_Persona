from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from app.backend.core.config import Settings, get_settings
from app.backend.persona_builder.web_research.adapters import (
    BasicCrawler,
    BasicSearchProvider,
    SearchProvider,
    WebCrawler,
    canonical_url,
    normalize_space,
    source_id_for,
)
from app.backend.services.metadata_store import MetadataStore


class WebResearchError(RuntimeError):
    """A user-facing web-research failure."""


SOURCE_FAMILY_BASE_SCORE = {
    "official": 0.95,
    "authored": 0.62,
    "repo": 0.38,
    "interview": 0.78,
    "encyclopedia": 0.72,
    "news": 0.62,
    "social": 0.36,
    "critique": 0.46,
    "weak_clue": 0.32,
}

SOURCE_FAMILY_TRUST = {
    "official": "official_profile",
    "authored": "authored_artifact",
    "repo": "authored_artifact",
    "interview": "interview",
    "encyclopedia": "reputable_secondary",
    "news": "reputable_secondary",
    "social": "weak_clue",
    "critique": "weak_clue",
    "weak_clue": "weak_clue",
}


def run_web_research(
    *,
    owner_user_id: str,
    persona_id: str,
    settings: Settings | None = None,
    search_provider: SearchProvider | None = None,
    crawler: WebCrawler | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    store = MetadataStore(settings.sqlite_path)
    persona = _owner_persona(store, owner_user_id, persona_id)
    run_id = f"web_{uuid.uuid4().hex}"
    artifact_dir = (
        settings.data_dir
        / "user_personas"
        / owner_user_id
        / persona_id
        / "web_research"
        / run_id
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    run = store.create_user_persona_web_research_run(
        run_id=run_id,
        owner_user_id=owner_user_id,
        persona_id=persona_id,
        provider=settings.web_research_provider,
        artifact_dir=str(artifact_dir),
    )
    try:
        if not settings.web_research_enabled:
            raise WebResearchError("联网资料搜索当前未启用。")
        search_provider = search_provider or BasicSearchProvider(timeout_seconds=20)
        crawler = crawler or BasicCrawler(timeout_seconds=settings.crawl_timeout_seconds)

        store.update_user_persona_web_research_run(
            run_id=run_id,
            status="running",
            phase="生成搜索问题",
            progress=0.12,
        )
        queries = build_research_queries(
            persona=persona,
            parsed_file_summaries=_parsed_file_summaries(store, owner_user_id, persona_id),
            max_queries=settings.web_research_max_queries,
        )
        _write_json(artifact_dir / "queries.json", {"queries": queries})

        store.update_user_persona_web_research_run(
            run_id=run_id,
            phase="搜索候选来源",
            progress=0.28,
            query_count=len(queries),
        )
        candidates = _search_candidates(
            queries,
            provider=search_provider,
            max_sources=settings.web_research_max_sources,
        )
        _write_json(artifact_dir / "candidate_urls.json", {"candidates": candidates})

        store.update_user_persona_web_research_run(
            run_id=run_id,
            phase="抓取网页资料",
            progress=0.48,
            source_count=len(candidates),
        )
        sources = _crawl_and_score_sources(
            candidates,
            persona=persona,
            crawler=crawler,
            artifact_dir=artifact_dir / "sources",
            owner_user_id=owner_user_id,
            persona_id=persona_id,
            run_id=run_id,
            max_included=settings.web_research_max_included_sources,
        )
        stored_sources = store.replace_user_persona_web_sources(run_id=run_id, sources=sources)
        included_count = sum(1 for source in stored_sources if source["status"] == "included")

        store.update_user_persona_web_research_run(
            run_id=run_id,
            phase="生成研究摘要",
            progress=0.76,
            source_count=len(stored_sources),
            included_source_count=included_count,
        )
        artifacts = _write_research_artifacts(
            artifact_dir=artifact_dir,
            persona=persona,
            queries=queries,
            sources=stored_sources,
        )
        quality = {
            "web_research_status": "succeeded",
            "query_count": len(queries),
            "source_count": len(stored_sources),
            "included_source_count": included_count,
            "usable_markdown_rate": (
                included_count / len(stored_sources) if stored_sources else 0
            ),
            "artifacts": artifacts,
        }
        run = store.update_user_persona_web_research_run(
            run_id=run_id,
            status="succeeded",
            phase="联网资料整理完成",
            progress=1.0,
            source_count=len(stored_sources),
            included_source_count=included_count,
            quality_summary=quality,
            finished=True,
        )
        return run or {}
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        run = store.update_user_persona_web_research_run(
            run_id=run_id,
            status="failed",
            phase="联网资料整理失败",
            progress=1.0,
            error=message,
            quality_summary={"web_research_status": "failed", "error": message},
            finished=True,
        )
        if isinstance(exc, WebResearchError):
            return run or {}
        raise


def latest_web_research_payload(
    *,
    owner_user_id: str,
    persona_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    store = MetadataStore(settings.sqlite_path)
    run = store.latest_user_persona_web_research_run(
        owner_user_id=owner_user_id,
        persona_id=persona_id,
    )
    sources: list[dict[str, Any]] = []
    if run is not None:
        sources = store.list_user_persona_web_sources(
            owner_user_id=owner_user_id,
            persona_id=persona_id,
            run_id=run["run_id"],
        )
    return {"run": run, "sources": sources}


def build_web_sources_for_deepseek(
    *,
    owner_user_id: str,
    persona_id: str,
    settings: Settings | None = None,
    auto_run_if_missing: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    settings = settings or get_settings()
    store = MetadataStore(settings.sqlite_path)
    run = store.latest_user_persona_web_research_run(
        owner_user_id=owner_user_id,
        persona_id=persona_id,
        succeeded_only=True,
    )
    if run is None and auto_run_if_missing and settings.web_research_enabled:
        run = run_web_research(owner_user_id=owner_user_id, persona_id=persona_id, settings=settings)
    if run is None or run.get("status") != "succeeded":
        status = "unavailable"
        if run is not None:
            status = run.get("status") or status
        return [], {"web_research_status": status, "included_source_count": 0}
    rows = store.list_user_persona_web_sources(
        owner_user_id=owner_user_id,
        persona_id=persona_id,
        run_id=run["run_id"],
        status="included",
    )
    web_sources = [_deepseek_source(row) for row in rows]
    return web_sources, {
        "web_research_status": "succeeded",
        "run_id": run["run_id"],
        "included_source_count": len(web_sources),
        "quality_summary": run.get("quality_summary") or {},
    }


def build_research_queries(
    *,
    persona: dict[str, Any],
    parsed_file_summaries: list[str],
    max_queries: int,
) -> list[str]:
    name = str(persona.get("name") or "").strip()
    description = str(persona.get("description") or "").strip()
    keywords = _keywords_from_text(" ".join([description, *parsed_file_summaries]))
    base_terms = [name, *keywords[:8]]
    if _contains_cjk(name):
        queries = [
            f'"{name}" 简介',
            f'"{name}" 官方',
            f'"{name}" 创始人',
            f'"{name}" 采访',
            f'"{name}" 演讲',
            f'"{name}" 作品',
        ]
    else:
        queries = [
            f'"{name}" biography',
            f'"{name}" official profile',
            f'"{name}" interview',
            f'"{name}" works',
            f'"{name}" writing speech',
        ]
    for keyword in keywords[:8]:
        if _is_noisy_query_keyword(keyword):
            continue
        queries.append(f"{name} {keyword}")
    if base_terms:
        queries.append(" ".join(base_terms[:5]))
    return _unique_nonempty(queries)[: max(1, max_queries)]


def _search_candidates(
    queries: list[str],
    *,
    provider: SearchProvider,
    max_sources: int,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    per_query_limit = max(3, min(10, max_sources))
    for query in queries:
        for candidate in provider.search(query, limit=per_query_limit):
            canonical = canonical_url(candidate.url)
            if canonical in seen:
                continue
            seen.add(canonical)
            candidates.append(
                {
                    "query": query,
                    "url": candidate.url,
                    "canonical_url": canonical,
                    "title": candidate.title,
                    "snippet": candidate.snippet,
                    "channel": candidate.channel,
                }
            )
            if len(candidates) >= max_sources:
                return candidates
    return candidates


def _crawl_and_score_sources(
    candidates: list[dict[str, Any]],
    *,
    persona: dict[str, Any],
    crawler: WebCrawler,
    artifact_dir: Path,
    owner_user_id: str,
    persona_id: str,
    run_id: str,
    max_included: int,
) -> list[dict[str, Any]]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    crawled: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    seen_source_ids: set[str] = set()
    for candidate in candidates:
        page = crawler.crawl(candidate["url"])
        content_hash = page.content_hash or ""
        duplicate = bool(content_hash and content_hash in seen_hashes)
        if content_hash:
            seen_hashes.add(content_hash)
        family = _source_family(page.final_url or candidate["url"], page.title, page.text)
        score = _source_score(
            family=family,
            persona=persona,
            title=page.title or candidate.get("title") or "",
            text=page.text,
            warning=page.warning,
            duplicate=duplicate,
        )
        status = "candidate"
        if not page.warning and not duplicate and score >= 0.52:
            status = "included"
        source_id = f"{source_id_for(page.final_url or candidate['url'], content_hash)}_{run_id[-12:]}"
        if source_id in seen_source_ids:
            continue
        seen_source_ids.add(source_id)
        source_dir = artifact_dir / source_id
        source_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = source_dir / "document.md"
        metadata = {
            "query": candidate.get("query") or "",
            "snippet": candidate.get("snippet") or "",
            "fetched_at": time.time(),
            "markdown_chars": len(page.markdown),
            "text_chars": len(page.text),
            "duplicate_content": duplicate,
        }
        if page.markdown:
            markdown_path.write_text(page.markdown.strip() + "\n", encoding="utf-8")
        _write_json(
            source_dir / "provenance.json",
            {
                "source_id": source_id,
                "url": page.final_url or candidate["url"],
                "title": page.title or candidate.get("title") or "",
                "content_hash": content_hash,
                "source_family": family,
                "channel": candidate.get("channel") or "",
            },
        )
        crawled.append(
            {
                "source_id": source_id,
                "run_id": run_id,
                "persona_id": persona_id,
                "owner_user_id": owner_user_id,
                "url": page.final_url or candidate["url"],
                "canonical_url": canonical_url(page.final_url or candidate["url"]),
                "title": page.title or candidate.get("title") or candidate["url"],
                "source_family": family,
                "channel": candidate.get("channel") or "",
                "trust_level": SOURCE_FAMILY_TRUST.get(family, "weak_clue"),
                "score": score,
                "status": status,
                "content_hash": content_hash,
                "artifact_path": str(source_dir),
                "locator": "web",
                "warning": page.warning or ("重复内容" if duplicate else ""),
                "metadata": metadata,
                "_markdown": page.markdown,
            }
        )
    crawled.sort(key=lambda item: item["score"], reverse=True)
    included_seen = 0
    for item in crawled:
        if item["status"] != "included":
            continue
        included_seen += 1
        if included_seen > max_included:
            item["status"] = "candidate"
    return [{key: value for key, value in item.items() if key != "_markdown"} for item in crawled]


def _write_research_artifacts(
    *,
    artifact_dir: Path,
    persona: dict[str, Any],
    queries: list[str],
    sources: list[dict[str, Any]],
) -> dict[str, str]:
    included = [source for source in sources if source["status"] == "included"]
    web_sources_payload = [_artifact_source(source) for source in sources]
    manifest = {
        "persona_id": persona["persona_id"],
        "name": persona["name"],
        "created_at": time.time(),
        "queries": queries,
        "source_count": len(sources),
        "included_source_count": len(included),
        "sources": [
            {
                "source_id": source["source_id"],
                "title": source["title"],
                "url": source["url"],
                "status": source["status"],
                "source_family": source["source_family"],
                "trust_level": source["trust_level"],
                "score": source["score"],
                "content_hash": source["content_hash"],
            }
            for source in sources
        ],
    }
    claim_graph = _claim_graph(persona=persona, sources=included)
    brief = _research_brief(persona=persona, sources=included, queries=queries, claim_graph=claim_graph)
    report = _research_report(persona=persona, sources=sources, claim_graph=claim_graph)
    _write_json(artifact_dir / "web_sources.json", {"sources": web_sources_payload})
    _write_json(artifact_dir / "source_manifest.json", manifest)
    _write_json(artifact_dir / "claim_graph.json", claim_graph)
    (artifact_dir / "research_brief.md").write_text(brief, encoding="utf-8")
    (artifact_dir / "web_research_report.md").write_text(report, encoding="utf-8")
    return {
        "web_sources": "web_sources.json",
        "source_manifest": "source_manifest.json",
        "claim_graph": "claim_graph.json",
        "research_brief": "research_brief.md",
        "web_research_report": "web_research_report.md",
    }


def _deepseek_source(row: dict[str, Any]) -> dict[str, Any]:
    artifact_dir = Path(row["artifact_path"])
    markdown = _read_text(artifact_dir / "document.md")[:50000]
    return {
        "web_source_id": row["source_id"],
        "source_id": row["source_id"],
        "title": row["title"],
        "url": row["url"],
        "source_family": row["source_family"],
        "trust_level": row["trust_level"],
        "score": row["score"],
        "content_hash": row["content_hash"],
        "document_md": markdown,
        "provenance": [
            {
                "web_source_id": row["source_id"],
                "url": row["url"],
                "title": row["title"],
                "locator": row["locator"] or "web",
                "content_hash": row["content_hash"],
                "source_family": row["source_family"],
                "trust_level": row["trust_level"],
            }
        ],
    }


def _artifact_source(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": row["source_id"],
        "title": row["title"],
        "url": row["url"],
        "source_family": row["source_family"],
        "trust_level": row["trust_level"],
        "score": row["score"],
        "status": row["status"],
        "content_hash": row["content_hash"],
        "warning": row["warning"],
        "artifact_path": row["artifact_path"],
    }


def _claim_graph(*, persona: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    claims: list[dict[str, Any]] = []
    name = str(persona.get("name") or "")
    for source in sources:
        markdown = _read_text(Path(source["artifact_path"]) / "document.md")
        for index, sentence in enumerate(_sentences(markdown)):
            if len(sentence) < 12:
                continue
            if name and name.lower() not in sentence.lower() and index > 8:
                continue
            claims.append(
                {
                    "claim_id": f"claim_{len(claims) + 1:04d}",
                    "text": sentence[:420],
                    "entities": _entities(name=name, text=sentence),
                    "source_ids": [source["source_id"]],
                    "support": [
                        {
                            "source_id": source["source_id"],
                            "url": source["url"],
                            "title": source["title"],
                            "content_hash": source["content_hash"],
                            "locator": f"sentence:{index + 1}",
                        }
                    ],
                    "confidence": min(0.95, max(0.25, source["score"])),
                }
            )
            if len(claims) >= 80:
                break
        if len(claims) >= 80:
            break
    return {
        "persona_id": persona["persona_id"],
        "entities": [{"name": name, "type": "persona"}] if name else [],
        "claims": claims,
        "conflicts": [],
        "notes": "冲突检测 V1 只保留结构入口；DeepSeek skill 会继续做矛盾标记。",
    }


def _research_brief(
    *,
    persona: dict[str, Any],
    sources: list[dict[str, Any]],
    queries: list[str],
    claim_graph: dict[str, Any],
) -> str:
    lines = [
        f"# {persona['name']} 联网资料研究简报",
        "",
        "## 搜索范围",
        "",
    ]
    lines.extend(f"- {query}" for query in queries)
    lines.extend(["", "## 已纳入来源", ""])
    for source in sources:
        lines.append(
            f"- [{source['title']}]({source['url']}) / {source['source_family']} / "
            f"{source['trust_level']} / score={source['score']:.2f}"
        )
    lines.extend(["", "## 初步关键声明", ""])
    for claim in (claim_graph.get("claims") or [])[:20]:
        lines.append(f"- {claim['text']} ({', '.join(claim.get('source_ids') or [])})")
    return "\n".join(lines).strip() + "\n"


def _research_report(*, persona: dict[str, Any], sources: list[dict[str, Any]], claim_graph: dict[str, Any]) -> str:
    included = [source for source in sources if source["status"] == "included"]
    lines = [
        f"# {persona['name']} Web Research Report",
        "",
        f"- source_count: {len(sources)}",
        f"- included_source_count: {len(included)}",
        f"- claim_count: {len(claim_graph.get('claims') or [])}",
        "",
        "## Sources",
        "",
    ]
    for source in sources:
        lines.append(
            f"- `{source['status']}` {source['score']:.2f} "
            f"[{source['title']}]({source['url']}) ({source['source_family']})"
        )
    return "\n".join(lines).strip() + "\n"


def _owner_persona(store: MetadataStore, owner_user_id: str, persona_id: str) -> dict[str, Any]:
    persona = store.get_user_persona(persona_id)
    if persona is None or persona["owner_user_id"] != owner_user_id:
        raise WebResearchError("虚拟分身不存在或不可访问。")
    return persona


def _parsed_file_summaries(store: MetadataStore, owner_user_id: str, persona_id: str) -> list[str]:
    summaries: list[str] = []
    for row in store.list_user_persona_files(owner_user_id=owner_user_id, persona_id=persona_id):
        if row["parse_status"] != "parsed":
            continue
        path = Path(row["parsed_markdown_path"])
        if not path.exists():
            continue
        summaries.append(_read_text(path)[:1200])
        if len(summaries) >= 4:
            break
    return summaries


def _source_family(url: str, title: str, text: str) -> str:
    host = urlparse_host(url)
    combined = f"{title} {text[:2000]}".lower()
    if _is_official_host(host):
        return "official"
    if any(part in host for part in ["wikipedia.org", "wikidata.org", "baike.baidu.com", "baike.com", "mbalib.com", "baike.sogou.com"]):
        return "encyclopedia"
    if any(part in host for part in ["github.com", "gitlab.com", "gitee.com"]):
        return "repo"
    if _is_low_trust_host(host):
        return "weak_clue"
    if any(part in host for part in ["twitter.com", "x.com", "weibo.com", "zhihu.com", "reddit.com", "bilibili.com"]):
        return "social"
    if any(part in host for part in ["news", "nytimes", "bbc", "thepaper", "36kr", "techcrunch"]):
        return "news"
    if any(term in combined for term in ["interview", "采访", "podcast", "访谈"]):
        return "interview"
    if any(term in combined for term in ["official website", "官方网站", "官网", "about me"]):
        return "official"
    if any(term in combined for term in ["blog", "essay", "文章", "newsletter"]):
        return "authored"
    return "weak_clue"


def _source_score(
    *,
    family: str,
    persona: dict[str, Any],
    title: str,
    text: str,
    warning: str,
    duplicate: bool,
) -> float:
    if warning or duplicate:
        return 0.05 if warning else 0.15
    score = SOURCE_FAMILY_BASE_SCORE.get(family, 0.35)
    name = str(persona.get("name") or "").lower()
    body = f"{title} {text[:5000]}".lower()
    if name and name in body:
        score += 0.08
    elif name:
        score -= 0.28
    if len(text) < 400:
        score -= 0.22
    if _looks_like_seo(body):
        score -= 0.2
    if _looks_like_mojibake(body):
        score -= 0.35
    if family in {"repo", "social", "weak_clue"} and _looks_like_same_name_noise(body):
        score -= 0.22
    return max(0.0, min(1.0, score))


def _looks_like_seo(text: str) -> bool:
    markers = ["coupon", "casino", "betting", "免费下载", "点击下载", "seo", "top 10"]
    return any(marker in text for marker in markers)


def _looks_like_mojibake(text: str) -> bool:
    markers = ["锟", "�", "ï¿½", "%ef%bf%bd"]
    return any(marker in text for marker in markers)


def _looks_like_same_name_noise(text: str) -> bool:
    markers = [
        "生成雷军声音",
        "fish audio",
        "仓库 - 雷军",
        "github",
        "gitee.com",
        "csdn",
        "51cto",
        "点击查看",
    ]
    return any(marker in text for marker in markers)


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def _is_noisy_query_keyword(keyword: str) -> bool:
    lowered = keyword.lower()
    noisy = {"github", "gitee", "csdn", "代码", "开发者", "程序", "项目"}
    return lowered in noisy or keyword in noisy


def _is_official_host(host: str) -> bool:
    official_hosts = {
        "mi.com",
        "www.mi.com",
        "mi.cn",
        "www.mi.cn",
        "xiaomi.com",
        "www.xiaomi.com",
        "ir.mi.com",
    }
    return host in official_hosts or host.endswith(".mi.com") or host.endswith(".xiaomi.com")


def _is_low_trust_host(host: str) -> bool:
    markers = [
        "csdn.net",
        "51cto.com",
        "toutiao.com",
        "sohu.com",
        "douyin.com",
        "jianshu.com",
        "myzaker.com",
        "wenku.baidu.com",
        "blog.",
    ]
    return any(marker in host for marker in markers)


def _keywords_from_text(text: str) -> list[str]:
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_+-]{2,}", text)
    stop = {"the", "and", "with", "for", "this", "that", "from", "about", "virtual", "persona"}
    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        clean = token.strip()
        if clean.lower() in stop or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result[:24]


def _unique_nonempty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = normalize_space(value)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？.!?])\s+|\n+", text)
    return [normalize_space(part) for part in parts if normalize_space(part)]


def _entities(*, name: str, text: str) -> list[str]:
    entities = [name] if name and name in text else []
    entities.extend(re.findall(r"[A-Z][A-Za-z0-9_-]{2,}(?:\s+[A-Z][A-Za-z0-9_-]{2,})?", text)[:4])
    return _unique_nonempty(entities)


def urlparse_host(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).netloc.lower()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")
