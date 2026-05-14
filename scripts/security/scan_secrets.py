"""Scan tracked project files for secrets without printing secret values."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable


API_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |)PRIVATE KEY-----")
ENV_SECRET_RE = re.compile(
    r"^\s*(?:export\s+)?([A-Z0-9_]*(?:PASSWORD|API_KEY|TOKEN|SECRET|AUTHORIZATION_CODE)[A-Z0-9_]*)\s*=\s*(.*?)\s*$"
)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
WINDOWS_USER_PATH_RE = re.compile(r"(?i)\bC:\\Users\\[^\\\s]+")
ABSOLUTE_WINDOWS_PATH_RE = re.compile(r"(?i)\b[A-Z]:\\[^\n\r]*")

PLACEHOLDER_MARKERS = (
    "",
    "your_",
    "example",
    "placeholder",
    "change_me",
    "<",
    "${",
    "local.persona-rag",
)
IGNORED_DIR_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "models",
    "data/cache",
    "data/eval_reports",
    "data/runtime_logs",
    "data/screenshots",
    ".deploy",
}
BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".ico",
    ".pdf",
    ".zip",
    ".7z",
    ".dll",
    ".exe",
}
RAW_CONTEXT_PARTS = {
    "data/persona_sources",
    "github_research",
    "literature/papers",
}


@dataclass(frozen=True)
class Finding:
    severity: str
    kind: str
    path: str
    line: int
    message: str


def is_placeholder(value: str) -> bool:
    normalized = value.strip().strip('"').strip("'").lower()
    return any(marker in normalized for marker in PLACEHOLDER_MARKERS)


def is_ignored_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(part in normalized.split("/") or normalized.startswith(f"{part}/") for part in IGNORED_DIR_PARTS)


def is_raw_reference_context(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized == "uv.lock" or any(normalized.startswith(f"{part}/") for part in RAW_CONTEXT_PARTS)


def tracked_files() -> list[str]:
    output = subprocess.check_output(["git", "ls-files"], text=True, encoding="utf-8", errors="replace")
    return [line.strip() for line in output.splitlines() if line.strip()]


def iter_files(paths: Iterable[str]) -> Iterable[Path]:
    for raw in paths:
        if is_ignored_path(raw):
            continue
        path = Path(raw)
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        if path.is_file():
            yield path


def scan_text(text: str, path: str) -> list[Finding]:
    findings: list[Finding] = []
    raw_reference_context = is_raw_reference_context(path)
    for line_number, line in enumerate(text.splitlines(), 1):
        if API_KEY_RE.search(line):
            findings.append(
                Finding(
                    severity="high",
                    kind="api_key",
                    path=path,
                    line=line_number,
                    message="API key-like token is present.",
                )
            )
        if PRIVATE_KEY_RE.search(line):
            findings.append(
                Finding(
                    severity="high",
                    kind="private_key",
                    path=path,
                    line=line_number,
                    message="Private key header is present.",
                )
            )
        env_secret = ENV_SECRET_RE.match(line)
        if env_secret:
            key, value = env_secret.groups()
            if not is_placeholder(value):
                findings.append(
                    Finding(
                        severity="high",
                        kind="secret_assignment",
                        path=path,
                        line=line_number,
                        message=f"Non-placeholder value assigned to {key}.",
                    )
                )
        for email in EMAIL_RE.findall(line):
            if not raw_reference_context and not is_placeholder(email):
                findings.append(
                    Finding(
                        severity="low",
                        kind="email",
                        path=path,
                        line=line_number,
                        message="Email address is present.",
                    )
                )
        for ip_text in IP_RE.findall(line):
            try:
                ip = ipaddress.ip_address(ip_text)
            except ValueError:
                continue
            if ip.is_global and not raw_reference_context:
                findings.append(
                    Finding(
                        severity="medium",
                        kind="public_ip",
                        path=path,
                        line=line_number,
                        message="Public IP address is present.",
                    )
                )
        if raw_reference_context:
            continue
        if WINDOWS_USER_PATH_RE.search(line):
            findings.append(
                Finding(
                    severity="medium",
                    kind="windows_user_path",
                    path=path,
                    line=line_number,
                    message="Windows user path is present.",
                )
            )
        elif ABSOLUTE_WINDOWS_PATH_RE.search(line):
            findings.append(
                Finding(
                    severity="low",
                    kind="windows_absolute_path",
                    path=path,
                    line=line_number,
                    message="Windows absolute path is present.",
                )
            )
    return findings


def scan_files(paths: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        findings.extend(scan_text(text, str(path)))
    return findings


def format_finding(finding: Finding) -> str:
    return f"{finding.severity}\t{finding.kind}\t{finding.path}:{finding.line}\t{finding.message}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracked", action="store_true", help="scan files tracked by Git")
    parser.add_argument("--fail-on-high", action="store_true", help="exit 1 when high-severity findings exist")
    parser.add_argument("--json", action="store_true", help="write JSON findings")
    parser.add_argument("paths", nargs="*", help="extra files or directories to scan")
    args = parser.parse_args(argv)

    raw_paths: list[str] = []
    if args.tracked or not args.paths:
        raw_paths.extend(tracked_files())
    raw_paths.extend(args.paths)
    paths = list(iter_files(raw_paths))
    findings = scan_files(paths)

    if args.json:
        print(json.dumps([finding.__dict__ for finding in findings], ensure_ascii=False, indent=2))
    else:
        if not findings:
            print("No secret or personal-info findings.")
        for finding in findings:
            print(format_finding(finding))
    if args.fail_on_high and any(finding.severity == "high" for finding in findings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
