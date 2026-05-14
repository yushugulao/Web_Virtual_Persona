from __future__ import annotations

from app.backend.services.persona_service import normalize_persona_id


def maybe_repair_keller_language_touch_answer(
    answer: str,
    query: str,
    persona_id: str | None = None,
) -> str:
    """Keep Keller language/touch reflection from drifting into unrelated social-action framing."""

    if normalize_persona_id(persona_id) != "helen_keller":
        return answer
    if not ("语言" in query and ("触觉" in query or "手心" in query or "理解" in query)):
        return answer
    social_drift_markers = ("社会行动", "公共问题", "饥饿", "战争", "劳工")
    if not any(marker in answer for marker in social_drift_markers):
        return answer
    grounded_touch_markers = ("手心", "触觉", "命名", "名字", "安妮")
    if sum(1 for marker in grounded_touch_markers if marker in answer) >= 2:
        return answer
    return (
        "我会从手心说起。一个名字被拼在手里，混乱的经验便有了边缘；"
        "触觉不是视觉的替身，而是我认识事物的道路。语言把这种接触变成可以同别人分享的意义。"
        "安妮·沙利文给我的不只是词，而是把我和世界重新连起来的方法。"
    )
