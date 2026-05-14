"""Create a sanitized public-export tree for a fresh GitHub repository."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "dist" / "public-export"

COPY_ENTRIES = [
    "app",
    "configs",
    "corpus",
    "deploy",
    "scripts",
    ".editorconfig",
    ".env.example",
    ".env.windows.example",
    ".env.linux.example",
    ".gitattributes",
    ".gitignore",
    "pyproject.toml",
    "uv.lock",
]

PUBLIC_SCRIPT_DIRS = {
    "deploy",
    "dev",
    "document_reader",
    "models",
    "release",
    "security",
    "setup",
}

PUBLIC_SCRIPT_FILES = {
    ("scripts", "models", "check_models.ps1"),
    ("scripts", "models", "pull_models.ps1"),
    ("scripts", "models", "pull_required_models.ps1"),
    ("scripts", "models", "pull_required_models.sh"),
    ("scripts", "models", "set_model_cache_env.ps1"),
    ("scripts", "models", "smoke_generate.ps1"),
    ("scripts", "models", "start_ollama.ps1"),
}

EXCLUDE_PARTS = {
    ".git",
    ".venv",
    ".deploy",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    "dist",
    "secrets",
    "logs",
    "data",
    "models",
    "literature",
    "github_research",
    "tests",
    "evals",
    "docs/governance",
    "docs/experiments",
    "tools",
}

EXCLUDE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".db",
    ".sqlite",
    ".gguf",
    ".pem",
    ".key",
    ".exe",
    ".tsbuildinfo",
}

EXCLUDE_FILENAMES = {
    "vite.config.d.ts",
    "vite.config.js",
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
    ".env",
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


def should_skip(path: Path) -> bool:
    normalized = path.as_posix()
    parts = set(path.parts)
    if len(path.parts) >= 2 and path.parts[0] == "scripts":
        script_dir = path.parts[1]
        if script_dir not in PUBLIC_SCRIPT_DIRS and tuple(path.parts) not in PUBLIC_SCRIPT_FILES:
            return True
        if path.parts[:2] == ("scripts", "models"):
            allowed = tuple(path.parts) in PUBLIC_SCRIPT_FILES
            if not allowed:
                return True
        if path.name in EXCLUDE_FILENAMES:
            return True
        return path.suffix.lower() in EXCLUDE_SUFFIXES
    if parts & EXCLUDE_PARTS:
        return True
    if normalized.startswith("docs/governance/") or normalized.startswith("docs/experiments/"):
        return True
    if path.name in EXCLUDE_FILENAMES:
        return True
    return path.suffix.lower() in EXCLUDE_SUFFIXES


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name.startswith(".env")


def sanitize_text(text: str) -> str:
    text = text.replace("<PUBLIC_SERVER_IP>", "<PUBLIC_SERVER_IP>")
    text = text.replace("E:\\综合课程设计", "<PROJECT_ROOT>")
    text = re.sub(r"(?i)C:\\Users\\[^\\\s]+", r"<USER_HOME>", text)
    text = re.sub(r"(?i)[A-Z]:\\综合课程设计", "<PROJECT_ROOT>", text)
    text = re.sub(r"(?i)sk-[A-Za-z0-9_-]{20,}", "<API_KEY>", text)
    return text


def copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if is_text_file(source):
        try:
            text = source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copy2(source, target)
            return
        target.write_text(sanitize_text(text), encoding="utf-8", newline="\n")
    else:
        shutil.copy2(source, target)


def copy_entry(entry: str, output: Path) -> None:
    source = ROOT / entry
    if not source.exists():
        return
    target = output / entry
    if source.is_file():
        copy_file(source, target)
        return
    for item in source.rglob("*"):
        rel = item.relative_to(ROOT)
        if should_skip(rel):
            continue
        if item.is_file():
            copy_file(item, output / rel)


def write_public_docs(output: Path) -> None:
    public_docs = ROOT / "docs" / "public"
    docs_target = output / "docs"
    if public_docs.exists():
        for item in public_docs.rglob("*"):
            if item.is_file():
                rel = item.relative_to(public_docs)
                copy_file(item, docs_target / rel)
        readme = public_docs / "README.md"
        if readme.exists():
            copy_file(readme, output / "README.md")


def write_runtime_placeholders(output: Path) -> None:
    for directory in [
        "data/indexes",
        "data/sqlite",
        "data/feedback",
        "data/logs",
        "data/runtime_logs",
        "data/screenshots",
        "data/cache",
        "data/eval_reports",
        "models/ollama",
        "models/huggingface",
        "models/document_reader",
        "logs",
    ]:
        path = output / directory
        path.mkdir(parents=True, exist_ok=True)
        (path / ".gitkeep").write_text("", encoding="utf-8")
    copy_file(ROOT / "models" / "README.md", output / "models" / "README.md")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="export directory")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    for entry in COPY_ENTRIES:
        copy_entry(entry, output)
    write_public_docs(output)
    write_runtime_placeholders(output)
    print(f"Public export written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
