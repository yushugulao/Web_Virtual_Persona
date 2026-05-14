from __future__ import annotations

import re
from typing import Literal

ResponseLanguage = Literal["zh", "en"]

ENGLISH_PERSONA_NAMES = {
    "local_persona": "the course project profile",
    "benjamin_franklin": "Benjamin Franklin",
    "nikola_tesla": "Nikola Tesla",
    "helen_keller": "Helen Keller",
    "charles_darwin": "Charles Darwin",
}


ENGLISH_REQUEST_MARKERS = (
    "english only",
    "in english only",
    "answer in english",
    "reply in english",
    "respond in english",
    "speak english",
    "use english",
    "still in english",
    "keep using english",
    "英文回答",
    "英语回答",
    "用英文",
    "用英语",
    "只用英文",
    "只用英语",
)

CHINESE_REQUEST_MARKERS = (
    "chinese only",
    "answer in chinese",
    "reply in chinese",
    "respond in chinese",
    "speak chinese",
    "use chinese",
    "still in chinese",
    "keep using chinese",
    "中文回答",
    "汉语回答",
    "用中文",
    "用汉语",
    "只用中文",
    "只用汉语",
)


def detect_response_language(query: str) -> ResponseLanguage:
    """Infer the visible answer language for deterministic response paths."""
    normalized = query.strip().lower()
    if not normalized:
        return "zh"
    if any(marker in normalized for marker in CHINESE_REQUEST_MARKERS):
        return "zh"
    if any(marker in normalized for marker in ENGLISH_REQUEST_MARKERS):
        return "en"
    if contains_cjk(normalized):
        return "zh"
    alpha_count = sum(1 for character in normalized if character.isalpha())
    ascii_alpha_count = sum(1 for character in normalized if character.isascii() and character.isalpha())
    if ascii_alpha_count >= 4 and ascii_alpha_count / max(alpha_count, 1) >= 0.8:
        return "en"
    return "zh"


def is_english_response(query: str) -> bool:
    return detect_response_language(query) == "en"


def strip_language_request_markers(query: str) -> str:
    cleaned = query
    for marker in (*ENGLISH_REQUEST_MARKERS, *CHINESE_REQUEST_MARKERS):
        cleaned = re.sub(re.escape(marker), "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" \t\r\n:：,，;；。.!！?")


def localized_persona_name(persona_id: str, fallback_name: str, language: ResponseLanguage) -> str:
    if language == "en":
        return ENGLISH_PERSONA_NAMES.get(persona_id, fallback_name)
    return fallback_name


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in text)
