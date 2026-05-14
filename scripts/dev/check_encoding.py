from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

TEXT_EXTENSIONS = {
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "screenshots",
    "runtime_logs",
    "models",
    "huggingface",
}

MOJIBAKE_PATTERNS = (
    "\ufffd",
    "\u9225",
    "\u9229",
    "\u6d63",
    "\u6d93",
    "\u93c2",
    "\u93c8",
    "\u9352",
    "\u9422",
    "\u7ee0",
    "\u97eb",
    "\u94cf",
)

DOC_WARN_PATHS = (
    Path("PROJECT_STATE.md"),
    Path("docs/governance/task_board.md"),
    Path("docs/governance/work_log.md"),
    Path("docs/governance/decision_log.md"),
)


def iter_text_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for start in paths:
        if start.is_file():
            if start.suffix.lower() in TEXT_EXTENSIONS:
                files.append(start)
            continue
        for path in start.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            files.append(path)
    return sorted(set(files))


def is_doc_warning(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return relative in DOC_WARN_PATHS


def main() -> int:
    parser = argparse.ArgumentParser(description="Check project text files for UTF-8 and mojibake regressions.")
    parser.add_argument("paths", nargs="*", help="Paths to scan. Defaults to active source/config/script folders.")
    parser.add_argument(
        "--strict-docs",
        action="store_true",
        help="Treat mojibake in governance docs as failures instead of warnings.",
    )
    args = parser.parse_args()

    scan_roots = [ROOT / path for path in args.paths] if args.paths else [
        ROOT / "app",
        ROOT / "configs",
        ROOT / "scripts",
        ROOT / "tests",
        ROOT / "PROJECT_STATE.md",
        ROOT / "docs" / "governance",
    ]

    failures: list[str] = []
    warnings: list[str] = []
    scanned = 0

    for path in iter_text_files(scan_roots):
        scanned += 1
        relative = path.relative_to(ROOT)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            failures.append(f"{relative}: not valid UTF-8 ({exc})")
            continue
        found = [pattern for pattern in MOJIBAKE_PATTERNS if pattern in text]
        if found:
            message = f"{relative}: suspicious mojibake patterns {', '.join(found[:6])}"
            if is_doc_warning(path) and not args.strict_docs:
                warnings.append(message)
            else:
                failures.append(message)

    for warning in warnings:
        print(f"[WARN] {warning}")
    for failure in failures:
        print(f"[FAIL] {failure}")

    print(f"Encoding check scanned {scanned} files: {len(failures)} failure(s), {len(warnings)} warning(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
