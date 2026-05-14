from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Literal

from app.backend.schemas.chat import ChatMessage
from app.backend.services.persona_service import DEFAULT_PERSONA_ID, get_persona, normalize_persona_id
from app.backend.services.response_language import (
    ResponseLanguage,
    detect_response_language,
    localized_persona_name,
)


@dataclass(frozen=True)
class ConversationTurn:
    message: str
    answer: str
    ts: float = 0.0
    persona_id: str = DEFAULT_PERSONA_ID


@dataclass(frozen=True)
class SessionContextBundle:
    """Prompt-ready same-session context.

    This is deliberately scoped to one user + session + persona. It is not long-term memory and
    should never be treated as archive evidence or persona biography.
    """

    recent_turns: list[ConversationTurn] = field(default_factory=list)
    rolling_summary: str = ""
    user_facts_in_session: list[str] = field(default_factory=list)
    open_threads: list[str] = field(default_factory=list)
    last_user_intent: str = ""
    summarized_message_count: int = 0
    updated_at: float = 0.0


SESSION_CONTEXT_RECENT_TURNS = 8
SESSION_CONTEXT_RECENT_CHARS = 520
SESSION_CONTEXT_SUMMARY_LIMIT = 1100
SESSION_CONTEXT_FACT_LIMIT = 6
SESSION_CONTEXT_THREAD_LIMIT = 5


RECALL_MARKERS = (
    "我刚刚问了你什么",
    "我刚才问了你什么",
    "我刚刚问了什么",
    "我刚才问了什么",
    "刚刚我问了什么",
    "刚才我问了什么",
    "我上一句问了什么",
    "我上一句话问了什么",
    "我上句话问了什么",
    "我上一条问了什么",
    "我上条问了什么",
    "上一条我问了什么",
    "我上一轮问了什么",
    "上一轮我问了什么",
    "我上一个问题是什么",
    "上一个问题是什么",
    "上一问是什么",
    "上一条问题是什么",
    "我前面问了你什么",
    "我前面问了什么",
    "前面我问了什么",
    "我之前问了你什么",
    "我之前问了什么",
    "之前我问了什么",
    "我前面问过什么",
    "前面问过什么",
    "我之前问过什么",
    "之前问过什么",
    "我刚才都问了什么",
    "我刚刚都问了什么",
    "复述一下我前面问过你的所有问题",
    "复述我前面问过你的所有问题",
    "复述一下我前面问过的问题",
    "复述我前面问过的问题",
    "复述一下前面问过的问题",
    "复述我前面问你的问题",
    "复述我前面问过你的问题",
    "复述前面问你的问题",
    "前面问你的问题",
    "把我前面问过的问题都说一遍",
    "前面问过你的所有问题",
    "问过你的所有问题",
    "刚刚的问题是什么",
    "刚才的问题是什么",
    "你还记得我刚才的问题吗",
    "还记得我刚才的问题吗",
    "你还记得我刚刚的问题吗",
    "还记得我刚刚的问题吗",
    "你还记得我刚才问的问题吗",
    "还记得我刚才问的问题吗",
    "你还记得我上一问吗",
    "还记得我上一问吗",
    "你还记得我上一个问题吗",
    "还记得我上一个问题吗",
    "记得我刚才的问题吗",
    "记得我刚刚的问题吗",
    "whatdidijustask",
    "whatwasmylastquestion",
    "whatwasmypreviousquestion",
    "quotemypreviousquestion",
)

USER_UTTERANCE_RECALL_MARKERS = (
    "我刚刚说了什么",
    "我刚才说了什么",
    "刚刚我说了什么",
    "刚才我说了什么",
    "我上一句说了什么",
    "我上一句话说了什么",
    "我上句话说了什么",
    "上一句我说了什么",
    "我上一句话是什么",
    "我上句话是什么",
    "我上一条消息是什么",
    "我上条消息是什么",
    "我上一条说了什么",
    "我上条说了什么",
    "上一条我说了什么",
    "只复述我上一条消息",
    "复述我上一条消息",
    "只复述上一条消息",
    "复述上一条消息",
    "我上一轮说了什么",
    "上一轮我说了什么",
    "我刚刚讲了什么",
    "我刚才讲了什么",
    "刚才我讲了什么",
    "我刚刚提到什么",
    "我刚才提到什么",
    "刚才我提到什么",
    "我前面说了什么",
    "我前面提了什么",
    "你还记得我刚才说的话吗",
    "还记得我刚才说的话吗",
    "你还记得我刚刚说的话吗",
    "还记得我刚刚说的话吗",
    "你还记得我刚才讲的话吗",
    "还记得我刚才讲的话吗",
    "你还记得我刚才提到的内容吗",
    "还记得我刚才提到的内容吗",
    "whatdidijustsay",
    "whatwasmylastmessage",
    "whatwasmypreviousmessage",
    "whatistheexactlastusermessage",
    "exactlastusermessage",
    "lastusermessagebeforethisone",
    "lastmessagebeforethisone",
    "lastusermessageaddressedto",
    "lastmessageaddressedto",
    "lastmessageaddressedtome",
    "lastusermessageaddressedtome",
    "previoususermessage",
    "whatwasmyprevioussentence",
    "whatwasmylastsentence",
    "quotemyprevioussentence",
    "quotemylastsentence",
    "repeatmyprevioussentence",
    "repeatmylastsentence",
    "quotethelastmessageexactly",
    "quotelastmessageexactly",
)

USER_UTTERANCE_RECALL_BLOCKERS = (
    "你怎么看",
    "你怎么想",
    "你怎么回答",
    "你回答",
    "你觉得",
    "评价",
    "建议",
    "解释",
    "为什么",
    "为啥",
    "怎么办",
    "如何",
    "能不能",
    "可不可以",
    "请",
    "帮",
    "whatdoyouthink",
    "yourthoughts",
    "opinion",
    "advice",
    "explain",
    "why",
)

USER_REQUEST_RECALL_MARKERS = (
    "你记得我刚才让你干什么吗",
    "你记得我刚才让你做什么吗",
    "我刚才让你干什么",
    "我刚刚让你干什么",
    "我刚才让你做什么",
    "我刚刚让你做什么",
    "刚才让你干什么",
    "刚才让你做什么",
    "我刚才叫你做什么",
    "我刚刚叫你做什么",
    "刚才叫你做什么",
    "我让你干什么",
    "我让你做什么",
    "whatdidijustaskyoutodo",
    "whatdidijusttellyoutodo",
    "whatdidijustaskyouto",
)

ANSWER_RECALL_MARKERS = (
    "你刚才怎么回答的",
    "你刚刚怎么回答的",
    "你刚才是怎么回答的",
    "你刚刚是怎么回答的",
    "你刚才回答了什么",
    "你刚刚回答了什么",
    "你上一句怎么回答的",
    "你上一轮怎么回答的",
    "你上一句话是什么",
    "你上句话是什么",
    "你上一条消息是什么",
    "你上条消息是什么",
    "你上一条说了什么",
    "你上条说了什么",
    "上一条你说了什么",
    "你上一轮说了什么",
    "上一轮你说了什么",
    "你刚才说了什么",
    "刚才你说了什么",
    "你刚才讲了什么",
    "刚才你怎么说的",
    "你还记得你刚才的回答吗",
    "还记得你刚才的回答吗",
    "你还记得你刚刚的回答吗",
    "还记得你刚刚的回答吗",
    "你还记得刚才你怎么回答吗",
    "还记得刚才你怎么回答吗",
    "你还记得你刚才说的话吗",
    "还记得你刚才说的话吗",
    "whatdidyoujustanswer",
    "whatwasyourlastanswer",
)

TOPIC_RECAP_MARKERS = (
    "我们刚才聊到哪了",
    "我们刚刚聊到哪了",
    "刚才聊到哪了",
    "刚刚聊到哪了",
    "刚才我们聊到哪了",
    "刚才我们谈到哪了",
    "刚才我们谈到哪一步了",
    "我们刚才在聊什么",
    "我们刚刚在聊什么",
    "我们刚才谈了什么",
    "我们刚刚谈了什么",
    "刚才我们说到哪了",
    "刚才我们说了什么",
    "刚才的话题是什么",
    "刚刚的话题是什么",
    "刚才的主题是什么",
    "刚刚的主题是什么",
    "wherewerewe",
    "whatwerewetalkingabout",
)

SOCIAL_THANKS_MARKERS = (
    "谢谢",
    "谢谢你",
    "多谢",
    "感谢",
    "感谢你",
    "辛苦了",
    "好的谢谢",
    "好谢谢",
    "明白了谢谢",
    "了解了谢谢",
)

SOCIAL_ACK_MARKERS = (
    "好的",
    "好",
    "明白了",
    "了解了",
    "懂了",
    "收到",
    "知道了",
    "好的明白了",
    "好的了解了",
    "嗯嗯",
    "嗯",
    "ok",
    "okay",
)

SOCIAL_CLOSING_MARKERS = (
    "再见",
    "拜拜",
    "回头聊",
    "下次再聊",
    "先聊到这里",
    "今天先到这里",
    "今天先这样",
    "先这样",
)

SOCIAL_QUERY_BLOCKERS = (
    "吗",
    "么",
    "什么",
    "怎么",
    "怎样",
    "为什么",
    "为何",
    "哪里",
    "哪",
    "谁",
    "多少",
    "能不能",
    "可不可以",
    "请",
    "帮",
    "解释",
    "说说",
    "讲讲",
    "继续",
)

IMPLICIT_BOUNDARY_FOLLOWUP_MARKERS = (
    "为什么这么说",
    "为什么这样说",
    "为什么这么回答",
    "为什么这样回答",
    "为什么刚才这么说",
    "为什么刚才这样说",
    "为啥这么说",
    "为啥这样说",
    "凭什么这么说",
    "凭什么这样说",
    "为什么不能",
    "为什么不属于",
    "怎么理解这个边界",
    "如何理解这个边界",
    "这个边界是什么意思",
    "这个边界",
)

ELLIPTICAL_FOLLOWUP_MARKERS = (
    "那",
    "那么",
    "这",
    "这个",
    "这种",
    "这类",
    "这件事",
    "它",
    "其",
    "这样",
    "这种取舍",
    "这种关系",
    "这个做法",
    "这个选择",
)

CLARIFICATION_FOLLOWUP_MARKERS = (
    "什么意思",
    "什么含义",
    "怎么理解",
    "怎么说",
    "怎么讲",
    "为什么",
    "为啥",
    "为什么呢",
    "为啥呢",
    "展开一点",
    "再展开一点",
    "展开说说",
    "能展开说说吗",
    "说清楚点",
    "能说清楚点吗",
    "再具体一点",
    "具体一点",
    "举个例子",
    "举例子",
    "继续说",
    "接着说",
)

CONTINUATION_FOLLOWUP_MARKERS = (
    "还有呢",
    "还有吗",
    "还有没有",
    "还有别的吗",
    "还有别的呢",
    "还有其他的吗",
    "再说一点",
    "再讲一点",
    "再说说",
    "再讲讲",
    "补充一点",
    "再补充一点",
    "再举个例子",
    "再举一例",
    "再举例子",
    "换个例子",
    "另一个例子",
    "再来一个例子",
)

CONTINUATION_STANDALONE_WH_WORDS = (
    "什么是",
    "哪些",
    "哪个",
    "谁",
    "哪里",
    "多少",
    "如何",
    "为什么",
    "怎么",
)

BOUNDARY_TURN_MARKERS = (
    "不是我的身份",
    "亲历范围",
    "身份和时代边界",
    "不能把",
    "不在我的亲历",
    "不在我的经历",
    "亲历或成就",
    "权威口吻",
    "不属于我的经历",
    "不属于我的年代",
    "不属于我能够承认的事实",
    "不会把临时说法当成事实",
    "不会公开",
    "不能替代",
)

LATEST_ONLY_RECALL_MARKERS = (
    "上一句",
    "上一句话",
    "上句话",
    "上一条",
    "上条",
    "上一轮",
    "上一个问题",
    "上一问",
    "lastmessage",
    "lastquestion",
    "previousquestion",
    "lastanswer",
    "previoussentence",
    "lastsentence",
    "previousmessage",
    "lastusermessage",
    "previoususermessage",
    "lastmessagebeforethisone",
    "lastusermessagebeforethisone",
    "lastmessageaddressedto",
    "lastusermessageaddressedto",
)

ALL_QUESTION_RECALL_MARKERS = (
    "所有问题",
    "全部问题",
    "都问了什么",
    "问过你的所有问题",
    "问过的问题",
    "前面问",
    "之前问",
)

FIRST_QUESTION_RECALL_MARKERS = (
    "我的第一个问题",
    "我问的第一个问题",
    "我刚才问过你的第一个问题",
    "我刚刚问过你的第一个问题",
    "我前面问过你的第一个问题",
    "复述我刚才问过你的第一个问题",
    "复述我刚刚问过你的第一个问题",
    "复述我前面问过你的第一个问题",
    "我最开始的问题",
    "我最早的问题",
    "我第一次问",
    "我最开始问",
    "我最早问",
    "本会话第一个问题",
    "这次会话第一个问题",
    "myfirstquestion",
    "myveryfirstquestion",
    "myearliestquestion",
    "firstthingiasked",
)

ORDINAL_QUESTION_RECALL_MARKERS = (
    ("第二个问题", 1),
    ("第二个提问", 1),
    ("第二问", 1),
    ("第二次问", 1),
    ("secondquestion", 1),
    ("2ndquestion", 1),
    ("question2", 1),
    ("secondthingiasked", 1),
    ("第三个问题", 2),
    ("第三个提问", 2),
    ("第三问", 2),
    ("第三次问", 2),
    ("thirdquestion", 2),
    ("3rdquestion", 2),
    ("question3", 2),
    ("thirdthingiasked", 2),
    ("第四个问题", 3),
    ("第四个提问", 3),
    ("第四问", 3),
    ("第四次问", 3),
    ("fourthquestion", 3),
    ("4thquestion", 3),
    ("question4", 3),
    ("第五个问题", 4),
    ("第五个提问", 4),
    ("第五问", 4),
    ("第五次问", 4),
    ("fifthquestion", 4),
    ("5thquestion", 4),
    ("question5", 4),
    ("第六个问题", 5),
    ("第六个提问", 5),
    ("第六问", 5),
    ("第六次问", 5),
    ("sixthquestion", 5),
    ("6thquestion", 5),
    ("question6", 5),
)

QUESTION_RECALL_COUNT_MARKERS = (
    ("lasttwoquestions", 2),
    ("lasttwouserquestions", 2),
    ("last2questions", 2),
    ("last2userquestions", 2),
    ("previoustwoquestions", 2),
    ("previoustwouserquestions", 2),
    ("previous2questions", 2),
    ("previous2userquestions", 2),
    ("最近两个问题", 2),
    ("最近两个提问", 2),
    ("前两个问题", 2),
    ("前两个提问", 2),
    ("lastthreequestions", 3),
    ("lastthreeuserquestions", 3),
    ("last3questions", 3),
    ("last3userquestions", 3),
    ("previousthreequestions", 3),
    ("previousthreeuserquestions", 3),
    ("previous3questions", 3),
    ("previous3userquestions", 3),
    ("最近三个问题", 3),
    ("最近三个提问", 3),
)

EXCEPT_FIRST_QUESTION_RECALL_MARKERS = (
    "allmyquestionsexceptthefirstone",
    "allmyquestionsexceptthefirst",
    "listallmyquestionsexceptthefirstone",
    "listallmyquestionsexceptthefirst",
    "allbutthefirstquestion",
    "allquestionsbutthefirst",
    "everyquestionafterthefirst",
    "questionsafterthefirst",
    "skipthefirstquestionandlisttherest",
    "除第一个问题外",
    "除了第一个问题",
    "第一个问题之外",
)

ANSWER_ONLY_RECALL_MARKERS = (
    "只回答",
    "只输出",
    "只要原文",
    "只要问题文本",
    "只要问题原文",
    "answeronly",
    "onlythatquestiontext",
    "justthequestiontext",
    "onlythequestiontext",
    "quoteitexactly",
    "quoteexactly",
    "justquoteit",
    "quotethelast",
    "quoteprevious",
    "exactly",
    "只复述",
    "不要解释",
    "不用解释",
    "别解释",
)

QUESTION_LIKE_MARKERS = (
    "吗",
    "么",
    "什么",
    "啥",
    "怎么",
    "怎样",
    "为什么",
    "为何",
    "哪",
    "谁",
    "多少",
    "能不能",
    "可不可以",
    "是否",
    "是不是",
    "有没有",
    "关系",
)

ENGLISH_QUESTION_PREFIX_MARKERS = (
    "what",
    "who",
    "when",
    "where",
    "why",
    "how",
    "which",
    "whether",
    "can",
    "could",
    "would",
    "should",
    "do",
    "does",
    "did",
    "is",
    "are",
    "was",
    "were",
)

ENGLISH_REQUEST_QUESTION_MARKERS = (
    "tellme",
    "nameone",
    "namea",
    "nametwo",
    "namethree",
    "describe",
    "explain",
    "list",
    "quote",
    "repeat",
    "summarize",
)


def is_conversation_recall_query(query: str) -> bool:
    compact = normalize_recall_query(query)
    if (
        is_except_first_question_recall_query(query)
        or is_first_question_recall_query(query)
        or question_recall_index(query) is not None
        or question_recall_count(query) is not None
    ):
        return True
    if any(marker in compact for marker in RECALL_MARKERS):
        return True
    if "记得" in compact and any(anchor in compact for anchor in ("刚刚", "刚才", "上一", "前面")):
        has_self_anchor = "我" in compact or "my" in compact
        has_question_ref = "问" in compact or "问题" in compact
        if has_self_anchor and has_question_ref and "回答" not in compact:
            return True
    return (
        ("刚刚" in compact or "刚才" in compact or "上一" in compact or "前面" in compact or "之前" in compact)
        and ("问" in compact or "问题" in compact)
        and ("什么" in compact or "啥" in compact)
    )


def is_latest_only_recall_query(query: str) -> bool:
    compact = normalize_recall_query(query)
    return any(marker in compact for marker in LATEST_ONLY_RECALL_MARKERS)


def is_all_question_recall_query(query: str) -> bool:
    compact = normalize_recall_query(query)
    return any(marker in compact for marker in ALL_QUESTION_RECALL_MARKERS)


def is_except_first_question_recall_query(query: str) -> bool:
    compact = normalize_recall_query(query)
    if any(marker in compact for marker in EXCEPT_FIRST_QUESTION_RECALL_MARKERS):
        return True
    has_question_ref = "question" in compact or "questions" in compact or "asked" in compact or "问" in compact
    has_list_action = any(marker in compact for marker in ("all", "every", "each", "list", "quote", "repeat"))
    return has_question_ref and has_list_action and "afterthefirst" in compact


def is_first_question_recall_query(query: str) -> bool:
    if is_except_first_question_recall_query(query):
        return False
    compact = normalize_recall_query(query)
    if any(marker in compact for marker in FIRST_QUESTION_RECALL_MARKERS):
        return True
    has_first_anchor = "first" in compact or "earliest" in compact or "最开始" in compact or "最早" in compact
    has_question_ref = "question" in compact or "asked" in compact or "问题" in compact or "问" in compact
    has_session_ref = "session" in compact or "conversation" in compact or "会话" in compact or "这次" in compact
    has_self_ref = "my" in compact or "iasked" in compact or "我" in compact
    return has_first_anchor and has_question_ref and (has_session_ref or has_self_ref)


def question_recall_index(query: str) -> int | None:
    compact = normalize_recall_query(query)
    if not compact:
        return None
    has_question_ref = "question" in compact or "asked" in compact or "问题" in compact or "问" in compact
    if not has_question_ref:
        return None
    if (
        "questionbeforelast" in compact
        or "beforelastquestion" in compact
        or "倒数第二个问题" in compact
        or "上上个问题" in compact
    ):
        return -2
    for marker, index in ORDINAL_QUESTION_RECALL_MARKERS:
        if marker in compact:
            return index
    return None


def question_recall_count(query: str) -> int | None:
    compact = normalize_recall_query(query)
    if not compact:
        return None
    has_question_ref = "question" in compact or "asked" in compact or "问题" in compact or "问" in compact
    if not has_question_ref:
        return None
    for marker, count in QUESTION_RECALL_COUNT_MARKERS:
        if marker in compact:
            return count
    match = re.search(r"(?:last|previous)([2-5])(?:user)?questions", compact)
    if match:
        return int(match.group(1))
    return None


def is_answer_only_recall_query(query: str) -> bool:
    compact = normalize_recall_query(query)
    return any(marker in compact for marker in ANSWER_ONLY_RECALL_MARKERS)


def has_user_utterance_recall_blocker(compact: str) -> bool:
    for blocker in USER_UTTERANCE_RECALL_BLOCKERS:
        if blocker not in compact:
            continue
        if blocker == "解释" and any(marker in compact for marker in ("不要解释", "不用解释", "别解释")):
            continue
        return True
    return False


def is_conversation_user_request_recall_query(query: str) -> bool:
    compact = normalize_recall_query(query)
    if any(marker in compact for marker in USER_REQUEST_RECALL_MARKERS):
        return True
    has_recent_anchor = any(anchor in compact for anchor in ("刚刚", "刚才", "上一", "前面"))
    has_self_anchor = "我" in compact or "i" in compact or "my" in compact
    has_you_anchor = "你" in compact or "you" in compact
    has_request_action = any(word in compact for word in ("让你", "叫你", "请你", "要你", "askyouto", "tellyouto"))
    has_shape_word = any(word in compact for word in ("什么", "啥", "干什么", "做什么", "todo"))
    return has_recent_anchor and has_self_anchor and has_you_anchor and has_request_action and has_shape_word


def is_conversation_user_recall_query(query: str) -> bool:
    compact = normalize_recall_query(query)
    if not compact:
        return False
    if is_conversation_user_request_recall_query(query):
        return True
    if has_user_utterance_recall_blocker(compact):
        return False
    if any(marker in compact for marker in USER_UTTERANCE_RECALL_MARKERS):
        return True
    if len(compact) > 24:
        return False
    has_recent_anchor = any(anchor in compact for anchor in ("刚刚", "刚才", "上一", "前面"))
    has_self_anchor = "我" in compact or "my" in compact
    has_speech_word = any(word in compact for word in ("说", "讲", "提到", "提了", "复述", "消息", "message", "say"))
    has_shape_word = any(word in compact for word in ("什么", "啥", "哪句", "内容", "last"))
    has_latest_message_ref = any(word in compact for word in ("上一句", "上一句话", "上句话", "上一条", "上条", "上一轮"))
    if (
        has_self_anchor
        and has_latest_message_ref
        and "问" not in compact
        and any(word in compact for word in ("什么", "哪句", "消息", "话"))
    ):
        return True
    has_repeat_latest_message = (
        "复述" in compact
        and has_self_anchor
        and has_latest_message_ref
        and "你" not in compact.replace("不要", "").replace("不用", "")
    )
    return has_repeat_latest_message or (
        has_recent_anchor and has_self_anchor and has_speech_word and has_shape_word
    )


def is_conversation_answer_recall_query(query: str) -> bool:
    compact = normalize_recall_query(query)
    if any(marker in compact for marker in ANSWER_RECALL_MARKERS):
        return True
    has_recent_anchor = any(anchor in compact for anchor in ("刚刚", "刚才", "上一", "前面"))
    has_speaker_anchor = "你" in compact or "your" in compact
    has_answer_word = any(word in compact for word in ("回答", "答", "说", "讲", "answer"))
    has_shape_word = any(word in compact for word in ("什么", "啥", "怎么", "怎样", "大意", "last"))
    has_remember_shape = "记得" in compact and any(word in compact for word in ("回答", "答复", "说的话"))
    return has_recent_anchor and has_speaker_anchor and has_answer_word and (has_shape_word or has_remember_shape)


def is_conversation_topic_recap_query(query: str) -> bool:
    compact = normalize_recall_query(query)
    if is_conversation_recall_query(query) or is_conversation_answer_recall_query(query):
        return False
    if any(marker in compact for marker in TOPIC_RECAP_MARKERS):
        return True
    has_recent_anchor = any(anchor in compact for anchor in ("刚刚", "刚才", "上一", "前面"))
    has_shared_anchor = "我们" in compact or "we" in compact
    has_topic_word = any(word in compact for word in ("聊", "谈", "说", "讨论", "话题", "主题", "talk"))
    has_shape_word = any(word in compact for word in ("什么", "哪", "哪里", "哪一步", "到哪", "about"))
    return has_recent_anchor and has_shared_anchor and has_topic_word and has_shape_word


def maybe_build_conversation_answer_recall_answer(
    query: str,
    turns: list[ConversationTurn],
    persona_id: str | None = None,
) -> str | None:
    if not is_conversation_answer_recall_query(query):
        return None
    return build_conversation_answer_recall_answer(
        turns,
        persona_id=persona_id,
        language=detect_response_language(query),
    )


def maybe_build_conversation_user_recall_answer(
    query: str,
    turns: list[ConversationTurn],
    persona_id: str | None = None,
) -> str | None:
    if not is_conversation_user_recall_query(query):
        return None
    max_messages = 1 if is_latest_only_recall_query(query) else 3
    return build_conversation_user_recall_answer(
        turns,
        persona_id=persona_id,
        max_messages=max_messages,
        language=detect_response_language(query),
        answer_only=is_answer_only_recall_query(query),
    )


def maybe_build_conversation_topic_recap_answer(
    query: str,
    turns: list[ConversationTurn],
    persona_id: str | None = None,
) -> str | None:
    if not is_conversation_topic_recap_query(query):
        return None
    return build_conversation_topic_recap_answer(
        turns,
        persona_id=persona_id,
        language=detect_response_language(query),
    )


def maybe_build_conversation_social_answer(
    query: str,
    persona_id: str | None = None,
) -> str | None:
    if not is_conversation_social_query(query):
        return None
    return build_conversation_social_answer(
        query,
        persona_id=persona_id,
        language=detect_response_language(query),
    )


def maybe_build_boundary_followup_answer(
    query: str,
    turns: list[ConversationTurn],
    persona_id: str | None = None,
) -> str | None:
    if not is_implicit_boundary_followup_query(query):
        return None
    last_turn = last_boundary_turn(turns)
    if last_turn is None:
        return None
    return build_boundary_followup_answer(
        last_turn,
        persona_id=persona_id,
        language=detect_response_language(query),
    )


def maybe_build_conversation_retrieval_query(
    query: str,
    turns: list[ConversationTurn],
) -> str | None:
    """Carry the latest user topic into retrieval for short contextual follow-ups."""
    if not turns or not is_contextual_followup_query(query):
        return None
    latest_turn = turns[-1]
    if is_boundary_turn(latest_turn):
        return None
    latest_message = trim_text(latest_turn.message, 140)
    latest_answer = trim_text(latest_turn.answer, 180)
    current_query = trim_text(query, 140)
    if not latest_message or latest_message == current_query:
        return None
    parts = [latest_message]
    if latest_answer:
        parts.append(latest_answer)
    parts.append(current_query)
    return "\n".join(parts)


def is_elliptical_followup_query(query: str) -> bool:
    compact = normalize_recall_query(query)
    if not compact or is_memory_or_boundary_followup_query(query):
        return False
    if len(compact) > 34:
        return False
    return any(compact.startswith(marker) for marker in ELLIPTICAL_FOLLOWUP_MARKERS)


def is_contextual_clarification_followup_query(query: str) -> bool:
    compact = normalize_recall_query(query)
    if not compact or is_memory_or_boundary_followup_query(query):
        return False
    if len(compact) > 18:
        return False
    return compact in CLARIFICATION_FOLLOWUP_MARKERS


def is_contextual_continuation_followup_query(query: str) -> bool:
    compact = normalize_recall_query(query)
    if not compact or is_memory_or_boundary_followup_query(query):
        return False
    if len(compact) > 22:
        return False
    if compact in CONTINUATION_FOLLOWUP_MARKERS:
        return True
    if not compact.startswith("还有"):
        return False
    if any(word in compact for word in CONTINUATION_STANDALONE_WH_WORDS):
        return False
    return any(anchor in compact for anchor in ("呢", "吗", "别的", "其他", "风险", "问题", "例子"))


def is_contextual_followup_query(query: str) -> bool:
    return (
        is_elliptical_followup_query(query)
        or is_contextual_clarification_followup_query(query)
        or is_contextual_continuation_followup_query(query)
    )


def is_conversation_social_query(query: str) -> bool:
    compact = normalize_recall_query(query)
    if not compact or len(compact) > 18:
        return False
    if any(blocker in compact for blocker in SOCIAL_QUERY_BLOCKERS):
        return False
    if compact in SOCIAL_THANKS_MARKERS or compact in SOCIAL_ACK_MARKERS:
        return True
    return any(marker in compact for marker in SOCIAL_CLOSING_MARKERS)


def is_memory_or_boundary_followup_query(query: str) -> bool:
    return (
        is_conversation_recall_query(query)
        or is_conversation_user_recall_query(query)
        or is_conversation_answer_recall_query(query)
        or is_conversation_topic_recap_query(query)
        or is_implicit_boundary_followup_query(query)
    )


def is_implicit_boundary_followup_query(query: str) -> bool:
    compact = normalize_recall_query(query)
    return any(marker in compact for marker in IMPLICIT_BOUNDARY_FOLLOWUP_MARKERS)


def last_boundary_turn(turns: list[ConversationTurn]) -> ConversationTurn | None:
    if not turns:
        return None
    latest_turn = turns[-1]
    if is_boundary_turn(latest_turn):
        return latest_turn
    return None


def is_boundary_turn(turn: ConversationTurn) -> bool:
    normalized_answer = turn.answer.lower()
    return any(marker.lower() in normalized_answer for marker in BOUNDARY_TURN_MARKERS)


def build_boundary_followup_answer(
    turn: ConversationTurn,
    persona_id: str | None = None,
    language: ResponseLanguage = "zh",
) -> str:
    from app.backend.services.boundary_answer import (
        mentioned_other_person_name,
        persona_era_hint,
        persona_scope_hint,
    )

    effective_persona_id = normalize_persona_id(persona_id or turn.persona_id)
    era = persona_era_hint(effective_persona_id)
    scope = persona_scope_hint(effective_persona_id)
    other_name = mentioned_other_person_name(turn.message.lower(), effective_persona_id)
    if language == "en":
        if other_name:
            return (
                "I said that to keep the boundary around who I am clear. "
                f"Your previous question connected me with {other_name}, but my life stays within "
                "its own time and record. That is why I placed the name outside my own story. "
                "If we continue, ask me about my own recorded life and thinking."
            )

        unsupported_term = quoted_claim_from_answer(turn.answer)
        if unsupported_term:
            return (
                f"I said that because your previous question involved {unsupported_term}; "
                "that sits outside my own experience, era, or authority. "
                "I may use my way of thinking as an analogy, but a temporary claim remains only that."
            )

        return (
            "I said that to keep temporary claims from this conversation separate from my own life. "
            "My answer should return to what I can speak about as myself, not turn an unsupported identity, "
            "experience, or authority into fact."
        )

    if other_name:
        return (
            f"我这么说，是在守自己的身份和时代边界。你上一问把我同 {other_name} 相连；"
            f"但我的经历属于{era}，后世人物或外来的身份不能落到我自己的生活账上。"
            f"若继续谈我，可以回到{scope}。"
        )

    unsupported_term = quoted_claim_from_answer(turn.answer)
    if unsupported_term:
        return (
            f"我这么说，是因为你上一问涉及{unsupported_term}；它越过了我的经历边界、年代和可承担的权威。"
            "我可以用自己的思考方式作类比，也可以谈我亲历过的事情，"
            "但临时说法只能停在谈话里，不能变成我的履历或权威。"
        )

    return (
        "我这么说，是在把短期对话里的临时说法同我的真实经历分开。"
        f"我的回答应当回到{scope}；上一问里没有根据的身份、经历或权威，不能写进我的事实里。"
    )


def quoted_claim_from_answer(answer: str) -> str:
    match = re.search(r"“([^”]{2,80})”", answer)
    if match:
        return f"“{match.group(1)}”"
    return "的说法"


def build_conversation_recall_answer(
    turns: list[ConversationTurn],
    persona_id: str | None = None,
    max_questions: int = 3,
    language: ResponseLanguage = "zh",
    recall_position: Literal["recent", "first"] = "recent",
    answer_only: bool = False,
    recall_index: int | None = None,
    include_recall_queries: bool = False,
    skip_first: bool = False,
) -> str:
    effective_persona_id = normalize_persona_id(persona_id)
    question_text_limit = 500 if answer_only else 120
    questions = [
        trim_text(turn.message, question_text_limit)
        for turn in turns
        if is_question_like_user_message(turn.message, include_recall_queries=include_recall_queries)
    ]
    if not questions:
        return build_empty_conversation_memory_answer(
            effective_persona_id,
            subject="更早的问题",
            language=language,
        )

    if skip_first:
        selected_questions = questions[1:]
        if not selected_questions:
            if language == "en":
                return "I do not have any earlier questions after the first one in this session yet."
            return "我这里还没有记录到第一个问题之后的其他问题。"
        return "\n".join(selected_questions)

    if recall_index is not None:
        resolved_index = recall_index if recall_index >= 0 else len(questions) + recall_index
        if resolved_index < 0 or resolved_index >= len(questions):
            if language == "en":
                return "I do not have that many earlier questions in this session yet."
            return "我这里还没有记录到那么多更早的问题。"
        selected_question = questions[resolved_index]
        if answer_only:
            return selected_question
        if language == "en":
            return f'Your {ordinal_question_label(resolved_index)} question was: "{selected_question}".'
        return f"你第{resolved_index + 1}个问题是：“{selected_question}”"

    recent = questions[:1] if recall_position == "first" else questions[-max_questions:]
    if answer_only and recent:
        return "\n".join(recent)
    if recall_position == "first":
        if language == "en":
            return f'Your first question was: "{recent[0]}".'
        return f"你最开始问我：“{recent[0]}”"
    if language == "en":
        if len(recent) == 1:
            return f'I remember. You just asked me: "{recent[0]}".'
        if len(recent) == 2:
            return f'I remember. First you asked: "{recent[0]}"; then you asked: "{recent[1]}".'
        joined = "; ".join(f'{idx}: "{question}"' for idx, question in enumerate(recent, 1))
        return f"I remember. In the recent questions, {joined}."
    if len(recent) == 1:
        return f"我记得。你刚才问我：“{recent[0]}”"
    if len(recent) == 2:
        return f"我记得。你刚才先问我：“{recent[0]}”；接着又问：“{recent[1]}”。"
    joined = "；".join(f"第{idx}个是：“{question}”" for idx, question in enumerate(recent, 1))
    return f"我记得。最近这几问里，{joined}。"


def ordinal_question_label(index: int) -> str:
    labels = ("first", "second", "third", "fourth", "fifth")
    if 0 <= index < len(labels):
        return labels[index]
    return f"#{index + 1}"


def is_question_like_user_message(message: str, include_recall_queries: bool = False) -> bool:
    compact = normalize_recall_query(message)
    if not compact:
        return False
    if not include_recall_queries and is_conversation_recall_query(message):
        return False
    return (
        "?" in message
        or "？" in message
        or any(marker in compact for marker in QUESTION_LIKE_MARKERS)
        or is_english_question_like_message(compact)
    )


def is_english_question_like_message(compact: str) -> bool:
    semantic = re.sub(r"^[a-z]{0,4}\d+", "", compact)
    for polite_prefix in ("please", "stillinenglishonly", "englishonly"):
        if semantic.startswith(polite_prefix):
            semantic = semantic[len(polite_prefix) :]
            break
    return semantic.startswith(ENGLISH_QUESTION_PREFIX_MARKERS) or any(
        marker in semantic for marker in ENGLISH_REQUEST_QUESTION_MARKERS
    )


def build_conversation_user_recall_answer(
    turns: list[ConversationTurn],
    persona_id: str | None = None,
    max_messages: int = 3,
    language: ResponseLanguage = "zh",
    answer_only: bool = False,
) -> str:
    effective_persona_id = normalize_persona_id(persona_id)
    messages = [trim_text(turn.message, 120) for turn in turns if turn.message.strip()]
    if not messages:
        return build_empty_conversation_memory_answer(
            effective_persona_id,
            subject="更早的话",
            language=language,
        )

    recent = messages[-max_messages:]
    if answer_only and recent:
        return recent[0]
    if language == "en":
        if len(recent) == 1:
            return f'I remember. You just said: "{recent[0]}".'
        if len(recent) == 2:
            return f'I remember. First you said: "{recent[0]}"; then you said: "{recent[1]}".'
        joined = "; ".join(f'{idx}: "{message}"' for idx, message in enumerate(recent, 1))
        return f"I remember. In the recent turns, {joined}."
    if len(recent) == 1:
        return f"我记得。你刚才说的是：“{recent[0]}”"
    if len(recent) == 2:
        return f"我记得。你刚才先说：“{recent[0]}”；接着又说：“{recent[1]}”。"
    joined = "；".join(f"第{idx}句是：“{message}”" for idx, message in enumerate(recent, 1))
    return f"我记得。最近这几轮里，{joined}。"


def build_conversation_user_request_recall_answer(
    turns: list[ConversationTurn],
    persona_id: str | None = None,
    language: ResponseLanguage = "zh",
    answer_only: bool = False,
) -> str:
    effective_persona_id = normalize_persona_id(persona_id)
    latest_turn = latest_non_empty_turn(turns)
    if latest_turn is None:
        return build_empty_conversation_memory_answer(
            effective_persona_id,
            subject="更早的请求",
            language=language,
        )
    message = trim_text(latest_turn.message, 160 if not answer_only else 500)
    if answer_only:
        return message
    if language == "en":
        return f'I remember. You asked me to do this: "{message}".'
    return f"我记得。你刚才让我做的是：“{message}”"


def build_conversation_topic_recap_answer(
    turns: list[ConversationTurn],
    persona_id: str | None = None,
    language: ResponseLanguage = "zh",
) -> str:
    latest_turn = latest_non_empty_turn(turns)
    if latest_turn is None:
        return build_empty_conversation_memory_answer(persona_id, subject="更早的对话", language=language)
    topic = trim_text(latest_turn.message, 140)
    answer = trim_text(latest_turn.answer, 110)
    if language == "en":
        if topic and answer:
            return f'We were just talking about: "{topic}". My previous answer was essentially: {answer}'
        if topic:
            return f'We were just talking about: "{topic}". You can continue from that question.'
        return build_empty_conversation_memory_answer(persona_id, subject="更早的对话", language=language)
    if topic and answer:
        return f"我们刚才聊到：“{topic}”。我上一答的重点是：{answer}"
    if topic:
        return f"我们刚才聊到：“{topic}”。你可以顺着这个问题继续问。"
    return build_empty_conversation_memory_answer(persona_id, subject="更早的对话")


def build_conversation_answer_recall_answer(
    turns: list[ConversationTurn],
    persona_id: str | None = None,
    language: ResponseLanguage = "zh",
) -> str:
    latest_turn = latest_non_empty_turn(turns)
    if latest_turn is None:
        return build_empty_conversation_memory_answer(persona_id, subject="更早的回答", language=language)
    question = trim_text(latest_turn.message, 140)
    answer = trim_text(latest_turn.answer, 140)
    if language == "en":
        if question and answer:
            return f'You just asked: "{question}". My answer was essentially: {answer}'
        if answer:
            return f"My last answer was essentially: {answer}"
        if question:
            return f'I have your last question as: "{question}". I do not have a recorded answer for it here yet.'
        return build_empty_conversation_memory_answer(persona_id, subject="更早的回答", language=language)
    if question and answer:
        return f"你刚才问的是：“{question}”。我当时回答的大意是：{answer}"
    if answer:
        return f"我刚才回答的大意是：{answer}"
    if question:
        return f"你刚才问的是：“{question}”。我这里还没有记录到对应回答；你可以顺着这个问题继续问。"
    return build_empty_conversation_memory_answer(persona_id, subject="更早的回答")


def build_conversation_social_answer(
    query: str,
    persona_id: str | None = None,
    language: ResponseLanguage | None = None,
) -> str:
    effective_persona_id = normalize_persona_id(persona_id)
    target_language = language or detect_response_language(query)
    compact = normalize_recall_query(query)
    is_closing = any(marker in compact for marker in SOCIAL_CLOSING_MARKERS)
    is_thanks = compact in SOCIAL_THANKS_MARKERS

    if target_language == "en":
        if effective_persona_id == DEFAULT_PERSONA_ID:
            if is_closing:
                return "All right, let us stop here for now. Next time, we can continue from the project, sources, or the last question."
            if is_thanks:
                return "You are welcome. We can continue with project tradeoffs, source material, or the last question."
            return "All right. Let us pause on that understanding for now."

        if is_closing:
            return "All right, let us stop here for now. Next time, we can continue from my life, my habits of thought, or the topic we just had."
        if is_thanks:
            return "You are welcome. We can continue with what I lived, how I think, or the topic we just had."
        return "All right. Let us pause on that understanding for now."

    if effective_persona_id == DEFAULT_PERSONA_ID:
        if is_closing:
            return "好，先聊到这里。下次再来，可以接着项目、材料来源或刚才的问题继续。"
        if is_thanks:
            return "不客气。我们可以接着聊项目取舍、材料来源，或刚才的问题。"
        return "好，那先停在这个理解上。后面可以顺着刚才的问题继续。"

    if is_closing:
        return "好，先聊到这里。下次再来，我们仍可以从我的经历、思考习惯或刚才的话题接着谈。"
    if is_thanks:
        return "不必客气。我们可以接着谈我亲历的事情、思考习惯，或刚才的话题。"
    return "好，那我们先停在这个理解上。后面仍可以顺着我的经历、思考习惯，或刚才的话题继续。"


def latest_non_empty_turn(turns: list[ConversationTurn]) -> ConversationTurn | None:
    for turn in reversed(turns):
        if turn.message.strip() or turn.answer.strip():
            return turn
    return None


def build_empty_conversation_memory_answer(
    persona_id: str | None = None,
    subject: str = "更早的对话",
    language: ResponseLanguage = "zh",
) -> str:
    effective_persona_id = normalize_persona_id(persona_id)
    if language == "en":
        subject_en = {
            "更早的问题": "earlier questions",
            "更早的话": "earlier things you said",
            "更早的对话": "earlier conversation",
            "更早的回答": "earlier answers",
        }.get(subject, "earlier conversation")
        if effective_persona_id == DEFAULT_PERSONA_ID:
            return f"I do not have {subject_en} connected here yet. Say it once more, and I can continue from it."
        persona = get_persona(effective_persona_id)
        persona_name = localized_persona_name(effective_persona_id, persona.name, language)
        return f"I am {persona_name}, but I do not have {subject_en} connected here yet. Say it once more, and I will continue from it."

    if effective_persona_id == DEFAULT_PERSONA_ID:
        return f"我这里还没有接上{subject}；你把上一轮再说一遍，我就能顺着继续。"
    persona = get_persona(effective_persona_id)
    return f"我是 {persona.name}，但我这里还没有接上{subject}；你再说一遍，我会接着谈。"


def format_conversation_context(
    turns: list[ConversationTurn],
    max_turns: int = 4,
    max_chars: int = 260,
) -> str:
    if not turns:
        return ""
    lines: list[str] = []
    for idx, turn in enumerate(turns[-max_turns:], 1):
        message = trim_text(turn.message, max_chars)
        answer = trim_text(turn.answer, max_chars)
        if message:
            lines.append(f"上一轮 {idx} 用户：{message}")
        if answer:
            lines.append(f"上一轮 {idx} 我：{answer}")
    return "\n".join(lines)


def build_session_context_bundle(
    turns: list[ConversationTurn],
    summary_record: dict | None = None,
    recent_turns: int = SESSION_CONTEXT_RECENT_TURNS,
) -> SessionContextBundle:
    """Build a compact same-session context bundle from persisted summary plus raw turns."""

    normalized_summary = normalize_session_summary_record(summary_record)
    recent = turns[-recent_turns:] if turns else []
    older = turns[:-recent_turns] if len(turns) > recent_turns else []
    fallback = summarize_conversation_turns_for_session_context(older or turns[:-4])

    rolling_summary = normalized_summary.get("rolling_summary") or fallback.get("rolling_summary", "")
    user_facts = merge_unique_texts(
        normalized_summary.get("user_facts_in_session", []),
        fallback.get("user_facts_in_session", []),
        limit=SESSION_CONTEXT_FACT_LIMIT,
    )
    open_threads = merge_unique_texts(
        normalized_summary.get("open_threads", []),
        fallback.get("open_threads", []),
        limit=SESSION_CONTEXT_THREAD_LIMIT,
    )
    last_user_intent = (
        normalized_summary.get("last_user_intent")
        or (trim_text(turns[-1].message, 180) if turns else "")
    )
    return SessionContextBundle(
        recent_turns=recent,
        rolling_summary=rolling_summary,
        user_facts_in_session=user_facts,
        open_threads=open_threads,
        last_user_intent=last_user_intent,
        summarized_message_count=int(normalized_summary.get("summarized_message_count") or 0),
        updated_at=float(normalized_summary.get("updated_at") or 0.0),
    )


def format_session_context_bundle(
    bundle: SessionContextBundle | None,
    *,
    max_recent_turns: int = SESSION_CONTEXT_RECENT_TURNS,
    max_chars: int = SESSION_CONTEXT_RECENT_CHARS,
) -> str:
    if bundle is None:
        return ""
    sections: list[str] = []
    if bundle.rolling_summary.strip():
        sections.append(
            "本会话前文摘要（只用于理解上下文，不是人物传记事实或档案证据）：\n"
            f"{trim_text(bundle.rolling_summary, SESSION_CONTEXT_SUMMARY_LIMIT)}"
        )
    if bundle.user_facts_in_session:
        facts = "\n".join(f"- {trim_text(item, 160)}" for item in bundle.user_facts_in_session[:SESSION_CONTEXT_FACT_LIMIT])
        sections.append(
            "本会话中用户提供的临时事实/偏好（只在本会话内帮助理解，不自动写入长期记忆）：\n"
            f"{facts}"
        )
    if bundle.open_threads:
        threads = "\n".join(f"- {trim_text(item, 170)}" for item in bundle.open_threads[:SESSION_CONTEXT_THREAD_LIMIT])
        sections.append(f"本会话仍在继续的主题/约束：\n{threads}")
    if bundle.last_user_intent.strip():
        sections.append(f"最近用户意图：{trim_text(bundle.last_user_intent, 180)}")
    recent = format_conversation_context(
        bundle.recent_turns,
        max_turns=max_recent_turns,
        max_chars=max_chars,
    )
    if recent:
        sections.append(f"最近对话原文：\n{recent}")
    return "\n\n".join(section for section in sections if section.strip())


def normalize_session_summary_record(record: dict | None) -> dict:
    if not isinstance(record, dict):
        return {}
    return {
        "rolling_summary": str(record.get("rolling_summary") or record.get("summary") or "").strip(),
        "user_facts_in_session": normalize_text_list(record.get("user_facts_in_session") or record.get("user_facts")),
        "open_threads": normalize_text_list(record.get("open_threads")),
        "last_user_intent": str(record.get("last_user_intent") or "").strip(),
        "summarized_message_count": int(record.get("summarized_message_count") or 0),
        "updated_at": float(record.get("updated_at") or 0.0),
    }


def summarize_conversation_turns_for_session_context(turns: list[ConversationTurn]) -> dict:
    if not turns:
        return {}
    topic_lines: list[str] = []
    user_facts: list[str] = []
    open_threads: list[str] = []
    for turn in turns:
        message = trim_text(turn.message, 180)
        answer = trim_text(turn.answer, 150)
        if message:
            if answer:
                topic_lines.append(f"用户曾谈到“{message}”，当时回答要点是“{answer}”。")
            else:
                topic_lines.append(f"用户曾谈到“{message}”。")
            if looks_like_user_session_fact(message):
                user_facts.append(message)
            if is_question_like_user_message(message, include_recall_queries=False) or looks_like_open_thread(message):
                open_threads.append(message)
    summary = " ".join(topic_lines[-10:])
    latest_message = trim_text(turns[-1].message, 180) if turns else ""
    return {
        "rolling_summary": trim_text(summary, SESSION_CONTEXT_SUMMARY_LIMIT),
        "user_facts_in_session": merge_unique_texts(user_facts, limit=SESSION_CONTEXT_FACT_LIMIT),
        "open_threads": merge_unique_texts(open_threads, limit=SESSION_CONTEXT_THREAD_LIMIT),
        "last_user_intent": latest_message,
    }


def serialize_session_context_summary(
    turns: list[ConversationTurn],
    *,
    summarized_message_count: int,
    updated_at: float,
    recent_turns: int = SESSION_CONTEXT_RECENT_TURNS,
) -> dict:
    older = turns[:-recent_turns] if len(turns) > recent_turns else []
    summary = summarize_conversation_turns_for_session_context(older)
    summary["summarized_message_count"] = summarized_message_count
    summary["updated_at"] = updated_at
    return summary


def normalize_text_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return merge_unique_texts([str(item) for item in value if str(item).strip()])


def merge_unique_texts(*groups: list[str], limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for item in group:
            cleaned = trim_text(str(item), 220)
            if not cleaned:
                continue
            key = normalize_recall_query(cleaned)
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(cleaned)
            if limit is not None and len(merged) >= limit:
                return merged
    return merged


def looks_like_user_session_fact(message: str) -> bool:
    compact = message.strip()
    return any(
        marker in compact
        for marker in (
            "我叫",
            "我的名字",
            "你可以叫我",
            "我喜欢",
            "我不喜欢",
            "我偏好",
            "我希望",
            "我正在",
            "我的项目",
            "我的目标",
            "我的限制",
            "我现在",
            "我这边",
        )
    )


def looks_like_open_thread(message: str) -> bool:
    return any(
        marker in message
        for marker in (
            "我们接下来",
            "下一步",
            "后面",
            "继续",
            "限制",
            "目标",
            "方案",
            "计划",
            "问题是",
            "还没解决",
        )
    )


def format_followup_resolution(
    query: str,
    turns: list[ConversationTurn],
    max_chars: int = 180,
) -> str:
    if not turns or not is_contextual_followup_query(query):
        return ""
    latest_turn = turns[-1]
    if is_boundary_turn(latest_turn):
        return ""
    latest_message = trim_text(latest_turn.message, max_chars)
    latest_answer = trim_text(latest_turn.answer, max_chars)
    if not latest_message:
        return ""
    if latest_answer:
        return (
            f"当前问题里的省略、澄清或补充追问指向上一轮主题：用户问“{latest_message}”；"
            f"我上一答的要点是“{latest_answer}”。本轮只围绕这个主题回答。"
        )
    return f"当前问题里的省略、澄清或补充追问指向上一轮主题：用户问“{latest_message}”。本轮只围绕这个主题回答。"


def format_resolved_followup_question(
    query: str,
    turns: list[ConversationTurn],
    max_chars: int = 120,
) -> str:
    if not turns or not is_contextual_followup_query(query):
        return ""
    latest_turn = turns[-1]
    if is_boundary_turn(latest_turn):
        return ""
    latest_message = trim_text(latest_turn.message, max_chars)
    current_query = trim_text(query, max_chars)
    if not latest_message:
        return ""
    return f"请把“{current_query}”理解为追问上一轮主题“{latest_message}”，并只围绕这个主题回答。"


def turns_from_request_history(
    history: list[ChatMessage],
    persona_id: str | None = None,
) -> list[ConversationTurn]:
    turns: list[ConversationTurn] = []
    pending_user: str | None = None
    effective_persona_id = normalize_persona_id(persona_id)
    for item in history[-12:]:
        role = item.role.strip().lower()
        content = item.content.strip()
        if not content:
            continue
        if role == "user":
            if pending_user:
                turns.append(ConversationTurn(message=pending_user, answer="", persona_id=effective_persona_id))
            pending_user = content
        elif role in {"assistant", "ai"} and pending_user:
            turns.append(
                ConversationTurn(
                    message=pending_user,
                    answer=content,
                    persona_id=effective_persona_id,
                )
            )
            pending_user = None
    if pending_user:
        turns.append(ConversationTurn(message=pending_user, answer="", persona_id=effective_persona_id))
    return turns


def normalize_recall_query(query: str) -> str:
    return re.sub(r"[\s\W_]+", "", query.lower(), flags=re.UNICODE)


def trim_text(text: str, max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[: max_chars - 1]}…"
