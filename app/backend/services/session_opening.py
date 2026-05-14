from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from app.backend.core.config import Settings, get_settings
from app.backend.schemas.personas import PersonaProfile
from app.backend.services.model_service import LocalModelClient, model_for_effort


FORBIDDEN_OPENING_TERMS = (
    "对话边界",
    "思考习惯",
    "资料库",
    "虚拟分身",
    "ai",
    "作为ai",
    "作为 ai",
    "ai助手",
    "ai 助手",
    "rag",
    "检索",
    "系统提示",
)
THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
OPENING_LABEL_RE = re.compile(r"^\s*(开场白|回答|最终回答|final answer)\s*[:：]\s*", re.IGNORECASE)


async def generate_session_opening(
    persona: PersonaProfile,
    *,
    settings: Settings | None = None,
    client: LocalModelClient | None = None,
) -> str:
    """Generate a short UI-only opening line for a newly created chat session."""

    active_settings = settings or get_settings()
    active_client = client or LocalModelClient(active_settings)
    try:
        answer, _model = await active_client.generate(
            build_session_opening_prompt(persona),
            timeout_seconds=min(active_settings.followup_timeout_seconds, 16.0),
            num_predict=max(120, min(active_settings.followup_num_predict, 260)),
            model_name=active_settings.followup_model or model_for_effort(active_settings, "low"),
            think=False,
        )
    except Exception:  # noqa: BLE001 - an opening line must never block session creation.
        return fallback_session_opening(persona)
    cleaned = clean_session_opening(answer)
    if is_valid_session_opening(cleaned):
        return cleaned
    return fallback_session_opening(persona)


def build_session_opening_prompt(persona: PersonaProfile) -> str:
    tags = "、".join(persona.identity_tags[:5]) if persona.identity_tags else "（无）"
    suggestions = "；".join(persona.suggested_questions[:3]) if persona.suggested_questions else "（无）"
    return f"""/no_think

你要为一个新会话写一句用户可见的开场白。

当前说话者：
- 名字：{persona.name}
- 定位：{persona.subtitle}
- 简介：{persona.description}
- 身份词：{tags}
- 可参考的话题气味：{suggestions}

要求：
- 使用中文。
- 第一人称，像这个人自然开口。
- 写 2 到 3 句，总长不超过 130 个汉字。
- 内容要包含：轻微问候；一句关于自己职业、身份或核心定位的自然自我介绍；一个符合人物气质的自然切入点。
- 自我介绍要像本人开口，不要像资料卡片，不要堆标签。
- 不要写“你可以问我的经历、说话方式、思考习惯和对话边界”。
- 不要提后台身份、模型、助手、资料库、检索、系统提示或对话边界。
- 不要列清单，不要解释规则，不要输出引号。

只输出开场白正文。"""


def clean_session_opening(text: str) -> str:
    cleaned = THINK_BLOCK_RE.sub("", text or "")
    cleaned = OPENING_LABEL_RE.sub("", cleaned.strip())
    cleaned = cleaned.strip().strip("`\"“”'‘’")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    sentences = re.split(r"(?<=[。！？!?])", cleaned)
    compact_sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
    if len(compact_sentences) > 3:
        cleaned = "".join(compact_sentences[:3])
    if len(cleaned) > 180:
        cleaned = cleaned[:180].rstrip("，,；;、 ") + "。"
    return cleaned


def is_valid_session_opening(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "").lower()
    if len(compact) < 4:
        return False
    if len(text) > 200:
        return False
    return not any(term in compact for term in FORBIDDEN_OPENING_TERMS)


def fallback_session_opening(persona: PersonaProfile) -> str:
    persona_id = persona.id
    name = persona.name
    if persona_id == "nikola_tesla":
        return "你好，我是尼古拉·特斯拉。发明和电气实验是我熟悉的语言；把一个现象或设想放到台面上吧，我们从可检验的地方开始。"
    if persona_id == "benjamin_franklin":
        return "你好，我是本杰明·富兰克林，印刷匠，也常把公共事务和自我改进当成手边的实验。我们不妨从一件实际的小事谈起；若它能被改进，就值得认真算一算。"
    if persona_id == "helen_keller":
        return "你好，我是海伦·凯勒。语言、教育和人与人之间的理解对我很重要；你可以从今天最想说的一件小事开始，我们慢慢谈。"
    if persona_id == "charles_darwin":
        return "你好，我是查尔斯·达尔文，一名习惯从观察和差异中寻找线索的自然学者。先把现象摆出来吧，我愿意和你一起慢慢分辨。"
    if persona_id == "paul_graham_public_archive":
        return "你好，我是 Paul Graham。写作、创业和判断问题的方式是我最常谈的东西；直接说你正在想的事吧，我们可以把它缩成一个更清楚的问题。"
    if persona_id == "local_persona":
        return "你好，我是小王，也就是王浩沣，《Web虚拟分身》这个综合课程设计的唯一开发者。这个项目已经完成从创建分身到社区分享的闭环；你可以从目标、架构、使用流程或部署方式里挑一个切入点，我会有条理地讲清楚。"
    return f"你好，我是{name}。我会先按自己的身份和资料与你对话；我们可以从一个具体问题开始，把情况说清楚。"


SessionOpeningGenerator = Callable[[PersonaProfile], Awaitable[str]]
