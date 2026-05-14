from __future__ import annotations

import csv
import contextlib
import gc
import hashlib
import html.parser
import io
import json
import re
from pathlib import Path

from app.backend.document_reader.adapters import (
    AdapterAvailability,
    AdapterParseResult,
    DoclingGraniteVlmAdapter,
    DoclingStandardAdapter,
    MarkerSuryaAdapter,
    PaddleOcrVlAdapter,
    parser_registry,
)
from app.backend.document_reader.schemas import (
    CODE_EXTENSIONS,
    IMAGE_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    DocumentBlock,
    DocumentPageDiagnostic,
    DocumentQualitySummary,
    DocumentReadResult,
    ParserCandidate,
    ProvenanceEntry,
)


class _HtmlTextExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"p", "div", "section", "article", "br", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        clean = data.strip()
        if clean:
            self.parts.append(clean)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", " ".join(self.parts).replace("\n ", "\n")).strip()


class DocumentReader:
    """Local-first multimodal document reader with parser candidates and diagnostics."""

    def __init__(self, *, file_id: str | None = None):
        self.file_id = file_id

    def read(
        self,
        raw_path: Path,
        output_dir: Path,
        *,
        original_filename: str,
        mime_type: str = "",
    ) -> DocumentReadResult:
        extension = raw_path.suffix.lower().lstrip(".")
        if extension not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"不支持的文件格式：{extension}")
        output_dir.mkdir(parents=True, exist_ok=True)
        sha256 = sha256_file(raw_path)

        if extension in CODE_EXTENSIONS:
            result = self._simple_result(raw_path, original_filename, "code")
        elif extension in {"txt", "md"}:
            result = self._simple_result(raw_path, original_filename, "text")
        elif extension in {"csv", "tsv"}:
            result = self._simple_result(raw_path, original_filename, "table")
        elif extension in {"html", "htm"}:
            result = self._simple_result(raw_path, original_filename, "html")
        elif extension == "rtf":
            result = self._simple_result(raw_path, original_filename, "rtf")
        elif extension in IMAGE_EXTENSIONS:
            result = self._read_image(raw_path, original_filename)
        else:
            result = self._read_binary_document(raw_path, original_filename, extension)

        blocks: list[DocumentBlock] = result["blocks"]
        markdown: str = result["markdown"]
        parser_chain: list[str] = result["parser_chain"]
        warnings: list[str] = result["warnings"]
        page_count: int | None = result["page_count"]
        quality_score: float = result["quality_score"]
        diagnostics: list[DocumentPageDiagnostic] = result["diagnostics"]
        parser_candidates: list[ParserCandidate] = result["parser_candidates"]

        if not blocks:
            block = DocumentBlock(
                block_id="block_0001",
                block_type="warning",
                text="该文件已保存，但当前本地解析器没有抽取到可用正文。",
                page=1,
                confidence=0.0,
                metadata={"note": "no_content_extracted"},
            )
            blocks = [block]
            markdown = f"# {original_filename}\n\n> 该文件已保存，但当前本地解析器没有抽取到可用正文。\n"
            quality_score = min(quality_score, 0.25)
            warnings.append("未抽取到正文，需要后续高级 OCR/VLM 或人工复查。")
            fallback_candidate = _candidate_from_blocks(
                parser="fallback",
                blocks=blocks,
                quality_score=quality_score,
                status="fallback",
                warnings=warnings,
                reason="no_content_extracted",
                page=1,
            )
            parser_candidates.append(fallback_candidate)
            diagnostics = [
                _page_diagnostic(
                    page=1,
                    route="fallback",
                    selected_parser="fallback",
                    quality_score=quality_score,
                    warnings=warnings,
                    candidates=[fallback_candidate],
                    needs_ocr=True,
                )
            ]
            parser_chain = parser_chain or ["fallback"]

        quality_summary = _quality_summary(
            blocks=blocks,
            diagnostics=diagnostics,
            quality_score=quality_score,
            warnings=warnings,
        )
        provenance = [
            ProvenanceEntry(
                block_id=block.block_id,
                file_id=self.file_id,
                filename=original_filename,
                parser=block.metadata.get("parser") or (parser_chain[-1] if parser_chain else "unknown"),
                page=block.page,
                region=block.region,
                confidence=block.confidence,
                note=str(block.metadata.get("note", "")),
            )
            for block in blocks
        ]

        markdown_path = output_dir / "document.md"
        blocks_path = output_dir / "blocks.json"
        provenance_path = output_dir / "provenance.json"
        diagnostics_path = output_dir / "diagnostics.json"
        markdown_path.write_text(markdown, encoding="utf-8")
        blocks_path.write_text(
            json.dumps([block.model_dump(mode="json") for block in blocks], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        provenance_path.write_text(
            json.dumps(
                [entry.model_dump(mode="json") for entry in provenance],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        diagnostics_path.write_text(
            json.dumps(
                {
                    "pages": [item.model_dump(mode="json") for item in diagnostics],
                    "parser_candidates": [
                        item.model_dump(mode="json") for item in parser_candidates
                    ],
                    "quality_summary": quality_summary.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return DocumentReadResult(
            sha256=sha256,
            mime_type=mime_type,
            extension=extension,
            page_count=page_count,
            parser_chain=parser_chain,
            quality_score=quality_score,
            warnings=warnings,
            markdown_path=str(markdown_path),
            blocks_path=str(blocks_path),
            provenance_path=str(provenance_path),
            diagnostics_path=str(diagnostics_path),
            blocks=blocks,
            provenance=provenance,
            diagnostics=diagnostics,
            parser_candidates=parser_candidates,
            quality_summary=quality_summary,
        )

    def _simple_result(self, path: Path, filename: str, route: str) -> dict:
        if route == "code":
            blocks, markdown, parser_chain, warnings = self._read_code(path, filename)
            quality = 0.92
        elif route == "text":
            blocks, markdown, parser_chain, warnings = self._read_text(path, filename)
            quality = 0.9
        elif route == "table":
            blocks, markdown, parser_chain, warnings = self._read_table(path, filename, path.suffix.lower().lstrip("."))
            quality = 0.88
        elif route == "html":
            blocks, markdown, parser_chain, warnings = self._read_html(path, filename)
            quality = 0.82
        else:
            blocks, markdown, parser_chain, warnings = self._read_rtf(path, filename)
            quality = 0.65
        candidate = _candidate_from_blocks(
            parser=parser_chain[-1],
            blocks=blocks,
            quality_score=quality,
            status="selected",
            warnings=warnings,
            page=1,
        )
        diagnostics = [
            _page_diagnostic(
                page=1,
                route=route,
                selected_parser=parser_chain[-1],
                quality_score=quality,
                warnings=warnings,
                candidates=[candidate, *_disabled_backend_candidates(skip=set(parser_chain))],
            )
        ]
        return _result_payload(
            blocks=blocks,
            markdown=markdown,
            parser_chain=parser_chain,
            warnings=warnings,
            quality_score=quality,
            page_count=1,
            diagnostics=diagnostics,
            parser_candidates=[candidate],
        )

    def _read_text(
        self,
        path: Path,
        filename: str,
    ) -> tuple[list[DocumentBlock], str, list[str], list[str]]:
        text, encoding, warnings = decode_text_file(path)
        block = DocumentBlock(
            block_id="block_0001",
            block_type="paragraph",
            text=text,
            page=1,
            confidence=0.9,
            metadata={"encoding": encoding, "parser": "text_decoder"},
        )
        return [block], f"# {filename}\n\n{text}\n", ["text_decoder"], warnings

    def _read_code(
        self,
        path: Path,
        filename: str,
    ) -> tuple[list[DocumentBlock], str, list[str], list[str]]:
        text, encoding, warnings = decode_text_file(path)
        language = path.suffix.lower().lstrip(".")
        block = DocumentBlock(
            block_id="block_0001",
            block_type="code",
            text=text,
            page=1,
            confidence=0.92,
            metadata={"encoding": encoding, "language": language, "parser": "code_decoder"},
        )
        markdown = f"# {filename}\n\n```{language}\n{text.rstrip()}\n```\n"
        return [block], markdown, ["code_decoder"], warnings

    def _read_table(
        self,
        path: Path,
        filename: str,
        extension: str,
    ) -> tuple[list[DocumentBlock], str, list[str], list[str]]:
        text, encoding, warnings = decode_text_file(path)
        delimiter = "\t" if extension == "tsv" else ","
        rows = list(csv.reader(text.splitlines(), delimiter=delimiter))
        markdown_table = rows_to_markdown(rows)
        block = DocumentBlock(
            block_id="block_0001",
            block_type="table",
            text=markdown_table,
            page=1,
            confidence=0.88,
            metadata={"encoding": encoding, "rows": rows, "parser": "csv_table_reader"},
        )
        return [block], f"# {filename}\n\n{markdown_table}\n", ["csv_table_reader"], warnings

    def _read_html(
        self,
        path: Path,
        filename: str,
    ) -> tuple[list[DocumentBlock], str, list[str], list[str]]:
        text, encoding, warnings = decode_text_file(path)
        extractor = _HtmlTextExtractor()
        extractor.feed(text)
        extracted = extractor.text()
        if not extracted:
            warnings.append("HTML 页面未抽取到明显正文。")
        block = DocumentBlock(
            block_id="block_0001",
            block_type="paragraph",
            text=extracted,
            page=1,
            confidence=0.82 if extracted else 0.1,
            metadata={"encoding": encoding, "parser": "html_text_extractor"},
        )
        return [block], f"# {filename}\n\n{extracted}\n", ["html_text_extractor"], warnings

    def _read_rtf(
        self,
        path: Path,
        filename: str,
    ) -> tuple[list[DocumentBlock], str, list[str], list[str]]:
        text, encoding, warnings = decode_text_file(path)
        stripped = re.sub(r"\\'[0-9a-fA-F]{2}", "", text)
        stripped = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", stripped)
        stripped = re.sub(r"[{}]", "", stripped)
        stripped = re.sub(r"\n{3,}", "\n\n", stripped).strip()
        warnings.append("RTF 使用轻量规则抽取，复杂排版需要 Docling 或人工复查。")
        block = DocumentBlock(
            block_id="block_0001",
            block_type="paragraph",
            text=stripped,
            page=1,
            confidence=0.65,
            metadata={"encoding": encoding, "parser": "rtf_light_extractor"},
        )
        return [block], f"# {filename}\n\n{stripped}\n", ["rtf_light_extractor"], warnings

    def _read_image(self, path: Path, filename: str) -> dict:
        candidates: list[ParserCandidate] = []
        parser_chain: list[str] = []
        warnings: list[str] = []
        failed_runtime_metadata: list[dict[str, object]] = []
        tried_adapters: set[str] = set()
        for ocr in (MarkerSuryaAdapter(), PaddleOcrVlAdapter()):
            tried_adapters.add(ocr.name)
            availability = ocr.available()
            if not availability.available:
                candidates.append(_candidate_from_availability(availability, page=1))
                continue
            parsed = _parse_with_ocr_adapter(ocr, path, filename=filename, page=1)
            candidate = _candidate_from_adapter_result(parsed, status="selected" if parsed.blocks else "failed")
            candidates.append(candidate)
            warnings.extend(parsed.warnings)
            if not parsed.blocks and parsed.runtime_metadata:
                failed_runtime_metadata.append(
                    {"parser": parsed.parser, "runtime_metadata": parsed.runtime_metadata}
                )
            if parsed.blocks:
                parser_chain.append(ocr.name)
                diagnostics = [
                    _page_diagnostic(
                        page=1,
                        route="image_ocr",
                        selected_parser=ocr.name,
                        quality_score=parsed.quality_score,
                        warnings=warnings,
                        candidates=[candidate, *_disabled_backend_candidates(skip={ocr.name})],
                        needs_ocr=False,
                        runtime_metadata=parsed.runtime_metadata,
                    )
                ]
                return _result_payload(
                    blocks=parsed.blocks,
                    markdown=parsed.markdown,
                    parser_chain=parser_chain,
                    warnings=warnings,
                    quality_score=parsed.quality_score,
                    page_count=1,
                    diagnostics=diagnostics,
                    parser_candidates=candidates,
                )
        warnings.extend(
            [
                "图片需要 OCR/VLM 后端才能高质量解析；当前仅保留文件和 provenance。",
                *_adapter_status_notes(skip=tried_adapters),
            ]
        )
        block = DocumentBlock(
            block_id="block_0001",
            block_type="image",
            text=f"[图片文件] {filename}",
            page=1,
            confidence=0.25,
            metadata={"note": "ocr_vlm_pending", "path": str(path), "parser": "image_metadata_reader"},
        )
        markdown = f"# {filename}\n\n![{filename}]({path.as_posix()})\n\n> 图片文字识别需要启用本地 OCR/VLM 后端后补充。\n"
        fallback = _candidate_from_blocks(
            parser="image_metadata_reader",
            blocks=[block],
            quality_score=0.3,
            status="fallback",
            warnings=warnings,
            reason="needs_ocr_backend",
            page=1,
            features=["image", "provenance"],
        )
        candidates.append(fallback)
        diagnostics = [
            _page_diagnostic(
                page=1,
                route="image_needs_ocr",
                selected_parser="image_metadata_reader",
                quality_score=0.3,
                warnings=warnings,
                candidates=candidates,
                needs_ocr=True,
                runtime_metadata={"failed_ocr_attempts": failed_runtime_metadata}
                if failed_runtime_metadata
                else None,
            )
        ]
        return _result_payload(
            blocks=[block],
            markdown=markdown,
            parser_chain=["image_metadata_reader"],
            warnings=warnings,
            quality_score=0.3,
            page_count=1,
            diagnostics=diagnostics,
            parser_candidates=candidates,
        )

    def _read_binary_document(self, path: Path, filename: str, extension: str) -> dict:
        page_count = _estimate_pdf_pages(path) if extension == "pdf" else None
        scan_hint = _pdf_needs_ocr_hint(path) if extension == "pdf" else False
        candidates: list[ParserCandidate] = []
        parser_chain: list[str] = []
        warnings: list[str] = []
        failed_runtime_metadata: list[dict[str, object]] = []

        for adapter in (DoclingStandardAdapter(), DoclingGraniteVlmAdapter()):
            availability = adapter.available()
            if not availability.available:
                candidates.append(_candidate_from_availability(availability))
                continue
            try:
                markdown = _export_markdown_quietly(adapter, path)
                blocks = _blocks_from_markdown(markdown, parser=adapter.name)
                quality = _score_blocks(blocks, warnings)
                if not blocks:
                    warnings.append(f"{adapter.name} 已运行，但未抽取到可用正文。")
                candidate = _candidate_from_blocks(
                    parser=adapter.name,
                    blocks=blocks,
                    quality_score=quality,
                    status="candidate",
                    warnings=warnings,
                    features=["layout", "tables", "reading_order"],
                )
                candidates.append(candidate)
                if blocks:
                    if extension == "pdf" and scan_hint and adapter.name == "docling_standard":
                        warnings.append(
                            "Docling 已抽取部分内容，但该 PDF 可能包含扫描页或图片页，继续尝试 OCR/VLM 后端。"
                        )
                        continue
                    selected = _select_candidate(candidates)
                    if selected.parser == adapter.name:
                        selected.status = "selected"
                        parser_chain.append(adapter.name)
                        diagnostics = _binary_diagnostics(
                            extension=extension,
                            page_count=page_count,
                            selected_parser=adapter.name,
                            quality_score=quality,
                            candidates=candidates,
                            warnings=warnings,
                            needs_ocr=False,
                        )
                        return _result_payload(
                            blocks=blocks,
                            markdown=f"# {filename}\n\n{markdown}\n",
                            parser_chain=parser_chain,
                            warnings=warnings,
                            quality_score=quality,
                            page_count=page_count,
                            diagnostics=diagnostics,
                            parser_candidates=candidates,
                        )
            except Exception as exc:  # pragma: no cover - depends on external parser internals.
                candidates.append(
                    ParserCandidate(parser=adapter.name, status="failed", reason=str(exc), warnings=[str(exc)])
                )
                warnings.append(f"{adapter.name} 解析失败，已进入后续候选或 fallback：{exc}")

        if extension in {"pdf", "docx", "pptx", "xlsx", "html", "htm"}:
            for ocr in (MarkerSuryaAdapter(), PaddleOcrVlAdapter()):
                if extension != "pdf" and ocr.name == "paddleocr_vl":
                    continue
                availability = ocr.available()
                if not availability.available:
                    candidates.append(_candidate_from_availability(availability))
                    continue
                parsed = _parse_with_ocr_adapter(ocr, path, filename=filename, page=None)
                candidate = _candidate_from_adapter_result(parsed, status="selected" if parsed.blocks else "failed")
                candidates.append(candidate)
                warnings.extend(parsed.warnings)
                if not parsed.blocks and parsed.runtime_metadata:
                    failed_runtime_metadata.append(
                        {"parser": parsed.parser, "runtime_metadata": parsed.runtime_metadata}
                    )
                if parsed.blocks:
                    diagnostics = _binary_diagnostics(
                        extension=extension,
                        page_count=page_count,
                        selected_parser=ocr.name,
                        quality_score=parsed.quality_score,
                        candidates=candidates,
                        warnings=warnings,
                        needs_ocr=False,
                        runtime_metadata=parsed.runtime_metadata,
                    )
                    return _result_payload(
                        blocks=parsed.blocks,
                        markdown=parsed.markdown,
                        parser_chain=[ocr.name],
                        warnings=warnings,
                        quality_score=parsed.quality_score,
                        page_count=page_count,
                        diagnostics=diagnostics,
                        parser_candidates=candidates,
                    )

        if extension == "pdf" and not any(item.parser == "paddleocr_vl" for item in candidates):
            ocr = PaddleOcrVlAdapter()
            availability = ocr.available()
            if availability.available:
                parsed = ocr.parse_image(path, filename=filename, page=None)
                candidate = _candidate_from_adapter_result(parsed, status="selected" if parsed.blocks else "failed")
                candidates.append(candidate)
                warnings.extend(parsed.warnings)
                if not parsed.blocks and parsed.runtime_metadata:
                    failed_runtime_metadata.append(
                        {"parser": parsed.parser, "runtime_metadata": parsed.runtime_metadata}
                    )
                if parsed.blocks:
                    diagnostics = _binary_diagnostics(
                        extension=extension,
                        page_count=page_count,
                        selected_parser=ocr.name,
                        quality_score=parsed.quality_score,
                        candidates=candidates,
                        warnings=warnings,
                        needs_ocr=False,
                        runtime_metadata=parsed.runtime_metadata,
                    )
                    return _result_payload(
                        blocks=parsed.blocks,
                        markdown=parsed.markdown,
                        parser_chain=[ocr.name],
                        warnings=warnings,
                        quality_score=parsed.quality_score,
                        page_count=page_count,
                        diagnostics=diagnostics,
                        parser_candidates=candidates,
                    )
            else:
                candidates.append(_candidate_from_availability(availability))

        warnings.extend(_adapter_status_notes(skip={"docling_standard", "docling_granite_vlm"}))
        warnings.append(f".{extension} 已保存；当前本地环境缺少可用高质量解析器。")
        block = DocumentBlock(
            block_id="block_0001",
            block_type="warning",
            text=f"{filename} 已保存，当前未抽取到正文。",
            page=1,
            confidence=0.1,
            metadata={"note": "advanced_parser_required", "extension": extension, "parser": "binary_document_fallback"},
        )
        fallback = _candidate_from_blocks(
            parser="binary_document_fallback",
            blocks=[block],
            quality_score=0.35,
            status="fallback",
            warnings=warnings,
            reason="needs_ocr_backend" if scan_hint else "advanced_parser_required",
            features=["provenance"],
        )
        candidates.append(fallback)
        diagnostics = _binary_diagnostics(
            extension=extension,
            page_count=page_count,
            selected_parser="binary_document_fallback",
            quality_score=0.35,
            candidates=candidates,
            warnings=warnings,
            needs_ocr=scan_hint or extension == "pdf",
            runtime_metadata={"failed_ocr_attempts": failed_runtime_metadata}
            if failed_runtime_metadata
            else None,
        )
        markdown = f"# {filename}\n\n> 文件已保存；当前环境需要 Docling/OCR/VLM 后端才能高质量解析该格式。\n"
        return _result_payload(
            blocks=[block],
            markdown=markdown,
            parser_chain=["binary_document_fallback"],
            warnings=warnings,
            quality_score=0.35,
            page_count=page_count,
            diagnostics=diagnostics,
            parser_candidates=candidates,
        )


def read_document(
    raw_path: Path,
    output_dir: Path,
    *,
    original_filename: str,
    mime_type: str = "",
    file_id: str | None = None,
) -> DocumentReadResult:
    return DocumentReader(file_id=file_id).read(
        raw_path,
        output_dir,
        original_filename=original_filename,
        mime_type=mime_type,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode_text_file(path: Path) -> tuple[str, str, list[str]]:
    data = path.read_bytes()
    warnings: list[str] = []
    encoding = "utf-8-replace"
    for candidate in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
        try:
            text = data.decode(candidate)
            encoding = candidate
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 should always decode.
        text = data.decode("utf-8", errors="replace")
    if "\ufffd" in text:
        warnings.append("文本中仍存在替换字符，可能需要人工检查编码。")
    if _looks_like_mojibake(text):
        warnings.append("检测到疑似乱码片段，后续整理阶段应复核。")
    return text.replace("\r\n", "\n").replace("\r", "\n"), encoding, warnings


def rows_to_markdown(rows: list[list[str]], *, max_rows: int = 200) -> str:
    if not rows:
        return ""
    trimmed = rows[:max_rows]
    width = max(len(row) for row in trimmed)
    normalized = [row + [""] * (width - len(row)) for row in trimmed]
    header = normalized[0]
    body = normalized[1:] or [[""] * width]
    lines = [
        "| " + " | ".join(_escape_table_cell(cell) for cell in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines.extend("| " + " | ".join(_escape_table_cell(cell) for cell in row) + " |" for row in body)
    if len(rows) > max_rows:
        lines.append(f"\n> 仅展示前 {max_rows} 行，原表格共有 {len(rows)} 行。")
    return "\n".join(lines)


def _blocks_from_markdown(markdown: str, *, parser: str = "docling_standard") -> list[DocumentBlock]:
    blocks: list[DocumentBlock] = []
    parts = [part.strip() for part in re.split(r"\n{2,}", markdown) if part.strip()]
    for index, part in enumerate(parts, start=1):
        if part.startswith("#"):
            block_type = "heading"
        elif part.startswith("|") and "\n|" in part:
            block_type = "table"
        else:
            block_type = "paragraph"
        blocks.append(
            DocumentBlock(
                block_id=f"block_{index:04d}",
                block_type=block_type,
                text=part,
                page=None,
                confidence=0.8,
                metadata={"parser": parser},
            )
        )
    return blocks


def _export_markdown_quietly(adapter: DoclingStandardAdapter | DoclingGraniteVlmAdapter, path: Path) -> str:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            return adapter.export_markdown(path)
        except Exception:
            gc.collect()
            raise


def _parse_with_ocr_adapter(
    adapter: MarkerSuryaAdapter | PaddleOcrVlAdapter,
    path: Path,
    *,
    filename: str,
    page: int | None,
) -> AdapterParseResult:
    if isinstance(adapter, MarkerSuryaAdapter):
        return adapter.parse_document(path, filename=filename, page=page, force_ocr=True)
    return adapter.parse_image(path, filename=filename, page=page)


def _result_payload(
    *,
    blocks: list[DocumentBlock],
    markdown: str,
    parser_chain: list[str],
    warnings: list[str],
    quality_score: float,
    page_count: int | None,
    diagnostics: list[DocumentPageDiagnostic],
    parser_candidates: list[ParserCandidate],
) -> dict:
    return {
        "blocks": blocks,
        "markdown": markdown,
        "parser_chain": parser_chain,
        "warnings": warnings,
        "quality_score": quality_score,
        "page_count": page_count,
        "diagnostics": diagnostics,
        "parser_candidates": parser_candidates,
    }


def _candidate_from_adapter_result(result: AdapterParseResult, *, status: str) -> ParserCandidate:
    return ParserCandidate(
        parser=result.parser,
        status=status,
        page=result.page,
        block_count=len(result.blocks),
        text_chars=sum(len(block.text) for block in result.blocks),
        quality_score=result.quality_score,
        confidence=_average_confidence(result.blocks),
        warnings=result.warnings,
        reason=result.reason,
        features=result.features,
    )


def _candidate_from_blocks(
    *,
    parser: str,
    blocks: list[DocumentBlock],
    quality_score: float,
    status: str,
    warnings: list[str],
    reason: str = "",
    page: int | None = None,
    features: list[str] | None = None,
) -> ParserCandidate:
    return ParserCandidate(
        parser=parser,
        status=status,
        page=page,
        block_count=len(blocks),
        text_chars=sum(len(block.text) for block in blocks),
        quality_score=quality_score,
        confidence=_average_confidence(blocks),
        warnings=warnings,
        reason=reason,
        features=features or _features_from_blocks(blocks),
    )


def _candidate_from_availability(availability: AdapterAvailability, *, page: int | None = None) -> ParserCandidate:
    return ParserCandidate(
        parser=availability.name,
        status="disabled" if not availability.enabled else "failed",
        page=page,
        reason=availability.reason,
        warnings=[availability.reason] if availability.reason else [],
    )


def _disabled_backend_candidates(skip: set[str] | None = None) -> list[ParserCandidate]:
    skipped = skip or set()
    candidates: list[ParserCandidate] = []
    for adapter in parser_registry():
        if adapter.name in skipped:
            continue
        availability = adapter.available()
        if not availability.available:
            candidates.append(_candidate_from_availability(availability))
    return candidates


def _page_diagnostic(
    *,
    page: int,
    route: str,
    selected_parser: str,
    quality_score: float,
    warnings: list[str],
    candidates: list[ParserCandidate],
    needs_ocr: bool = False,
    runtime_metadata: dict[str, object] | None = None,
) -> DocumentPageDiagnostic:
    return DocumentPageDiagnostic(
        page=page,
        route=route,
        selected_parser=selected_parser,
        quality_score=quality_score,
        needs_ocr=needs_ocr,
        requires_review=quality_score < 0.5 or needs_ocr or bool(warnings),
        warnings=warnings,
        candidates=candidates,
        runtime_metadata=runtime_metadata or {},
    )


def _binary_diagnostics(
    *,
    extension: str,
    page_count: int | None,
    selected_parser: str,
    quality_score: float,
    candidates: list[ParserCandidate],
    warnings: list[str],
    needs_ocr: bool,
    runtime_metadata: dict[str, object] | None = None,
) -> list[DocumentPageDiagnostic]:
    count = max(page_count or 1, 1)
    route = "pdf_scanned_or_mixed" if needs_ocr and extension == "pdf" else f"{extension}_document"
    return [
        _page_diagnostic(
            page=page,
            route=route,
            selected_parser=selected_parser,
            quality_score=quality_score,
            warnings=warnings,
            candidates=candidates,
            needs_ocr=needs_ocr,
            runtime_metadata=runtime_metadata,
        )
        for page in range(1, count + 1)
    ]


def _quality_summary(
    *,
    blocks: list[DocumentBlock],
    diagnostics: list[DocumentPageDiagnostic],
    quality_score: float,
    warnings: list[str],
) -> DocumentQualitySummary:
    return DocumentQualitySummary(
        overall_score=quality_score,
        low_quality_pages=sum(1 for item in diagnostics if item.quality_score < 0.5),
        ocr_pages=sum(
            1
            for item in diagnostics
            if item.selected_parser in {"marker_surya", "paddleocr_vl", "docling_granite_vlm"}
        ),
        table_blocks=sum(1 for block in blocks if block.block_type == "table"),
        image_blocks=sum(1 for block in blocks if block.block_type == "image"),
        formula_blocks=sum(1 for block in blocks if block.block_type == "formula"),
        warning_blocks=sum(1 for block in blocks if block.block_type == "warning"),
        mojibake_warnings=sum(1 for warning in warnings if "乱码" in warning or "mojibake" in warning.lower()),
        needs_review=quality_score < 0.5 or any(item.requires_review for item in diagnostics),
        needs_ocr_backend=any(item.needs_ocr for item in diagnostics),
    )


def _select_candidate(candidates: list[ParserCandidate]) -> ParserCandidate:
    return max(candidates, key=lambda item: (item.quality_score, item.text_chars, item.block_count))


def _score_blocks(blocks: list[DocumentBlock], warnings: list[str]) -> float:
    if not blocks:
        return 0.2
    text_chars = sum(len(block.text.strip()) for block in blocks)
    table_bonus = 0.03 if any(block.block_type == "table" for block in blocks) else 0
    warning_penalty = min(len(warnings) * 0.05, 0.25)
    base = 0.55 + min(text_chars / 4000, 0.3) + table_bonus - warning_penalty
    return max(0.1, min(base, 0.9))


def _average_confidence(blocks: list[DocumentBlock]) -> float | None:
    values = [block.confidence for block in blocks if block.confidence is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _features_from_blocks(blocks: list[DocumentBlock]) -> list[str]:
    features: set[str] = set()
    for block in blocks:
        if block.block_type in {"table", "code", "image", "formula"}:
            features.add(block.block_type)
    if any(block.text.strip() for block in blocks):
        features.add("text")
    return sorted(features)


def _adapter_status_notes(skip: set[str] | None = None) -> list[str]:
    skipped = skip or set()
    notes: list[str] = []
    for adapter in parser_registry():
        if adapter.name in skipped:
            continue
        availability = adapter.available()
        if not availability.available:
            notes.append(f"{adapter.name} 后端未启用：{availability.reason}")
    return notes


def _escape_table_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _looks_like_mojibake(text: str) -> bool:
    markers = ("\u951f", "\u93c2", "\u6d7c", "\u7a0b", "\u9225", "\u00c3", "\u00c2")
    return sum(text.count(marker) for marker in markers) >= 3


def _estimate_pdf_pages(path: Path) -> int | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    count = data.count(b"/Type /Page")
    return int(count) if count > 0 else None


def _pdf_needs_ocr_hint(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return True
    text_markers = (b"BT", b" Tj", b" TJ", b"/Font", b"/ToUnicode")
    image_markers = (b"/Image", b"/XObject", b"/Subtype /Image")
    has_text = any(marker in data for marker in text_markers)
    has_images = any(marker in data for marker in image_markers)
    return has_images or not has_text
