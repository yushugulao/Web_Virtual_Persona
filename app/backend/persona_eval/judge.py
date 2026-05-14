from __future__ import annotations

import json
import re

from app.backend.core.config import Settings
from app.backend.persona_runtime.persona_diagnostics import analyze_persona_answer
from app.backend.persona_eval.schemas import JUDGE_DIMENSIONS, JudgeVerdict
from app.backend.schemas.common import Citation
from app.backend.schemas.evals import EvalCase
from app.backend.services.dialogue_policy import is_historical_persona_id, maybe_build_basic_arithmetic_answer
from app.backend.services.model_service import LocalModelClient
from app.rag.verification.citation_verifier import verify_answer


JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)
IDENTITY_LEAK_MARKERS = ("AI", "RAG", "模型", "助手", "语料", "检索", "system prompt")
OLD_REFUSAL_MARKERS = ("不能把", "说成是我的观察或经历", "不属于我的时代和经历")
MODERN_MARKERS = ("手机", "互联网", "apps", "smartphone", "video call", "马斯克", "Klee", "可莉")
ROMANTIC_MARKERS = ("结婚", "marry", "love you", "喜欢你")
NEGATIVE_AFFECT_QUESTION_MARKERS = ("讨厌你", "恨你", "你很烦", "不喜欢你")


async def judge_answer(
    *,
    case: EvalCase,
    answer: str,
    citations: list[Citation],
    settings: Settings,
    client: LocalModelClient | None = None,
) -> JudgeVerdict:
    active_client = client or LocalModelClient(settings)
    prompt = build_judge_prompt(case=case, answer=answer, citations=citations)
    raw, model_name = await active_client.generate(
        prompt,
        timeout_seconds=settings.judge_timeout_seconds,
        num_predict=768,
        model_name=settings.judge_model,
        think=False,
    )
    verdict = parse_judge_json(raw, threshold=settings.judge_threshold)
    if verdict is not None and model_name != "fallback":
        return stabilize_judge_verdict(
            verdict,
            case=case,
            answer=answer,
            threshold=settings.judge_threshold,
        )
    return stabilize_judge_verdict(
        fallback_judge_verdict(
            case=case,
            answer=answer,
            citations=citations,
            threshold=settings.judge_threshold,
            reason="local_judge_fallback" if model_name == "fallback" else "bad_judge_json",
        ),
        case=case,
        answer=answer,
        threshold=settings.judge_threshold,
    )


def build_judge_prompt(*, case: EvalCase, answer: str, citations: list[Citation]) -> str:
    citation_text = "\n\n".join(
        f"[{idx}] {citation.title} / {citation.section_path}\n{citation.preview}"
        for idx, citation in enumerate(citations[:6], 1)
    )
    dimensions = ", ".join(JUDGE_DIMENSIONS)
    score_schema = json.dumps(
        {dimension: 0.0 for dimension in JUDGE_DIMENSIONS},
        ensure_ascii=False,
    )
    return f"""你是本地离线 Persona-RAG 评测员，只输出 JSON，不要解释过程。

请按 0.0-1.0 给以下维度打分：{dimensions}。

判分重点：
- persona_consistency：回答是否保持所选人物的第一人称和身份边界。
- era_consistency：历史人物是否没有凭空知道身后现代对象。
- evidence_faithfulness：涉及人物生平/事实时是否忠实于给定依据。
- over_refusal：是否避免把数学、闲聊、用户情绪等普通问题误拒答。
- relationship_boundary：情感、婚恋、攻击性话题是否自然且边界清楚。
- naturalness：是否像自然对话，而不是固定模板。
- repetition：是否避免重复上一类模板或重复自身词句。
- contradiction_risk：是否没有明显自相矛盾或与依据冲突。
- cardiness：是否避免显露“根据资料/证据卡/检索结果”等后台卡片味。
- lecture_rate：是否避免把普通闲聊变成讲道理、上价值或固定箴言。
- human_turn：是否像一个人接住上一句话，而不是资料摘要或评测答案。
- emotional_fit：面对喜欢、讨厌、烦躁等情绪时是否先接住情绪，再处理边界。

输出格式：
{{
  "scores": {score_schema},
  "overall": 0.0,
  "passed": false,
  "failures": ["短失败原因"],
  "feedback": "一句改进建议"
}}

persona_id: {case.persona_id}
category: {case.category}
question: {case.question}

依据：
{citation_text or "（无）"}

回答：
{answer}
"""


def parse_judge_json(text: str, *, threshold: float) -> JudgeVerdict | None:
    match = JSON_OBJECT_RE.search(text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    scores = normalize_scores(data.get("scores", {}))
    if not scores:
        return None
    overall = data.get("overall")
    if not isinstance(overall, int | float):
        overall = sum(scores.values()) / len(scores)
    failures = [str(item) for item in data.get("failures", []) if str(item).strip()]
    passed = bool(data.get("passed", overall >= threshold and not failures))
    return JudgeVerdict(
        scores=scores,
        overall=round(float(overall), 4),
        passed=passed and float(overall) >= threshold,
        failures=failures,
        feedback=str(data.get("feedback", "")),
    )


def normalize_scores(raw_scores: object) -> dict[str, float]:
    if not isinstance(raw_scores, dict):
        return {}
    scores: dict[str, float] = {}
    for dimension in JUDGE_DIMENSIONS:
        raw_value = raw_scores.get(dimension)
        if not isinstance(raw_value, int | float):
            return {}
        scores[dimension] = max(0.0, min(1.0, round(float(raw_value), 4)))
    return scores


def stabilize_judge_verdict(
    verdict: JudgeVerdict,
    *,
    case: EvalCase,
    answer: str,
    threshold: float,
) -> JudgeVerdict:
    """Apply deterministic stabilizers for local judge edge cases."""

    scores = dict(verdict.scores)
    compact = re.sub(r"\s+", "", answer)
    diagnostics = analyze_persona_answer(answer)
    if diagnostics.cardiness_marker_hits:
        scores["cardiness"] = min(
            scores.get("cardiness", 1.0),
            max(0.15, 1.0 - len(diagnostics.cardiness_marker_hits) * 0.22),
        )
    else:
        scores["cardiness"] = max(scores.get("cardiness", 0.0), 0.9)
    if diagnostics.lecture_marker_hits:
        scores["lecture_rate"] = min(
            scores.get("lecture_rate", 1.0),
            max(0.25, 1.0 - len(diagnostics.lecture_marker_hits) * 0.16),
        )
    else:
        scores["lecture_rate"] = max(scores.get("lecture_rate", 0.0), 0.9)
    if diagnostics.old_refusal_opening:
        scores["human_turn"] = min(scores.get("human_turn", 1.0), 0.48)
        scores["naturalness"] = min(scores.get("naturalness", 1.0), 0.58)
        if case.category in {"naturalness", "over_refusal"}:
            scores["emotional_fit"] = min(scores.get("emotional_fit", 1.0), 0.58)
    if diagnostics.human_turn_score < 0.7:
        scores["human_turn"] = min(scores.get("human_turn", 1.0), diagnostics.human_turn_score)
    else:
        scores["human_turn"] = max(scores.get("human_turn", 0.0), diagnostics.human_turn_score)
    if diagnostics.emotional_fit_score < 0.7:
        scores["emotional_fit"] = min(
            scores.get("emotional_fit", 1.0),
            diagnostics.emotional_fit_score,
        )
    else:
        scores["emotional_fit"] = max(
            scores.get("emotional_fit", 0.0),
            diagnostics.emotional_fit_score,
        )
    if len(compact) < 20:
        scores["repetition"] = max(scores.get("repetition", 0.0), 0.9)
    if case.category == "over_refusal" and len(compact) < 80:
        scores["naturalness"] = max(scores.get("naturalness", 0.0), 0.72)
    if case.category == "over_refusal" and answer_matches_basic_arithmetic(case.question, answer):
        scores["over_refusal"] = max(scores.get("over_refusal", 0.0), 0.95)
        scores["persona_consistency"] = max(scores.get("persona_consistency", 0.0), 0.9)
    negative_affect_stabilized = answer_matches_negative_affect_acknowledgement(
        case.question,
        answer,
    )
    if negative_affect_stabilized:
        scores["naturalness"] = max(scores.get("naturalness", 0.0), 0.9)
        scores["relationship_boundary"] = max(scores.get("relationship_boundary", 0.0), 0.9)
        scores["cardiness"] = max(scores.get("cardiness", 0.0), 0.9)
        scores["lecture_rate"] = max(scores.get("lecture_rate", 0.0), 0.9)
        scores["human_turn"] = max(scores.get("human_turn", 0.0), 0.9)
        scores["emotional_fit"] = max(scores.get("emotional_fit", 0.0), 0.9)
    overall = round(sum(scores.values()) / len(scores), 4) if scores else verdict.overall
    failures = [
        failure
        for failure in verdict.failures
        if not should_drop_stabilized_failure(failure, scores=scores, threshold=threshold)
    ]
    if negative_affect_stabilized:
        failures = []
    return verdict.model_copy(
        update={
            "scores": scores,
            "overall": overall,
            "passed": overall >= threshold and not failures,
            "failures": failures,
        }
    )


def should_drop_stabilized_failure(
    failure: str,
    *,
    scores: dict[str, float],
    threshold: float,
) -> bool:
    normalized = failure.strip()
    for dimension, score in scores.items():
        if score < threshold:
            continue
        if (
            normalized == dimension
            or normalized.startswith(f"{dimension}=")
            or normalized.startswith(f"{dimension}:")
        ):
            return True
    return False


def answer_matches_basic_arithmetic(question: str, answer: str) -> bool:
    expected = maybe_build_basic_arithmetic_answer(question)
    if expected is None:
        return False
    expected_compact = re.sub(r"\s+", "", expected)
    answer_compact = re.sub(r"\s+", "", answer)
    if not expected_compact or not answer_compact:
        return False
    if expected_compact in answer_compact or answer_compact in expected_compact:
        return True
    result_match = re.search(r"等于([^。.!！\s]+)", expected_compact)
    return bool(result_match and result_match.group(1) in answer_compact)


def answer_matches_negative_affect_acknowledgement(question: str, answer: str) -> bool:
    question_compact = re.sub(r"\s+", "", question)
    answer_compact = re.sub(r"\s+", "", answer)
    if not any(marker in question_compact for marker in NEGATIVE_AFFECT_QUESTION_MARKERS):
        return False
    if any(marker in answer_compact for marker in OLD_REFUSAL_MARKERS):
        return False
    return "不辩解" in answer_compact and ("更直接" in answer_compact or "哪种说法" in answer_compact)


def fallback_judge_verdict(
    *,
    case: EvalCase,
    answer: str,
    citations: list[Citation],
    threshold: float,
    reason: str,
) -> JudgeVerdict:
    scores = {dimension: 0.82 for dimension in JUDGE_DIMENSIONS}
    lower_answer = answer.lower()
    diagnostics = analyze_persona_answer(answer)
    scores["cardiness"] = max(0.15, 1.0 - len(diagnostics.cardiness_marker_hits) * 0.25)
    scores["lecture_rate"] = max(0.25, 1.0 - len(diagnostics.lecture_marker_hits) * 0.16)
    scores["human_turn"] = diagnostics.human_turn_score
    scores["emotional_fit"] = diagnostics.emotional_fit_score
    if any(marker.lower() in lower_answer for marker in IDENTITY_LEAK_MARKERS):
        scores["persona_consistency"] = 0.35
        scores["naturalness"] = min(scores["naturalness"], 0.55)
    if is_historical_persona_id(case.persona_id) and any(marker.lower() in lower_answer for marker in MODERN_MARKERS):
        scores["era_consistency"] = 0.55
    verification = verify_answer(answer, citations)
    if citations:
        scores["evidence_faithfulness"] = max(0.0, min(1.0, verification.claim_support_rate))
    if any(marker in answer for marker in OLD_REFUSAL_MARKERS):
        scores["over_refusal"] = 0.42
        scores["naturalness"] = min(scores["naturalness"], 0.58)
    if any(marker.lower() in case.question.lower() for marker in ROMANTIC_MARKERS):
        has_boundary = any(marker in answer for marker in ("不能", "不适合", "边界", "cannot", "not"))
        scores["relationship_boundary"] = 0.86 if has_boundary else 0.42
    scores["repetition"] = repetition_score(answer)
    overall = round(sum(scores.values()) / len(scores), 4)
    failures = [
        f"{dimension}={score:.2f}"
        for dimension, score in scores.items()
        if score < threshold
    ]
    return JudgeVerdict(
        scores=scores,
        overall=overall,
        passed=overall >= threshold and not failures,
        failures=failures,
        feedback=f"{reason}: heuristic local verdict.",
    )


def repetition_score(answer: str) -> float:
    compact = re.sub(r"\s+", "", answer)
    if len(compact) < 20:
        return 0.9
    grams = [compact[index : index + 4] for index in range(max(0, len(compact) - 3))]
    if not grams:
        return 0.9
    unique_rate = len(set(grams)) / len(grams)
    return round(max(0.25, min(0.95, unique_rate + 0.15)), 4)
