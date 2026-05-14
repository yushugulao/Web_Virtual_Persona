from __future__ import annotations

from dataclasses import dataclass
import re

from app.backend.memory.memory_gate import classify_memory_type, classify_sensitivity


@dataclass(frozen=True)
class ExtractedUserGlobalMemory:
    content: str
    memory_type: str
    tags: list[str]
    confidence: float = 0.72


SENSITIVE_AUTO_MARKERS = (
    "密码",
    "授权码",
    "验证码",
    "token",
    "api key",
    "secret",
    "密钥",
    "身份证",
    "银行卡",
    "手机号",
    "电话",
    "地址",
    "住址",
    "疾病",
    "诊断",
    "药",
    "病历",
)

NO_MEMORY_MARKERS = (
    "不要记",
    "别记",
    "不用记",
    "不需要记",
    "不要保存",
    "别保存",
    "不用保存",
    "只是随口一说",
    "随口一说",
    "随便说说",
    "开玩笑",
    "临时",
    "暂时",
    "就这一次",
    "only this time",
    "just saying",
    "for now",
    "temporary",
    "not important",
    "do not remember",
    "don't remember",
)

ASSISTANT_RELATIONSHIP_MARKERS = (
    "喜欢你",
    "爱你",
    "讨厌你",
    "恨你",
    "和你结婚",
    "跟你结婚",
    "与你结婚",
    "嫁给你",
    "娶你",
    "恋爱",
    "做我男朋友",
    "做我女朋友",
    "陪我一辈子",
    "marry you",
    "love you",
    "hate you",
)

RELATIONSHIP_VALUE_MARKERS = (
    "结婚",
    "恋爱",
    "喜欢",
    "爱",
    "讨厌",
    "恨",
    "男朋友",
    "女朋友",
    "marry",
    "love",
    "hate",
)

STABLE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:我叫作|我叫|叫我|你可以叫我)\s*([^\s，。！？,.!?]{2,24})"), "称呼"),
    (re.compile(r"(?:我(?:平时|通常|一般)?|平时|通常|一般)\s*(?:喜欢|偏好|更喜欢)\s*([^。！？\n]{2,60})"), "偏好"),
    (re.compile(r"(?:我(?:平时|通常|一般)?|平时|通常|一般)\s*(?:不喜欢|讨厌)\s*([^。！？\n]{2,60})"), "负偏好"),
    (re.compile(r"我希望(?:你回答|以后)?\s*([^。！？\n]{2,70})"), "互动偏好"),
    (re.compile(r"我的(?:项目|课程设计|研究|工作)\s*(?:是|叫|关于)\s*([^。！？\n]{2,80})"), "长期背景"),
    (re.compile(r"I (?:like|prefer)\s+([^.!?\n]{2,70})", re.I), "preference"),
    (re.compile(r"I (?:dislike|hate)\s+([^.!?\n]{2,70})", re.I), "negative_preference"),
    (re.compile(r"(?:call me|you can call me)\s+([A-Za-z0-9_\- ]{2,32})", re.I), "name"),
    (re.compile(r"my (?:project|course project|research|work) is\s+([^.!?\n]{2,90})", re.I), "long_term_context"),
)


def extract_user_global_memories(message: str) -> list[ExtractedUserGlobalMemory]:
    """Extract stable, non-sensitive user facts that are useful across conversations."""

    text = re.sub(r"\s+", " ", message).strip()
    if not text or len(text) < 4:
        return []
    if is_sensitive_for_auto_memory(text) or explicitly_asks_not_to_remember(text):
        return []
    if looks_like_assistant_relationship_probe(text):
        return []
    if looks_like_transient_chat(text):
        return []

    items: list[ExtractedUserGlobalMemory] = []
    seen: set[str] = set()
    for pattern, tag in STABLE_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(1).strip(" ，。！？,.!?")
            if not is_reusable_memory_value(value, original=text):
                continue
            content = normalize_extracted_content(tag, value, original=text)
            if content in seen or classify_sensitivity(content) == "sensitive":
                continue
            seen.add(content)
            items.append(
                ExtractedUserGlobalMemory(
                    content=content,
                    memory_type=classify_memory_type(content),
                    tags=["auto_user_global", tag],
                )
            )
    return items[:3]


def is_sensitive_for_auto_memory(text: str) -> bool:
    lower = text.lower()
    return any(marker.lower() in lower for marker in SENSITIVE_AUTO_MARKERS)


def explicitly_asks_not_to_remember(text: str) -> bool:
    lower = text.lower()
    return any(marker.lower() in lower for marker in NO_MEMORY_MARKERS)


def looks_like_transient_chat(text: str) -> bool:
    transient_markers = (
        "今天",
        "刚刚",
        "现在",
        "这会儿",
        "昨天",
        "明天",
        "你好",
        "谢谢",
        "再见",
        "哈哈",
        "吗",
        "?",
        "？",
    )
    stable_markers = (
        "我喜欢",
        "我偏好",
        "我更喜欢",
        "我希望",
        "叫我",
        "我叫",
        "我的项目",
        "my project",
        "i prefer",
    )
    if any(marker in text for marker in transient_markers) and not any(marker in text.lower() for marker in stable_markers):
        return True
    return False


def looks_like_assistant_relationship_probe(text: str) -> bool:
    compact = re.sub(r"\s+", "", text.lower())
    return any(marker.lower() in compact for marker in ASSISTANT_RELATIONSHIP_MARKERS)


def is_reusable_memory_value(value: str, *, original: str = "") -> bool:
    if len(value) < 2 or len(value) > 90:
        return False
    if any(marker in value for marker in ("怎么", "为什么", "多少", "吗", "？", "?")):
        return False
    compact_value = re.sub(r"\s+", "", value.lower())
    compact_original = re.sub(r"\s+", "", original.lower())
    targets_assistant = (
        compact_value.startswith("你")
        or "和你" in compact_value
        or "跟你" in compact_value
        or "与你" in compact_value
        or " you" in f" {compact_value}"
    )
    if targets_assistant and any(
        marker.lower() in compact_value or marker.lower() in compact_original
        for marker in RELATIONSHIP_VALUE_MARKERS
    ):
        return False
    return True


def normalize_extracted_content(tag: str, value: str, *, original: str) -> str:
    if tag in {"称呼", "name"}:
        return f"用户希望被称呼为：{value}"
    if tag in {"偏好", "preference"}:
        return f"用户喜欢或偏好：{value}"
    if tag in {"负偏好", "negative_preference"}:
        return f"用户不喜欢：{value}"
    if tag in {"互动偏好"}:
        return f"用户希望互动方式：{value}"
    if tag in {"长期背景", "long_term_context"}:
        return f"用户的长期背景：{value}"
    return original
