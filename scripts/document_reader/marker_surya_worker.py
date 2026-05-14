from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import traceback
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = ROOT / "models" / "document_reader"


def _configure_cache(cache_dir: Path, device: str = "auto") -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    defaults = {
        "HF_HOME": cache_dir / "huggingface",
        "HF_HUB_CACHE": cache_dir / "huggingface" / "hub",
        "HUGGINGFACE_HUB_CACHE": cache_dir / "huggingface" / "hub",
        "TRANSFORMERS_CACHE": cache_dir / "huggingface" / "hub",
        "TORCH_HOME": cache_dir / "torch",
        "XDG_CACHE_HOME": cache_dir / "xdg",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, str(value))
    if device and device != "auto":
        os.environ["TORCH_DEVICE"] = device


def _torch_runtime(device: str = "auto") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "requested_device": device,
        "parser_runtime": "marker_surya_cpu",
        "cuda_available": False,
    }
    try:
        import torch  # type: ignore
    except Exception as exc:
        payload["torch_error"] = str(exc)
        return payload
    payload["torch"] = getattr(torch, "__version__", "")
    payload["torch_cuda_version"] = getattr(torch.version, "cuda", None)
    payload["cuda_available"] = bool(torch.cuda.is_available())
    payload["cuda_device_count"] = int(torch.cuda.device_count()) if payload["cuda_available"] else 0
    if payload["cuda_available"]:
        payload["parser_runtime"] = "marker_surya_cuda"
        payload["cuda_device_name"] = torch.cuda.get_device_name(0)
        payload["cuda_device_capability"] = list(torch.cuda.get_device_capability(0))
        try:
            payload["cuda_memory_allocated_mb"] = round(torch.cuda.memory_allocated(0) / 1048576, 2)
            payload["cuda_memory_reserved_mb"] = round(torch.cuda.memory_reserved(0) / 1048576, 2)
            payload["cuda_max_memory_allocated_mb"] = round(torch.cuda.max_memory_allocated(0) / 1048576, 2)
            payload["cuda_max_memory_reserved_mb"] = round(torch.cuda.max_memory_reserved(0) / 1048576, 2)
        except Exception:
            pass
    return payload


def _cuda_required_error(device: str) -> str:
    runtime = _torch_runtime(device)
    if device == "cuda" and not runtime.get("cuda_available"):
        return (
            "Marker/Surya 被要求使用 CUDA，但当前 runtime 的 torch.cuda.is_available() 为 False。"
            f" torch={runtime.get('torch') or runtime.get('torch_error')}; "
            f"torch_cuda={runtime.get('torch_cuda_version')}"
        )
    return ""


def _json_line(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def _versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    try:
        import marker  # type: ignore

        versions["marker"] = getattr(marker, "__version__", "")
    except Exception as exc:
        versions["marker_error"] = str(exc)
    try:
        import surya  # type: ignore

        versions["surya"] = getattr(surya, "__version__", "")
    except Exception as exc:
        versions["surya_error"] = str(exc)
    runtime = _torch_runtime(os.environ.get("TORCH_DEVICE", "auto"))
    for key, value in runtime.items():
        versions[str(key)] = str(value)
    marker_single = shutil.which("marker_single")
    if marker_single:
        versions["marker_single"] = marker_single
    return versions


def _block_type(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("|") and "\n|" in stripped:
        return "table"
    if re.search(r"(\$[^$]+\$|\\frac|\\sum|\\int|[=≈≤≥])", stripped):
        return "formula" if len(stripped) < 800 else "paragraph"
    if stripped.startswith("```"):
        return "code"
    if stripped.startswith("#"):
        return "heading"
    return "paragraph"


def _markdown_to_blocks(markdown: str, *, page: int | None, input_path: Path) -> list[dict[str, Any]]:
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", markdown) if chunk.strip()]
    blocks: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        blocks.append(
            {
                "block_id": f"marker_surya_{index:04d}",
                "block_type": _block_type(chunk),
                "text": chunk,
                "page": page,
                "confidence": 0.78,
                "metadata": {
                    "parser": "marker_surya",
                    "source_file": str(input_path),
                },
            }
        )
    return blocks


def _quality_score(markdown: str, blocks: list[dict[str, Any]]) -> float:
    text_chars = len(markdown.strip())
    if text_chars <= 0:
        return 0.0
    mojibake_tokens = ("\ufffd", "\u6d63", "\u93c2", "\u9225", "\u951b")
    mojibake_hits = sum(markdown.count(token) for token in mojibake_tokens)
    table_bonus = 0.04 if any(block.get("block_type") == "table" for block in blocks) else 0
    formula_bonus = 0.03 if any(block.get("block_type") == "formula" for block in blocks) else 0
    score = 0.48 + min(text_chars / 4500, 0.34) + min(len(blocks) / 50, 0.12)
    score += table_bonus + formula_bonus
    score -= min(mojibake_hits * 0.03, 0.25)
    return max(0.0, min(0.95, round(score, 4)))


def _read_markdown_outputs(output_dir: Path) -> str:
    parts: list[str] = []
    for markdown_path in sorted(output_dir.rglob("*.md")):
        try:
            text = markdown_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if text:
            parts.append(text)
    if parts:
        return "\n\n".join(parts)
    for json_path in sorted(output_dir.rglob("*.json")):
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        text = _text_from_json(payload)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _text_from_json(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value if len(value.strip()) > 20 else ""
    texts: list[str] = []
    if isinstance(value, dict):
        for key in ("markdown", "text", "html", "content"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                texts.append(nested.strip())
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                nested_text = _text_from_json(nested)
                if nested_text:
                    texts.append(nested_text)
    elif isinstance(value, list):
        for item in value:
            nested_text = _text_from_json(item)
            if nested_text:
                texts.append(nested_text)
    return "\n".join(dict.fromkeys(texts))


def _run_marker_cli(
    input_path: Path,
    output_dir: Path,
    *,
    force_ocr: bool,
) -> tuple[bool, str, list[str]]:
    marker_single = shutil.which("marker_single")
    if not marker_single:
        return False, "", ["marker_single 命令不存在。"]
    command = [
        marker_single,
        str(input_path),
        "--output_dir",
        str(output_dir),
        "--output_format",
        "markdown",
    ]
    if force_ocr:
        command.append("--force_ocr")
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=None,
        check=False,
    )
    warnings: list[str] = []
    if completed.returncode != 0:
        warnings.append(f"marker_single exit code={completed.returncode}: {completed.stderr.strip()}")
        return False, "", warnings
    markdown = _read_markdown_outputs(output_dir).strip()
    if not markdown:
        warnings.append("marker_single 已运行，但没有找到 Markdown/JSON 输出。")
        return False, "", warnings
    return True, markdown, warnings


def _run_marker_python(input_path: Path, *, force_ocr: bool) -> tuple[bool, str, list[str]]:
    try:
        from marker.config.parser import ConfigParser  # type: ignore
        from marker.converters.pdf import PdfConverter  # type: ignore
        from marker.models import create_model_dict  # type: ignore
        from marker.output import text_from_rendered  # type: ignore
    except Exception as exc:
        return False, "", [f"Marker Python API 不可用: {exc}"]
    config: dict[str, Any] = {"output_format": "markdown"}
    if force_ocr:
        config["force_ocr"] = True
    try:
        parser = ConfigParser(config)
        converter = PdfConverter(
            config=parser.generate_config_dict(),
            artifact_dict=create_model_dict(),
            processor_list=parser.get_processors(),
            renderer=parser.get_renderer(),
            llm_service=parser.get_llm_service(),
        )
        rendered = converter(str(input_path))
        text, _, _ = text_from_rendered(rendered)
    except Exception as exc:
        return False, "", [f"Marker Python API 解析失败: {exc}"]
    return bool(str(text).strip()), str(text).strip(), []


def parse_document(
    input_path: Path,
    output_dir: Path,
    filename: str,
    device: str,
    page: int | None,
    *,
    cache_dir: Path,
    force_ocr: bool,
) -> dict[str, Any]:
    _configure_cache(cache_dir, device)
    cuda_error = _cuda_required_error(device)
    if cuda_error:
        return {
            "ok": False,
            "parser": "marker_surya",
            "markdown": "",
            "blocks": [],
            "warnings": [cuda_error],
            "quality_score": 0.0,
            "features": ["ocr", "layout", "image"],
            "page": page,
            "device": device,
            "force_ocr": force_ocr,
            "runtime": _torch_runtime(device),
            "versions": _versions(),
        }
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats(0)
    except Exception:
        pass
    output_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="marker-surya-worker-") as temp_name:
        temp_dir = Path(temp_name)
        ok, markdown_body, cli_warnings = _run_marker_cli(
            input_path,
            temp_dir,
            force_ocr=force_ocr,
        )
        warnings.extend(cli_warnings)
        if not ok:
            ok, markdown_body, api_warnings = _run_marker_python(input_path, force_ocr=force_ocr)
            warnings.extend(api_warnings)
        markdown_body = markdown_body.strip()
        markdown = f"# {filename}\n\n{markdown_body}\n" if markdown_body else ""
        blocks = _markdown_to_blocks(markdown, page=page, input_path=input_path)
        markdown_path = output_dir / "marker_surya.md"
        blocks_path = output_dir / "marker_surya.blocks.json"
        structure_path = output_dir / "marker_surya.structured_summary.json"
        markdown_path.write_text(markdown, encoding="utf-8")
        blocks_path.write_text(json.dumps(blocks, ensure_ascii=False, indent=2), encoding="utf-8")
        structured_summary = _summarize_structured_outputs(temp_dir)
        structure_path.write_text(
            json.dumps(structured_summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        runtime = _torch_runtime(device)
        for block in blocks:
            block.setdefault("metadata", {})
            block["metadata"]["parser_runtime"] = runtime.get("parser_runtime")
            block["metadata"]["runtime"] = runtime
        if not markdown:
            warnings.append("Marker/Surya 已运行，但没有产出可用 Markdown 文本。")
        return {
            "ok": bool(markdown.strip()),
            "parser": "marker_surya",
            "markdown": markdown,
            "markdown_path": str(markdown_path),
            "blocks": blocks,
            "blocks_path": str(blocks_path),
            "warnings": warnings,
            "quality_score": _quality_score(markdown, blocks),
            "features": ["ocr", "layout", "table", "formula", "image", "multilingual"],
            "page": page,
            "device": device,
            "force_ocr": force_ocr,
            "runtime": runtime,
            "structured_output_summary_path": str(structure_path),
            "structured_outputs": structured_summary,
            "versions": _versions(),
        }


def _summarize_structured_outputs(output_dir: Path) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    for json_path in sorted(output_dir.rglob("*.json"))[:12]:
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            summaries.append({"path": str(json_path), "error": str(exc)})
            continue
        keys: list[str] = []
        if isinstance(payload, dict):
            keys = [str(key) for key in list(payload.keys())[:20]]
        text = _text_from_json(payload)
        summaries.append(
            {
                "path": str(json_path),
                "top_level_type": type(payload).__name__,
                "top_level_keys": keys,
                "text_chars": len(text),
            }
        )
    return {"json_output_count": len(summaries), "json_outputs": summaries}


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated Marker/Surya document-reader worker.")
    parser.add_argument("input_path", nargs="?", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--filename", default="")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--force-ocr", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    _configure_cache(cache_dir, args.device)
    if args.check:
        versions = _versions()
        cuda_error = _cuda_required_error(args.device)
        ok = ("marker_error" not in versions or bool(versions.get("marker_single"))) and not cuda_error
        _json_line(
            {
                "ok": ok,
                "parser": "marker_surya",
                "mode": "worker",
                "versions": versions,
                "runtime": _torch_runtime(args.device),
                "error": cuda_error,
                "cache_dir": str(cache_dir),
            }
        )
        return 0 if ok else 1

    input_path = Path(args.input_path)
    output_dir = Path(args.output_dir)
    if not input_path.exists():
        _json_line({"ok": False, "parser": "marker_surya", "error": f"文件不存在: {input_path}"})
        return 2
    if not args.output_dir:
        _json_line({"ok": False, "parser": "marker_surya", "error": "缺少 --output-dir"})
        return 2
    filename = args.filename or input_path.name
    try:
        payload = parse_document(
            input_path,
            output_dir,
            filename,
            args.device,
            args.page,
            cache_dir=cache_dir,
            force_ocr=args.force_ocr,
        )
        _json_line(payload)
        return 0 if payload.get("ok") else 3
    except Exception as exc:  # pragma: no cover - depends on optional runtime.
        payload = {
            "ok": False,
            "parser": "marker_surya",
            "error": str(exc),
            "traceback": traceback.format_exc() if args.debug else "",
            "versions": _versions(),
        }
        _json_line(payload)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
