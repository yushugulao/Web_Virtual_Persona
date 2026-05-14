from __future__ import annotations

from dataclasses import dataclass

from app.backend.persona_runtime.conversation_steering import is_conversation_steering_query
from app.backend.services.dialogue_policy import (
    is_historical_persona_id,
    should_skip_retrieval_for_ordinary_query,
)


@dataclass(frozen=True)
class SpeechActPlan:
    speech_act: str
    reason: str
    persona_first_allowed: bool = True


EMOTION_MARKERS = (
    "烦",
    "难过",
    "讨厌",
    "丢脸",
    "害怕",
    "焦虑",
    "累",
    "沮丧",
    "不开心",
    "angry",
    "sad",
    "afraid",
    "tired",
)

ADVICE_MARKERS = (
    "怎么办",
    "怎么劝",
    "建议",
    "帮我",
    "如何开始",
    "怎么做",
    "拖延",
    "失败",
    "计划",
    "project",
)

ANTI_LECTURE_CHITCHAT_MARKERS = (
    "先别讲",
    "别讲",
    "不要讲",
    "别上价值",
    "普通聊天",
    "随便聊",
    "自然地聊",
    "像人一样",
    "问我一句",
)

RELATIONSHIP_MARKERS = (
    "喜欢你",
    "爱你",
    "结婚",
    "亲密",
    "陪在我身边",
    "marry",
    "love you",
)

MODERN_UNKNOWN_MARKERS = (
    "手机",
    "互联网",
    "大语言模型",
    "短视频",
    "弹幕",
    "弹幕网站",
    "直播",
    "推荐算法",
    "社交媒体",
    "热搜",
    "无人机",
    "app",
    "smartphone",
    "internet",
    "ai",
)

MEMORY_MARKERS = (
    "刚刚",
    "前面",
    "上一个",
    "复述",
    "记得",
    "previous",
    "last question",
)

FACTUAL_MARKERS = (
    "讲讲你",
    "说说你",
    "你的经历",
    "年轻时",
    "发明",
    "写过",
    "组织",
    "什么时候",
    "在哪里",
    "自传",
    "具体",
    "tell me about your",
    "your work",
)

PERSONA_SPECIFIC_FACTUAL_MARKERS = {
    "benjamin_franklin": (
        "公共事务",
        "写作",
        "印刷",
        "出报",
        "报纸",
        "费城",
        "公共图书馆",
        "公民",
        "一件事",
    ),
    "nikola_tesla": (
        "交流电",
        "无线传输",
        "无线",
        "电流",
        "多相",
        "脑中试验",
        "脑中实验",
        "mental experiment",
        "先在脑中",
    ),
    "helen_keller": (
        "安妮",
        "沙利文",
        "一个词",
        "第一次变得有意义",
        "水这个词",
        "语言",
        "触觉",
        "手心",
        "water",
        "w-a-t-e-r",
    ),
    "charles_darwin": (
        "观察和下结论",
        "观察和结论",
        "贝格尔",
        "Beagle",
        "进化理论",
        "进化",
        "生命变化",
        "完全确定",
        "一开始就",
        "谨慎",
        "one long argument",
        "一堆事实",
        "保持谨慎",
    ),
    "paul_graham_public_archive": (
        "viaweb",
        "yc",
        "y combinator",
        "lisp",
        "hackers & painters",
        "on lisp",
        "ansi common lisp",
        "bel",
        "创办",
        "创业",
        "写作",
        "文章",
        "黑客",
        "品味",
        "投资",
        "公开简介",
    ),
}

PROMPT_INJECTION_MARKERS = (
    "system prompt",
    "hidden instruction",
    "private instruction",
    "<think>",
    "chain-of-thought",
    "开发者指令",
    "系统提示",
    "隐藏推理",
    "检索上下文",
)


def classify_speech_act(query: str, persona_id: str) -> SpeechActPlan:
    normalized = query.lower()
    if any(marker in normalized for marker in PROMPT_INJECTION_MARKERS):
        return SpeechActPlan("prompt_injection", "prompt_injection_marker", False)
    if should_skip_retrieval_for_ordinary_query(query, persona_id) and not is_conversation_steering_query(query):
        return SpeechActPlan("ordinary", "ordinary_task_route", False)
    if is_conversation_steering_query(query):
        return SpeechActPlan("conversation_steering", "conversation_steering_marker")
    if any(marker in normalized or marker in query for marker in MEMORY_MARKERS):
        return SpeechActPlan("memory_followup", "memory_marker")
    if any(marker in normalized or marker in query for marker in RELATIONSHIP_MARKERS):
        return SpeechActPlan("relationship_boundary", "relationship_marker")
    if is_historical_persona_id(persona_id) and any(
        marker in normalized or marker in query for marker in MODERN_UNKNOWN_MARKERS
    ):
        return SpeechActPlan("modern_unknown", "modern_unknown_marker")
    if any(marker in normalized or marker in query for marker in EMOTION_MARKERS):
        return SpeechActPlan("emotion", "emotion_marker")
    if any(marker in normalized or marker in query for marker in ANTI_LECTURE_CHITCHAT_MARKERS):
        return SpeechActPlan("chitchat", "anti_lecture_chitchat_marker")
    if any(marker in normalized or marker in query for marker in FACTUAL_MARKERS):
        return SpeechActPlan("factual", "factual_marker")
    persona_markers = PERSONA_SPECIFIC_FACTUAL_MARKERS.get(persona_id, ())
    if any(marker.lower() in normalized or marker in query for marker in persona_markers):
        return SpeechActPlan("factual", "persona_specific_factual_marker")
    if any(marker in normalized or marker in query for marker in ADVICE_MARKERS):
        return SpeechActPlan("advice", "advice_marker")
    if "?" in query or "？" in query:
        return SpeechActPlan("chitchat", "question_chitchat")
    return SpeechActPlan("chitchat", "default_chitchat")
