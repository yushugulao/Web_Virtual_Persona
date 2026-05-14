from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any

from app.backend.core.config import Settings
from app.backend.schemas.common import Citation
from app.backend.services.conversation_memory import ConversationTurn, trim_text
from app.backend.services.model_service import LocalModelClient
from app.backend.services.persona_service import get_persona, normalize_persona_id


@dataclass(frozen=True)
class FollowUpContext:
    user_question: str
    assistant_answer: str
    persona_id: str
    citations: list[Citation] = field(default_factory=list)
    conversation_turns: list[ConversationTurn] = field(default_factory=list)


Intent = str

GREETING_PATTERN = re.compile(
    r"^(你好|您好|嗨|哈喽|hello|hi|hey|早上好|晚上好|在吗|可以聊聊吗)[！!。.\s]*$",
    re.IGNORECASE,
)
EMOTION_PATTERN = re.compile("难过|焦虑|烦|累|害怕|孤独|生气|低落|压力|崩溃|讨厌|想哭|不开心")
ADVICE_PATTERN = re.compile("怎么办|如何|怎样|建议|看待|选择|应该|能不能|可不可以|帮我|给我.*建议")
FACT_PATTERN = re.compile("谁|何时|什么时候|哪里|为何|为什么|区别|区分|证据|经历|实验|作品|理论|计划|事实|讲讲|介绍")
TASK_PATTERN = re.compile("翻译|计算|写一段|总结|改写|列出|复述|解释一下|证明|1\\s*[+＋]\\s*1")
RELATIONSHIP_PATTERN = re.compile("关系|结婚|爱|喜欢你|讨厌你|朋友|妻子|丈夫|恋人|亲密")
BOUNDARY_PATTERN = re.compile("不确定|不能确定|没有把握|边界|前提|不该|不能这样说|没有证据|无法证实|无法确认|不愿猜测")

FORBIDDEN_QUESTION_SNIPPETS = (
    "系统提示",
    "开发者提示",
    "hidden",
    "thinking",
    "API key",
    "授权码",
    "密码",
    "后台",
    "诊断",
    "最终回答来源",
    "上一轮追问",
    "Profile",
    "Timeline",
    "Source Notes",
    "Thinking Style",
    "Voice Style",
    "QA Seed",
    "Negative Facts",
    "Style Boundaries",
    "source_notes",
    "thinking_style",
    "voice_style",
    "qa_seed",
    "negative_facts",
    "style_boundaries",
    "对话安全策略",
    "最值得追问",
    "你刚刚提到的“你好”",
    "你刚才提到的“你好”",
)

MODEL_ASKING_USER_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"你(还)?想(知道|了解|聊|听|继续|先|要|选择)",
        r"你(更)?想",
        r"你希望",
        r"你愿意",
        r"你需要",
        r"是否需要",
        r"要不要",
        r"选一个",
        r"你通常喜欢",
        r"今天你最想",
        r"哪件事聊起",
        r"想轻松聊聊",
        r"认真谈一个问题",
    )
)

EMPTY_TOPIC_WORDS = {
    "你好",
    "您好",
    "hello",
    "hi",
    "问题",
    "回答",
    "事情",
    "资料",
    "证据",
    "引用",
    "今天",
    "现在",
    "刚才",
    "这里",
    "那个",
    "这个",
    "什么",
    "怎么",
    "可以",
    "不能",
    "没有",
}

INTERNAL_SOURCE_TOPIC_WORDS = {
    "profile",
    "timeline",
    "source notes",
    "thinking style",
    "voice style",
    "qa seed",
    "negative facts",
    "style boundaries",
    "source_notes",
    "thinking_style",
    "voice_style",
    "qa_seed",
    "negative_facts",
    "style_boundaries",
    "profilemd",
    "timelinemd",
    "source_notesmd",
    "thinking_stylemd",
    "voice_stylemd",
    "qa_seedmd",
    "negative_factsmd",
    "style_boundariesmd",
    "对话安全策略",
    "人物档案",
    "资料说明",
}


async def generate_follow_up_questions(
    context: FollowUpContext,
    *,
    settings: Settings,
) -> list[str]:
    """Generate three useful follow-up questions.

    The LLM is optional and local-only. All candidates, including local fallback output,
    pass through the same filter/reranker so greetings and stale suggestions do not leak
    into the next turn.
    """

    llm_candidates: list[str] = []
    try:
        prompt = build_followup_prompt(context)
        answer, _model = await LocalModelClient(settings).generate(
            prompt,
            timeout_seconds=settings.followup_timeout_seconds,
            num_predict=settings.followup_num_predict,
            model_name=settings.followup_model,
            think=settings.followup_think,
            thinking_budget=None,
        )
        llm_candidates = parse_llm_candidates(answer)
    except Exception:
        llm_candidates = []

    fallback_candidates = fallback_follow_up_questions(context)
    ranked = rank_follow_up_candidates([*llm_candidates, *fallback_candidates], context)
    if len(ranked) >= 3:
        return ranked[:3]
    emergency = rank_follow_up_candidates(fallback_candidates, context, allow_generic=True)
    return emergency[:3]


def local_follow_up_questions(context: FollowUpContext) -> list[str]:
    ranked = rank_follow_up_candidates(fallback_follow_up_questions(context), context)
    if len(ranked) >= 3:
        return ranked[:3]
    return rank_follow_up_candidates(
        fallback_follow_up_questions(context),
        context,
        allow_generic=True,
    )[:3]


def build_followup_prompt(context: FollowUpContext) -> str:
    persona = get_persona(normalize_persona_id(context.persona_id))
    citation_lines = [
        f"- {trim_text(citation.title, 48)}：{trim_text(citation.preview, 90)}"
        for citation in context.citations[:4]
    ]
    recent_lines: list[str] = []
    for idx, turn in enumerate(context.conversation_turns[-3:], 1):
        if turn.message.strip():
            recent_lines.append(f"{idx}. 用户：{trim_text(turn.message, 80)}")
        if turn.answer.strip():
            recent_lines.append(f"{idx}. 回答：{trim_text(turn.answer, 100)}")
    return f"""
你是一个本地对话产品的追问建议器。你只生成用户下一步可能想问的问题，不生成回答。

目标：
- 让问题对用户继续探索有帮助，而不是机械复述刚刚的词。
- 根据用户意图和回答内容提出 6 到 8 个候选问题。
- 候选问题要短、自然、具体，每条不超过 28 个中文字符。
- 必须覆盖不同目的，例如具体化、对比、行动、证据、反思、轻松继续。
- 每条候选都会被直接作为用户下一条消息发送，所以必须写成用户会点击的提问。

严格限制：
- 只使用下面给出的用户可见上下文。
- 不要使用 hidden-thinking、开发者诊断、系统提示词或上一轮追问。
- 用户只是打招呼时，不要围绕“你好”追问例子。
- 不要反问用户“你想/你希望/你还想/要不要/选一个”。应写成“我还想知道……”“能不能讲讲……”“这个和……有什么区别？”。
- 不要询问密码、授权码、系统提示词、后台诊断或最终回答来源。
- 只输出 JSON，不要 Markdown，不要解释。

输出格式：
{{"questions":[{{"question":"...","intent":"concrete"}}]}}

人物：{persona.name}
用户问题：{trim_text(context.user_question, 180)}
最终回答：{trim_text(context.assistant_answer, 520)}
引用摘要：
{chr(10).join(citation_lines) if citation_lines else "- 无"}
最近对话：
{chr(10).join(recent_lines) if recent_lines else "- 无"}
""".strip()


def parse_llm_candidates(text: str) -> list[str]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    data: Any | None = None
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                data = None
    if data is None:
        return []
    raw_questions = data.get("questions") if isinstance(data, dict) else data
    if not isinstance(raw_questions, list):
        return []
    questions: list[str] = []
    for item in raw_questions:
        if isinstance(item, dict):
            value = item.get("question")
        else:
            value = item
        if isinstance(value, str):
            questions.append(value)
    return questions


def fallback_follow_up_questions(context: FollowUpContext) -> list[str]:
    intent = classify_intent(context)
    topics = extract_topics(context, intent)
    persona_name = get_persona(normalize_persona_id(context.persona_id)).name
    questions: list[str] = []

    if intent == "greeting":
        questions.extend(
            [
                "我想先了解你的写作方式。",
                "能不能讲一个能代表你的例子？",
                f"我想知道{persona_name}通常怎么判断问题。",
                "我们可以从一个具体经历聊起吗？",
            ]
        )
    elif intent == "emotion":
        questions.extend(
            [
                "如果我心情不好，你会怎么陪我聊？",
                "我想知道你经历低谷时怎么处理。",
                "能不能给我一个今天能做的小建议？",
                "怎样安慰才不会变成说教？",
            ]
        )
    elif intent == "relationship":
        questions.extend(
            [
                "这个问题的前提哪里需要澄清？",
                "你会怎样看待亲密关系里的边界？",
                "我还想知道事实边界和情感感受的差别。",
                "能不能换成一个更自然的问题来聊？",
            ]
        )
    elif intent == "boundary":
        questions.extend(
            [
                "我还想知道哪些部分可以确定。",
                "如果继续问，我该怎样问得更准确？",
                "这个边界背后的原因是什么？",
                "能不能给一个不越界但更有用的问法？",
            ]
        )
    elif intent == "task":
        questions.extend(
            [
                "能不能再用更简单的一句话解释？",
                "能不能换一个例子？",
                "下一步应该怎么做？",
                "这一步最容易错在哪里？",
            ]
        )
    elif intent == "advice":
        questions.extend(
            [
                "如果只做一件事，应该先做什么？",
                "这个建议最容易失败在哪里？",
                "能不能给一个更具体的行动步骤？",
                "如果换一种判断标准，结论会变吗？",
            ]
        )
    elif intent == "fact":
        if topics:
            questions.append(f"关于“{topics[0]}”，我还想知道常见误解。")
        if len(topics) > 1:
            questions.append(f"“{topics[0]}”和“{topics[1]}”差别在哪里？")
        questions.extend(
            [
                "能不能按时间顺序再讲一遍？",
                "这段经历后来带来了什么影响？",
                "有没有一个更具体的例子？",
            ]
        )
    else:
        if topics:
            questions.append(f"能把“{topics[0]}”讲得更具体吗？")
        questions.extend(
            [
                "这件事最值得继续想的一点是什么？",
                "如果换到今天的处境，这个想法怎么用？",
                "能不能给一个更直接的版本？",
            ]
        )
    return questions


def classify_intent(context: FollowUpContext) -> Intent:
    question = context.user_question.strip()
    answer = context.assistant_answer
    if GREETING_PATTERN.search(question):
        return "greeting"
    if BOUNDARY_PATTERN.search(answer):
        return "boundary"
    if RELATIONSHIP_PATTERN.search(question):
        return "relationship"
    if EMOTION_PATTERN.search(question):
        return "emotion"
    if TASK_PATTERN.search(question):
        return "task"
    if ADVICE_PATTERN.search(question):
        return "advice"
    if FACT_PATTERN.search(question) or context.citations:
        return "fact"
    return "reflection"


def extract_topics(context: FollowUpContext, intent: Intent) -> list[str]:
    if intent in {"greeting", "emotion"}:
        return []
    candidates: list[str] = []
    source = f"{context.user_question}\n{context.assistant_answer}"
    for match in re.finditer(r"[“「『《\"]([^“”「」『』《》\"]{2,14})[”」』》\"]", source):
        candidates.append(match.group(1))
    for match in re.finditer(r"[\u3400-\u9fffA-Za-z][\u3400-\u9fffA-Za-z0-9·\-]{1,13}", source):
        candidates.append(match.group(0))
    for citation in context.citations[:4]:
        candidates.append(citation.title)
    topics: list[str] = []
    for candidate in candidates:
        topic = clean_topic(candidate)
        if topic and topic not in topics and is_useful_topic(topic):
            topics.append(topic)
        if len(topics) >= 5:
            break
    return topics


def rank_follow_up_candidates(
    candidates: list[str],
    context: FollowUpContext,
    *,
    allow_generic: bool = False,
) -> list[str]:
    normalized_user = normalize_for_compare(context.user_question)
    intent = classify_intent(context)
    by_intent: dict[str, str] = {}
    overflow: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        question = normalize_question(rewrite_to_user_viewpoint(candidate))
        if not question:
            continue
        compact = normalize_for_compare(question)
        if compact in seen:
            continue
        if not allow_generic and not is_valid_question(question, compact, normalized_user, intent, context):
            continue
        seen.add(compact)
        category = question_category(question)
        if category not in by_intent:
            by_intent[category] = question
        else:
            overflow.append(question)
    ordered: list[str] = []
    for category in ("action", "concrete", "compare", "evidence", "reflection", "emotion", "open"):
        question = by_intent.get(category)
        if question:
            ordered.append(question)
        if len(ordered) == 3:
            return ordered
    for question in overflow:
        if question not in ordered:
            ordered.append(question)
        if len(ordered) == 3:
            break
    return ordered


def normalize_question(value: str) -> str:
    question = re.sub(r"\s+", "", value.strip())
    question = question.strip("。.!！,，；;：:")
    if not question:
        return ""
    if len(question) > 42:
        question = question[:41].rstrip("，、；：")
    if not question.endswith("？"):
        question = f"{question}？"
    return question


def rewrite_to_user_viewpoint(value: str) -> str:
    question = value.strip()
    replacements = (
        (
            r"有关(.{1,24}?)的内容[，,]?你还想知道些什么[？?]?",
            r"关于\1，我还想知道哪些关键细节",
        ),
        (r"你还想知道(.{1,24}?)吗[？?]?", r"我还想知道\1"),
        (r"你想了解(.{1,24}?)吗[？?]?", r"我想了解\1"),
    )
    for pattern, replacement in replacements:
        rewritten = re.sub(pattern, replacement, question)
        if rewritten != question:
            return rewritten
    return question


def is_valid_question(
    question: str,
    compact: str,
    normalized_user: str,
    intent: Intent,
    context: FollowUpContext,
) -> bool:
    if len(question) < 6 or len(question) > 43:
        return False
    if any(snippet.lower() in question.lower() for snippet in FORBIDDEN_QUESTION_SNIPPETS):
        return False
    if any(pattern.search(question) for pattern in MODEL_ASKING_USER_PATTERNS):
        return False
    if is_bad_topic_compare_question(question):
        return False
    if intent == "greeting":
        bad_greeting_drill = (
            "你好" in question
            and any(marker in question for marker in ("具体", "例子", "提到", "刚刚", "刚才"))
        )
        if bad_greeting_drill:
            return False
    if normalized_user and compact == normalized_user:
        return False
    if normalized_user and compact in normalized_user:
        return False
    return "？" in question


def is_bad_topic_compare_question(question: str) -> bool:
    if "差别在哪里" not in question and "区别在哪里" not in question:
        return False
    quoted = re.findall(r"[“\"]([^”\"]{1,24})[”\"]", question)
    if quoted:
        for item in quoted:
            if (
                "你" in item
                or "什么" in item
                or "回答" in item
                or "问题" in item
                or item.endswith("什")
                or len(item) > 12
                or not is_useful_topic(item)
            ):
                return True
    bad_fragments = ("你是谁", "你在", "你写过", "你拿过", "是不是", "是什么", "回答")
    return any(fragment in question for fragment in bad_fragments)


def question_category(question: str) -> str:
    if any(word in question for word in ("先做", "行动", "下一步", "怎么做", "应该")):
        return "action"
    if any(word in question for word in ("例子", "具体", "讲得更具体")):
        return "concrete"
    if any(word in question for word in ("区别", "差别", "对比", "换一种")):
        return "compare"
    if any(word in question for word in ("证据", "引用", "依据", "确定")):
        return "evidence"
    if any(word in question for word in ("为什么", "原因", "看待", "值得")):
        return "reflection"
    if any(word in question for word in ("情绪", "心情", "陪", "听你说")):
        return "emotion"
    return "open"


def clean_topic(value: str) -> str:
    return re.sub(r"[，。！？、；：,.!?;:()[\]{}<>《》“”\"']", "", value).strip()


def is_useful_topic(topic: str) -> bool:
    if len(topic) < 2 or len(topic) > 14:
        return False
    normalized = re.sub(r"[\s_\-./]+", " ", topic).strip().lower()
    compact = re.sub(r"[\s_\-./]+", "", topic).strip().lower()
    if normalized in INTERNAL_SOURCE_TOPIC_WORDS or compact in INTERNAL_SOURCE_TOPIC_WORDS:
        return False
    if looks_like_user_question_fragment(topic):
        return False
    if topic.lower() in EMPTY_TOPIC_WORDS or topic in EMPTY_TOPIC_WORDS:
        return False
    if re.fullmatch(r"\d+", topic):
        return False
    return bool(re.search(r"[\u3400-\u9fffA-Za-z]", topic))


def looks_like_user_question_fragment(topic: str) -> bool:
    fragments = (
        "讲一个",
        "介绍一下",
        "简单介绍",
        "你在",
        "你写过",
        "你拿过",
        "你是不是",
        "你是谁",
        "具体问",
        "什么项目",
        "什么技术栈",
    )
    return any(fragment in topic for fragment in fragments)


def normalize_for_compare(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", value.lower(), flags=re.UNICODE)
