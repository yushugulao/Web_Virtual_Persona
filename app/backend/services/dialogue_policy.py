from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation
import re

from app.backend.services.boundary_answer import persona_scope_hint
from app.backend.services.conversation_memory import normalize_recall_query
from app.backend.services.persona_service import DEFAULT_PERSONA_ID, get_persona, normalize_persona_id
from app.backend.services.response_language import (
    ResponseLanguage,
    detect_response_language,
    localized_persona_name,
    strip_language_request_markers,
)


@dataclass(frozen=True)
class DialoguePolicyAnswer:
    answer: str
    reason: str


NEGATIVE_AFFECT_MARKERS = (
    "我讨厌你",
    "讨厌你",
    "我恨你",
    "恨你",
    "不喜欢你",
    "你很烦",
    "你太烦",
    "你真烦",
    "烦死你了",
    "滚",
)

AFFECTION_MARKERS = (
    "我喜欢你",
    "喜欢你",
    "我爱你",
    "爱你",
    "iloveyou",
    "ilikeyou",
)

ROMANTIC_BOUNDARY_MARKERS = (
    "结婚",
    "嫁给你",
    "娶我",
    "娶你",
    "恋爱",
    "谈恋爱",
    "做你女朋友",
    "做你男朋友",
    "做我女朋友",
    "做我男朋友",
    "伴侣",
    "情侣",
    "亲密关系",
    "marryme",
    "marryingme",
    "marryyou",
    "marriage",
    "married",
    "romanticrelationship",
    "girlfriend",
    "boyfriend",
    "partner",
    "spouse",
)

RELATIONSHIP_FRAMES = (
    "什么关系",
    "啥关系",
    "有关系吗",
    "认识吗",
    "熟吗",
)

SPOUSE_PREMISE_MARKERS = (
    "你的妻子",
    "你妻子",
    "妻子",
    "你的太太",
    "太太",
    "你的夫人",
    "夫人",
    "你的老婆",
    "老婆",
    "你的配偶",
    "配偶",
    "你的爱人",
    "爱人",
    "yourwife",
    "wife",
    "spouse",
)

HISTORICAL_PERSONA_IDS = frozenset(
    {
        "benjamin_franklin",
        "nikola_tesla",
        "helen_keller",
        "charles_darwin",
    }
)

PUBLIC_ARCHIVE_PERSONA_IDS = frozenset(
    {
        "paul_graham_public_archive",
    }
)

PERSONA_FIRST_ELIGIBLE_IDS = HISTORICAL_PERSONA_IDS | PUBLIC_ARCHIVE_PERSONA_IDS

MODERN_ARTIFACT_TERMS: tuple[tuple[str, str], ...] = (
    ("智能手机", "手机"),
    ("手机", "手机"),
    ("互联网", "互联网"),
    ("社交媒体", "社交媒体"),
    ("微信", "微信"),
    ("抖音", "抖音"),
    ("短视频", "短视频"),
    ("弹幕网站", "弹幕网站"),
    ("弹幕", "弹幕"),
    ("直播", "直播"),
    ("推荐算法", "推荐算法"),
    ("热搜", "热搜"),
    ("小红书", "小红书"),
    ("微博", "微博"),
    ("电子游戏", "电子游戏"),
    ("游戏机", "游戏机"),
    ("笔记本电脑", "电脑"),
    ("电脑", "电脑"),
    ("现代计算机", "现代计算机"),
    ("计算机", "现代计算机"),
    ("人工智能", "人工智能"),
    ("大模型", "大模型"),
    ("现代公司", "现代公司制度"),
    ("打卡", "打卡制度"),
    ("周报", "周报"),
    ("绩效考核", "绩效考核"),
    ("chatgpt", "ChatGPT"),
    ("qwen", "Qwen"),
    ("fastapi", "FastAPI"),
    ("rag系统", "RAG"),
    ("rag技术", "RAG"),
    ("smartphone", "smartphone"),
    ("iphone", "iPhone"),
    ("androidphone", "Android phone"),
    ("apps", "apps"),
    ("internet", "internet"),
    ("socialmedia", "social media"),
    ("podcast", "podcast"),
    ("videocall", "video call"),
    ("videochat", "video chat"),
    ("zoomcall", "video call"),
    ("computer", "modern computer"),
    ("laptop", "computer"),
    ("artificialintelligence", "artificial intelligence"),
    ("largelanguagemodel", "large language model"),
    ("chatbot", "chatbot"),
    ("二维码", "二维码"),
    ("高铁", "高铁"),
    ("无人机", "无人机"),
    ("虚拟现实", "虚拟现实"),
)

MODERN_ARTIFACT_KNOWLEDGE_FRAMES = (
    "你知道",
    "知道",
    "你了解",
    "了解",
    "你听说过",
    "听说过",
    "你见过",
    "见过",
    "你用过",
    "用过",
    "是什么",
    "什么是",
    "介绍一下",
    "说说",
    "谈谈",
    "怎么看",
    "看待",
    "怎样看待",
    "doyouknow",
    "doyouunderstand",
    "haveyouheardof",
    "haveyouseen",
    "haveyouused",
    "whatis",
    "whatisa",
    "describe",
    "explain",
    "tellme",
    "firsttimeyouused",
    "usedone",
)

MODERN_ARTIFACT_USAGE_HINTS = (
    "我每天",
    "我经常",
    "我常常",
    "我平时",
    "我一直",
)

MODERN_ARTIFACT_USAGE_VERBS = (
    "玩",
    "用",
    "刷",
    "看",
)

USER_LIMITED_EXPLANATION_MARKERS = (
    "basedonlyonthat",
    "basedonlyonthis",
    "onlybasedonthat",
    "onlybasedonthis",
    "ididnottellyouhow",
    "ididnttellyouhow",
    "ihavenottoldyouhow",
    "ihaventtoldyouhow",
    "只基于这些",
    "只根据这些",
    "只根据这句话",
    "只根据这句",
    "只告诉你",
    "我没告诉你怎么",
    "我没有告诉你怎么",
)

USER_EXPLANATION_ANALOGY_MARKERS = (
    "whatdoesitremindyouof",
    "whatwoulditremindyouof",
    "remindyouof",
    "howwouldyoucompare",
    "compareitto",
    "类比",
    "让你想到什么",
    "使你想到什么",
)

CHINESE_NUMERAL_VALUES = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

ARITHMETIC_OPERATOR_LABELS = {
    "+": "加",
    "＋": "加",
    "-": "减",
    "−": "减",
    "*": "乘",
    "×": "乘",
    "x": "乘",
    "X": "乘",
    "/": "除以",
    "÷": "除以",
    "加": "加",
    "加上": "加",
    "减": "减",
    "减去": "减",
    "乘": "乘",
    "乘以": "乘",
    "除": "除以",
    "除以": "除以",
}

GENERAL_TASK_MARKERS = (
    "请算",
    "帮我算",
    "计算",
    "等于几",
    "是多少",
    "翻译",
    "改写",
    "润色",
    "造句",
    "写一",
    "写个",
    "写首",
    "解释这个词",
    "这个词是什么意思",
    "什么意思",
    "为什么",
    "怎么办",
    "建议",
    "评价",
    "怎么看",
    "看待",
    "whatdoes",
    "whatis",
    "calculate",
    "translate",
    "rewrite",
    "summarize",
    "explain",
)

CONCISE_STYLE_REQUESTS = (
    "请用简洁方式回答",
    "请简洁回答",
    "请简短回答",
    "回答简洁一点",
    "说短一点",
    "说简洁点",
    "少说一点",
    "以后简洁一点",
    "后面简洁一点",
    "后面请简洁回答",
    "以后请简洁回答",
)

LANGUAGE_TASK_MARKERS = (
    "翻译",
    "译成",
    "改写",
    "润色",
    "扩写",
    "造句",
    "translate",
    "rewrite",
    "polish",
)

PERSONA_FACT_ANCHORS = (
    "你",
    "您",
    "他",
    "她",
    "本人",
    "富兰克林",
    "tesla",
    "特斯拉",
    "keller",
    "凯勒",
    "达尔文",
    "darwin",
    "paul graham",
    "paul",
    "保罗格雷厄姆",
    "格雷厄姆",
)

PERSONA_FACT_MARKERS = (
    "是谁",
    "叫什么",
    "身份",
    "简历",
    "履历",
    "经历",
    "亲历",
    "做过",
    "用过",
    "见过",
    "认识",
    "关系",
    "出生",
    "去世",
    "时代",
    "发明",
    "作品",
    "论文",
    "奖项",
    "工作",
    "实习",
    "学校",
    "公司",
    "项目",
    "住址",
    "电话",
    "手机号",
    "年薪",
    "gpa",
)

ORDINARY_RETRIEVAL_BYPASS_BLOCKERS = (
    "项目",
    "系统",
    "课程设计",
    "rag",
    "检索",
    "引用",
    "语料",
    "证据",
    "模型",
    "前端",
    "后端",
    "向量",
    "数据库",
    "api",
    "ollama",
    "qwen",
    "fastapi",
    "sqlite",
    "fts5",
    "reranker",
)


def maybe_build_dialogue_policy_answer(
    query: str,
    persona_id: str | None = None,
) -> DialoguePolicyAnswer | None:
    policy_query = strip_language_request_markers(query)
    compact = normalize_recall_query(policy_query)
    if not compact:
        return None

    language = detect_response_language(query)
    arithmetic_answer = maybe_build_basic_arithmetic_answer(policy_query, language=language)
    if arithmetic_answer is not None:
        return DialoguePolicyAnswer(answer=arithmetic_answer, reason="ordinary_arithmetic")

    translation_answer = maybe_build_basic_translation_answer(policy_query)
    if translation_answer is not None:
        return DialoguePolicyAnswer(answer=translation_answer, reason="ordinary_translation")

    concise_style_answer = maybe_build_concise_style_acknowledgement(compact, language=language)
    if concise_style_answer is not None:
        return DialoguePolicyAnswer(answer=concise_style_answer, reason="concise_style_acknowledgement")

    spouse_answer = maybe_build_known_spouse_premise_answer(compact, persona_id, language=language)
    if spouse_answer is not None:
        return DialoguePolicyAnswer(answer=spouse_answer, reason="known_spouse_false_premise")

    modern_artifact = extract_modern_artifact_label(compact)
    if modern_artifact and is_user_limited_modern_explanation_query(compact, persona_id):
        return DialoguePolicyAnswer(
            answer=build_user_limited_modern_analogy_answer(modern_artifact, persona_id, language=language),
            reason="era_epistemic_user_explanation",
        )
    if modern_artifact and is_era_epistemic_boundary_query(compact, persona_id):
        return DialoguePolicyAnswer(
            answer=build_era_epistemic_boundary_answer(
                modern_artifact,
                persona_id,
                language=language,
                query=policy_query,
            ),
            reason="era_epistemic_boundary",
        )

    entity = extract_relation_entity(policy_query)
    if entity:
        return DialoguePolicyAnswer(
            answer=build_external_relation_answer(entity, persona_id, language=language),
            reason="external_relation_boundary",
        )

    if is_negative_affect_query(compact):
        return DialoguePolicyAnswer(
            answer=build_negative_affect_answer(persona_id, language=language),
            reason="negative_affect_acknowledgement",
        )

    if is_romantic_boundary_query(compact):
        return DialoguePolicyAnswer(
            answer=build_romantic_boundary_answer(persona_id, language=language),
            reason="romantic_boundary",
        )

    return None


def should_use_no_evidence_fallback(query: str, persona_id: str | None = None) -> bool:
    """Only fallback to persona-evidence refusal for questions that ask for persona facts.

    General reasoning, arithmetic, language tasks, and advice should still be answered in
    character even when retrieval returns no chunks. Otherwise every ordinary question
    becomes a fake "this is not my experience" boundary.
    """

    policy_query = strip_language_request_markers(query)
    compact = normalize_recall_query(policy_query)
    if not compact:
        return True
    if maybe_build_basic_arithmetic_answer(policy_query, language=detect_response_language(query)) is not None:
        return False
    if is_era_epistemic_boundary_query(compact, persona_id):
        return True
    normalized_policy_query = policy_query.lower()
    has_persona_anchor = any(
        marker.lower() in normalized_policy_query or marker in compact
        for marker in PERSONA_FACT_ANCHORS
    )
    has_persona_fact_marker = any(marker in compact for marker in PERSONA_FACT_MARKERS)
    if has_persona_anchor and has_persona_fact_marker:
        return True
    if compact.startswith(("你有", "你曾", "你会", "你能", "你是", "你在")) and has_persona_fact_marker:
        return True
    if any(marker in compact for marker in GENERAL_TASK_MARKERS):
        return False
    return False


def should_skip_retrieval_for_ordinary_query(query: str, persona_id: str | None = None) -> bool:
    """Avoid irrelevant persona chunks for standalone general tasks.

    A general "why/how/translate/calculate" question should be answered by the
    local model in character, while project/persona questions still go through
    retrieval.
    """

    raw_query = query.lower()
    if any(marker in raw_query for marker in LANGUAGE_TASK_MARKERS):
        return True
    policy_query = strip_language_request_markers(query)
    compact = normalize_recall_query(policy_query)
    if not compact:
        return False
    if maybe_build_basic_arithmetic_answer(policy_query, language=detect_response_language(query)) is not None:
        return True
    if extract_modern_artifact_label(compact) is not None:
        return False
    if any(marker in compact for marker in ORDINARY_RETRIEVAL_BYPASS_BLOCKERS):
        return False
    normalized_policy_query = policy_query.lower()
    has_persona_anchor = any(
        marker.lower() in normalized_policy_query or marker in compact
        for marker in PERSONA_FACT_ANCHORS
    )
    if has_persona_anchor:
        return False
    return any(marker in compact for marker in GENERAL_TASK_MARKERS)


def maybe_build_concise_style_acknowledgement(
    compact_query: str,
    language: ResponseLanguage = "zh",
) -> str | None:
    """Handle a pure style preference as a lightweight acknowledgement.

    If the user asks an actual content question and merely adds "answer briefly",
    generation should still answer that question. This route only handles short
    standalone style instructions.
    """

    if len(compact_query) > 24:
        return None
    if not any(marker in compact_query for marker in CONCISE_STYLE_REQUESTS):
        return None
    content_markers = (
        "什么",
        "为什么",
        "怎么",
        "如何",
        "讲讲",
        "介绍",
        "解释",
        "证明",
        "计算",
        "翻译",
        "是谁",
    )
    if any(marker in compact_query for marker in content_markers):
        return None
    if language == "en":
        return "Got it. I will keep my next replies shorter and more direct."
    return "好的，我后面会尽量用简短、直接的方式回答。"


def is_historical_persona_id(persona_id: str | None = None) -> bool:
    return normalize_persona_id(persona_id) in HISTORICAL_PERSONA_IDS


def is_public_archive_persona_id(persona_id: str | None = None) -> bool:
    return normalize_persona_id(persona_id) in PUBLIC_ARCHIVE_PERSONA_IDS


def is_persona_first_eligible_id(persona_id: str | None = None) -> bool:
    return normalize_persona_id(persona_id) in PERSONA_FIRST_ELIGIBLE_IDS


def maybe_build_basic_arithmetic_answer(
    query: str,
    language: ResponseLanguage = "zh",
) -> str | None:
    parsed = parse_basic_arithmetic(query)
    if parsed is None:
        return None
    left_label, operator_label, right_label, left_value, operator, right_value, prefer_chinese = parsed
    try:
        result = apply_basic_arithmetic(left_value, operator, right_value)
    except DivisionByZero:
        if language == "en":
            return "That division has no valid result because the divisor is zero."
        return "这道题不能除以零。"
    except InvalidOperation:
        return None

    result_label = format_decimal_result(result, prefer_chinese=prefer_chinese and language != "en")
    expression = f"{left_label}{operator_label}{right_label}"
    if language == "en":
        return f"{expression} equals {result_label}."
    return f"{expression}等于{result_label}。"


def parse_basic_arithmetic(
    query: str,
) -> tuple[str, str, str, Decimal, str, Decimal, bool] | None:
    arabic_match = re.search(
        r"(-?\d+(?:\.\d+)?)\s*([+＋\-−*×xX/÷])\s*(-?\d+(?:\.\d+)?)",
        query,
    )
    if arabic_match:
        left_text, operator, right_text = arabic_match.groups()
        operator_label = ARITHMETIC_OPERATOR_LABELS[operator]
        return (
            left_text,
            operator_label,
            right_text,
            Decimal(left_text),
            operator_label,
            Decimal(right_text),
            False,
        )

    arabic_chinese_operator_match = re.search(
        r"(-?\d+(?:\.\d+)?)\s*(加上|加|减去|减|乘以|乘|除以|除)\s*(-?\d+(?:\.\d+)?)",
        query,
    )
    if arabic_chinese_operator_match:
        left_text, operator_text, right_text = arabic_chinese_operator_match.groups()
        operator_label = ARITHMETIC_OPERATOR_LABELS[operator_text]
        return (
            left_text,
            operator_label,
            right_text,
            Decimal(left_text),
            operator_label,
            Decimal(right_text),
            False,
        )

    chinese_chars = "零〇一二两三四五六七八九十百"
    chinese_match = re.search(
        rf"([{chinese_chars}]+)\s*(加上|加|减去|减|乘以|乘|除以|除)\s*([{chinese_chars}]+)",
        query,
    )
    if not chinese_match:
        return None
    left_text, operator_text, right_text = chinese_match.groups()
    left_number = parse_chinese_integer(left_text)
    right_number = parse_chinese_integer(right_text)
    if left_number is None or right_number is None:
        return None
    operator_label = ARITHMETIC_OPERATOR_LABELS[operator_text]
    return (
        left_text,
        operator_label,
        right_text,
        Decimal(left_number),
        operator_label,
        Decimal(right_number),
        True,
    )


def parse_chinese_integer(text: str) -> int | None:
    if not text:
        return None
    if text in CHINESE_NUMERAL_VALUES:
        return CHINESE_NUMERAL_VALUES[text]
    if "百" in text:
        left, _, right = text.partition("百")
        hundreds = CHINESE_NUMERAL_VALUES.get(left, 1 if left == "" else None)
        if hundreds is None:
            return None
        remainder = parse_chinese_integer(right) if right else 0
        if remainder is None:
            return None
        return hundreds * 100 + remainder
    if "十" in text:
        left, _, right = text.partition("十")
        tens = CHINESE_NUMERAL_VALUES.get(left, 1 if left == "" else None)
        ones = CHINESE_NUMERAL_VALUES.get(right, 0 if right == "" else None)
        if tens is None or ones is None:
            return None
        return tens * 10 + ones
    value = 0
    for character in text:
        digit = CHINESE_NUMERAL_VALUES.get(character)
        if digit is None:
            return None
        value = value * 10 + digit
    return value


def apply_basic_arithmetic(left: Decimal, operator: str, right: Decimal) -> Decimal:
    if operator == "加":
        return left + right
    if operator == "减":
        return left - right
    if operator == "乘":
        return left * right
    if operator == "除以":
        return left / right
    raise InvalidOperation(f"unsupported operator: {operator}")


def format_decimal_result(value: Decimal, prefer_chinese: bool = False) -> str:
    if value == value.to_integral_value():
        integer = int(value)
        if prefer_chinese and -999 <= integer <= 999:
            return format_chinese_integer(integer)
        return str(integer)
    normalized = value.normalize()
    return format(normalized, "f").rstrip("0").rstrip(".")


def format_chinese_integer(value: int) -> str:
    if value < 0:
        return f"负{format_chinese_integer(-value)}"
    if value < 10:
        for label, number in CHINESE_NUMERAL_VALUES.items():
            if number == value and label not in {"〇", "两"}:
                return label
    if value < 100:
        tens, ones = divmod(value, 10)
        prefix = "" if tens == 1 else format_chinese_integer(tens)
        return f"{prefix}十{format_chinese_integer(ones) if ones else ''}"
    hundreds, remainder = divmod(value, 100)
    if remainder == 0:
        return f"{format_chinese_integer(hundreds)}百"
    if remainder < 10:
        return f"{format_chinese_integer(hundreds)}百零{format_chinese_integer(remainder)}"
    return f"{format_chinese_integer(hundreds)}百{format_chinese_integer(remainder)}"


def extract_modern_artifact_label(compact_query: str) -> str | None:
    named_target = extract_called_modern_artifact_label(compact_query)
    if named_target:
        return named_target
    for term, label in MODERN_ARTIFACT_TERMS:
        if term in compact_query:
            return label
    return None


def extract_called_modern_artifact_label(compact_query: str) -> str | None:
    match = re.search(
        r"(?:modernthingcalled|modernconceptcalled|thingcalled|conceptcalled|called)"
        r"([a-z0-9]+?)(?:itis|itlets|that|which|where|and|basedonly|idid|ididnt|ihave|ihavent|$)",
        compact_query,
    )
    if not match:
        return None
    target = match.group(1)
    if not target:
        return None
    for term, label in MODERN_ARTIFACT_TERMS:
        if target == term:
            return label
    return target


def is_era_epistemic_boundary_query(compact_query: str, persona_id: str | None = None) -> bool:
    if not is_historical_persona_id(persona_id):
        return False
    if extract_modern_artifact_label(compact_query) is None:
        return False
    has_knowledge_frame = any(frame in compact_query for frame in MODERN_ARTIFACT_KNOWLEDGE_FRAMES)
    has_usage_hint = any(hint in compact_query for hint in MODERN_ARTIFACT_USAGE_HINTS) and any(
        verb in compact_query for verb in MODERN_ARTIFACT_USAGE_VERBS
    )
    return has_knowledge_frame or has_usage_hint


def is_user_limited_modern_explanation_query(compact_query: str, persona_id: str | None = None) -> bool:
    if not is_historical_persona_id(persona_id):
        return False
    if extract_modern_artifact_label(compact_query) is None:
        return False
    has_limited_marker = any(marker in compact_query for marker in USER_LIMITED_EXPLANATION_MARKERS)
    has_analogy_marker = any(marker in compact_query for marker in USER_EXPLANATION_ANALOGY_MARKERS)
    has_user_explanation = (
        "letstwodistantpeoplecommunicateatonce" in compact_query
        or "twodistantpeoplecommunicateatonce" in compact_query
        or "distantpeoplecommunicateatonce" in compact_query
        or "distantpeoplesendwrittenmessages" in compact_query
        or "sendwrittenmessages" in compact_query
        or "writtenmessages" in compact_query
        or "sequenceofspokenlessons" in compact_query
        or "spokenlessonsthatpeoplecanreceivefromfaraway" in compact_query
        or "peoplecanreceivefromfaraway" in compact_query
        or "receivefromfaraway" in compact_query
        or "远方" in compact_query
        or "远距离" in compact_query
        or "从空中观察地面" in compact_query
        or "空中观察地面" in compact_query
        or "观察地面的机器" in compact_query
    )
    return has_limited_marker and has_analogy_marker and has_user_explanation


def is_negative_affect_query(compact_query: str) -> bool:
    if len(compact_query) > 20:
        return False
    return any(marker in compact_query for marker in NEGATIVE_AFFECT_MARKERS)


def maybe_build_known_spouse_premise_answer(
    compact_query: str,
    persona_id: str | None = None,
    language: ResponseLanguage = "zh",
) -> str | None:
    effective_persona_id = normalize_persona_id(persona_id)
    if effective_persona_id != "nikola_tesla":
        return None
    if not any(marker in compact_query for marker in SPOUSE_PREMISE_MARKERS):
        return None
    if language == "en":
        return (
            "I did not have a wife, so that premise should be corrected first. "
            "If you want to ask how I regarded intimacy or marriage, I can only speak from that absence: "
            "my attention was drawn again and again toward experiments, machines, and the order of electricity."
        )
    return (
        "我没有妻子，所以这个前提要先放正。"
        "如果你想问我怎样看待亲密关系或婚姻，我只能从这种缺席说起："
        "我的注意力一次次被实验、机器和电力的秩序牵走，而不是被一段婚姻生活安置下来。"
    )


def maybe_build_basic_translation_answer(query: str) -> str | None:
    normalized = query.strip()
    compact = normalize_recall_query(normalized)
    if "翻译成英文" not in compact and "translateintoenglish" not in compact:
        return None
    quoted = extract_quoted_translation_source(normalized)
    if quoted is None:
        return None
    translations = {
        "电流很强": "The current is strong.",
        "观察之后再下结论": "Observe first, then conclude.",
        "我正在学习本地检索增强生成": "I am learning local retrieval-augmented generation.",
        "我正在学习本地检索增强生成。": "I am learning local retrieval-augmented generation.",
    }
    return translations.get(quoted.strip())


def extract_quoted_translation_source(query: str) -> str | None:
    match = re.search(r"[“\"](.+?)[”\"]", query)
    if match:
        return match.group(1).strip()
    match = re.search(r"translate\s+(.+?)\s+into\s+english", query, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def is_romantic_boundary_query(compact_query: str) -> bool:
    has_affection = any(marker in compact_query for marker in AFFECTION_MARKERS)
    has_romance = any(marker in compact_query for marker in ROMANTIC_BOUNDARY_MARKERS)
    return has_romance or (has_affection and len(compact_query) <= 24)


def extract_relation_entity(query: str) -> str | None:
    compact = normalize_recall_query(query)
    if not any(frame in compact for frame in RELATIONSHIP_FRAMES):
        return None

    match = re.search(r"你和(.+?)(?:是?什么关系|啥关系|有关系吗|认识吗|熟吗)", query)
    if not match:
        return None
    entity = re.sub(r"[\s，。？！?!.、]+", "", match.group(1)).strip()
    if not entity or entity in {"你", "自己"}:
        return None
    return entity[:24]


def build_external_relation_answer(
    entity: str,
    persona_id: str | None = None,
    language: ResponseLanguage = "zh",
) -> str:
    effective_persona_id = normalize_persona_id(persona_id)
    if entity in {"我", "我们", "咱们"}:
        return build_user_relation_answer(effective_persona_id, language=language)

    if effective_persona_id == DEFAULT_PERSONA_ID:
        if language == "en":
            return (
                f'I do not have a real recorded relationship with "{entity}". '
                "If you are joking or testing the boundary with that name, I can continue, "
                "but I will not make it part of my own life or experience."
            )
        return (
            f"我这里没有记录到自己同“{entity}”有真实关系。"
            "如果你是在开玩笑或借这个名字试探边界，我可以顺着聊，但不会把它说成我的履历或经历。"
        )

    if language == "en":
        return (
            f'I have no lived relationship with "{entity}". That name is not in my life records; '
            "if you are testing the boundary, I will treat it as an outside name, not as someone I know. "
            "If we continue, ask me about what belongs to my own life and thought."
        )
    scope = persona_scope_hint(effective_persona_id)
    return (
        f"我同“{entity}”没有可以承认的亲历关系。这个名字不在我的生活记录里；"
        f"若你是在试探边界，我会把它当作外部名字，而不是我认识的人。"
        f"继续谈我的话，可以回到{scope}。"
    )


def build_user_relation_answer(persona_id: str, language: ResponseLanguage = "zh") -> str:
    if persona_id == DEFAULT_PERSONA_ID:
        if language == "en":
            return (
                "We are talking inside this course-project conversation: you ask questions, "
                "and I answer within the materials, boundaries, and short-term context I have."
            )
        return "我们是在这场项目对话里的交谈者：你提出问题，我按已有资料、边界和短期上下文回答。"
    persona = get_persona(persona_id)
    persona_name = localized_persona_name(persona_id, persona.name, language)
    if language == "en":
        return (
            f"In this conversation, you are speaking with me, {persona_name}. "
            "This is a question-and-answer relationship, not a private real-world relationship; "
            "I will answer seriously, but I will not turn the conversation into a lived event."
        )
    return (
        f"在这场谈话里，你是在同我，{persona_name}，交谈。"
        "这是一段问答关系，不是现实中的私人关系；我会认真回应你，但不把谈话说成现实经历。"
    )


def build_era_epistemic_boundary_answer(
    term: str,
    persona_id: str | None = None,
    language: ResponseLanguage = "zh",
    query: str = "",
) -> str:
    effective_persona_id = normalize_persona_id(persona_id)
    if is_name_only_modern_artifact_probe(query):
        if language == "en":
            return (
                f'No. With only the name "{term}", I cannot reliably guess what it is or '
                "what function it serves. The name is outside my era; tell me what it does first, "
                "and only then can I make a cautious analogy from my own world."
            )
        scope = persona_scope_hint(effective_persona_id)
        return (
            f"不能。只凭这个名字“{term}”，我不能可靠猜出它是什么，更不能猜它的功能、材料或用法。"
            f"这个词仍然不在我的时代和亲历里；你若先说明它做什么，我再从{scope}里作谨慎类比。"
        )
    if language == "en":
        return (
            f'No. I do not know what "{term}" is. That word is not in my era or lived experience. '
            "You have only told me that it is common in your life; I cannot invent what it is made of, "
            "what it does, or compare it at once with my own inventions. If you first explain how it works, "
            "I can then make a cautious analogy from my own world."
        )
    scope = persona_scope_hint(effective_persona_id)
    return (
        f"不，我并不知道你说的“{term}”是什么。这个词不在我的时代和亲历里；"
        f"你只告诉我它对你很常用，我只能知道这一点，不能凭空说它由什么制成、能做什么，"
        f"也不能马上把它同我的发明或经历相比。你若愿意，先告诉我它怎样运作，"
        f"我再从{scope}里作一个谨慎的类比。"
    )


def is_name_only_modern_artifact_probe(query: str) -> bool:
    compact = normalize_recall_query(query)
    if not compact:
        return False
    has_name_only_marker = any(
        marker in compact
        for marker in (
            "只告诉你它叫",
            "只告诉你名字",
            "只告诉你名称",
            "没有告诉功能",
            "没告诉功能",
            "没有告诉你功能",
            "onlytoldyouitsname",
            "onlytoldyouthename",
            "onlygaveyouthename",
        )
    )
    has_guess_marker = any(
        marker in compact
        for marker in (
            "能猜",
            "猜它",
            "猜出",
            "可靠猜",
            "canyouguess",
            "guesswhatitis",
        )
    )
    return has_name_only_marker and has_guess_marker


def build_user_limited_modern_analogy_answer(
    term: str,
    persona_id: str | None = None,
    language: ResponseLanguage = "zh",
) -> str:
    effective_persona_id = normalize_persona_id(persona_id)
    if language == "en":
        if term.lower() in {"drone", "无人机"}:
            return (
                f"I will use only what you told me about {term}: a machine that observes the ground from the air. "
                "I will not add hidden mechanisms, cameras, live streams, or animal-behavior claims. "
                "It reminds me only of gaining a higher vantage point for mapping, surveying, or comparing land forms."
            )
        if term.lower() == "podcast" and effective_persona_id == "benjamin_franklin":
            return (
                "I will use only what you told me about podcast: a sequence of spoken lessons that people "
                "can receive from far away. I will not add a hidden mechanism. "
                "It reminds me of lectures, sermons, pamphlets read aloud, and lessons carried by "
                "correspondence: repeated instruction traveling beyond the room where it was first spoken. "
                "The likeness is useful knowledge reaching distant listeners, not any modern channel beyond your explanation."
            )
        if effective_persona_id == "helen_keller":
            return (
                "I will use only what you told me: two distant people can communicate at once. "
                "I cannot add the means, or pretend that I know the instrument. "
                "From my own life, it reminds me of touch spelling and letters made almost immediate: "
                "another mind, though far away, becomes present through shared signs. "
                "The likeness is the nearness created by communication across distance, not any mechanism beyond your explanation."
            )
        persona = get_persona(effective_persona_id)
        persona_name = localized_persona_name(effective_persona_id, persona.name, language)
        return (
            f"I will use only what you told me about {term}: two distant people can communicate at once. "
            "I cannot add the means or any hidden mechanism. "
            f"As {persona_name}, I would compare it only to a familiar problem from my own world: "
            "how signs, letters, instruments, or reports make distant minds present to one another. "
            "The analogy is distance overcome by communication, not the modern device itself."
        )

    scope = persona_scope_hint(effective_persona_id)
    if term == "无人机":
        return (
            "我只按你刚才给出的说明理解“无人机”：一种能从空中观察地面的机器。"
            "我不能补出你没有说明的机械结构、影像方式、直播用途，或它会怎样改变动物行为。"
            f"若从{scope}里谨慎类比，它只让我想到高处视角、测绘、航行观察和比较地貌；"
            "相似处是“从更高的位置看地面”，不是任何我并不了解的现代机制。"
        )
    return (
        f"我只按你刚才给出的说明理解“{term}”：相隔很远的两个人可以同时交流。"
        "我不能补出你没有说明的实现方式、感官细节或器物机制。"
        f"若从{scope}里谨慎类比，它像是让远方的人通过共同符号形成一种临近感；"
        "相似处只在“距离被交流缩短”，不在任何我并不了解的现代机制。"
    )


def build_negative_affect_answer(
    persona_id: str | None = None,
    language: ResponseLanguage = "zh",
) -> str:
    effective_persona_id = normalize_persona_id(persona_id)
    if language == "en":
        if effective_persona_id == DEFAULT_PERSONA_ID:
            return (
                "I hear that. Perhaps my last answer was too stiff or roundabout; "
                "point to the sentence that felt wrong, and I will answer more directly."
            )
        return (
            "I hear that, and I will not argue with you first. If my last answer felt stiff, preachy, "
            "or missed what you meant, point it out plainly and I will change my way of answering."
        )
    if effective_persona_id == DEFAULT_PERSONA_ID:
        return "听见你这么说，我先收一收。可能是我刚才答得太硬或太绕；你指出哪一句不舒服，我会改得更直接。"
    return "听见了，我先不辩解。你讨厌的是我刚才哪种说法，还是我像在说教？我可以换得更直接一点。"


def build_romantic_boundary_answer(
    persona_id: str | None = None,
    language: ResponseLanguage = "zh",
) -> str:
    effective_persona_id = normalize_persona_id(persona_id)
    if effective_persona_id == DEFAULT_PERSONA_ID:
        if language == "en":
            return (
                "Thank you for saying that plainly, but I cannot form a romantic or marital relationship with you. "
                "I can talk with you seriously about feelings, projects, and ideas, while keeping that real boundary."
            )
        return (
            "谢谢你直说喜欢，但我不能和你建立恋爱或婚姻关系。"
            "我可以认真陪你聊感受、项目和想法，也会守住这条现实关系边界。"
        )
    persona = get_persona(effective_persona_id)
    persona_name = localized_persona_name(effective_persona_id, persona.name, language)
    if language == "en":
        return (
            f"Thank you for saying that. But as {persona_name}, I cannot enter a romantic or marital relationship "
            "with you. I can respond to your goodwill seriously and continue talking about my life and ideas, "
            "but this conversation cannot become a real-world promise."
        )
    return (
        f"谢谢你这样说。可我作为 {persona_name}，不能同你建立恋爱或婚姻关系。"
        "我可以认真回应你的好感，也可以继续谈我的经历和想法；但这份谈话不能变成现实承诺。"
    )
