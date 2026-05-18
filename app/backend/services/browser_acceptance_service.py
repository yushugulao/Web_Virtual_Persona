from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

from app.backend.schemas.browser_acceptance import (
    BrowserAcceptanceCaseFeedback,
    BrowserAcceptanceMatrixResponse,
)
from app.backend.schemas.feedback import PersonaTurnFeedbackRecord
from app.backend.services.feedback_service import read_persona_turn_feedback


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MATRIX_PATH = PROJECT_ROOT / "evals" / "questions" / "persona_browser_acceptance_matrix.json"
EMPTY_MATRIX_PAYLOAD: dict[str, Any] = {
    "schema_version": "1.0",
    "description": "Browser acceptance matrix is not configured in this build.",
    "default_thinking_effort": "medium",
    "personas": [],
    "categories": [],
    "cases": [],
}
POSITIVE_ISSUES = {"good"}
NEGATIVE_ISSUES = {
    "cardiness",
    "lecture",
    "too_long",
    "unnatural",
    "memory_error",
    "era_boundary_error",
    "fact_error",
    "other",
}


def load_browser_acceptance_matrix(
    *,
    matrix_path: Path | None = None,
    data_dir: Path | None = None,
    persona_id: str | None = None,
    category_id: str | None = None,
) -> BrowserAcceptanceMatrixResponse:
    path = matrix_path or DEFAULT_MATRIX_PATH
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else dict(EMPTY_MATRIX_PAYLOAD)
    all_cases = list(payload.get("cases", []))
    cases = [
        case
        for case in all_cases
        if (not persona_id or case.get("persona_id") == persona_id)
        and (not category_id or case.get("category_id") == category_id)
    ]
    response_payload: dict[str, Any] = {
        **payload,
        "cases": cases,
        "total_cases": len(all_cases),
        "filtered_cases": len(cases),
        "by_persona": dict(sorted(Counter(case["persona_id"] for case in all_cases).items())),
        "by_category": dict(sorted(Counter(case["category_id"] for case in all_cases).items())),
    }
    response_payload.update(_progress_payload(cases, data_dir=data_dir))
    matrix = BrowserAcceptanceMatrixResponse.model_validate(response_payload)
    _validate_matrix(matrix)
    return matrix


def _progress_payload(
    cases: list[dict[str, Any]],
    *,
    data_dir: Path | None,
) -> dict[str, Any]:
    if data_dir is None:
        return {
            "matched_feedback_records": 0,
            "tested_cases": 0,
            "negative_cases": 0,
            "positive_cases": 0,
            "case_feedback": {},
        }

    records, _invalid_line_count = read_persona_turn_feedback(data_dir=data_dir)
    feedback_by_case = _match_feedback_to_cases(cases, records)
    case_feedback: dict[str, BrowserAcceptanceCaseFeedback] = {}
    for case_id, matched_records in feedback_by_case.items():
        case_feedback[case_id] = _summarize_case_feedback(matched_records)

    return {
        "matched_feedback_records": sum(
            summary.matched_feedback_count for summary in case_feedback.values()
        ),
        "tested_cases": sum(1 for summary in case_feedback.values() if summary.matched_feedback_count),
        "negative_cases": sum(1 for summary in case_feedback.values() if summary.negative_feedback_count),
        "positive_cases": sum(1 for summary in case_feedback.values() if summary.positive_feedback_count),
        "case_feedback": case_feedback,
    }


def _match_feedback_to_cases(
    cases: list[dict[str, Any]],
    records: list[PersonaTurnFeedbackRecord],
) -> dict[str, list[PersonaTurnFeedbackRecord]]:
    case_by_key = {
        (case["persona_id"], _normalize_prompt(case["prompt"])): case["case_id"]
        for case in cases
    }
    case_ids = {case["case_id"] for case in cases}
    feedback_by_case: dict[str, list[PersonaTurnFeedbackRecord]] = defaultdict(list)
    for record in records:
        if record.acceptance_case_id and record.acceptance_case_id in case_ids:
            feedback_by_case[record.acceptance_case_id].append(record)
            continue
        case_id = case_by_key.get((record.persona_id, _normalize_prompt(record.user_message)))
        if case_id:
            feedback_by_case[case_id].append(record)
    return feedback_by_case


def _summarize_case_feedback(
    records: list[PersonaTurnFeedbackRecord],
) -> BrowserAcceptanceCaseFeedback:
    latest = records[-1] if records else None
    return BrowserAcceptanceCaseFeedback(
        matched_feedback_count=len(records),
        negative_feedback_count=sum(1 for record in records if record.issue in NEGATIVE_ISSUES),
        positive_feedback_count=sum(1 for record in records if record.issue in POSITIVE_ISSUES),
        issue_counts=dict(sorted(Counter(record.issue for record in records).items())),
        latest_feedback_id=latest.feedback_id if latest else None,
        latest_issue=latest.issue if latest else None,
        latest_severity=latest.severity if latest else None,
        latest_created_at=latest.created_at if latest else None,
    )


def _normalize_prompt(value: str) -> str:
    return "".join(value.strip().split())


def _validate_matrix(matrix: BrowserAcceptanceMatrixResponse) -> None:
    persona_ids = {persona.persona_id for persona in matrix.personas}
    category_ids = {category.category_id for category in matrix.categories}
    case_ids: set[str] = set()
    duplicate_case_ids: set[str] = set()

    for case in matrix.cases:
        if case.case_id in case_ids:
            duplicate_case_ids.add(case.case_id)
        case_ids.add(case.case_id)
        if case.persona_id not in persona_ids:
            raise ValueError(f"Unknown persona_id in browser acceptance matrix: {case.persona_id}")
        if case.category_id not in category_ids:
            raise ValueError(f"Unknown category_id in browser acceptance matrix: {case.category_id}")

    if duplicate_case_ids:
        duplicate_text = ", ".join(sorted(duplicate_case_ids))
        raise ValueError(f"Duplicate browser acceptance case ids: {duplicate_text}")
