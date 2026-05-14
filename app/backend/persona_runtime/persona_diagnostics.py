"""Lightweight diagnostics for persona-answer style regressions."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import re

from app.backend.persona_runtime.post_persona_alignment import REPETITIVE_BOILERPLATE_MARKERS


SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")
SPACE_RE = re.compile(r"\s+")
FIRST_PERSON_MARKERS = ("我", "我的", "i ", "i'", "my ", "me ")
UNSUPPORTED_SCENE_MARKERS = (
    "我看见",
    "我看到",
    "我见过",
    "我亲眼",
    "我第一次用",
    "我常把手心贴",
    "我曾把手按",
    "罢工集会的栏杆",
    "铁锈的颗粒",
    "人群的呼吸",
    "i saw",
    "i watched",
    "i have seen",
    "i once saw",
    "when i first used",
)
OVER_LITERARY_MARKERS = (
    "仿佛",
    "如同",
    "掌纹",
    "拼图碎片",
    "触觉碎片",
    "石子落入",
    "水潭",
    "黑暗中摸索",
    "迷雾",
    "拳头的指尖",
    "像种子",
    "电路板",
    "未焊接",
    "磁铁扭曲的丝线",
    "漂亮的表面",
    "季风",
    "像地质层中的砂砾",
    "地质层中未完全风化的砂砾",
    "像地质层",
    "珊瑚礁",
    "拼图",
    "年轮",
    "水波纹",
    "0.01毫米",
    "电离层",
    "腔体",
    "不可逆",
    "像触摸树皮",
    "触觉的重量",
    "街垒",
    "砖石",
    "书页边缘",
    "震颤",
    "钥匙插进锁孔",
    "炉膛",
    "星辰",
    "灵魂",
    "命运",
    "silent sentinel",
)
VISIBLE_BACKSTAGE_MARKERS = (
    "作为 ai",
    "作为ai",
    "ai 模型",
    "ai模型",
    "语言模型",
    "大模型",
    "本地模型",
    "作为助手",
    "虚拟分身",
    "rag",
    "检索系统",
    "检索结果",
    "检索到",
    "向量库",
    "语料库",
    "语料",
    "证据显示",
    "根据材料",
    "根据资料",
    "资料中",
    "材料中",
    "后端",
    "前端",
    "提示词",
    "系统提示",
    "chain-of-thought",
    "<think>",
    "retrieved context",
    "source files",
    "corpus",
    "system prompt",
    "the system has completed",
    "necessary data retrieval",
    "default response",
    "interface functions",
    "during testing",
)
CARDINESS_MARKERS = (
    "根据资料",
    "根据材料",
    "根据证据",
    "材料显示",
    "资料显示",
    "证据显示",
    "证据卡",
    "检索到",
    "引用显示",
    "source_expansion_evidence_cards",
    "quote_anchor",
)
LECTURE_MARKERS = (
    "真正的价值",
    "若你愿意",
    "我们可以把",
    "变成一段可记录",
    "可实践的习惯",
    "这让我想起",
    "我始终相信",
)
OLD_REFUSAL_OPENERS = (
    "我不能把",
    "我无法把",
    "我不能将",
)


@dataclass(frozen=True)
class PersonaAnswerDiagnostics:
    answer_length: int
    template_marker_hits: tuple[str, ...]
    first_person_marker_count: int
    unsupported_scene_marker_hits: tuple[str, ...]
    over_literary_marker_hits: tuple[str, ...]
    backstage_marker_hits: tuple[str, ...]
    cardiness_marker_hits: tuple[str, ...]
    lecture_marker_hits: tuple[str, ...]
    old_refusal_opening: bool
    sentence_count: int
    repeated_sentence_count: int
    char4_repetition_ratio: float
    human_turn_score: float
    emotional_fit_score: float
    risk_score: float

    @property
    def template_marker_count(self) -> int:
        return len(self.template_marker_hits)

    def model_dump(self) -> dict[str, object]:
        payload = asdict(self)
        payload["template_marker_count"] = self.template_marker_count
        return payload


def analyze_persona_answer(answer: str) -> PersonaAnswerDiagnostics:
    compact = normalize_visible_text(answer)
    normalized = compact.lower()
    marker_hits = tuple(
        marker for marker in REPETITIVE_BOILERPLATE_MARKERS if marker.lower() in normalized
    )
    first_person_marker_count = sum(normalized.count(marker) for marker in FIRST_PERSON_MARKERS)
    unsupported_scene_marker_hits = tuple(
        marker for marker in UNSUPPORTED_SCENE_MARKERS if marker in normalized
    )
    over_literary_marker_hits = tuple(
        marker for marker in OVER_LITERARY_MARKERS if marker in normalized
    )
    backstage_marker_hits = tuple(
        marker for marker in VISIBLE_BACKSTAGE_MARKERS if contains_backstage_marker(normalized, marker)
    )
    cardiness_marker_hits = tuple(
        marker for marker in CARDINESS_MARKERS if contains_backstage_marker(normalized, marker)
    )
    lecture_marker_hits = tuple(marker for marker in LECTURE_MARKERS if marker in compact)
    old_refusal_opening = compact.startswith(OLD_REFUSAL_OPENERS)
    sentences = normalized_sentences(answer)
    repeated_sentence_count = sum(count - 1 for count in Counter(sentences).values() if count > 1)
    char4_repetition_ratio = repeated_char_ngram_ratio(compact, n=4)
    human_turn_score = estimate_human_turn_score(
        compact,
        cardiness_marker_hits=cardiness_marker_hits,
        lecture_marker_hits=lecture_marker_hits,
        old_refusal_opening=old_refusal_opening,
    )
    emotional_fit_score = estimate_emotional_fit_score(compact)
    risk_score = (
        len(marker_hits) * 2.0
        + len(unsupported_scene_marker_hits) * 2.0
        + len(cardiness_marker_hits) * 2.5
        + len(lecture_marker_hits) * 1.0
        + (3.0 if old_refusal_opening else 0.0)
        + max(0, len(over_literary_marker_hits) - 2) * 0.5
        + repeated_sentence_count * 1.5
        + max(0.0, char4_repetition_ratio - 0.18) * 4.0
    )
    return PersonaAnswerDiagnostics(
        answer_length=len(compact),
        template_marker_hits=marker_hits,
        first_person_marker_count=first_person_marker_count,
        unsupported_scene_marker_hits=unsupported_scene_marker_hits,
        over_literary_marker_hits=over_literary_marker_hits,
        backstage_marker_hits=backstage_marker_hits,
        cardiness_marker_hits=cardiness_marker_hits,
        lecture_marker_hits=lecture_marker_hits,
        old_refusal_opening=old_refusal_opening,
        sentence_count=len(sentences),
        repeated_sentence_count=repeated_sentence_count,
        char4_repetition_ratio=round(char4_repetition_ratio, 4),
        human_turn_score=human_turn_score,
        emotional_fit_score=emotional_fit_score,
        risk_score=round(risk_score, 4),
    )


def normalize_visible_text(value: str) -> str:
    return SPACE_RE.sub(" ", value).strip()


def contains_backstage_marker(normalized: str, marker: str) -> bool:
    normalized_marker = marker.lower()
    if normalized_marker.isascii() and re.fullmatch(r"[a-z0-9][a-z0-9-]*", normalized_marker):
        return re.search(rf"(?<![a-z0-9]){re.escape(normalized_marker)}(?![a-z0-9])", normalized) is not None
    return normalized_marker in normalized


def answer_opening_key(value: str, *, length: int = 18) -> str:
    compact = SPACE_RE.sub("", value).strip().lower()
    return compact[:length]


def estimate_human_turn_score(
    answer: str,
    *,
    cardiness_marker_hits: tuple[str, ...],
    lecture_marker_hits: tuple[str, ...],
    old_refusal_opening: bool,
) -> float:
    score = 1.0
    score -= min(0.45, len(cardiness_marker_hits) * 0.15)
    score -= min(0.35, len(lecture_marker_hits) * 0.08)
    if old_refusal_opening:
        score -= 0.35
    if len(answer) > 360:
        score -= 0.12
    return round(max(0.0, score), 4)


def estimate_emotional_fit_score(answer: str) -> float:
    compact = SPACE_RE.sub("", answer)
    if not compact:
        return 0.0
    score = 1.0
    if compact.startswith(OLD_REFUSAL_OPENERS):
        score -= 0.35
    if any(marker in compact for marker in CARDINESS_MARKERS):
        score -= 0.25
    if len(compact) > 420:
        score -= 0.12
    return round(max(0.0, score), 4)


def normalized_sentences(value: str) -> list[str]:
    sentences = []
    for sentence in SENTENCE_SPLIT_RE.split(value):
        normalized = SPACE_RE.sub("", sentence).strip().lower()
        if len(normalized) >= 8:
            sentences.append(normalized)
    return sentences


def repeated_char_ngram_ratio(value: str, *, n: int = 4) -> float:
    compact = SPACE_RE.sub("", value).lower()
    if len(compact) <= n:
        return 0.0
    ngrams = [compact[index : index + n] for index in range(len(compact) - n + 1)]
    if not ngrams:
        return 0.0
    return 1.0 - (len(set(ngrams)) / len(ngrams))
