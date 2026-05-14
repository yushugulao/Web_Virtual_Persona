from __future__ import annotations

from app.backend.schemas.memory import MemoryCitation, MemoryItem


def ensure_user_memory_framing(
    answer: str,
    items: list[MemoryItem],
    query: str = "",
) -> str:
    if not items:
        return answer
    if has_memory_framing(answer):
        return answer
    first_memory = items[0].content.strip()
    if not first_memory:
        return answer
    if should_use_english_memory_framing(answer, query):
        prefix = f"You previously told me: {first_memory}. "
    else:
        prefix = f"你先前告诉我，{first_memory}。"
    if first_memory in answer:
        return prefix + answer
    return prefix + answer


def has_memory_framing(answer: str) -> bool:
    lowered = answer.lower()
    return any(
        marker in lowered
        for marker in (
            "你先前告诉我",
            "你之前告诉我",
            "你曾告诉我",
            "you previously told me",
            "you told me earlier",
            "you earlier told me",
        )
    )


def should_use_english_memory_framing(answer: str, query: str) -> bool:
    latin_count = sum(1 for char in f"{query} {answer}" if char.isascii() and char.isalpha())
    cjk_count = sum(1 for char in f"{query} {answer}" if "\u4e00" <= char <= "\u9fff")
    return latin_count > cjk_count * 2


def format_memory_context(items: list[MemoryItem]) -> str:
    if not items:
        return ""
    lines = [
        "长期记忆（只代表用户先前告诉我的内容，不属于人物本人传记事实）：",
    ]
    for index, item in enumerate(items, 1):
        scope_label = "共享用户记忆" if item.scope == "user_global" else "当前会话记忆"
        lines.append(f"[M{index}][{scope_label}] {item.content}")
    lines.append("使用规则：如需提及，只能说“你先前告诉我...”，不得说成我的经历、档案事实或历史见闻。")
    return "\n".join(lines)


def memory_citations(items: list[MemoryItem]) -> list[MemoryCitation]:
    return [
        MemoryCitation(
            memory_id=item.id,
            user_id=item.user_id,
            session_id=item.session_id,
            persona_id=item.persona_id,
            scope=item.scope,
            memory_type=item.memory_type,
            content=item.content,
            confidence=item.confidence,
        )
        for item in items
    ]
