from __future__ import annotations

from dataclasses import dataclass
import re


REMEMBER_RE = re.compile(r"^\s*(?:请)?记住[:：]\s*(?P<content>.+?)\s*$", re.S)
CORRECTION_RE = re.compile(r"^\s*(?:更正|纠正)[:：]\s*(?P<content>.+?)\s*$", re.S)
SENSITIVE_MARKERS = (
    "密码",
    "身份证",
    "手机号",
    "手机号码",
    "银行卡",
    "住址",
    "地址",
    "token",
    "api key",
    "密钥",
    "疾病",
    "诊断",
    "药",
)


@dataclass(frozen=True)
class MemoryWriteDecision:
    content: str
    status: str
    sensitivity: str
    memory_type: str
    reason: str


def detect_explicit_memory_write(message: str) -> MemoryWriteDecision | None:
    correction = CORRECTION_RE.match(message)
    if correction:
        content = correction.group("content").strip()
        sensitivity = classify_sensitivity(content)
        status = "pending" if sensitivity == "sensitive" or len(content) < 4 else "approved"
        return MemoryWriteDecision(
            content=content,
            status=status,
            sensitivity=sensitivity,
            memory_type="correction",
            reason="explicit_correction",
        )
    match = REMEMBER_RE.match(message)
    if not match:
        return None
    content = match.group("content").strip()
    sensitivity = classify_sensitivity(content)
    status = "pending" if sensitivity == "sensitive" or len(content) < 4 else "approved"
    return MemoryWriteDecision(
        content=content,
        status=status,
        sensitivity=sensitivity,
        memory_type=classify_memory_type(content),
        reason="explicit_remember",
    )


def classify_sensitivity(content: str) -> str:
    lower = content.lower()
    if any(marker in lower for marker in SENSITIVE_MARKERS):
        return "sensitive"
    return "normal"


def classify_memory_type(content: str) -> str:
    if any(marker in content for marker in ("喜欢", "讨厌", "偏好", "希望", "不喜欢")):
        return "user_profile"
    if any(marker in content for marker in ("我们", "关系", "称呼")):
        return "relationship"
    if any(marker in content for marker in ("项目", "课程设计", "任务")):
        return "semantic"
    return "user_profile"
