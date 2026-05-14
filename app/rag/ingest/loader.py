from pathlib import Path


def iter_markdown_files(corpus_dir: Path) -> list[Path]:
    if not corpus_dir.exists():
        return []
    return sorted(path for path in corpus_dir.rglob("*.md") if path.is_file())


def read_markdown(path: Path) -> str:
    return path.read_text(encoding="utf-8")

