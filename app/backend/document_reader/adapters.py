from __future__ import annotations

import base64
from dataclasses import dataclass
from dataclasses import field
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Protocol

from app.backend.core.config import Settings, get_settings
from app.backend.document_reader.schemas import DocumentBlock


@dataclass(frozen=True)
class AdapterAvailability:
    name: str
    available: bool
    reason: str = ""
    enabled: bool = True


@dataclass
class AdapterParseResult:
    parser: str
    markdown: str
    blocks: list[DocumentBlock]
    warnings: list[str]
    quality_score: float
    features: list[str]
    page: int | None = None
    reason: str = ""
    runtime_metadata: dict[str, object] = field(default_factory=dict)
    diagnostics: dict[str, object] = field(default_factory=dict)


def re_split_markdown_blocks(markdown: str) -> list[str]:
    return [part for part in re.split(r"\n\s*\n", markdown) if part.strip()]


def _tail(value: object, *, limit: int = 2000) -> str:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[-limit:]


class DocumentParserAdapter(Protocol):
    name: str

    def available(self) -> AdapterAvailability:
        ...


class DoclingStandardAdapter:
    name = "docling_standard"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def available(self) -> AdapterAvailability:
        if not self.settings.document_reader_enable_docling:
            return AdapterAvailability(
                self.name,
                False,
                "disabled by DOCUMENT_READER_ENABLE_DOCLING=false",
                False,
            )
        try:
            import docling.document_converter  # noqa: F401
        except Exception as exc:  # pragma: no cover - exact import errors vary by install.
            return AdapterAvailability(self.name, False, str(exc))
        return AdapterAvailability(self.name, True)

    def export_markdown(self, path: Path) -> str:
        from docling.document_converter import DocumentConverter

        result = DocumentConverter().convert(str(path))
        return result.document.export_to_markdown()


class DoclingGraniteVlmAdapter:
    name = "docling_granite_vlm"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def available(self) -> AdapterAvailability:
        if not self.settings.document_reader_enable_granite_docling:
            return AdapterAvailability(
                self.name,
                False,
                "disabled by DOCUMENT_READER_ENABLE_GRANITE_DOCLING=false",
                False,
            )
        try:
            import docling.datamodel.pipeline_options  # noqa: F401
            import docling.document_converter  # noqa: F401
            import docling.pipeline.vlm_pipeline  # noqa: F401
        except Exception as exc:  # pragma: no cover - optional provider.
            return AdapterAvailability(self.name, False, str(exc))
        return AdapterAvailability(self.name, True)

    def export_markdown(self, path: Path) -> str:
        from docling.datamodel import vlm_model_specs
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import VlmPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.pipeline.vlm_pipeline import VlmPipeline

        pipeline_options = VlmPipelineOptions(
            vlm_options=vlm_model_specs.GRANITEDOCLING_TRANSFORMERS
        )
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_cls=VlmPipeline,
                    pipeline_options=pipeline_options,
                )
            }
        )
        result = converter.convert(str(path))
        return result.document.export_to_markdown()


class MarkerSuryaAdapter:
    name = "marker_surya"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @property
    def worker_script(self) -> Path:
        return Path("scripts/document_reader/marker_surya_worker.py").resolve()

    @property
    def worker_python(self) -> Path:
        configured = self.settings.document_reader_marker_surya_python.strip()
        if configured:
            return Path(configured)
        runtime_root = (
            Path(self.settings.document_reader_model_cache_dir)
            / "runtimes"
            / "marker_surya"
            / ".venv"
        )
        windows_python = runtime_root / "Scripts" / "python.exe"
        if windows_python.exists():
            return windows_python
        return runtime_root / "bin" / "python"

    def available(self) -> AdapterAvailability:
        if not self.settings.document_reader_enable_marker_surya:
            return AdapterAvailability(
                self.name,
                False,
                "disabled by DOCUMENT_READER_ENABLE_MARKER_SURYA=false",
                False,
            )
        python_path = self.worker_python
        if not python_path.exists():
            return AdapterAvailability(
                self.name,
                False,
                f"Marker/Surya worker Python 不存在: {python_path}",
            )
        if not self.worker_script.exists():
            return AdapterAvailability(
                self.name,
                False,
                f"Marker/Surya worker 脚本不存在: {self.worker_script}",
            )
        try:
            completed = subprocess.run(
                [
                    str(python_path),
                    str(self.worker_script),
                    "--check",
                    "--cache-dir",
                    str(self.settings.document_reader_model_cache_dir),
                    "--device",
                    self.settings.document_reader_marker_surya_device,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
                env=self._worker_env(),
            )
        except Exception as exc:  # pragma: no cover - depends on local runtime.
            return AdapterAvailability(self.name, False, f"worker check failed: {exc}")
        payload = self._json_from_stdout(completed.stdout)
        if completed.returncode != 0 or not payload.get("ok"):
            reason = payload.get("error") or payload.get("versions") or completed.stderr
            return AdapterAvailability(self.name, False, f"worker unavailable: {reason}")
        return AdapterAvailability(self.name, True, "worker")

    def parse_document(
        self,
        path: Path,
        *,
        filename: str,
        page: int | None = 1,
        force_ocr: bool = True,
    ) -> AdapterParseResult:
        worker_python = self.worker_python
        if not worker_python.exists():
            return self._failure_result(
                reason="worker_python_missing",
                page=page,
                warnings=[f"Marker/Surya worker Python 不存在: {worker_python}"],
                attempts=[],
                path=path,
            )
        if not path.exists():
            return self._failure_result(
                reason="input_file_missing",
                page=page,
                warnings=[f"待解析文件不存在: {path}"],
                attempts=[],
                path=path,
            )

        attempts: list[dict[str, object]] = []
        max_attempts = 2
        with tempfile.TemporaryDirectory(prefix="marker-surya-adapter-") as temp_name:
            temp_root = Path(temp_name)
            for attempt in range(1, max_attempts + 1):
                output_dir = temp_root / f"attempt_{attempt}"
                output_dir.mkdir(parents=True, exist_ok=True)
                started = time.perf_counter()
                try:
                    completed = subprocess.run(
                        [
                            str(worker_python),
                            str(self.worker_script),
                            str(path),
                            "--output-dir",
                            str(output_dir),
                            "--filename",
                            filename,
                            "--page",
                            str(page or 1),
                            "--device",
                            self.settings.document_reader_marker_surya_device,
                            "--cache-dir",
                            str(self.settings.document_reader_model_cache_dir),
                            *(["--force-ocr"] if force_ocr else []),
                        ],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=self.settings.document_reader_marker_surya_timeout_seconds,
                        check=False,
                        env=self._worker_env(),
                    )
                except subprocess.TimeoutExpired as exc:
                    attempts.append(
                        self._attempt_record(
                            attempt=attempt,
                            reason="timeout",
                            elapsed_ms=(time.perf_counter() - started) * 1000,
                            stdout=getattr(exc, "stdout", "") or "",
                            stderr=getattr(exc, "stderr", "") or "",
                            timed_out=True,
                        )
                    )
                    return self._failure_result(
                        reason="timeout",
                        page=page,
                        warnings=["Marker/Surya worker 超时。"],
                        attempts=attempts,
                        path=path,
                    )
                except Exception as exc:  # pragma: no cover - depends on local runtime.
                    attempts.append(
                        self._attempt_record(
                            attempt=attempt,
                            reason="subprocess_exception",
                            elapsed_ms=(time.perf_counter() - started) * 1000,
                            exception=str(exc),
                        )
                    )
                    if attempt < max_attempts:
                        continue
                    return self._failure_result(
                        reason="subprocess_exception",
                        page=page,
                        warnings=[f"Marker/Surya worker 启动失败: {exc}"],
                        attempts=attempts,
                        path=path,
                    )

                payload = self._json_from_stdout(completed.stdout)
                elapsed_ms = (time.perf_counter() - started) * 1000
                if not payload:
                    attempts.append(
                        self._attempt_record(
                            attempt=attempt,
                            reason="no_json_stdout",
                            elapsed_ms=elapsed_ms,
                            returncode=completed.returncode,
                            stdout=completed.stdout,
                            stderr=completed.stderr,
                            found_json=False,
                        )
                    )
                    if attempt < max_attempts:
                        continue
                    return self._failure_result(
                        reason="no_json_stdout",
                        page=page,
                        warnings=[
                            "Marker/Surya worker 没有返回 JSON。",
                            _tail(completed.stderr),
                        ],
                        attempts=attempts,
                        path=path,
                    )

                result = self._result_from_payload(payload, path=path, page=page)
                reason = self._result_failure_reason(result, payload=payload, returncode=completed.returncode)
                attempts.append(
                    self._attempt_record(
                        attempt=attempt,
                        reason=reason or "ok",
                        elapsed_ms=elapsed_ms,
                        returncode=completed.returncode,
                        stdout=completed.stdout,
                        stderr=completed.stderr,
                        found_json=True,
                    )
                )
                worker_diag = self._worker_diagnostics(
                    attempts=attempts,
                    final_reason=reason or "ok",
                    successful_retry=attempt > 1 and not reason,
                )
                result.reason = reason
                result.diagnostics = worker_diag
                result.runtime_metadata.setdefault("worker", worker_diag)
                if completed.returncode != 0 and not result.warnings:
                    result.warnings.append(f"Marker/Surya worker exit code={completed.returncode}")
                if not reason:
                    if attempt > 1:
                        result.warnings.append("Marker/Surya worker 首次调用失败，重试后成功。")
                    return result
                if reason == "cuda_unavailable":
                    return result
                if attempt < max_attempts:
                    continue
                return result

        return self._failure_result(
            reason="unknown_worker_failure",
            page=page,
            warnings=["Marker/Surya worker 未产出可用结果。"],
            attempts=attempts,
            path=path,
        )

    def _attempt_record(
        self,
        *,
        attempt: int,
        reason: str,
        elapsed_ms: float,
        returncode: int | None = None,
        stdout: str = "",
        stderr: str = "",
        found_json: bool = False,
        timed_out: bool = False,
        exception: str = "",
    ) -> dict[str, object]:
        return {
            "attempt": attempt,
            "reason": reason,
            "returncode": returncode,
            "elapsed_ms": round(elapsed_ms, 2),
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
            "found_json": found_json,
            "timed_out": timed_out,
            "exception": exception,
        }

    def _worker_diagnostics(
        self,
        *,
        attempts: list[dict[str, object]],
        final_reason: str,
        successful_retry: bool = False,
    ) -> dict[str, object]:
        return {
            "worker_python": str(self.worker_python),
            "worker_script": str(self.worker_script),
            "requested_device": self.settings.document_reader_marker_surya_device,
            "attempt_count": len(attempts),
            "attempts": attempts,
            "final_reason": final_reason,
            "successful_retry": successful_retry,
            "runtime_check_summary": self._runtime_check_summary() if final_reason != "ok" else {},
        }

    def _runtime_check_summary(self) -> dict[str, object]:
        python_path = self.worker_python
        if not python_path.exists() or not self.worker_script.exists():
            return {
                "ok": False,
                "reason": "worker_runtime_missing",
                "worker_python_exists": python_path.exists(),
                "worker_script_exists": self.worker_script.exists(),
            }
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                [
                    str(python_path),
                    str(self.worker_script),
                    "--check",
                    "--cache-dir",
                    str(self.settings.document_reader_model_cache_dir),
                    "--device",
                    self.settings.document_reader_marker_surya_device,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
                env=self._worker_env(),
            )
        except Exception as exc:  # pragma: no cover - depends on local runtime.
            return {
                "ok": False,
                "reason": "runtime_check_exception",
                "error": str(exc),
            }
        payload = self._json_from_stdout(completed.stdout)
        return {
            "ok": bool(payload.get("ok")) and completed.returncode == 0,
            "returncode": completed.returncode,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "versions": payload.get("versions") or payload.get("runtime") or {},
            "error": payload.get("error") or "",
            "stdout_tail": _tail(completed.stdout),
            "stderr_tail": _tail(completed.stderr),
        }

    def _result_failure_reason(
        self,
        result: AdapterParseResult,
        *,
        payload: dict,
        returncode: int,
    ) -> str:
        error_text = " ".join(str(item) for item in [payload.get("error"), *result.warnings]).lower()
        if "cuda" in error_text and (
            "unavailable" in error_text
            or "not available" in error_text
            or "is_available() is false" in error_text
            or "is_available false" in error_text
            or "cuda_available" in error_text
            or "不可用" in error_text
        ):
            return "cuda_unavailable"
        if not payload.get("ok"):
            return "worker_payload_error"
        if returncode != 0:
            return "nonzero_exit"
        if not result.markdown.strip():
            return "empty_markdown"
        if not result.blocks:
            return "empty_blocks"
        return ""

    def _failure_result(
        self,
        *,
        reason: str,
        page: int | None,
        warnings: list[str],
        attempts: list[dict[str, object]],
        path: Path,
    ) -> AdapterParseResult:
        diagnostics = self._worker_diagnostics(
            attempts=attempts,
            final_reason=reason,
            successful_retry=False,
        )
        filtered_warnings = [warning for warning in warnings if warning]
        return AdapterParseResult(
            parser=self.name,
            markdown="",
            blocks=[],
            warnings=filtered_warnings,
            quality_score=0.0,
            features=["ocr", "layout", "image"],
            page=page,
            reason=reason,
            runtime_metadata={
                "parser_runtime": "marker_surya_worker",
                "source_file": str(path),
                "worker": diagnostics,
            },
            diagnostics=diagnostics,
        )

    def _worker_env(self) -> dict[str, str]:
        env = os.environ.copy()
        cache_dir = Path(self.settings.document_reader_model_cache_dir)
        defaults = {
            "HF_HOME": cache_dir / "huggingface",
            "HF_HUB_CACHE": cache_dir / "huggingface" / "hub",
            "HUGGINGFACE_HUB_CACHE": cache_dir / "huggingface" / "hub",
            "TRANSFORMERS_CACHE": cache_dir / "huggingface" / "hub",
            "TORCH_HOME": cache_dir / "torch",
            "XDG_CACHE_HOME": cache_dir / "xdg",
        }
        for key, value in defaults.items():
            env.setdefault(key, str(value))
        device = self.settings.document_reader_marker_surya_device
        if device and device != "auto":
            env["TORCH_DEVICE"] = device
        return env

    def _json_from_stdout(self, stdout: str) -> dict:
        for line in reversed(stdout.splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        return {}

    def _result_from_payload(
        self,
        payload: dict,
        *,
        path: Path,
        page: int | None,
    ) -> AdapterParseResult:
        blocks: list[DocumentBlock] = []
        for block_payload in payload.get("blocks") or []:
            try:
                blocks.append(DocumentBlock.model_validate(block_payload))
            except Exception:
                continue
        warnings = [str(item) for item in payload.get("warnings") or []]
        if not payload.get("ok"):
            error = payload.get("error") or "Marker/Surya worker 未产出可用结果。"
            warnings.append(str(error))
        markdown = str(payload.get("markdown") or "")
        features = [str(item) for item in payload.get("features") or ["ocr", "layout"]]
        quality_score = float(payload.get("quality_score") or (0.78 if markdown else 0.0))
        runtime_metadata = dict(payload.get("runtime") or {})
        for block in blocks:
            block.metadata.setdefault("source_file", str(path))
            block.metadata.setdefault("parser", self.name)
            if runtime_metadata:
                block.metadata.setdefault("runtime", runtime_metadata)
                block.metadata.setdefault("parser_runtime", runtime_metadata.get("parser_runtime"))
        return AdapterParseResult(
            parser=self.name,
            markdown=markdown,
            blocks=blocks,
            warnings=warnings,
            quality_score=quality_score,
            features=features,
            page=page,
            runtime_metadata=runtime_metadata,
        )


class PaddleOcrVlAdapter:
    name = "paddleocr_vl"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    @property
    def mode(self) -> str:
        mode = (self.settings.document_reader_paddleocr_vl_mode or "worker").lower()
        return mode if mode in {"worker", "http", "direct"} else "worker"

    @property
    def worker_script(self) -> Path:
        return Path("scripts/document_reader/paddleocr_vl_worker.py").resolve()

    @property
    def worker_python(self) -> Path:
        configured = self.settings.document_reader_paddleocr_vl_python.strip()
        if configured:
            return Path(configured)
        return (
            Path(self.settings.document_reader_model_cache_dir)
            / "runtimes"
            / "paddleocr_vl"
            / ".venv"
            / "Scripts"
            / "python.exe"
        )

    def available(self) -> AdapterAvailability:
        if not self.settings.document_reader_enable_paddleocr_vl:
            return AdapterAvailability(
                self.name,
                False,
                "disabled by DOCUMENT_READER_ENABLE_PADDLEOCR_VL=false",
                False,
            )
        if self.mode == "worker":
            return self._available_worker()
        if self.mode == "http":
            endpoint = self.settings.document_reader_paddleocr_vl_endpoint.strip()
            if not endpoint:
                return AdapterAvailability(
                    self.name,
                    False,
                    "DOCUMENT_READER_PADDLEOCR_VL_ENDPOINT is empty",
                )
            try:
                import httpx

                response = httpx.get(endpoint.rstrip("/") + "/docs", timeout=5)
                if response.status_code >= 500:
                    return AdapterAvailability(
                        self.name,
                        False,
                        f"HTTP endpoint returned {response.status_code}",
                    )
            except Exception as exc:
                return AdapterAvailability(self.name, False, f"HTTP endpoint unavailable: {exc}")
            return AdapterAvailability(self.name, True, "http endpoint reachable")
        try:
            from paddleocr import PaddleOCRVL  # noqa: F401
        except Exception as exc:  # pragma: no cover - optional provider.
            return AdapterAvailability(self.name, False, str(exc))
        return AdapterAvailability(self.name, True)

    def _available_worker(self) -> AdapterAvailability:
        python_path = self.worker_python
        if not python_path.exists():
            return AdapterAvailability(
                self.name,
                False,
                f"PaddleOCR-VL worker Python 不存在: {python_path}",
            )
        if not self.worker_script.exists():
            return AdapterAvailability(
                self.name,
                False,
                f"PaddleOCR-VL worker 脚本不存在: {self.worker_script}",
            )
        try:
            completed = subprocess.run(
                [
                    str(python_path),
                    str(self.worker_script),
                    "--check",
                    "--cache-dir",
                    str(self.settings.document_reader_model_cache_dir),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
                env=self._worker_env(),
            )
        except Exception as exc:  # pragma: no cover - depends on local runtime.
            return AdapterAvailability(self.name, False, f"worker check failed: {exc}")
        payload = self._json_from_stdout(completed.stdout)
        if completed.returncode != 0 or not payload.get("ok"):
            reason = payload.get("error") or payload.get("versions") or completed.stderr
            return AdapterAvailability(self.name, False, f"worker unavailable: {reason}")
        return AdapterAvailability(self.name, True, "worker")

    def parse_image(self, path: Path, *, filename: str, page: int | None = 1) -> AdapterParseResult:
        if self.mode == "worker":
            return self._parse_image_worker(path, filename=filename, page=page)
        if self.mode == "http":
            return self._parse_image_http(path, filename=filename, page=page)
        return self._parse_image_direct(path, filename=filename, page=page)

    def _worker_env(self) -> dict[str, str]:
        env = os.environ.copy()
        cache_dir = Path(self.settings.document_reader_model_cache_dir)
        defaults = {
            "PADDLE_HOME": cache_dir / "paddle",
            "HF_HOME": cache_dir / "huggingface",
            "HF_HUB_CACHE": cache_dir / "huggingface" / "hub",
            "HUGGINGFACE_HUB_CACHE": cache_dir / "huggingface" / "hub",
            "TRANSFORMERS_CACHE": cache_dir / "huggingface" / "hub",
            "MODELSCOPE_CACHE": cache_dir / "modelscope",
            "XDG_CACHE_HOME": cache_dir / "xdg",
        }
        for key, value in defaults.items():
            env.setdefault(key, str(value))
        return env

    def _json_from_stdout(self, stdout: str) -> dict:
        for line in reversed(stdout.splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        return {}

    def _result_from_payload(
        self,
        payload: dict,
        *,
        path: Path,
        page: int | None,
    ) -> AdapterParseResult:
        blocks: list[DocumentBlock] = []
        for block_payload in payload.get("blocks") or []:
            try:
                blocks.append(DocumentBlock.model_validate(block_payload))
            except Exception:
                continue
        warnings = [str(item) for item in payload.get("warnings") or []]
        if not payload.get("ok"):
            error = payload.get("error") or "PaddleOCR-VL worker 未产出可用结果。"
            warnings.append(str(error))
        markdown = str(payload.get("markdown") or "")
        features = [str(item) for item in payload.get("features") or ["ocr", "vlm", "image"]]
        quality_score = float(payload.get("quality_score") or (0.75 if markdown else 0.0))
        for block in blocks:
            block.metadata.setdefault("source_image", str(path))
            block.metadata.setdefault("parser", self.name)
        return AdapterParseResult(
            parser=self.name,
            markdown=markdown,
            blocks=blocks,
            warnings=warnings,
            quality_score=quality_score,
            features=features,
            page=page,
        )

    def _parse_image_worker(
        self,
        path: Path,
        *,
        filename: str,
        page: int | None = 1,
    ) -> AdapterParseResult:
        with tempfile.TemporaryDirectory(prefix="paddleocr-vl-adapter-") as temp_name:
            output_dir = Path(temp_name)
            try:
                completed = subprocess.run(
                    [
                        str(self.worker_python),
                        str(self.worker_script),
                        str(path),
                        "--output-dir",
                        str(output_dir),
                        "--filename",
                        filename,
                        "--page",
                        str(page or 1),
                        "--device",
                        self.settings.document_reader_paddleocr_vl_device,
                        "--cache-dir",
                        str(self.settings.document_reader_model_cache_dir),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.settings.document_reader_paddleocr_vl_timeout_seconds,
                    check=False,
                    env=self._worker_env(),
                )
            except subprocess.TimeoutExpired:
                return AdapterParseResult(
                    parser=self.name,
                    markdown="",
                    blocks=[],
                    warnings=["PaddleOCR-VL worker 超时。"],
                    quality_score=0.0,
                    features=["ocr", "vlm", "image"],
                    page=page,
                )
            except Exception as exc:  # pragma: no cover - depends on local runtime.
                return AdapterParseResult(
                    parser=self.name,
                    markdown="",
                    blocks=[],
                    warnings=[f"PaddleOCR-VL worker 启动失败: {exc}"],
                    quality_score=0.0,
                    features=["ocr", "vlm", "image"],
                    page=page,
                )
            payload = self._json_from_stdout(completed.stdout)
            if not payload:
                return AdapterParseResult(
                    parser=self.name,
                    markdown="",
                    blocks=[],
                    warnings=[
                        "PaddleOCR-VL worker 没有返回 JSON。",
                        completed.stderr.strip(),
                    ],
                    quality_score=0.0,
                    features=["ocr", "vlm", "image"],
                    page=page,
                )
            result = self._result_from_payload(payload, path=path, page=page)
            if completed.returncode != 0 and not result.warnings:
                result.warnings.append(f"PaddleOCR-VL worker exit code={completed.returncode}")
            return result

    def _parse_image_http(
        self,
        path: Path,
        *,
        filename: str,
        page: int | None = 1,
    ) -> AdapterParseResult:
        endpoint = self.settings.document_reader_paddleocr_vl_endpoint.strip()
        if not endpoint:
            return AdapterParseResult(
                parser=self.name,
                markdown="",
                blocks=[],
                warnings=["PaddleOCR-VL HTTP endpoint 未配置。"],
                quality_score=0.0,
                features=["ocr", "vlm", "image"],
                page=page,
            )
        try:
            import httpx

            base_url = endpoint.rstrip("/")
            encoded_file = base64.b64encode(path.read_bytes()).decode("ascii")
            file_type = self._official_file_type(path)
            layout_payload = {
                "file": encoded_file,
                "fileType": file_type,
                "visualize": False,
            }
            layout_response = httpx.post(
                f"{base_url}/layout-parsing",
                json=layout_payload,
                timeout=self.settings.document_reader_paddleocr_vl_timeout_seconds,
            )
            layout_response.raise_for_status()
            layout_payload_json = layout_response.json()
            layout_result = layout_payload_json.get("result") or layout_payload_json
            layout_pages = list(layout_result.get("layoutParsingResults") or [])
            if not layout_pages:
                return AdapterParseResult(
                    parser=self.name,
                    markdown="",
                    blocks=[],
                    warnings=["PaddleOCR-VL HTTP response missing layoutParsingResults."],
                    quality_score=0.0,
                    features=["ocr", "vlm", "http"],
                    page=page,
                )

            pages = [
                {
                    "prunedResult": item.get("prunedResult") or {},
                    "markdownImages": (item.get("markdown") or {}).get("images"),
                }
                for item in layout_pages
            ]
            restructure_payload = {
                "pages": pages,
                "concatenatePages": True,
                "prettifyMarkdown": True,
            }
            restructure_response = httpx.post(
                f"{base_url}/restructure-pages",
                json=restructure_payload,
                timeout=self.settings.document_reader_paddleocr_vl_timeout_seconds,
            )
            restructure_response.raise_for_status()
            restructure_json = restructure_response.json()
            payload = self._official_http_payload_to_worker_payload(
                layout_payload_json,
                restructure_json,
                path=path,
                filename=filename,
                page=page,
            )
        except Exception as exc:  # pragma: no cover - optional deployment mode.
            return AdapterParseResult(
                parser=self.name,
                markdown="",
                blocks=[],
                warnings=[f"PaddleOCR-VL HTTP worker 调用失败: {exc}"],
                quality_score=0.0,
                features=["ocr", "vlm", "image"],
                page=page,
            )
        return self._result_from_payload(payload, path=path, page=page)

    def _official_file_type(self, path: Path) -> int:
        # Official PaddleOCR-VL service uses 1 for images and 0 for PDFs.
        return 0 if path.suffix.lower() == ".pdf" else 1

    def _official_http_payload_to_worker_payload(
        self,
        layout_payload: dict,
        restructure_payload: dict,
        *,
        path: Path,
        filename: str,
        page: int | None,
    ) -> dict:
        layout_result = layout_payload.get("result") or layout_payload
        restructure_result = restructure_payload.get("result") or restructure_payload
        layout_pages = list(layout_result.get("layoutParsingResults") or [])
        restructured_pages = list(restructure_result.get("layoutParsingResults") or [])
        source_pages = restructured_pages or layout_pages
        markdown_parts: list[str] = []
        blocks: list[dict] = []
        warnings: list[str] = []
        for index, page_payload in enumerate(source_pages, start=1):
            markdown_obj = page_payload.get("markdown") or {}
            page_markdown = ""
            if isinstance(markdown_obj, dict):
                page_markdown = str(markdown_obj.get("text") or "")
            elif isinstance(markdown_obj, str):
                page_markdown = markdown_obj
            if not page_markdown:
                page_markdown = self._text_from_pruned_result(page_payload.get("prunedResult"))
            page_markdown = page_markdown.strip()
            if page_markdown:
                markdown_parts.append(page_markdown)
                blocks.extend(
                    self._blocks_from_markdown_lines(
                        page_markdown,
                        page=index if path.suffix.lower() == ".pdf" else page,
                        source_path=path,
                    )
                )

        markdown = "\n\n".join(markdown_parts).strip()
        if not markdown:
            warnings.append("PaddleOCR-VL HTTP returned no markdown text.")
        quality = 0.9 if markdown else 0.0
        features = ["ocr", "vlm", "http"]
        if path.suffix.lower() == ".pdf":
            features.append("pdf")
        else:
            features.append("image")
        return {
            "ok": bool(markdown),
            "markdown": f"# {filename}\n\n{markdown}\n" if markdown else "",
            "blocks": blocks,
            "warnings": warnings,
            "quality_score": quality,
            "features": features,
            "versions": {
                "mode": "http",
                "endpoint": self.settings.document_reader_paddleocr_vl_endpoint,
                "layout_pages": len(layout_pages),
                "restructured_pages": len(restructured_pages),
            },
        }

    def _text_from_pruned_result(self, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        texts: list[str] = []
        if isinstance(value, dict):
            for key in ("text", "html", "markdown"):
                nested = value.get(key)
                if isinstance(nested, str) and nested.strip():
                    texts.append(nested.strip())
            rec_texts = value.get("rec_texts") or value.get("texts")
            if isinstance(rec_texts, list):
                texts.extend(str(item).strip() for item in rec_texts if str(item).strip())
            for nested in value.values():
                if isinstance(nested, (dict, list)):
                    nested_text = self._text_from_pruned_result(nested)
                    if nested_text:
                        texts.append(nested_text)
        elif isinstance(value, list):
            for item in value:
                nested_text = self._text_from_pruned_result(item)
                if nested_text:
                    texts.append(nested_text)
        seen: set[str] = set()
        deduped: list[str] = []
        for text in texts:
            normalized = text.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduped.append(normalized)
        return "\n".join(deduped)

    def _blocks_from_markdown_lines(
        self,
        markdown: str,
        *,
        page: int | None,
        source_path: Path,
    ) -> list[dict]:
        blocks: list[dict] = []
        block_index = 1
        for raw_part in re_split_markdown_blocks(markdown):
            text = raw_part.strip()
            if not text:
                continue
            block_type = "paragraph"
            if text.startswith("#"):
                block_type = "heading"
            elif "|" in text and "\n" in text:
                block_type = "table"
            elif "$" in text or "\\[" in text or "\\(" in text:
                block_type = "formula"
            blocks.append(
                {
                    "block_id": f"paddleocr_vl_http_{block_index:04d}",
                    "block_type": block_type,
                    "text": text,
                    "page": page,
                    "confidence": 0.86,
                    "metadata": {
                        "parser": self.name,
                        "source_image": str(source_path),
                        "mode": "http",
                    },
                }
            )
            block_index += 1
        return blocks

    def _parse_image_direct(
        self,
        path: Path,
        *,
        filename: str,
        page: int | None = 1,
    ) -> AdapterParseResult:
        try:
            from paddleocr import PaddleOCRVL

            pipeline = PaddleOCRVL()
            output = pipeline.predict(str(path))
            markdown_parts: list[str] = []
            with tempfile.TemporaryDirectory(prefix="paddleocr-vl-") as temp_dir:
                temp_path = Path(temp_dir)
                for result in output:
                    try:
                        result.save_to_markdown(save_path=temp_path)
                    except Exception:
                        pass
                for markdown_path in sorted(temp_path.glob("*.md")):
                    markdown_parts.append(
                        markdown_path.read_text(encoding="utf-8", errors="replace")
                    )
        except Exception as exc:  # pragma: no cover - depends on installed PaddleOCR version.
            return AdapterParseResult(
                parser=self.name,
                markdown="",
                blocks=[],
                warnings=[f"PaddleOCR-VL/OCR 解析失败: {exc}"],
                quality_score=0.0,
                features=["ocr", "image"],
                page=page,
            )
        text = "\n\n".join(part.strip() for part in markdown_parts if part.strip()).strip()
        if not text:
            return AdapterParseResult(
                parser=self.name,
                markdown="",
                blocks=[],
                warnings=["PaddleOCR 已运行，但未识别到可用文字。"],
                quality_score=0.2,
                features=["ocr", "image"],
                page=page,
            )
        block = DocumentBlock(
            block_id="block_0001",
            block_type="paragraph",
            text=text,
            page=page,
            confidence=0.75,
            metadata={"source_image": str(path), "parser": self.name},
        )
        return AdapterParseResult(
            parser=self.name,
            markdown=f"# {filename}\n\n{text}\n",
            blocks=[block],
            warnings=[],
            quality_score=0.75,
            features=["ocr", "image", "multilingual"],
            page=page,
        )


class ImportOnlyAdapter:
    def __init__(self, name: str, import_name: str, enabled: bool, env_name: str):
        self.name = name
        self.import_name = import_name
        self.enabled = enabled
        self.env_name = env_name

    def available(self) -> AdapterAvailability:
        if not self.enabled:
            return AdapterAvailability(self.name, False, f"disabled by {self.env_name}=false", False)
        try:
            __import__(self.import_name)
        except Exception as exc:  # pragma: no cover - optional providers are environment-specific.
            return AdapterAvailability(self.name, False, str(exc))
        return AdapterAvailability(self.name, True)


def parser_registry(settings: Settings | None = None) -> tuple[DocumentParserAdapter, ...]:
    settings = settings or get_settings()
    return (
        DoclingStandardAdapter(settings),
        DoclingGraniteVlmAdapter(settings),
        MarkerSuryaAdapter(settings),
        PaddleOcrVlAdapter(settings),
        ImportOnlyAdapter(
            "mineru",
            "mineru",
            settings.document_reader_enable_mineru,
            "DOCUMENT_READER_ENABLE_MINERU",
        ),
        ImportOnlyAdapter(
            "olmocr",
            "olmocr",
            settings.document_reader_enable_olmocr,
            "DOCUMENT_READER_ENABLE_OLMOCR",
        ),
    )
