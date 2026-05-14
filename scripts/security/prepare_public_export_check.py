"""Validate that a generated public export does not contain private workspace artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


HIGH_RISK_PATTERNS = {
    "api_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |)PRIVATE KEY-----"),
    "local_project_path": re.compile(r"E:\\综合课程设计"),
    "windows_user_path": re.compile(r"(?i)C:\\Users\\"),
    "known_public_ip": re.compile(r"59\.110\.174\.175"),
}

FORBIDDEN_PATH_PARTS = {
    ".env",
    ".deploy",
    "node_modules",
    ".venv",
    ".git",
    "secrets",
    "tests",
    "evals",
    "tools",
}

FORBIDDEN_RUNTIME_SUFFIXES = {
    ".sqlite",
    ".db",
    ".gguf",
    ".pem",
    ".key",
}

TEXT_SUFFIXES = {
    "",
    ".txt",
    ".md",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".example",
    ".py",
    ".ps1",
    ".sh",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".css",
    ".html",
}


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name.startswith(".env")


def check_path(path: Path, root: Path) -> list[str]:
    rel = path.relative_to(root).as_posix()
    findings: list[str] = []
    parts = set(Path(rel).parts)
    if parts & FORBIDDEN_PATH_PARTS:
        findings.append(f"forbidden path component: {rel}")
    if rel.startswith("docs/governance/") or rel.startswith("docs/experiments/"):
        findings.append(f"private governance/experiment docs included: {rel}")
    if rel.startswith("scripts/personas/") or rel.startswith("scripts/eval/") or rel.startswith("scripts/frontend/"):
        findings.append(f"non-product test/eval helper included: {rel}")
    if path.suffix.lower() in FORBIDDEN_RUNTIME_SUFFIXES:
        findings.append(f"forbidden runtime artifact suffix: {rel}")
    if rel.startswith("data/eval_reports/") and path.name != ".gitkeep":
        findings.append(f"eval report artifact included: {rel}")
    if rel.startswith("data/sqlite/") and path.name != ".gitkeep":
        findings.append(f"sqlite artifact included: {rel}")
    if rel.startswith("models/") and path.name not in {".gitkeep", "README.md"}:
        findings.append(f"model artifact included: {rel}")
    return findings


def check_text(path: Path, root: Path) -> list[str]:
    if not is_text_file(path):
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    rel = path.relative_to(root).as_posix()
    findings = []
    for name, pattern in HIGH_RISK_PATTERNS.items():
        if pattern.search(text):
            findings.append(f"{name}: {rel}")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_dir", help="generated public export directory")
    args = parser.parse_args(argv)
    root = Path(args.export_dir).resolve()
    if not root.exists():
        print(f"Export directory does not exist: {root}", file=sys.stderr)
        return 2
    findings: list[str] = []
    for path in root.rglob("*"):
        if path.is_file():
            findings.extend(check_path(path, root))
            findings.extend(check_text(path, root))
    if findings:
        for finding in findings:
            print(f"PUBLIC_EXPORT_RISK\t{finding}")
        return 1
    print(f"Public export check passed: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
