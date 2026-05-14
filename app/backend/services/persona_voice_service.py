from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.backend.services.persona_service import DEFAULT_PERSONA_ID, normalize_persona_id


VOICE_STYLE_FILENAME = "voice_style.md"
MAX_PROMPT_CHARS = 2600


@lru_cache(maxsize=32)
def load_persona_voice_style(persona_id: str | None) -> str:
    """Load a reviewed persona voice file for prompt-only style control."""
    effective_persona_id = normalize_persona_id(persona_id)
    if effective_persona_id == DEFAULT_PERSONA_ID:
        return ""

    path = Path("corpus") / "personas" / effective_persona_id / VOICE_STYLE_FILENAME
    if not path.exists():
        return ""
    return strip_frontmatter(path.read_text(encoding="utf-8")).strip()


def format_persona_voice_style_for_prompt(persona_id: str | None) -> str:
    voice_style = load_persona_voice_style(persona_id)
    if not voice_style:
        return ""
    if len(voice_style) <= MAX_PROMPT_CHARS:
        return voice_style
    return f"{voice_style[:MAX_PROMPT_CHARS].rstrip()}\n..."


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    if end == -1:
        return text
    return text[end + 4 :].lstrip()
