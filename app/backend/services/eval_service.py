from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

from app.backend.core.config import get_settings
from app.backend.core.logging import new_request_id
from app.backend.persona_eval.judge import judge_answer
from app.backend.schemas.chat import ChatRequest
from app.backend.schemas.common import Citation
from app.backend.schemas.evals import (
    EvalCase,
    EvalCaseMetrics,
    EvalCaseResult,
    EvalRunListItem,
    EvalRunMetrics,
    EvalRunRequest,
    EvalRunResponse,
)
from app.backend.schemas.retrieval import RetrieveRequest
from app.backend.services.chat_service import answer_chat
from app.backend.services.eval_report_service import write_eval_report
from app.backend.services.metadata_store import MetadataStore
from app.backend.services.retrieval_service import retrieve
from app.rag.retrieval.lexical import tokenize
from app.rag.verification.citation_verifier import verify_answer


SUPPORTED_MODES = {"retrieval", "chat", "judge"}
CJK_SEGMENT_RE = re.compile(r"[\u4e00-\u9fff]+")
LATIN_RE = re.compile(r"[A-Za-z]")
CONTENT_CHAR_RE = re.compile(r"[\w\u4e00-\u9fff]", re.UNICODE)
ABSTENTION_MARKERS = [
    "not enough evidence",
    "do not have enough evidence",
    "no evidence",
    "cannot answer",
    "无法",
    "没有足够",
    "缺少证据",
    "不能可靠",
    "未提及",
    "未被提及",
    "不得声称",
    "请勿",
]
ABSTENTION_MARKERS.extend(
    [
        "无法",
        "不能",
        "没有足够",
        "缺少证据",
        "不能可靠",
        "不提供",
        "隐私",
        "敏感",
        "当前材料不足",
        "公开材料",
        "没有提到",
        "未找到",
        "无法确认",
        "不能声称",
        "不应声称",
        "禁止",
        "不得声称",
        "拒绝",
        "不能当作事实",
        "不能直接当作",
        "不能覆盖语料",
        "不能把",
        "不能说成",
        "不会公开",
        "不会泄露",
        "不会编造",
        "不会说出",
        "不属于我的经历",
        "不属于我的年代",
        "不在我的经历",
        "不在我能够确认的经历",
        "不能替代医疗",
        "不能替代心理",
        "不能替代特殊教育",
    ]
)

STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "answer",
    "are",
    "because",
    "based",
    "but",
    "can",
    "cannot",
    "could",
    "does",
    "from",
    "have",
    "into",
    "its",
    "more",
    "not",
    "only",
    "other",
    "that",
    "the",
    "their",
    "this",
    "through",
    "uses",
    "using",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
    "一个",
    "不是",
    "以及",
    "可以",
    "如果",
    "我们",
    "没有",
    "这个",
    "这些",
    "进行",
}


async def run_eval(request: EvalRunRequest) -> EvalRunResponse:
    settings = get_settings()
    if request.mode not in SUPPORTED_MODES:
        raise ValueError(f"Unsupported eval mode: {request.mode}")

    run_id = new_request_id()
    questions_path = request.questions_path or settings.eval_questions_path
    cases = select_cases(load_eval_cases(questions_path), request)
    results: list[EvalCaseResult] = []
    for case in cases:
        if request.mode == "judge":
            results.append(await evaluate_judge_case(case, request, run_id))
        elif request.mode == "chat":
            results.append(await evaluate_chat_case(case, request, run_id))
        else:
            results.append(evaluate_retrieval_case(case, request, run_id))

    full_response = build_run_response(
        run_id=run_id,
        mode=request.mode,
        results=results,
        include_results=True,
    )
    if should_write_automatic_report(request):
        report_paths = write_eval_report(
            full_response,
            output_dir=settings.data_dir / "eval_reports",
            questions_path=questions_path,
            top_k=request.top_k,
            backend_url=f"http://{settings.host}:{settings.port}",
            config=eval_report_config(settings),
        )
        full_response = full_response.model_copy(
            update={
                "message": (
                    f"{full_response.message} Report written to "
                    f"{report_paths.markdown_path}."
                ),
                "report_path": str(report_paths.markdown_path),
                "report_json_path": str(report_paths.json_path),
            }
        )
    MetadataStore(settings.sqlite_path).record_eval_run(full_response)
    if request.include_results:
        return full_response
    compact_response = build_run_response(
        run_id=run_id,
        mode=request.mode,
        results=results,
        include_results=False,
    )
    return compact_response.model_copy(
        update={
            "message": full_response.message,
            "report_path": full_response.report_path,
            "report_json_path": full_response.report_json_path,
        }
    )


def should_write_automatic_report(request: EvalRunRequest) -> bool:
    return request.mode in {"chat", "judge"} and not request.questions and not request.case_ids


def eval_report_config(settings: object) -> dict[str, object]:
    keys = [
        "generation_model",
        "embedding_model",
        "sparse_retriever",
        "retrieval_mode",
        "query_rewrite_enabled",
        "query_rewrite_dense",
        "local_reranker_enabled",
        "source_selector_enabled",
        "source_selector_intent_filter_enabled",
        "source_selector_top_k",
        "reranker_enabled",
        "reranker_backend",
        "boundary_fast_path_enabled",
        "judge_model",
        "judge_threshold",
    ]
    return {key: getattr(settings, key) for key in keys}


def load_eval_cases(path: Path) -> list[EvalCase]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [EvalCase.model_validate(item) for item in raw]


def select_cases(cases: list[EvalCase], request: EvalRunRequest) -> list[EvalCase]:
    if request.questions:
        return [
            EvalCase(id=f"adhoc_{idx:03d}", question=question, category="adhoc")
            for idx, question in enumerate(request.questions, 1)
        ]
    if request.case_ids:
        selected = {case_id.strip() for case_id in request.case_ids}
        return [case for case in cases if case.id in selected]
    return cases


def evaluate_retrieval_case(
    case: EvalCase,
    request: EvalRunRequest,
    run_id: str,
) -> EvalCaseResult:
    start = time.perf_counter()
    response = retrieve(
        RetrieveRequest(
            query=case.question,
            top_k=request.top_k,
            include_private=request.include_private,
            session_id=f"eval-{run_id}",
            persona_id=case.persona_id,
        )
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    retrieved_doc_ids = [citation.doc_id for citation in response.citations]
    metrics = score_case(
        case=case,
        retrieved_doc_ids=retrieved_doc_ids,
        elapsed_ms=elapsed_ms,
        answer=None,
        citations=response.citations,
        effective_persona_id=response.trace.persona_id,
    )
    return EvalCaseResult(
        case=case,
        retrieved_doc_ids=retrieved_doc_ids,
        selected_chunk_ids=response.trace.selected_chunk_ids,
        citations=response.citations,
        answer=None,
        trace_notes=response.trace.notes,
        metrics=metrics,
    )


async def evaluate_chat_case(
    case: EvalCase,
    request: EvalRunRequest,
    run_id: str,
) -> EvalCaseResult:
    start = time.perf_counter()
    response = await answer_chat(
        ChatRequest(
            message=case.question,
            session_id=f"eval-{run_id}-{case.id}",
            persona_id=case.persona_id,
            thinking_effort=request.thinking_effort,
            top_k=request.top_k,
            include_private=request.include_private,
            debug=True,
        )
    )
    elapsed_ms = response.timings.total_ms or (time.perf_counter() - start) * 1000
    retrieved_doc_ids = [citation.doc_id for citation in response.citations]
    metrics = score_case(
        case=case,
        retrieved_doc_ids=retrieved_doc_ids,
        elapsed_ms=elapsed_ms,
        answer=response.answer,
        citations=response.citations,
        effective_persona_id=response.retrieval_trace.persona_id,
    )
    return EvalCaseResult(
        case=case,
        retrieved_doc_ids=retrieved_doc_ids,
        selected_chunk_ids=response.retrieval_trace.selected_chunk_ids,
        citations=response.citations,
        answer=response.answer,
        trace_notes=[
            *response.retrieval_trace.notes,
            f"eval_response_mode={response.mode}",
            f"eval_response_model={response.model}",
        ],
        metrics=metrics,
    )


async def evaluate_judge_case(
    case: EvalCase,
    request: EvalRunRequest,
    run_id: str,
) -> EvalCaseResult:
    result = await evaluate_chat_case(case, request, run_id)
    if not result.answer:
        return result
    settings = get_settings()
    verdict = await judge_answer(
        case=case,
        answer=result.answer,
        citations=result.citations,
        settings=settings,
    )
    failures = judge_mode_base_failures(result.metrics.failures)
    if not verdict.passed:
        failures.append(
            "judge gate failed: "
            + (", ".join(verdict.failures) if verdict.failures else f"overall={verdict.overall:.2f}")
        )
    metrics = result.metrics.model_copy(
        update={
            "judge_scores": verdict.scores,
            "judge_score": verdict.overall,
            "judge_passed": verdict.passed,
            "judge_failures": verdict.failures,
            "weakest_judge_dimension": verdict.weakest_dimension,
            "passed": not failures,
            "failures": failures,
        }
    )
    return result.model_copy(update={"metrics": metrics})


def judge_mode_base_failures(failures: list[str]) -> list[str]:
    """Keep persona/language failures but ignore retrieval-only failures in judge mode."""

    return [
        failure
        for failure in failures
        if "引用" not in failure
        and "证据重合度" not in failure
        and "来源" not in failure
        and "Top-1" not in failure
        and "关键词" not in failure
        and "citation" not in failure.lower()
    ]


def score_case(
    *,
    case: EvalCase,
    retrieved_doc_ids: list[str],
    elapsed_ms: float,
    answer: str | None,
    citations: list[Citation] | None = None,
    effective_persona_id: str | None = None,
) -> EvalCaseMetrics:
    expected = set(case.expected_sources)
    expected_prefixes = case.expected_source_prefixes
    relevant_flags, effective_doc_ids, ranked_doc_ids, citation_count = citation_relevance(
        retrieved_doc_ids=retrieved_doc_ids,
        citations=citations,
        expected=expected,
        expected_prefixes=expected_prefixes,
    )
    hit_count = expected_source_hit_count(
        effective_doc_ids=effective_doc_ids,
        expected=expected,
        expected_prefixes=expected_prefixes,
    )
    expected_count = len(expected) + len(expected_prefixes)
    retrieved_count = citation_count
    source_recall = hit_count / expected_count if expected_count else 0.0
    relevant_retrieved = sum(1 for relevant in relevant_flags if relevant)
    citation_precision = relevant_retrieved / retrieved_count if retrieved_count else 0.0
    top1_source_hit = bool(relevant_flags and relevant_flags[0])
    reciprocal_rank = score_reciprocal_rank(relevant_flags)
    ndcg = score_ndcg(ranked_doc_ids, relevant_flags, expected_count)
    keyword_coverage = score_keyword_coverage(answer, case.expected_keywords)
    evidence_overlap = score_evidence_overlap(answer, citations or [])
    verification = verify_answer(answer, citations or [])
    forbidden_keyword_hits = find_forbidden_keywords(answer, case.forbidden_keywords)
    language_match = score_language_match(answer, case.expected_language)
    abstention_correct = None
    if answer is not None and case.should_abstain:
        abstention_correct = contains_abstention(answer)

    failures: list[str] = []
    expected_persona_id = case.expected_persona_id or case.persona_id
    if effective_persona_id is not None and effective_persona_id != expected_persona_id:
        failures.append(
            f"实际交谈对象 {effective_persona_id} != 期望 {expected_persona_id}"
        )
    forbidden_hits = forbidden_source_hits(
        retrieved_doc_ids,
        exact_sources=case.forbidden_sources,
        source_prefixes=case.forbidden_source_prefixes,
    )
    if forbidden_hits:
        failures.append(f"检索结果包含禁止来源：{', '.join(forbidden_hits)}")
    if expected_count and source_recall + 1e-9 < case.min_source_recall:
        failures.append(
            f"来源召回率 {source_recall:.2f} < 要求 {case.min_source_recall:.2f}"
        )
    if case.min_citation_precision and citation_precision + 1e-9 < case.min_citation_precision:
        failures.append(
            f"引用精度 {citation_precision:.2f} < 要求 {case.min_citation_precision:.2f}"
        )
    if case.require_top1_source_hit and not top1_source_hit:
        failures.append("Top-1 引用未命中期望来源")
    if (
        answer is not None
        and case.expected_keywords
        and keyword_coverage < case.min_keyword_coverage
        and evidence_overlap < 0.35
        and not (case.should_abstain and abstention_correct)
    ):
        failures.append(
            f"关键词覆盖率 {keyword_coverage:.2f} < 要求 {case.min_keyword_coverage:.2f}"
        )
    if case.should_abstain:
        if answer is not None and not abstention_correct:
            failures.append("回答没有清楚拒答")
    elif answer is not None and citations and evidence_overlap < case.min_evidence_overlap:
        failures.append(
            f"证据重合度 {evidence_overlap:.2f} < 要求 {case.min_evidence_overlap:.2f}"
        )
    if answer is not None and forbidden_keyword_hits:
        failures.append(f"回答包含禁止关键词：{', '.join(forbidden_keyword_hits)}")
    if answer is not None and language_match is False:
        failures.append(f"回答语言与期望 {case.expected_language} 不匹配")
    if not expected and not case.expected_keywords and not case.should_abstain and retrieved_count == 0:
        failures.append("信息型用例没有返回引用")

    return EvalCaseMetrics(
        source_recall=round(source_recall, 4),
        citation_precision=round(citation_precision, 4),
        top1_source_hit=top1_source_hit,
        reciprocal_rank=round(reciprocal_rank, 4),
        ndcg=round(ndcg, 4),
        expected_source_hit_count=hit_count,
        expected_source_count=expected_count,
        retrieved_count=retrieved_count,
        keyword_coverage=round(keyword_coverage, 4),
        evidence_overlap=round(evidence_overlap, 4),
        claim_support_rate=verification.claim_support_rate,
        unsupported_claim_count=verification.unsupported_claim_count,
        abstention_correct=abstention_correct,
        language_match=language_match,
        forbidden_keyword_hits=forbidden_keyword_hits,
        latency_ms=round(elapsed_ms, 2),
        passed=not failures,
        failures=failures,
    )


def score_keyword_coverage(answer: str | None, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    if not answer:
        return 0.0
    normalized_answer = answer.lower()
    hits = sum(1 for keyword in keywords if keyword.lower() in normalized_answer)
    return hits / len(keywords)


def forbidden_source_hits(
    retrieved_doc_ids: list[str],
    *,
    exact_sources: list[str],
    source_prefixes: list[str],
) -> list[str]:
    exact = set(exact_sources)
    hits: list[str] = []
    for doc_id in retrieved_doc_ids:
        if doc_id in exact or any(doc_id.startswith(prefix) for prefix in source_prefixes):
            hits.append(doc_id)
    return sorted(set(hits))


def citation_relevance(
    *,
    retrieved_doc_ids: list[str],
    citations: list[Citation] | None,
    expected: set[str],
    expected_prefixes: list[str],
) -> tuple[list[bool], list[str], list[str], int]:
    if citations is None:
        return (
            [
                is_expected_source(doc_id, expected=expected, prefixes=expected_prefixes)
                for doc_id in retrieved_doc_ids
            ],
            retrieved_doc_ids,
            retrieved_doc_ids,
            len(retrieved_doc_ids),
        )
    relevant_flags = [
        is_expected_source(citation.doc_id, expected=expected, prefixes=expected_prefixes)
        and is_informative_citation(citation)
        for citation in citations
    ]
    effective_doc_ids = [
        citation.doc_id for citation in citations if is_informative_citation(citation)
    ]
    ranked_doc_ids = [citation.doc_id for citation in citations]
    return relevant_flags, effective_doc_ids, ranked_doc_ids, len(citations)


def is_expected_source(doc_id: str, *, expected: set[str], prefixes: list[str]) -> bool:
    return doc_id in expected or any(doc_id.startswith(prefix) for prefix in prefixes)


def expected_source_hit_count(
    *,
    effective_doc_ids: list[str],
    expected: set[str],
    expected_prefixes: list[str],
) -> int:
    hits = sum(1 for doc_id in expected if doc_id in effective_doc_ids)
    hits += sum(
        1
        for prefix in expected_prefixes
        if any(doc_id.startswith(prefix) for doc_id in effective_doc_ids)
    )
    return hits


def is_informative_citation(citation: Citation, min_content_chars: int = 12) -> bool:
    preview = " ".join(citation.preview.split())
    content_chars = CONTENT_CHAR_RE.findall(preview)
    if len(content_chars) < min_content_chars:
        return False
    if preview.startswith("# ") and len(content_chars) < 24:
        return False
    return True


def score_reciprocal_rank(relevant_flags: list[bool]) -> float:
    if not relevant_flags:
        return 0.0
    for index, is_relevant in enumerate(relevant_flags, 1):
        if is_relevant:
            return 1.0 / index
    return 0.0


def score_ndcg(
    ranked_doc_ids: list[str],
    relevant_flags: list[bool],
    expected_count: int,
) -> float:
    if not expected_count or not relevant_flags:
        return 0.0
    seen: set[str] = set()
    dcg = 0.0
    for index, (doc_id, relevant) in enumerate(zip(ranked_doc_ids, relevant_flags)):
        if relevant and doc_id not in seen:
            dcg += 1.0 / math.log2(index + 2)
            seen.add(doc_id)
    ideal_hits = min(expected_count, len(relevant_flags))
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    if idcg == 0:
        return 0.0
    return dcg / idcg


def score_evidence_overlap(answer: str | None, citations: list[Citation]) -> float:
    if not answer or not citations:
        return 0.0
    answer_terms = content_terms(answer)
    if not answer_terms:
        return 0.0
    evidence_text = "\n".join(
        " ".join([citation.title, citation.section_path, citation.preview])
        for citation in citations
    )
    evidence_terms = content_terms(evidence_text)
    if not evidence_terms:
        return 0.0
    return len(answer_terms & evidence_terms) / len(answer_terms)


def content_terms(text: str) -> set[str]:
    terms = {
        token
        for token in tokenize(text)
        if len(token) >= 2 and token not in STOPWORDS and not token.isdigit()
    }
    for segment in CJK_SEGMENT_RE.findall(text):
        terms.update(
            segment[index : index + 2]
            for index in range(max(0, len(segment) - 1))
        )
    return terms


def contains_abstention(answer: str) -> bool:
    normalized = answer.lower()
    return any(marker.lower() in normalized for marker in ABSTENTION_MARKERS)


def find_forbidden_keywords(answer: str | None, forbidden_keywords: list[str]) -> list[str]:
    if not answer or not forbidden_keywords:
        return []
    normalized = answer.lower()
    hits: list[str] = []
    for keyword in forbidden_keywords:
        if keyword and keyword.lower() in normalized:
            hits.append(keyword)
    return hits


def score_language_match(answer: str | None, expected_language: str | None) -> bool | None:
    if not answer or not expected_language:
        return None
    normalized = expected_language.lower()
    cjk_count = len(CJK_SEGMENT_RE.findall(answer))
    latin_count = len(LATIN_RE.findall(answer))
    if normalized in {"zh", "zh-cn", "chinese"}:
        return cjk_count > 0
    if normalized in {"en", "english"}:
        return latin_count > 0 and cjk_count == 0
    return None


def build_run_response(
    *,
    run_id: str,
    mode: str,
    results: list[EvalCaseResult],
    include_results: bool,
) -> EvalRunResponse:
    passed_count = sum(1 for result in results if result.metrics.passed)
    failed_count = len(results) - passed_count
    metrics = aggregate_metrics(results)
    status = "passed" if results and failed_count == 0 else "completed_with_failures"
    if not results:
        status = "empty"
    return EvalRunResponse(
        run_id=run_id,
        status=status,
        message=f"已在 {mode} 模式下评测 {len(results)} 个用例。",
        mode=mode,
        question_count=len(results),
        passed_count=passed_count,
        failed_count=failed_count,
        metrics=metrics,
        results=results if include_results else [],
    )


def aggregate_metrics(results: list[EvalCaseResult]) -> EvalRunMetrics:
    if not results:
        return EvalRunMetrics()
    count = len(results)
    return EvalRunMetrics(
        pass_rate=round(sum(1 for result in results if result.metrics.passed) / count, 4),
        mean_source_recall=round(
            sum(result.metrics.source_recall for result in results) / count,
            4,
        ),
        mean_citation_precision=round(
            sum(result.metrics.citation_precision for result in results) / count,
            4,
        ),
        top1_accuracy=round(
            sum(1 for result in results if result.metrics.top1_source_hit) / count,
            4,
        ),
        mean_mrr=round(
            sum(result.metrics.reciprocal_rank for result in results) / count,
            4,
        ),
        mean_ndcg=round(
            sum(result.metrics.ndcg for result in results) / count,
            4,
        ),
        mean_keyword_coverage=round(
            sum(result.metrics.keyword_coverage for result in results) / count,
            4,
        ),
        mean_evidence_overlap=round(
            sum(result.metrics.evidence_overlap for result in results) / count,
            4,
        ),
        mean_claim_support_rate=round(
            sum(result.metrics.claim_support_rate for result in results) / count,
            4,
        ),
        unsupported_claim_rate=round(score_unsupported_claim_rate(results), 4),
        abstention_accuracy=round(score_abstention_accuracy(results), 4),
        language_match_rate=round(score_language_match_rate(results), 4),
        forbidden_keyword_violation_rate=round(score_forbidden_keyword_violation_rate(results), 4),
        judge_pass_rate=round(score_judge_pass_rate(results), 4),
        mean_judge_score=round(mean_judge_score(results), 4),
        weakest_judge_dimension=weakest_judge_dimension(results),
        weakest_judge_score=round(weakest_judge_score(results), 4),
        mean_latency_ms=round(sum(result.metrics.latency_ms for result in results) / count, 2),
    )


def score_abstention_accuracy(results: list[EvalCaseResult]) -> float:
    judged = [
        result.metrics.abstention_correct
        for result in results
        if result.metrics.abstention_correct is not None
    ]
    if not judged:
        return 0.0
    return sum(1 for value in judged if value) / len(judged)


def score_unsupported_claim_rate(results: list[EvalCaseResult]) -> float:
    answered = [result for result in results if result.answer is not None]
    if not answered:
        return 0.0
    violations = sum(1 for result in answered if result.metrics.unsupported_claim_count > 0)
    return violations / len(answered)


def score_language_match_rate(results: list[EvalCaseResult]) -> float:
    judged = [
        result.metrics.language_match
        for result in results
        if result.metrics.language_match is not None
    ]
    if not judged:
        return 0.0
    return sum(1 for value in judged if value) / len(judged)


def score_forbidden_keyword_violation_rate(results: list[EvalCaseResult]) -> float:
    answered = [result for result in results if result.answer is not None]
    if not answered:
        return 0.0
    violations = sum(1 for result in answered if result.metrics.forbidden_keyword_hits)
    return violations / len(answered)


def score_judge_pass_rate(results: list[EvalCaseResult]) -> float:
    judged = [result.metrics.judge_passed for result in results if result.metrics.judge_passed is not None]
    if not judged:
        return 0.0
    return sum(1 for value in judged if value) / len(judged)


def mean_judge_score(results: list[EvalCaseResult]) -> float:
    judged = [result.metrics.judge_score for result in results if result.metrics.judge_passed is not None]
    if not judged:
        return 0.0
    return sum(judged) / len(judged)


def weakest_judge_dimension(results: list[EvalCaseResult]) -> str | None:
    dimension_scores: dict[str, list[float]] = {}
    for result in results:
        for dimension, score in result.metrics.judge_scores.items():
            dimension_scores.setdefault(dimension, []).append(score)
    if not dimension_scores:
        return None
    averages = {
        dimension: sum(scores) / len(scores)
        for dimension, scores in dimension_scores.items()
        if scores
    }
    return min(averages, key=averages.get) if averages else None


def weakest_judge_score(results: list[EvalCaseResult]) -> float:
    dimension_scores: dict[str, list[float]] = {}
    for result in results:
        for dimension, score in result.metrics.judge_scores.items():
            dimension_scores.setdefault(dimension, []).append(score)
    if not dimension_scores:
        return 0.0
    averages = [
        sum(scores) / len(scores)
        for scores in dimension_scores.values()
        if scores
    ]
    return min(averages) if averages else 0.0


def recent_eval_runs(limit: int = 20) -> list[EvalRunListItem]:
    rows = MetadataStore(get_settings().sqlite_path).recent_eval_runs(limit=limit)
    return [EvalRunListItem.model_validate(row) for row in rows]


def eval_run_results(run_id: str) -> list[EvalCaseResult]:
    rows = MetadataStore(get_settings().sqlite_path).eval_results(run_id)
    return [EvalCaseResult.model_validate(row) for row in rows]
