from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.backend.core.config import get_settings  # noqa: E402
from app.backend.document_reader import read_document  # noqa: E402
from scripts.document_reader.prepare_benchmark_fixtures import prepare_fixtures  # noqa: E402


def _minimal_pdf_bytes(text: str) -> bytes:
    objects = [
        "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            "3 0 obj\n"
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\n"
            "endobj\n"
        ),
        "4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects.append(
        f"5 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("latin-1").decode(
            "latin-1"
        )
        + stream.decode("latin-1")
        + "\nendstream\nendobj\n"
    )
    content = b"%PDF-1.4\n"
    offsets = [0]
    for obj in objects:
        offsets.append(len(content))
        content += obj.encode("latin-1")
    xref_offset = len(content)
    xref_lines = ["xref\n", f"0 {len(objects) + 1}\n", "0000000000 65535 f \n"]
    xref_lines.extend(f"{offset:010d} 00000 n \n" for offset in offsets[1:])
    trailer = (
        "".join(xref_lines)
        + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        + f"startxref\n{xref_offset}\n%%EOF\n"
    )
    return content + trailer.encode("latin-1")


def _write_smoke_fixtures(root: Path) -> list[Path]:
    fixtures = root / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    (fixtures / "notes.txt").write_text(
        "第一段：这是一个用于读取器 smoke 的文本。\n\n第二段：保留结构。",
        encoding="utf-8",
    )
    (fixtures / "table.csv").write_text(
        "name,role\n张三,工程师\n李四,设计师\n",
        encoding="utf-8",
    )
    (fixtures / "page.html").write_text(
        "<h1>标题</h1><p>HTML 正文段落。</p>",
        encoding="utf-8",
    )
    (fixtures / "screen.png").write_bytes(b"\x89PNG\r\n\x1a\nplaceholder")
    (fixtures / "sample.pdf").write_bytes(_minimal_pdf_bytes("Document reader smoke PDF"))
    return sorted(fixtures.iterdir())


@contextmanager
def _temporary_ocr_backend(backend: str | None, *, paddle_mode: str | None = None):
    marker_key = "DOCUMENT_READER_ENABLE_MARKER_SURYA"
    paddle_key = "DOCUMENT_READER_ENABLE_PADDLEOCR_VL"
    paddle_mode_key = "DOCUMENT_READER_PADDLEOCR_VL_MODE"
    old_marker = os.environ.get(marker_key)
    old_paddle = os.environ.get(paddle_key)
    old_paddle_mode = os.environ.get(paddle_mode_key)
    os.environ[marker_key] = "true" if backend == "marker_surya" else "false"
    os.environ[paddle_key] = "true" if backend == "paddleocr_vl" else "false"
    if paddle_mode:
        os.environ[paddle_mode_key] = paddle_mode
    get_settings.cache_clear()
    try:
        yield
    finally:
        if old_marker is None:
            os.environ.pop(marker_key, None)
        else:
            os.environ[marker_key] = old_marker
        if old_paddle is None:
            os.environ.pop(paddle_key, None)
        else:
            os.environ[paddle_key] = old_paddle
        if old_paddle_mode is None:
            os.environ.pop(paddle_mode_key, None)
        else:
            os.environ[paddle_mode_key] = old_paddle_mode
        get_settings.cache_clear()


def _read_markdown(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _mojibake_rate(text: str) -> float:
    if not text:
        return 0.0
    mojibake_tokens = ("\ufffd", "\u6d63", "\u93c2", "\u9225", "\u951b", "\u7edb")
    hits = sum(text.count(token) for token in mojibake_tokens)
    return round(hits / max(len(text), 1), 6)


def _keyword_metrics(text: str, keywords: list[str]) -> dict[str, Any]:
    lowered = text.lower()
    hits = [keyword for keyword in keywords if keyword.lower() in lowered]
    return {
        "keyword_count": len(keywords),
        "keyword_hits": hits,
        "keyword_hit_rate": round(len(hits) / max(len(keywords), 1), 4),
        "missing_keywords": [keyword for keyword in keywords if keyword not in hits],
    }


def _strict_quality_metrics(text: str, result: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    category = str(case.get("category", "")).lower()
    keywords = [str(item) for item in case.get("keywords", [])]
    keyword_payload = _keyword_metrics(text, keywords)
    keyword_pass = True if not keywords else keyword_payload["keyword_hit_rate"] >= 0.5
    is_generated = str(case.get("kind", "")) == "generated"
    has_expectations = bool(keywords) or is_generated
    table_required = has_expectations and "table" in category
    formula_required = has_expectations and ("formula" in category or "math" in category)
    chart_required = has_expectations and "chart" in category
    reading_order_required = (
        len(keywords) >= 2
        and not any(token in category for token in ("table", "chart", "formula", "code_terminal"))
    )

    table_structure_pass = (
        _has_markdown_table(text) or result.get("table_blocks", 0) > 0
        if table_required
        else True
    )
    formula_pass = (
        _has_formula_signal(text) or result.get("formula_blocks", 0) > 0
        if formula_required
        else True
    )
    chart_label_pass = (
        keyword_payload["keyword_hit_rate"] >= 0.5 and _has_number_signal(text)
        if chart_required
        else True
    )
    reading_order_pass = _keywords_in_order(text, keywords) if reading_order_required else True
    runner_completed = result.get("status") == "passed"
    backend_used = bool(result.get("ocr_backend_used"))
    usable_parse = (
        runner_completed
        and not result.get("needs_ocr_backend")
        and result.get("markdown_chars", 0) > 0
    )
    strict_pass = all(
        [
            runner_completed,
            backend_used,
            usable_parse,
            keyword_pass,
            table_structure_pass,
            formula_pass,
            chart_label_pass,
            reading_order_pass,
            result.get("mojibake_rate", 1) <= 0.01,
        ]
    )
    failure_buckets: list[str] = []
    if not runner_completed:
        failure_buckets.append("runtime_failed")
    if runner_completed and not backend_used:
        failure_buckets.append("ocr_backend_not_used")
    if backend_used and not usable_parse:
        failure_buckets.append("usable_parse_failed")
    if not keyword_pass:
        failure_buckets.append("keyword_failed")
    if not table_structure_pass:
        failure_buckets.append("table_failed")
    if not formula_pass:
        failure_buckets.append("formula_failed")
    if not chart_label_pass:
        failure_buckets.append("chart_failed")
    if not reading_order_pass:
        failure_buckets.append("reading_order_failed")
    if result.get("mojibake_rate", 0) > 0.01:
        failure_buckets.append("mojibake_failed")
    return {
        "runner_completed": runner_completed,
        "ocr_backend_used_for_case": backend_used,
        "usable_parse": usable_parse,
        "strict_pass": strict_pass,
        "keyword_pass": keyword_pass,
        "table_structure_pass": table_structure_pass,
        "formula_pass": formula_pass,
        "chart_label_pass": chart_label_pass,
        "reading_order_pass": reading_order_pass,
        "failure_buckets": failure_buckets,
    }


def _has_markdown_table(text: str) -> bool:
    return bool(re.search(r"^\s*\|.+\|\s*$\n^\s*\|[\s:\-|]+\|\s*$", text, flags=re.MULTILINE))


def _has_formula_signal(text: str) -> bool:
    return bool(
        re.search(
            r"(softmax|loss|mc\^?2|mc²|exp\(|\\sum|Σ|=|frac|log\(|bleu)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _has_number_signal(text: str) -> bool:
    return bool(re.search(r"\d+(?:\.\d+)?\s*%?", text))


def _keywords_in_order(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    positions = [lowered.find(keyword.lower()) for keyword in keywords]
    found_positions = [position for position in positions if position >= 0]
    if len(found_positions) < 2:
        return True
    return found_positions == sorted(found_positions)


def _failure_bucket_counts(bucket_lists: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for buckets in bucket_lists:
        for bucket in buckets or []:
            counts[str(bucket)] = counts.get(str(bucket), 0) + 1
    return counts


def _case_status(result: Any) -> str:
    if result.quality_summary.needs_ocr_backend:
        return "needs_ocr_backend"
    if result.quality_score >= 0.5:
        return "parsed"
    return "parsed_low_quality"


def _gpu_snapshot() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    if completed.returncode != 0:
        return {"available": False, "error": completed.stderr.strip()}
    line = (completed.stdout or "").splitlines()[0] if completed.stdout.splitlines() else ""
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 4:
        return {"available": False, "raw": line}
    return {
        "available": True,
        "name": parts[0],
        "util_percent": _safe_float(parts[1]),
        "memory_used_mb": _safe_float(parts[2]),
        "memory_total_mb": _safe_float(parts[3]),
    }


class _GpuSampler:
    def __init__(self, interval_seconds: float = 0.75):
        self.interval_seconds = interval_seconds
        self.samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_GpuSampler":
        self.samples.append(_gpu_snapshot())
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.samples.append(_gpu_snapshot())

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.samples.append(_gpu_snapshot())

    def summary(self) -> dict[str, Any]:
        available_samples = [sample for sample in self.samples if sample.get("available")]
        if not available_samples:
            return {
                "available": False,
                "sample_count": len(self.samples),
                "samples": self.samples[:3],
            }
        return {
            "available": True,
            "sample_count": len(available_samples),
            "name": available_samples[-1].get("name"),
            "peak_util_percent": max(float(sample.get("util_percent", 0)) for sample in available_samples),
            "peak_memory_used_mb": max(float(sample.get("memory_used_mb", 0)) for sample in available_samples),
            "memory_total_mb": max(float(sample.get("memory_total_mb", 0)) for sample in available_samples),
            "first": available_samples[0],
            "last": available_samples[-1],
        }


def _safe_float(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0


def _run_one(
    file_path: Path,
    output_dir: Path,
    *,
    original_filename: str,
    ocr_backend: str | None,
    paddle_mode: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    gpu_before = _gpu_snapshot()
    try:
        with _GpuSampler() as gpu_sampler, _temporary_ocr_backend(ocr_backend, paddle_mode=paddle_mode):
            result = read_document(
                file_path,
                output_dir,
                original_filename=original_filename,
                mime_type="application/octet-stream",
            )
            settings = get_settings()
            backend_mode = settings.document_reader_paddleocr_vl_mode if ocr_backend == "paddleocr_vl" else ""
            endpoint = settings.document_reader_paddleocr_vl_endpoint if ocr_backend == "paddleocr_vl" else ""
        markdown = _read_markdown(result.markdown_path)
        gpu_after = _gpu_snapshot()
        parser_chain = [str(item) for item in result.parser_chain]
        paddle_used = any("paddleocr_vl" in item.lower() for item in parser_chain)
        marker_used = any("marker_surya" in item.lower() for item in parser_chain)
        runtime_metadata: list[dict[str, Any]] = [
            item.runtime_metadata for item in result.diagnostics if item.runtime_metadata
        ]
        return {
            "status": "passed",
            "ocr_backend": ocr_backend or "disabled",
            "paddle_used": paddle_used,
            "marker_used": marker_used,
            "ocr_backend_used": marker_used or paddle_used,
            "backend_mode": backend_mode,
            "endpoint": endpoint,
            "gpu_before": gpu_before,
            "gpu_after": gpu_after,
            "gpu_sampling": gpu_sampler.summary(),
            "runtime_metadata": runtime_metadata,
            "observed_gpu_memory_delta_mb": (
                round(
                    float(gpu_after.get("memory_used_mb", 0))
                    - float(gpu_before.get("memory_used_mb", 0)),
                    2,
                )
                if gpu_before.get("available") and gpu_after.get("available")
                else None
            ),
            "parse_status_hint": _case_status(result),
            "quality_score": result.quality_score,
            "parser_chain": parser_chain,
            "block_count": len(result.blocks),
            "ocr_pages": result.quality_summary.ocr_pages,
            "needs_ocr_backend": result.quality_summary.needs_ocr_backend,
            "table_blocks": result.quality_summary.table_blocks,
            "formula_blocks": result.quality_summary.formula_blocks,
            "image_blocks": result.quality_summary.image_blocks,
            "markdown_chars": len(markdown),
            "mojibake_rate": _mojibake_rate(markdown),
            "diagnostics_path": result.diagnostics_path,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:  # pragma: no cover - benchmark report path.
        gpu_after = _gpu_snapshot()
        return {
            "status": "failed",
            "error": str(exc),
            "gpu_before": gpu_before,
            "gpu_after": gpu_after,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }


def run_smoke(output_dir: Path) -> dict[str, Any]:
    files = _write_smoke_fixtures(output_dir)
    cases: list[dict[str, Any]] = []
    started = time.perf_counter()
    for file_path in files:
        parsed_dir = output_dir / "parsed" / file_path.stem
        result = _run_one(
            file_path,
            parsed_dir,
            original_filename=file_path.name,
            ocr_backend=None,
        )
        result["filename"] = file_path.name
        cases.append(result)
    return {
        "suite": "smoke",
        "status": "passed" if all(case["status"] == "passed" for case in cases) else "failed",
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "case_count": len(cases),
        "cases": cases,
    }


def _is_ocr_heavy(category: str) -> bool:
    return bool(re.search(r"(image|scan|screenshot|formula|chart|table)", category))


def run_ocr_heavy_benchmark(
    output_dir: Path,
    *,
    case_ids: set[str] | None = None,
    max_cases: int | None = None,
    ocr_backend: str = "marker_surya",
    paddle_mode: str | None = None,
) -> dict[str, Any]:
    fixture_manifest = prepare_fixtures()
    run_dir = output_dir / "ocr_heavy_run"
    cases: list[dict[str, Any]] = []
    started = time.perf_counter()
    selected_cases = [
        case
        for case in fixture_manifest["cases"]
        if not case_ids or str(case.get("case_id")) in case_ids
    ]
    if max_cases is not None:
        selected_cases = selected_cases[:max_cases]
    for case in selected_cases:
        if not case.get("prepared"):
            cases.append(
                {
                    "case_id": case["case_id"],
                    "status": "skipped",
                    "reason": case.get("prepare_status", "not prepared"),
                }
            )
            continue
        file_path = Path(case["path"])
        baseline = _run_one(
            file_path,
            run_dir / "docling_standard" / case["case_id"],
            original_filename=file_path.name,
            ocr_backend=None,
        )
        ocr_result = _run_one(
            file_path,
            run_dir / ocr_backend / case["case_id"],
            original_filename=file_path.name,
            ocr_backend=ocr_backend,
            paddle_mode=paddle_mode,
        )
        baseline_text = _read_markdown(
            str(run_dir / "docling_standard" / case["case_id"] / "document.md")
        )
        ocr_text = _read_markdown(str(run_dir / ocr_backend / case["case_id"] / "document.md"))
        keywords = [str(item) for item in case.get("keywords", [])]
        baseline_payload = baseline | _keyword_metrics(baseline_text, keywords)
        ocr_payload = ocr_result | _keyword_metrics(ocr_text, keywords)
        baseline_payload.update(_strict_quality_metrics(baseline_text, baseline_payload, case))
        ocr_payload.update(_strict_quality_metrics(ocr_text, ocr_payload, case))
        cases.append(
            {
                "case_id": case["case_id"],
                "kind": case.get("kind", ""),
                "category": case.get("category", ""),
                "filename": file_path.name,
                "ocr_heavy": _is_ocr_heavy(str(case.get("category", ""))),
                "keywords": keywords,
                "docling_standard": baseline_payload,
                ocr_backend: ocr_payload,
            }
        )
    ocr_cases = [case for case in cases if case.get("ocr_heavy")]
    usable_ocr_cases = [
        case
        for case in ocr_cases
        if case.get(ocr_backend, {}).get("status") == "passed"
        and not case.get(ocr_backend, {}).get("needs_ocr_backend")
        and case.get(ocr_backend, {}).get("markdown_chars", 0) > 0
    ]
    strict_pass_cases = [
        case for case in ocr_cases if case.get(ocr_backend, {}).get("strict_pass") is True
    ]
    summary = {
        "ocr_heavy_case_count": len(ocr_cases),
        "ocr_heavy_usable_count": len(usable_ocr_cases),
        "ocr_heavy_usable_rate": round(len(usable_ocr_cases) / max(len(ocr_cases), 1), 4),
        "strict_pass_count": len(strict_pass_cases),
        "strict_pass_rate": round(len(strict_pass_cases) / max(len(ocr_cases), 1), 4),
        "ocr_backend": ocr_backend,
        "ocr_runner_completed_cases": sum(
            1 for case in cases if case.get(ocr_backend, {}).get("status") == "passed"
        ),
        "ocr_backend_used_cases": sum(
            1 for case in cases if case.get(ocr_backend, {}).get("ocr_backend_used")
        ),
        "ocr_backend_usable_cases": sum(
            1
            for case in cases
            if case.get(ocr_backend, {}).get("ocr_backend_used")
            and not case.get(ocr_backend, {}).get("needs_ocr_backend")
            and case.get(ocr_backend, {}).get("markdown_chars", 0) > 0
        ),
        "strict_failure_buckets": _failure_bucket_counts(
            case.get(ocr_backend, {}).get("failure_buckets", []) for case in ocr_cases
        ),
    }
    status = (
        "passed"
        if summary["ocr_heavy_usable_rate"] >= 0.8 and summary["strict_pass_rate"] >= 0.7
        else "needs_runtime_or_quality_work"
    )
    return {
        "suite": "ocr_heavy",
        "status": status,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "ocr_backend": ocr_backend,
        "backend_mode": paddle_mode or "",
        "endpoint": get_settings().document_reader_paddleocr_vl_endpoint if ocr_backend == "paddleocr_vl" else "",
        "gpu": _gpu_snapshot(),
        "summary": summary,
        "fixture_manifest": fixture_manifest,
        "cases": cases,
    }


def _write_markdown_report(report: dict[str, Any], output_path: Path) -> None:
    lines = [
        f"# Document Reader Benchmark: {report['suite']}",
        "",
        f"- 状态：{report['status']}",
        f"- 耗时：{report.get('elapsed_ms', 0)} ms",
    ]
    summary = report.get("summary")
    if summary:
        lines.extend(
            [
                f"- OCR-heavy 可用率：{summary['ocr_heavy_usable_count']}/"
                f"{summary['ocr_heavy_case_count']} ({summary['ocr_heavy_usable_rate']})",
                f"- 严格通过率：{summary.get('strict_pass_count', 0)}/"
                f"{summary['ocr_heavy_case_count']} ({summary.get('strict_pass_rate', 0)})",
                f"- OCR 后端：{summary.get('ocr_backend', '')}",
                f"- Runner 完成：{summary.get('ocr_runner_completed_cases', 0)} case",
                f"- OCR 后端实际参与解析：{summary.get('ocr_backend_used_cases', 0)} case",
                f"- OCR 后端可用解析：{summary.get('ocr_backend_usable_cases', 0)} case",
                f"- 严格失败桶：{summary.get('strict_failure_buckets', {})}",
                "",
            ]
        )
    gpu = report.get("gpu") or {}
    if gpu:
        lines.extend(
            [
                f"- 当前 GPU：{gpu.get('name', '')}",
                f"- 当前显存：{gpu.get('memory_used_mb', '')}/{gpu.get('memory_total_mb', '')} MB",
                "",
            ]
        )
    lines.extend(["## Cases", ""])
    for case in report.get("cases", []):
        lines.append(f"### {case.get('case_id') or case.get('filename')}")
        if case.get("status") == "skipped":
            lines.append(f"- 跳过：{case.get('reason')}")
            lines.append("")
            continue
        labels = ["docling_standard"]
        summary_backend = (report.get("summary") or {}).get("ocr_backend")
        if summary_backend:
            labels.append(str(summary_backend))
        else:
            labels.extend(label for label in ("marker_surya", "paddleocr_vl") if case.get(label))
        for label in labels:
            item = case.get(label)
            if not item:
                continue
            lines.append(
                f"- {label}: {item.get('parse_status_hint')} / "
                f"quality={item.get('quality_score')} / "
                f"chars={item.get('markdown_chars')} / "
                f"keyword_hit_rate={item.get('keyword_hit_rate')} / "
                f"strict={item.get('strict_pass')} / "
                f"buckets={item.get('failure_buckets')} / "
                f"parser={','.join(item.get('parser_chain') or [])}"
            )
            gpu_sampling = item.get("gpu_sampling") or {}
            runtime_metadata = item.get("runtime_metadata") or []
            if gpu_sampling.get("available") or runtime_metadata:
                runtime = runtime_metadata[0] if runtime_metadata else {}
                lines.append(
                    "  - GPU/Runtime: "
                    f"peak_util={gpu_sampling.get('peak_util_percent')}%, "
                    f"peak_mem={gpu_sampling.get('peak_memory_used_mb')} MB, "
                    f"runtime={runtime.get('parser_runtime', '')}, "
                    f"torch={runtime.get('torch', '')}, "
                    f"cuda={runtime.get('torch_cuda_version', '')}"
                )
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a local document-reader fixture benchmark.")
    parser.add_argument("--suite", default="smoke", choices=["smoke", "ocr_heavy", "paddleocr_vl"])
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--case-id", default="", help="Comma-separated case ids for targeted runs.")
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument(
        "--paddle-mode",
        default="",
        choices=["", "worker", "http", "direct"],
        help="Temporarily force PaddleOCR-VL adapter mode for this benchmark.",
    )
    parser.add_argument(
        "--ocr-backend",
        default="marker_surya",
        choices=["marker_surya", "paddleocr_vl"],
        help="OCR-heavy backend to compare against Docling.",
    )
    args = parser.parse_args()

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = (
            ROOT
            / "data"
            / "cache"
            / "document_reader_benchmark"
            / "runs"
            / time.strftime("%Y%m%d_%H%M%S")
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.suite == "smoke":
        report = run_smoke(output_dir)
    else:
        case_ids = {item.strip() for item in args.case_id.split(",") if item.strip()}
        ocr_backend = "paddleocr_vl" if args.suite == "paddleocr_vl" else args.ocr_backend
        report = run_ocr_heavy_benchmark(
            output_dir,
            case_ids=case_ids or None,
            max_cases=args.max_cases,
            ocr_backend=ocr_backend,
            paddle_mode=args.paddle_mode or None,
        )

    json_path = output_dir / f"{args.suite}_benchmark.json"
    md_path = output_dir / f"{args.suite}_benchmark.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown_report(report, md_path)
    eval_dir = ROOT / "data" / "eval_reports"
    eval_dir.mkdir(parents=True, exist_ok=True)
    report_prefix = (
        "document_reader_ocr_heavy"
        if args.suite == "ocr_heavy" and not args.case_id and args.max_cases is None
        else "document_reader_paddleocr_vl_full"
        if args.suite == "paddleocr_vl" and not args.case_id and args.max_cases is None
        else f"document_reader_{args.suite}"
    )
    eval_json_path = eval_dir / f"{report_prefix}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    eval_md_path = eval_json_path.with_suffix(".md")
    eval_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown_report(report, eval_md_path)
    report["report_json_path"] = str(json_path)
    report["report_markdown_path"] = str(md_path)
    report["eval_report_json_path"] = str(eval_json_path)
    report["eval_report_markdown_path"] = str(eval_md_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.suite in {"ocr_heavy", "paddleocr_vl"}:
        return 0 if report["status"] in {"passed", "needs_runtime_or_quality_work"} else 1
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
