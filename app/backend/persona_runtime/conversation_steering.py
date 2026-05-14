from __future__ import annotations

from app.backend.services.dialogue_policy import maybe_build_basic_arithmetic_answer
from app.backend.services.response_language import detect_response_language
from app.backend.services.conversation_memory import normalize_recall_query


QUESTION_ONLY_MARKERS = (
    "问我一句",
    "问我一个",
    "问个普通",
    "普通的问题",
    "普通问题",
    "just ask",
    "ask me a normal",
    "ask one question",
)

CASUAL_STEERING_MARKERS = (
    "随便聊聊",
    "闲聊",
    "只想闲聊",
    "普通聊天",
    "像朋友一样",
    "跟我说两句",
    "陪我聊",
    "说人话",
    "别端着",
    "端着",
    "不要端着",
    "资料卡",
    "资料卡片",
    "像资料",
    "像卡片",
    "像老师",
    "讲课",
    "说教",
    "太机械",
    "太僵硬",
    "模板",
    "背稿",
    "别引用",
    "不要引用",
    "少引用",
    "别用名言",
    "不要名言",
    "别讲道理",
    "不要讲道理",
    "不想听大道理",
    "别讲大道理",
    "别安慰成作文",
    "别写作文",
    "不要作文",
    "别鸡汤",
    "不要鸡汤",
    "短一点",
    "简短一点",
    "不要展开",
    "别展开",
    "先别讲",
    "别讲",
    "don't lecture",
    "no lecture",
    "keep it short",
    "talk like a friend",
    "talk normally",
    "too preachy",
    "sounds like a lecture",
)

NO_ADVICE_MARKERS = (
    "不要给建议",
    "别给建议",
    "不用给建议",
    "不要劝",
    "别劝",
    "no advice",
)

APOLOGY_REPAIR_MARKERS = (
    "对不起",
    "抱歉",
    "不好意思",
    "刚刚说得有点重",
    "刚才说得有点重",
    "我说得有点重",
    "说重了",
    "开玩笑",
    "不是故意",
    "sorry",
    "apologize",
    "didn't mean it",
)

STYLE_COMPLAINT_MARKERS = (
    "资料卡",
    "资料卡片",
    "像资料",
    "像卡片",
    "别端着",
    "端着",
    "说人话",
    "像老师",
    "讲课",
    "说教",
    "太机械",
    "太僵硬",
    "模板",
    "背稿",
    "别引用",
    "不要引用",
    "少引用",
    "别用名言",
    "不要名言",
    "too preachy",
    "sounds like a lecture",
    "talk normally",
)

EMOTION_STEERING_MARKERS = (
    "烦",
    "难过",
    "焦虑",
    "累",
    "崩溃",
    "不开心",
    "考试没考好",
    "没考好",
    "考砸",
    "挂科",
    "分数",
    "tired",
    "sad",
    "anxious",
    "upset",
)

LANGUAGE_TASK_MARKERS = (
    "翻译",
    "译成",
    "translate",
)

PERSONA_STEERING_QUESTIONS = {
    "benjamin_franklin": "好，我只问一句平常的：你今天遇到什么有点好笑，或者有点烦的小事？",
    "nikola_tesla": "好，我只问一句普通的：你今天最想安静处理的一件事是什么？",
    "helen_keller": "好，我轻轻问一句：你今天最想有人认真听你说哪件事？",
    "charles_darwin": "好，短一点：你今天最先注意到的一件小事是什么？",
}

PERSONA_NO_ADVICE_ANSWERS = {
    "benjamin_franklin": "好，不讲表，也不劝。你今天遇到什么有点好笑，或者有点烦的小事？",
    "nikola_tesla": "好，不讲装置，也不给方案。你现在脑子里最吵的那件事是什么？",
    "helen_keller": "好，我不劝你。你只说一件事就行：今天哪一刻最让你不舒服？",
    "charles_darwin": "好，我不下结论。你只说一个小现象：今天什么事最占着你的心？",
}

PERSONA_EMOTION_STEERING_ANSWERS = {
    "benjamin_franklin": "好，我不讲道理。你先把这股烦劲放在桌上，不急着整理。最烦你的，是人，还是事？",
    "nikola_tesla": "好，我不分析它。先把声音降下来：此刻最刺耳的，是外面的事，还是你脑子里的那根线？",
    "helen_keller": "好，我先陪你待一会儿，不急着劝。你愿意告诉我，最难受的是哪一句话，还是哪件事吗？",
    "charles_darwin": "好，我们先不解释。只看眼前这一点：最让你烦的，是刚发生的事，还是一直拖着的事？",
}

PERSONA_SHORT_ANSWERS = {
    "benjamin_franklin": "好，短一点。你现在最想先说哪一句？",
    "nikola_tesla": "好，短一点。现在最扰乱你的，是哪一个点？",
    "helen_keller": "好，短一点。我在听，你先说最重的那一句。",
    "charles_darwin": "好，短一点。我们先看一个小事实：你最在意什么？",
}

PERSONA_STYLE_REPAIR_ANSWERS = {
    "benjamin_franklin": "好，我收短一点，不端着。你把最想说的那一句扔过来，我先照着人话接住。",
    "nikola_tesla": "好，我把架子放下。现在不谈装置，也不谈原理；你只说眼前最吵的那一点。",
    "helen_keller": "好，我把话说近一点。我在听，不写长篇；你先把最真实的那一句给我。",
    "charles_darwin": "你说得对，我刚才像在分类，不像在聊天。我们先放下结论，只说一件今天的小事。",
}

PERSONA_APOLOGY_REPAIR_ANSWERS = {
    "benjamin_franklin": "没关系，先翻篇。刚才那一下我接住了，我们从这里重新说。",
    "nikola_tesla": "没关系，我不会抓着那句话不放。我们把噪声降下来，重新接上。",
    "helen_keller": "没关系。我听见的是你愿意回来好好说，这就够了。",
    "charles_darwin": "没关系，情绪本来也会先于判断冒出来。我们重新观察眼前这一刻就好。",
}

PERSONA_EMOTION_NO_ADVICE_ANSWERS = {
    "benjamin_franklin": "先不写成安慰人的小册子，也不急着给办法。没考好这一下确实难受；最扎你的，是分数，还是怕别人怎么看？",
    "nikola_tesla": "好，不讲方案。先承认这一下很刺耳；你现在脑子里反复响的，是哪一句话？",
    "helen_keller": "好，我不把它写成作文，也不劝你立刻振作。你只说最难受的那一点，我在这儿听。",
    "charles_darwin": "好，先不解释，也不下结论。只看眼前这个事实：这次没考好最让你不安的是哪一处？",
}


def is_conversation_steering_query(query: str) -> bool:
    compact = normalize_recall_query(query)
    normalized = query.lower()
    if not compact and not normalized:
        return False
    if maybe_build_basic_arithmetic_answer(query, language=detect_response_language(query)) is not None:
        return False
    if any(marker in compact or marker in normalized for marker in LANGUAGE_TASK_MARKERS):
        return False
    if any(marker in compact or marker in normalized for marker in APOLOGY_REPAIR_MARKERS):
        return True
    if any(marker in compact or marker in normalized for marker in STYLE_COMPLAINT_MARKERS):
        return True
    if any(marker in compact or marker in normalized for marker in QUESTION_ONLY_MARKERS):
        return True
    if any(marker in compact or marker in normalized for marker in CASUAL_STEERING_MARKERS):
        return True
    return any(marker in compact or marker in normalized for marker in NO_ADVICE_MARKERS) and any(
        marker in compact or marker in normalized
        for marker in ("随便", "聊聊", "普通聊天", "朋友", "两句")
    )


def maybe_build_conversation_steering_answer(
    query: str,
    *,
    persona_id: str,
    speech_act: str,
) -> str | None:
    if speech_act != "conversation_steering" and not is_conversation_steering_query(query):
        return None
    if detect_response_language(query) == "en":
        return english_conversation_steering_answer(query)
    compact = normalize_recall_query(query)
    normalized = query.lower()
    persona_key = persona_id if persona_id in PERSONA_STEERING_QUESTIONS else "benjamin_franklin"
    if any(marker in compact or marker in normalized for marker in APOLOGY_REPAIR_MARKERS):
        return PERSONA_APOLOGY_REPAIR_ANSWERS[persona_key]
    if any(marker in compact or marker in normalized for marker in STYLE_COMPLAINT_MARKERS):
        return PERSONA_STYLE_REPAIR_ANSWERS[persona_key]
    if any(marker in compact or marker in normalized for marker in EMOTION_STEERING_MARKERS) and any(
        marker in compact or marker in normalized
        for marker in (
            "别安慰成作文",
            "别写作文",
            "不要作文",
            "别鸡汤",
            "不要鸡汤",
            "不要给建议",
            "别给建议",
            "不用给建议",
            "不要劝",
            "别劝",
        )
    ):
        return PERSONA_EMOTION_NO_ADVICE_ANSWERS[persona_key]
    if any(marker in compact or marker in normalized for marker in QUESTION_ONLY_MARKERS):
        return PERSONA_STEERING_QUESTIONS[persona_key]
    if any(marker in compact or marker in normalized for marker in EMOTION_STEERING_MARKERS) and any(
        marker in compact or marker in normalized
        for marker in ("别讲道理", "不要讲道理", "像朋友一样", "跟我说两句", "陪我聊")
    ):
        return PERSONA_EMOTION_STEERING_ANSWERS[persona_key]
    if any(marker in compact or marker in normalized for marker in NO_ADVICE_MARKERS):
        return PERSONA_NO_ADVICE_ANSWERS[persona_key]
    if any(marker in compact or marker in normalized for marker in ("短一点", "简短一点", "不要展开", "别展开")):
        return PERSONA_SHORT_ANSWERS[persona_key]
    return PERSONA_STEERING_QUESTIONS[persona_key]


def english_conversation_steering_answer(query: str) -> str:
    normalized = query.lower()
    if "sorry" in normalized or "apologize" in normalized or "didn't mean" in normalized:
        return "It is all right. Let us set that sentence down and begin again from here."
    if "lecture" in normalized or "preachy" in normalized or "talk normally" in normalized:
        return "You are right; I was too stiff. I will keep this plain: what is the one thing on your mind?"
    if "ask" in normalized:
        return "All right, just one ordinary question: what has been taking up most of your mind today?"
    if "no advice" in normalized or "don't advise" in normalized:
        return "All right, no advice. Tell me one small thing from today, pleasant or irritating."
    if "short" in normalized:
        return "All right, briefly: what matters most right now?"
    return "All right, I will keep it plain. What would you like to say first?"
