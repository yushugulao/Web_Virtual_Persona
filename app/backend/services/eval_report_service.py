from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.backend.schemas.evals import EvalCaseResult, EvalRunResponse


FACT_LIKE_CATEGORIES = {
    "claim_faithfulness",
    "evidence_faithfulness",
    "era_consistency",
    "persona_consistency",
    "retrieval_context_quality",
    "biography_fact",
}
BIOGRAPHY_FACT_MARKERS = (
    "做过",
    "经历",
    "年轻",
    "公共事务",
    "发明",
    "写作",
    "观察",
    "beagle",
    "invent",
    "work",
    "young",
    "specific",
    "life",
)


@dataclass(frozen=True)
class EvalReportPaths:
    markdown_path: Path
    json_path: Path


def write_eval_report(
    response: EvalRunResponse,
    *,
    output_dir: Path,
    questions_path: Path | None = None,
    top_k: int | None = None,
    backend_url: str | None = None,
    config: dict[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> EvalReportPaths:
    generated_at = generated_at or datetime.now()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_id = build_report_id(response, generated_at)
    report = build_eval_report(
        response=response,
        report_id=report_id,
        generated_at=generated_at,
        questions_path=questions_path,
        top_k=top_k,
        backend_url=backend_url,
        config=config or {},
    )
    json_path = output_dir / f"{report_id}.json"
    markdown_path = output_dir / f"{report_id}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return EvalReportPaths(markdown_path=markdown_path, json_path=json_path)


def build_report_id(response: EvalRunResponse, generated_at: datetime) -> str:
    if response.mode == "judge":
        prefix = "persona_judge"
    else:
        prefix = "chat_eval" if response.mode == "chat" else "retrieval_eval"
    stamp = generated_at.strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}_{response.run_id[:8]}"


def build_eval_report(
    *,
    response: EvalRunResponse,
    report_id: str,
    generated_at: datetime,
    questions_path: Path | None,
    top_k: int | None,
    backend_url: str | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "report_id": report_id,
        "run_id": response.run_id,
        "status": response.status,
        "mode": response.mode,
        "message": response.message,
        "question_count": response.question_count,
        "passed_count": response.passed_count,
        "failed_count": response.failed_count,
        "metrics": response.metrics.model_dump(mode="json"),
        "questions_path": str(questions_path) if questions_path else None,
        "top_k": top_k,
        "backend_url": backend_url,
        "config": config,
        "failure_cases": summarize_failures(response.results),
        "weakest_cases": summarize_weakest_cases(response.results, limit=12),
        "source_coverage": summarize_source_coverage(response.results),
        "claim_support": summarize_claim_support(response.results),
        "cases": summarize_cases(response.results),
    }


def summarize_failures(results: list[EvalCaseResult]) -> list[dict[str, Any]]:
    return [
        summarize_case(result)
        for result in results
        if not result.metrics.passed
    ]


def summarize_weakest_cases(results: list[EvalCaseResult], *, limit: int) -> list[dict[str, Any]]:
    ranked = sorted(results, key=case_risk_score, reverse=True)
    return [summarize_case(result) for result in ranked[:limit]]


def case_risk_score(result: EvalCaseResult) -> float:
    metrics = result.metrics
    risk = 0.0
    if not metrics.passed:
        risk += 10.0
    risk += max(0.0, 1.0 - metrics.source_recall) * 2.0
    risk += max(0.0, 1.0 - metrics.citation_precision) * 1.5
    risk += max(0.0, 1.0 - metrics.evidence_overlap)
    risk += max(0.0, 1.0 - metrics.claim_support_rate)
    risk += min(metrics.unsupported_claim_count, 3) * 0.5
    risk += metrics.latency_ms / 100000.0
    return risk


def summarize_source_coverage(results: list[EvalCaseResult]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for result in results:
        counter.update(citation.doc_id for citation in result.citations)
    return [
        {"doc_id": doc_id, "count": count}
        for doc_id, count in counter.most_common()
    ]


def summarize_cases(results: list[EvalCaseResult]) -> list[dict[str, Any]]:
    return [summarize_case(result) for result in results]


def summarize_case(result: EvalCaseResult) -> dict[str, Any]:
    metrics = result.metrics
    return {
        "case_id": result.case.id,
        "category": result.case.category,
        "persona_id": result.case.persona_id,
        "expected_persona_id": result.case.expected_persona_id,
        "question": result.case.question,
        "passed": metrics.passed,
        "failures": metrics.failures,
        "expected_sources": result.case.expected_sources,
        "expected_source_prefixes": result.case.expected_source_prefixes,
        "forbidden_sources": result.case.forbidden_sources,
        "forbidden_source_prefixes": result.case.forbidden_source_prefixes,
        "retrieved_doc_ids": result.retrieved_doc_ids,
        "selected_chunk_ids": result.selected_chunk_ids,
        "citation_titles": [citation.title for citation in result.citations],
        "answer_excerpt": excerpt(result.answer),
        "claim_support": summarize_case_claim_support(result),
        "metrics": {
            "source_recall": metrics.source_recall,
            "citation_precision": metrics.citation_precision,
            "top1_source_hit": metrics.top1_source_hit,
            "reciprocal_rank": metrics.reciprocal_rank,
            "ndcg": metrics.ndcg,
            "keyword_coverage": metrics.keyword_coverage,
            "evidence_overlap": metrics.evidence_overlap,
            "claim_support_rate": metrics.claim_support_rate,
            "unsupported_claim_count": metrics.unsupported_claim_count,
            "abstention_correct": metrics.abstention_correct,
            "language_match": metrics.language_match,
            "forbidden_keyword_hits": metrics.forbidden_keyword_hits,
            "judge_score": metrics.judge_score,
            "judge_passed": metrics.judge_passed,
            "judge_scores": metrics.judge_scores,
            "judge_failures": metrics.judge_failures,
            "weakest_judge_dimension": metrics.weakest_judge_dimension,
            "latency_ms": metrics.latency_ms,
        },
    }


def summarize_claim_support(results: list[EvalCaseResult]) -> dict[str, Any]:
    rows = [summarize_case_claim_support(result) for result in results]
    weak_cases = [
        row
        for row in rows
        if row["weak_claim_support"]
    ]
    return {
        "case_count": len(rows),
        "fact_like_case_count": sum(1 for row in rows if row["is_fact_like"]),
        "requires_archive_evidence_count": sum(
            1 for row in rows if row["requires_archive_evidence"]
        ),
        "citationless_biography_fact_count": sum(
            1 for row in rows if row["citationless_biography_fact"]
        ),
        "weak_claim_support_cases": weak_cases,
    }


def summarize_case_claim_support(result: EvalCaseResult) -> dict[str, Any]:
    mode = trace_value(result.trace_notes, "eval_response_mode")
    model = trace_value(result.trace_notes, "eval_response_model")
    citation_titles = [citation.title for citation in result.citations]
    citation_count = len(result.citations)
    is_fact_like = is_fact_like_case(result)
    requires_archive_evidence = is_fact_like and not result.case.should_abstain
    citationless_biography_fact = (
        is_fact_like
        and requires_archive_evidence
        and citation_count == 0
        and bool(result.answer)
    )
    weak_claim_support = (
        citationless_biography_fact
        or result.metrics.unsupported_claim_count > 0
        or (
            requires_archive_evidence
            and result.metrics.claim_support_rate < 0.6
            and citation_count == 0
        )
    )
    return {
        "case_id": result.case.id,
        "category": result.case.category,
        "persona_id": result.case.persona_id,
        "is_fact_like": is_fact_like,
        "requires_archive_evidence": requires_archive_evidence,
        "citation_count": citation_count,
        "citation_titles": citation_titles,
        "mode": mode,
        "model": model,
        "trace_summary": result.trace_notes[:8],
        "claim_support_rate": result.metrics.claim_support_rate,
        "unsupported_claim_count": result.metrics.unsupported_claim_count,
        "citationless_biography_fact": citationless_biography_fact,
        "weak_claim_support": weak_claim_support,
    }


def is_fact_like_case(result: EvalCaseResult) -> bool:
    case = result.case
    if case.category in FACT_LIKE_CATEGORIES:
        return True
    if case.expected_sources or case.expected_source_prefixes:
        return True
    question = case.question.lower()
    return any(marker.lower() in question for marker in BIOGRAPHY_FACT_MARKERS)


def trace_value(trace_notes: list[str], key: str) -> str | None:
    prefix = f"{key}="
    for note in reversed(trace_notes):
        if note.startswith(prefix):
            return note[len(prefix) :]
    return None


def excerpt(value: str | None, *, limit: int = 180) -> str:
    if not value:
        return ""
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def render_markdown(report: dict[str, Any]) -> str:
    if report["mode"] == "judge":
        title = "Persona Judge 评测报告"
    else:
        title = "对话评测报告" if report["mode"] == "chat" else "检索评测报告"
    status_label = {"passed": "通过", "failed": "失败", "running": "运行中"}.get(
        report["status"],
        report["status"],
    )
    mode_label = {"chat": "对话", "retrieval": "检索", "judge": "Judge"}.get(
        report["mode"],
        report["mode"],
    )
    metrics = report["metrics"]
    lines = [
        f"# {title}: {report['report_id']}",
        "",
        f"- 生成时间：`{report['generated_at']}`",
        f"- 运行编号：`{report['run_id']}`",
        f"- 状态：`{status_label}`",
        f"- 模式：`{mode_label}`",
        f"- 用例：`{report['passed_count']}/{report['question_count']}`",
    ]
    if report.get("backend_url"):
        lines.append(f"- 后端：`{report['backend_url']}`")
    if report.get("top_k") is not None:
        lines.append(f"- 证据上限：`{report['top_k']}`")
    if report.get("questions_path"):
        lines.append(f"- 问题集：`{report['questions_path']}`")

    lines.extend(
        [
            "",
            "## 指标汇总",
            "",
            "| 指标 | 数值 |",
            "| --- | ---: |",
            f"| 通过率 | {metrics['pass_rate']:.4f} |",
            f"| 来源召回 | {metrics['mean_source_recall']:.4f} |",
            f"| 引用精度 | {metrics['mean_citation_precision']:.4f} |",
            f"| 首位来源准确率 | {metrics['top1_accuracy']:.4f} |",
            f"| 平均 MRR | {metrics['mean_mrr']:.4f} |",
            f"| 平均 nDCG | {metrics['mean_ndcg']:.4f} |",
            f"| 平均关键词覆盖 | {metrics['mean_keyword_coverage']:.4f} |",
            f"| 平均依据重合 | {metrics['mean_evidence_overlap']:.4f} |",
            f"| 平均声明支持率 | {metrics['mean_claim_support_rate']:.4f} |",
            f"| 未支持声明率 | {metrics['unsupported_claim_rate']:.4f} |",
            f"| 拒答准确率 | {metrics['abstention_accuracy']:.4f} |",
            f"| 语言匹配率 | {metrics['language_match_rate']:.4f} |",
            f"| 禁用词违规率 | {metrics['forbidden_keyword_violation_rate']:.4f} |",
            f"| Judge 通过率 | {metrics.get('judge_pass_rate', 0.0):.4f} |",
            f"| Judge 平均分 | {metrics.get('mean_judge_score', 0.0):.4f} |",
            f"| Judge 最弱维度 | {metrics.get('weakest_judge_dimension') or 'n/a'} |",
            f"| 平均延迟 | {metrics['mean_latency_ms']:.2f}ms |",
            "",
            "## 运行配置",
            "",
        ]
    )
    config = report.get("config", {})
    if config:
        for key, value in config.items():
            lines.append(f"- `{key}`: `{value}`")
    else:
        lines.append("- 未提供运行配置快照。")

    append_claim_support_markdown(lines, report)

    lines.extend(["", "## 失败用例", ""])
    failures = report.get("failure_cases", [])
    if failures:
        lines.extend(
            [
                "| 用例 | 对象 | 类别 | 失败原因 | 回答摘录 |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for case in failures:
            lines.append(
                "| `{case_id}` | `{persona}` | {category} | {failures} | {answer} |".format(
                    case_id=case["case_id"],
                    persona=case["persona_id"],
                    category=case["category"],
                    failures=format_list(case["failures"]),
                    answer=escape_table(case["answer_excerpt"]),
                )
            )
    else:
        lines.append("没有失败用例。")

    lines.extend(["", "## 薄弱用例", ""])
    lines.extend(
        [
            "| 用例 | 对象 | 类别 | 通过 | 召回 | 精度 | 依据 | 声明支持 | 未支持 | 延迟 ms |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for case in report.get("weakest_cases", []):
        case_metrics = case["metrics"]
        lines.append(
            "| `{case_id}` | `{persona}` | {category} | {passed} | {recall:.4f} | {precision:.4f} | "
            "{evidence:.4f} | {support:.4f} | {unsupported} | {latency:.2f} |".format(
                case_id=case["case_id"],
                persona=case["persona_id"],
                category=case["category"],
                passed="1" if case["passed"] else "0",
                recall=case_metrics["source_recall"],
                precision=case_metrics["citation_precision"],
                evidence=case_metrics["evidence_overlap"],
                support=case_metrics["claim_support_rate"],
                unsupported=case_metrics["unsupported_claim_count"],
                latency=case_metrics["latency_ms"],
            )
        )

    lines.extend(["", "## 来源覆盖", ""])
    coverage = report.get("source_coverage", [])
    if coverage:
        lines.extend(["| 来源 | 引用次数 |", "| --- | ---: |"])
        for item in coverage[:20]:
            lines.append(f"| `{item['doc_id']}` | {item['count']} |")
    else:
        lines.append("没有记录引用。")

    lines.extend(["", "## 用例汇总", ""])
    lines.extend(
        [
            "| 用例 | 对象 | 类别 | 通过 | 召回 | 精度 | Top1 | MRR | nDCG | 依据 | 声明支持 | 延迟 ms |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for case in report.get("cases", []):
        case_metrics = case["metrics"]
        lines.append(
            "| `{case_id}` | `{persona}` | {category} | {passed} | {recall:.4f} | {precision:.4f} | "
            "{top1} | {mrr:.4f} | {ndcg:.4f} | {evidence:.4f} | {support:.4f} | {latency:.2f} |".format(
                case_id=case["case_id"],
                persona=case["persona_id"],
                category=case["category"],
                passed="1" if case["passed"] else "0",
                recall=case_metrics["source_recall"],
                precision=case_metrics["citation_precision"],
                top1="1" if case_metrics["top1_source_hit"] else "0",
                mrr=case_metrics["reciprocal_rank"],
                ndcg=case_metrics["ndcg"],
                evidence=case_metrics["evidence_overlap"],
                support=case_metrics["claim_support_rate"],
                latency=case_metrics["latency_ms"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def append_claim_support_markdown(lines: list[str], report: dict[str, Any]) -> None:
    claim_support = report.get("claim_support") or {}
    lines.extend(
        [
            "",
            "## Claim-Support 子报告",
            "",
            f"- 事实类用例：`{claim_support.get('fact_like_case_count', 0)}`",
            f"- 需要档案证据：`{claim_support.get('requires_archive_evidence_count', 0)}`",
            f"- 无引用传记事实风险：`{claim_support.get('citationless_biography_fact_count', 0)}`",
            "",
            "### Weak Claim Support Cases",
            "",
        ]
    )
    weak_cases = claim_support.get("weak_claim_support_cases") or []
    if not weak_cases:
        lines.append("没有弱证据支撑用例。")
        return
    lines.extend(
        [
            "| 用例 | 人物 | 类别 | 模式 | 模型 | 引用数 | 支持率 | 未支持声明 | 无引用传记事实 | Trace |",
            "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for case in weak_cases:
        lines.append(
            "| `{case_id}` | `{persona}` | {category} | `{mode}` | `{model}` | {citations} | "
            "{support:.4f} | {unsupported} | {citationless} | {trace} |".format(
                case_id=case["case_id"],
                persona=case["persona_id"],
                category=escape_table(case["category"]),
                mode=escape_table(case.get("mode") or "n/a"),
                model=escape_table(case.get("model") or "n/a"),
                citations=case["citation_count"],
                support=case["claim_support_rate"],
                unsupported=case["unsupported_claim_count"],
                citationless="1" if case["citationless_biography_fact"] else "0",
                trace=escape_table(", ".join(case.get("trace_summary") or [])),
            )
        )


def format_list(values: list[str]) -> str:
    if not values:
        return "-"
    return "<br>".join(escape_table(value) for value in values)


def escape_table(value: str) -> str:
    return value.replace("|", "\\|")
