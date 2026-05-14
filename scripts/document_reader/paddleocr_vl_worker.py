from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import tempfile
import traceback
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = ROOT / "models" / "document_reader"


def _configure_cache(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
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
        os.environ.setdefault(key, str(value))


def _json_line(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def _paddle_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    try:
        import paddle  # type: ignore

        versions["paddle"] = getattr(paddle, "__version__", "")
    except Exception as exc:
        versions["paddle_error"] = str(exc)
    try:
        import paddleocr  # type: ignore

        versions["paddleocr"] = getattr(paddleocr, "__version__", "")
    except Exception as exc:
        versions["paddleocr_error"] = str(exc)
    return versions


def _build_pipeline(device: str):
    from paddleocr import PaddleOCRVL  # type: ignore

    if device and device != "auto":
        for kwargs in ({"device": device}, {"device_name": device}):
            try:
                return PaddleOCRVL(**kwargs)
            except TypeError:
                continue
    return PaddleOCRVL()


def _extract_markdown_from_result(result: Any, output_dir: Path) -> list[str]:
    parts: list[str] = []
    try:
        result.save_to_markdown(save_path=output_dir)
    except Exception:
        pass
    try:
        result.save_to_json(save_path=output_dir)
    except Exception:
        pass
    if isinstance(result, dict):
        for key in ("markdown", "md", "text", "content"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value)
    for attr in ("markdown", "md", "text", "content"):
        value = getattr(result, attr, None)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    return parts


def _read_generated_markdown(output_dir: Path) -> list[str]:
    parts: list[str] = []
    for markdown_path in sorted(output_dir.rglob("*.md")):
        try:
            text = markdown_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if text:
            parts.append(text)
    return parts


def _block_type(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("|") and "\n|" in stripped:
        return "table"
    if re.search(r"(\$[^$]+\$|\\frac|\\sum|\\int|[=≈≤≥])", stripped):
        return "formula" if len(stripped) < 500 else "paragraph"
    if stripped.startswith("#"):
        return "heading"
    return "paragraph"


def _markdown_to_blocks(markdown: str, *, page: int | None, input_path: Path) -> list[dict[str, Any]]:
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", markdown) if chunk.strip()]
    blocks: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        text = chunk.strip()
        blocks.append(
            {
                "block_id": f"paddleocr_vl_{index:04d}",
                "block_type": _block_type(text),
                "text": text,
                "page": page,
                "confidence": 0.75,
                "metadata": {
                    "parser": "paddleocr_vl",
                    "source_file": str(input_path),
                },
            }
        )
    return blocks


def _quality_score(markdown: str, blocks: list[dict[str, Any]]) -> float:
    text_chars = len(markdown.strip())
    if text_chars <= 0:
        return 0.0
    mojibake_tokens = ("\ufffd", "\u6d63", "\u93c2", "\u9225")
    mojibake_hits = sum(markdown.count(token) for token in mojibake_tokens)
    score = 0.45 + min(text_chars / 4000, 0.35) + min(len(blocks) / 40, 0.15)
    if "|" in markdown:
        score += 0.03
    if re.search(r"(\$[^$]+\$|\\frac|\\sum|\\int|[=≈≤≥])", markdown):
        score += 0.02
    score -= min(mojibake_hits * 0.03, 0.25)
    return max(0.0, min(0.95, round(score, 4)))


def parse_document(input_path: Path, output_dir: Path, filename: str, device: str, page: int | None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="paddleocr-vl-worker-") as temp_name:
        temp_dir = Path(temp_name)
        pipeline = _build_pipeline(device)
        prediction = pipeline.predict(str(input_path))
        markdown_parts: list[str] = []
        result_count = 0
        for result in prediction:
            result_count += 1
            markdown_parts.extend(_extract_markdown_from_result(result, temp_dir))
        markdown_parts.extend(_read_generated_markdown(temp_dir))
        markdown = "\n\n".join(part.strip() for part in markdown_parts if part.strip()).strip()
        if markdown:
            markdown = f"# {filename}\n\n{markdown}\n"
        blocks = _markdown_to_blocks(markdown, page=page, input_path=input_path)
        markdown_path = output_dir / "paddleocr_vl.md"
        blocks_path = output_dir / "paddleocr_vl.blocks.json"
        markdown_path.write_text(markdown, encoding="utf-8")
        blocks_path.write_text(json.dumps(blocks, ensure_ascii=False, indent=2), encoding="utf-8")
        warnings: list[str] = []
        if not markdown.strip():
            warnings.append("PaddleOCR-VL 已运行，但没有产出可用 Markdown 文本。")
        return {
            "ok": bool(markdown.strip()),
            "parser": "paddleocr_vl",
            "markdown": markdown,
            "markdown_path": str(markdown_path),
            "blocks": blocks,
            "blocks_path": str(blocks_path),
            "warnings": warnings,
            "quality_score": _quality_score(markdown, blocks),
            "features": ["ocr", "vlm", "image", "table", "formula", "chart", "multilingual"],
            "page": page,
            "device": device,
            "result_count": result_count,
            "versions": _paddle_versions(),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated PaddleOCR-VL document-reader worker.")
    parser.add_argument("input_path", nargs="?", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--filename", default="")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    _configure_cache(Path(args.cache_dir))
    if args.check:
        versions = _paddle_versions()
        ok = "paddleocr" in versions and "paddle_error" not in versions
        _json_line(
            {
                "ok": ok,
                "parser": "paddleocr_vl",
                "mode": "worker",
                "versions": versions,
                "cache_dir": str(Path(args.cache_dir)),
            }
        )
        return 0 if ok else 1

    input_path = Path(args.input_path)
    output_dir = Path(args.output_dir)
    if not input_path.exists():
        _json_line({"ok": False, "parser": "paddleocr_vl", "error": f"文件不存在: {input_path}"})
        return 2
    if not args.output_dir:
        _json_line({"ok": False, "parser": "paddleocr_vl", "error": "缺少 --output-dir"})
        return 2
    filename = args.filename or input_path.name
    try:
        payload = parse_document(input_path, output_dir, filename, args.device, args.page)
        _json_line(payload)
        return 0 if payload.get("ok") else 3
    except Exception as exc:  # pragma: no cover - depends on optional runtime.
        payload = {
            "ok": False,
            "parser": "paddleocr_vl",
            "error": str(exc),
            "traceback": traceback.format_exc() if args.debug else "",
            "versions": _paddle_versions(),
        }
        _json_line(payload)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
