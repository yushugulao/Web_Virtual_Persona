from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import uuid4

from app.backend.schemas.feedback import (
    PersonaTurnFeedbackRecord,
    PersonaTurnFeedbackRequest,
    PersonaTurnFeedbackStatsResponse,
)


FEEDBACK_FILENAME = "persona_browser_feedback.jsonl"


def feedback_file_path(data_dir: Path) -> Path:
    return data_dir / "feedback" / FEEDBACK_FILENAME


def write_persona_turn_feedback(
    request: PersonaTurnFeedbackRequest,
    *,
    data_dir: Path,
) -> PersonaTurnFeedbackRecord:
    path = feedback_file_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = PersonaTurnFeedbackRecord(
        **request.model_dump(),
        feedback_id=uuid4().hex,
        created_at=datetime.now(UTC).isoformat(),
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False))
        handle.write("\n")
    return record


def list_persona_turn_feedback(
    *,
    data_dir: Path,
    limit: int = 50,
    persona_id: str | None = None,
    issue: str | None = None,
) -> list[PersonaTurnFeedbackRecord]:
    path = feedback_file_path(data_dir)
    if not path.exists():
        return []

    records: list[PersonaTurnFeedbackRecord] = []
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            record = PersonaTurnFeedbackRecord.model_validate_json(line)
        except ValueError:
            continue
        if persona_id and record.persona_id != persona_id:
            continue
        if issue and record.issue != issue:
            continue
        records.append(record)
        if len(records) >= limit:
            break
    return records


def summarize_persona_turn_feedback(
    *,
    data_dir: Path,
    recent_limit: int = 5,
) -> PersonaTurnFeedbackStatsResponse:
    records, invalid_line_count = read_persona_turn_feedback(data_dir=data_dir)
    latest_records = list(reversed(records))[:recent_limit]
    negative_total = sum(1 for record in records if record.issue != "good")
    positive_total = sum(1 for record in records if record.issue == "good")
    persona_issue_counter: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        persona_issue_counter[record.persona_id][record.issue] += 1

    return PersonaTurnFeedbackStatsResponse(
        total=len(records),
        negative_total=negative_total,
        positive_total=positive_total,
        invalid_line_count=invalid_line_count,
        by_issue=dict(sorted(Counter(record.issue for record in records).items())),
        by_persona=dict(sorted(Counter(record.persona_id for record in records).items())),
        by_severity=dict(sorted(Counter(record.severity for record in records).items())),
        by_persona_issue={
            persona_id: dict(sorted(issue_counts.items()))
            for persona_id, issue_counts in sorted(persona_issue_counter.items())
        },
        latest_records=latest_records,
    )


def read_persona_turn_feedback(
    *,
    data_dir: Path,
) -> tuple[list[PersonaTurnFeedbackRecord], int]:
    path = feedback_file_path(data_dir)
    if not path.exists():
        return [], 0

    records: list[PersonaTurnFeedbackRecord] = []
    invalid_line_count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(PersonaTurnFeedbackRecord.model_validate_json(line))
        except ValueError:
            invalid_line_count += 1
    return records, invalid_line_count
