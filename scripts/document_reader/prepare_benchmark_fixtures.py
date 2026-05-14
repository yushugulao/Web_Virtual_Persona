from __future__ import annotations

import argparse
import json
from pathlib import Path
import textwrap
from typing import Any
from urllib.request import urlretrieve


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = ROOT / "data" / "cache" / "document_reader_benchmark"
MANIFEST_PATH = ROOT / "evals" / "document_reader" / "ocr_heavy_fixture_manifest.json"


REAL_FIXTURES: list[dict[str, Any]] = [
    {
        "case_id": "paddle_official_demo_image",
        "kind": "real",
        "category": "mixed_layout_image",
        "url": "https://paddle-model-ecology.bj.bcebos.com/paddlex/imgs/demo_image/paddleocr_vl_demo.png",
        "filename": "paddleocr_vl_demo.png",
        "keywords": ["助力双方交往", "中文", "孔子学院"],
        "source": "PaddleOCR-VL official documentation demo image retained as OCR-heavy fixture",
    },
    {
        "case_id": "arxiv_formula_table_chart_pdf",
        "kind": "real",
        "category": "formula_table_chart_pdf",
        "url": "https://arxiv.org/pdf/1706.03762",
        "filename": "attention_is_all_you_need.pdf",
        "keywords": ["Attention", "Transformer", "BLEU"],
        "source": "arXiv PDF with formulas, tables, figures, and multi-column layout",
    },
]


OLMOCR_BENCH_TARGETS: list[dict[str, str]] = [
    {"case_id": "olmocr_math_sample", "category": "olmocr_math", "hint": "math"},
    {"case_id": "olmocr_old_scan_sample", "category": "olmocr_old_scan", "hint": "old"},
    {"case_id": "olmocr_table_sample", "category": "olmocr_table", "hint": "table"},
    {"case_id": "olmocr_multicolumn_sample", "category": "olmocr_multi_column", "hint": "column"},
    {"case_id": "olmocr_tiny_text_sample", "category": "olmocr_tiny_text", "hint": "tiny"},
]


GENERATED_FIXTURES: list[dict[str, Any]] = [
    {
        "case_id": "generated_mixed_resume_cn_en",
        "category": "mixed_language_resume",
        "filename": "generated_mixed_resume_cn_en.png",
        "keywords": ["张三", "Backend Engineer", "Rust", "检索增强"],
    },
    {
        "case_id": "generated_table_screenshot",
        "category": "table_screenshot",
        "filename": "generated_table_screenshot.png",
        "keywords": ["指标", "召回率", "延迟", "P95"],
    },
    {
        "case_id": "generated_formula_page",
        "category": "formula_page",
        "filename": "generated_formula_page.png",
        "keywords": ["E = mc", "softmax", "loss"],
    },
    {
        "case_id": "generated_chart_page",
        "category": "chart_page",
        "filename": "generated_chart_page.png",
        "keywords": ["OCR", "Docling", "Marker", "quality"],
    },
    {
        "case_id": "generated_terminal_code",
        "category": "code_terminal_screenshot",
        "filename": "generated_terminal_code.png",
        "keywords": ["pytest", "DocumentReader", "blocks.json", "provenance"],
    },
]


def _pil_available() -> bool:
    try:
        import PIL.Image  # noqa: F401
        import PIL.ImageDraw  # noqa: F401
    except Exception:
        return False
    return True


def _font(size: int):
    from PIL import ImageFont

    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_multiline(draw, xy: tuple[int, int], text: str, *, font, fill=(20, 20, 20), spacing=10):
    x, y = xy
    for line in text.splitlines():
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + spacing


def _write_generated_image(path: Path, case_id: str) -> None:
    from PIL import Image, ImageDraw

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1240, 1754), "#fbf7ef")
    draw = ImageDraw.Draw(image)
    title_font = _font(52)
    body_font = _font(34)
    small_font = _font(28)
    draw.rectangle((70, 70, 1170, 1684), outline="#242424", width=4)
    draw.rectangle((90, 90, 1150, 190), fill="#e8edf7", outline="#242424", width=2)

    if case_id == "generated_mixed_resume_cn_en":
        draw.text((120, 118), "张三 / Backend Engineer", font=title_font, fill="#111111")
        body = """核心经历
2019-2024 负责 Persona-RAG 后端、向量检索、文件读取器。
Skills: Python, Rust, FastAPI, SQLite, OCR, RAG.
项目亮点：检索增强、文档解析、可追溯 provenance、评测闭环。"""
        _draw_multiline(draw, (120, 250), body, font=body_font)
    elif case_id == "generated_table_screenshot":
        draw.text((120, 118), "OCR/VLM Fixture Benchmark 表格", font=title_font, fill="#111111")
        rows = [
            ["指标", "Docling", "Marker/Surya", "目标"],
            ["文字覆盖率", "0.42", "0.88", ">=0.80"],
            ["表格结构", "缺失", "命中", "命中"],
            ["P95 延迟", "1.2s", "8.4s", "可接受"],
        ]
        x0, y0 = 120, 280
        cell_w, cell_h = 250, 90
        for row_idx, row in enumerate(rows):
            for col_idx, value in enumerate(row):
                x = x0 + col_idx * cell_w
                y = y0 + row_idx * cell_h
                draw.rectangle((x, y, x + cell_w, y + cell_h), outline="#222222", width=2)
                draw.text((x + 18, y + 25), value, font=small_font, fill="#111111")
    elif case_id == "generated_formula_page":
        draw.text((120, 118), "公式与推导页", font=title_font, fill="#111111")
        body = """Einstein: E = mc²
softmax(x_i) = exp(x_i) / Σ_j exp(x_j)
loss = -Σ y_i log(p_i)
目标：检查公式符号、上下标、求和符号是否能被保留。"""
        _draw_multiline(draw, (120, 260), body, font=body_font)
    elif case_id == "generated_chart_page":
        draw.text((120, 118), "图表与标签识别", font=title_font, fill="#111111")
        axis = (180, 1180, 1040, 450)
        draw.line((axis[0], axis[1], axis[2], axis[1]), fill="#111111", width=4)
        draw.line((axis[0], axis[1], axis[0], axis[3]), fill="#111111", width=4)
        bars = [("Docling", 42, "#8aa0b8"), ("OCR", 65, "#f0a84b"), ("Marker/Surya", 88, "#4c9a62")]
        for idx, (label, value, color) in enumerate(bars):
            x = 260 + idx * 250
            h = int(value * 7)
            draw.rectangle((x, axis[1] - h, x + 120, axis[1]), fill=color, outline="#111111")
            draw.text((x - 25, axis[1] + 24), label, font=small_font, fill="#111111")
            draw.text((x + 20, axis[1] - h - 45), f"{value}%", font=small_font, fill="#111111")
        draw.text((120, 260), "quality score: OCR vs Docling vs Marker/Surya", font=body_font)
    else:
        draw.text((120, 118), "代码与终端截图", font=title_font, fill="#111111")
        draw.rectangle((120, 270, 1120, 1280), fill="#1f2328")
        code = """$ uv run pytest tests/test_document_reader.py -q
PASSED tests/test_document_reader.py::test_blocks_json
DocumentReader.parse("scan.pdf")
  -> document.md
  -> blocks.json
  -> provenance.json
  -> diagnostics.json"""
        _draw_multiline(draw, (160, 320), code, font=small_font, fill="#f1f5f9", spacing=16)

    image.save(path)


def _download(url: str, target: Path) -> tuple[bool, str]:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        return True, "cached"
    try:
        urlretrieve(url, target)
    except Exception as exc:
        return False, str(exc)
    return True, "downloaded"


def _prepare_olmocr_bench(cache_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except Exception as exc:
        return [], [f"olmOCR_bench skipped because huggingface_hub is unavailable: {exc}"]
    repo_id = "Voxel51/olmOCR_bench"
    try:
        files = HfApi().list_repo_files(repo_id=repo_id, repo_type="dataset")
    except Exception as exc:
        cached_cases = _prepare_cached_olmocr_bench(cache_dir)
        if cached_cases:
            return cached_cases, [
                f"olmOCR_bench file listing failed, reused cached local fixtures: {exc}"
            ]
        return [], [f"olmOCR_bench file listing failed: {exc}"]
    usable_files = [
        file
        for file in files
        if Path(file).suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
    ]
    cases: list[dict[str, Any]] = []
    used: set[str] = set()
    for target in OLMOCR_BENCH_TARGETS:
        hint = target["hint"].lower()
        selected = next(
            (
                file
                for file in usable_files
                if file not in used and hint in file.lower()
            ),
            "",
        )
        if not selected:
            selected = next((file for file in usable_files if file not in used), "")
        if not selected:
            warnings.append(f"olmOCR_bench no usable file for {target['case_id']}")
            continue
        used.add(selected)
        try:
            local_path = hf_hub_download(
                repo_id=repo_id,
                repo_type="dataset",
                filename=selected,
                local_dir=cache_dir / "real" / "olmocr_bench",
                local_dir_use_symlinks=False,
            )
            prepared = True
            prepare_status = "downloaded"
        except Exception as exc:
            local_path = str(cache_dir / "real" / "olmocr_bench" / selected)
            prepared = False
            prepare_status = str(exc)
            warnings.append(f"olmOCR_bench download failed for {selected}: {exc}")
        cases.append(
            {
                "case_id": target["case_id"],
                "kind": "real",
                "category": target["category"],
                "path": str(local_path),
                "prepared": prepared,
                "prepare_status": prepare_status,
                "source": f"huggingface://datasets/{repo_id}/{selected}",
                "keywords": [],
            }
        )
    return cases, warnings


def _prepare_cached_olmocr_bench(cache_dir: Path) -> list[dict[str, Any]]:
    root = cache_dir / "real" / "olmocr_bench"
    if not root.exists():
        return []
    files = sorted(
        file
        for file in root.rglob("*")
        if file.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
        and file.stat().st_size > 0
    )
    cases: list[dict[str, Any]] = []
    for target, file in zip(OLMOCR_BENCH_TARGETS, files, strict=False):
        cases.append(
            {
                "case_id": target["case_id"],
                "kind": "real",
                "category": target["category"],
                "path": str(file),
                "prepared": True,
                "prepare_status": "cached_local",
                "source": f"local-cache://{file.relative_to(cache_dir)}",
                "keywords": [],
            }
        )
    return cases


def prepare_fixtures(cache_dir: Path = DEFAULT_CACHE_DIR) -> dict[str, Any]:
    real_dir = cache_dir / "real"
    generated_dir = cache_dir / "generated"
    cases: list[dict[str, Any]] = []
    warnings: list[str] = []

    for item in REAL_FIXTURES:
        target = real_dir / item["filename"]
        ok, status = _download(item["url"], target)
        case = dict(item)
        case.update({"path": str(target), "prepared": ok, "prepare_status": status})
        cases.append(case)
        if not ok:
            warnings.append(f"{item['case_id']} 下载失败: {status}")

    olmocr_cases, olmocr_warnings = _prepare_olmocr_bench(cache_dir)
    cases.extend(olmocr_cases)
    warnings.extend(olmocr_warnings)

    if _pil_available():
        for item in GENERATED_FIXTURES:
            target = generated_dir / item["filename"]
            _write_generated_image(target, item["case_id"])
            case = dict(item)
            case.update(
                {
                    "kind": "generated",
                    "path": str(target),
                    "prepared": True,
                    "prepare_status": "generated",
                }
            )
            cases.append(case)
    else:
        warnings.append("Pillow 未安装，生成型图片 fixture 已跳过。")

    manifest = {
        "name": "ocr_heavy_fixture_manifest",
        "cache_dir": str(cache_dir),
        "cases": cases,
        "warnings": warnings,
        "notes": textwrap.dedent(
            """
            大文件和下载/生成的 fixture 位于 data/cache/document_reader_benchmark，
            默认不提交 Git。manifest 只记录来源、路径、预期关键词和类别。
            """
        ).strip(),
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare OCR/VLM benchmark fixtures.")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    args = parser.parse_args()
    manifest = prepare_fixtures(Path(args.cache_dir))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if any(case.get("prepared") for case in manifest["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
