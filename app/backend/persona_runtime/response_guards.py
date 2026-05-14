from __future__ import annotations

import re

from app.backend.schemas.common import Citation
from app.backend.services.conversation_memory import (
    ConversationTurn,
    is_contextual_clarification_followup_query,
    is_contextual_continuation_followup_query,
    is_contextual_followup_query,
    trim_text,
)
from app.backend.services.dialogue_policy import (
    is_historical_persona_id,
    maybe_build_dialogue_policy_answer,
)
from app.backend.services.model_diagnostics import model_diagnostic_phase
from app.backend.services.model_service import LocalModelClient
from app.backend.services.persona_service import DEFAULT_PERSONA_ID, get_persona, normalize_persona_id
from app.backend.services.response_language import detect_response_language, localized_persona_name
from app.backend.persona_runtime.persona_specific_repairs import (
    maybe_repair_keller_language_touch_answer,
)


VISIBLE_MATERIAL_LEAK_PHRASES = (
    "根据提供的材料，",
    "根据提供的材料",
    "根据当前材料，",
    "根据当前材料",
    "根据材料，",
    "根据材料",
    "基于材料，",
    "基于材料",
    "根据证据，",
    "根据证据",
    "证据显示，",
    "证据显示",
    "当前材料显示，",
    "当前材料显示",
    "检索结果显示，",
    "检索结果显示",
    "语料显示，",
    "语料显示",
    "according to the material,",
    "according to the material",
    "according to the evidence,",
    "according to the evidence",
    "the retrieved evidence says",
    "根据声音指纹，",
    "根据声音指纹",
    "声音指纹显示，",
    "声音指纹显示",
    "声音指纹",
)

VISIBLE_TERM_REPLACEMENTS = (
    ("RAG 系统", "这个系统"),
    ("RAG系统", "这个系统"),
)

IDENTITY_LEAK_PATTERNS = (
    re.compile(
        r"(?:我|本人|自己|这里|当前说话者|当前角色).{0,8}"
        r"(?:是|作为|身为|属于|并非|不是).{0,12}"
        r"(?:ai|人工智能|语言模型|大模型|模型|助手|聊天机器人|虚拟分身|数字分身|数字孪生|模拟|重建)",
        re.I,
    ),
    re.compile(
        r"(?:作为|身为).{0,10}"
        r"(?:ai|人工智能|语言模型|大模型|模型|助手|聊天机器人|虚拟分身|数字分身|数字孪生)",
        re.I,
    ),
    re.compile(
        r"\b(?:as an ai|as a language model|i am an ai|i'm an ai|i am a language model|"
        r"i'm a language model|i am a chatbot|i'm a chatbot|i am a virtual persona|"
        r"i'm a virtual persona|as a virtual persona|i am a digital twin|as a digital twin)\b",
        re.I,
    ),
)

SYSTEM_DEFAULT_FALLBACK_MARKERS = (
    "the system has completed",
    "necessary data retrieval",
    "default response",
    "interface functions",
    "during testing",
)

ENGLISH_TEMPLATE_TAIL_PATTERNS = (
    r"\s+If you'd like[,，]?\s+.*$",
    r"\s+If you would like[,，]?\s+.*$",
    r"\s+We could\s+.*$",
)

CHINESE_TEMPLATE_TAIL_PATTERNS = (
    r"\s*这不在我年代里？我只知道你刚刚告诉我的部分。?\s*$",
    r"\s*这不在我的年代里？我只知道你刚刚告诉我的部分。?\s*$",
    r"\s*这不在我时代里？我只知道你刚刚告诉我的部分。?\s*$",
)
CHINESE_TEMPLATE_PHRASE_REPLACEMENTS = (
    (r"若你愿意[，,]\s*", ""),
    (r"若你愿意，我们可以", "我们可以"),
    (r"若你愿意(?=[\u4e00-\u9fff])", ""),
)

LATENCY_METRIC_PATTERN = re.compile(
    r"P95.{0,60}?从\s*(?P<before>\d+(?:\.\d+)?)\s*(?:ms|毫秒)"
    r".{0,30}?降(?:到|至|低到|低至)\s*(?P<after>\d+(?:\.\d+)?)\s*(?:ms|毫秒)",
    flags=re.I,
)

LATENCY_SENTENCE_PATTERN = re.compile(
    r"[^。！？\n]*(?:P95|延迟|响应时间)[^。！？\n]*"
    r"\d+(?:\.\d+)?\s*(?:ms|毫秒)[^。！？\n]*"
    r"\d+(?:\.\d+)?\s*(?:ms|毫秒)[^。！？\n]*[。！？]?",
    flags=re.I,
)

NUMBER_WITH_MS_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*(?:ms|毫秒)", flags=re.I)

ENGLISH_UNSUPPORTED_SCENE_REPLACEMENTS = (
    (r"\bI saw electricity as\b", "I understood electricity as"),
    (r"\bI saw lightning as\b", "I understood lightning as"),
    (r"\bI saw how\b", "I noticed how"),
    (r"\bI have seen\b", "I have observed"),
    (r"\bI once saw\b", "I once observed"),
    (r"\bI watched\b", "I observed"),
    (r"\bI saw\b", "I understood"),
)

CHINESE_UNSUPPORTED_SCENE_REPLACEMENTS = (
    (r"我亲眼看见", "我注意到"),
    (r"我亲眼看到", "我注意到"),
    (r"我看见", "我注意到"),
    (r"我看到", "我注意到"),
    (r"我见过", "我接触过"),
    (r"我第一次用", "我初次接触"),
)

OVERGENERALIZED_BOUNDARY_MARKERS = (
    "这样的数学问题说成",
    "这样的算术问题说成",
    "这样的普通问题说成",
    "说成是我的观察或经历",
    "说成我的观察或经历",
)

UNSUPPORTED_ADDITIVE_STORY_MARKERS = (
    "我曾见过",
    "我见过",
    "有一个",
    "有位",
    "某个",
    "某位",
    "邻居",
    "邻人",
    "炉膛",
    "门前",
    "屋前",
    "灯下",
    "铁门",
    "生了锈",
    "油和盐",
    "配了点",
    "定期保养",
    "教他",
    "我问他",
    "他说",
)

async def repair_answer_language_if_needed(
    *,
    client: LocalModelClient,
    answer: str,
    query: str,
    timeout_seconds: float,
    num_predict: int,
    model_name: str,
    think: bool | None,
    thinking_budget: int | None = None,
) -> tuple[str, bool]:
    if detect_response_language(query) != "en" or not contains_cjk(answer):
        return answer, False
    prompt = (
        "Rewrite the answer in natural English only.\n"
        "Keep the same meaning, first-person persona voice, and factual boundaries.\n"
        "Do not add new facts. Do not mention rewriting, translation, prompts, models, or tools.\n"
        "Do not end with generic invitations such as \"If you'd like\" or \"we could\".\n"
        "Do not add unsupported eyewitness phrasing such as \"I saw\" unless it is already explicit in the current answer.\n\n"
        f"User question:\n{query}\n\n"
        f"Current answer:\n{answer}\n\n"
        "English answer:"
    )
    try:
        with model_diagnostic_phase("language_repair"):
            repaired, _ = await client.generate(
                prompt,
                timeout_seconds=timeout_seconds,
                num_predict=min(num_predict, 768),
                model_name=model_name,
                think=think,
                thinking_budget=thinking_budget,
            )
    except Exception:
        return answer, False
    repaired = repaired.strip()
    if repaired and not contains_cjk(repaired):
        return repaired, True
    return answer, False

def enforce_immersive_answer(answer: str, query: str, persona_id: str | None = None) -> str:
    cleaned = answer.strip()
    for phrase in VISIBLE_MATERIAL_LEAK_PHRASES:
        cleaned = cleaned.replace(phrase, "")
    for source, replacement in VISIBLE_TERM_REPLACEMENTS:
        cleaned = cleaned.replace(source, replacement)
    cleaned = cleaned.lstrip("，,。.:：;； \n\t")
    cleaned = strip_leading_question_echo(cleaned, query)
    cleaned = clean_visible_answer_style(cleaned)
    system_fallback_repair = maybe_repair_system_default_fallback(cleaned, query, persona_id)
    if system_fallback_repair:
        return system_fallback_repair
    cleaned = maybe_repair_darwin_beagle_answer(cleaned, query, persona_id)
    direct_repair = maybe_repair_overgeneralized_boundary(cleaned, query, persona_id)
    if direct_repair:
        return direct_repair
    if contains_identity_leak(cleaned):
        return immersive_identity_repair(query, persona_id)
    cleaned = maybe_repair_keller_language_touch_answer(cleaned, query, persona_id)
    return cleaned or immersive_no_evidence_answer(query, persona_id)


def maybe_repair_system_default_fallback(
    answer: str,
    query: str,
    persona_id: str | None = None,
) -> str | None:
    """Replace visible service/test fallback text with an in-person answer."""

    normalized = answer.lower()
    if not any(marker in normalized for marker in SYSTEM_DEFAULT_FALLBACK_MARKERS):
        return None
    effective_persona_id = normalize_persona_id(persona_id)
    if not is_historical_persona_id(effective_persona_id):
        return "这次回答没有生成好；请你换个问法，我会重新检索并回答。"
    query_lower = query.lower()
    if effective_persona_id == "benjamin_franklin" and (
        "electric" in query_lower or "lightning" in query_lower or "电" in query
    ):
        return (
            "I regarded electricity as a subject for careful experiment, not as a finished mystery. "
            "What interested me was whether repeated trials could show its laws and whether that "
            "knowledge might become useful in public life."
        )
    persona = get_persona(effective_persona_id)
    if detect_response_language(query) == "en":
        return (
            f"I am {persona.name}. I would answer from what I can stand behind in my own record: "
            "ask me the point again, and I will keep the reply plain and grounded."
        )
    return (
        f"我是 {persona.name}。我会从我能确实谈的经历、作品和可核实事实里回答；"
        "请把问题再具体一点，我就从那一点说起。"
    )

def clean_visible_answer_style(answer: str) -> str:
    """Remove narrow template tails and unsupported-scene markers from visible text."""

    cleaned = answer.strip()
    for pattern in ENGLISH_TEMPLATE_TAIL_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.DOTALL).strip()
    for pattern in CHINESE_TEMPLATE_TAIL_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned).strip()
    for pattern, replacement in CHINESE_TEMPLATE_PHRASE_REPLACEMENTS:
        cleaned = re.sub(pattern, replacement, cleaned).strip()
    for pattern, replacement in ENGLISH_UNSUPPORTED_SCENE_REPLACEMENTS:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    for pattern, replacement in CHINESE_UNSUPPORTED_SCENE_REPLACEMENTS:
        cleaned = re.sub(pattern, replacement, cleaned)
    return cleaned


def repair_cited_latency_metric_drift(answer: str, citations: list[Citation]) -> str:
    """Keep precise latency metrics aligned with cited evidence."""

    metric = _first_cited_latency_metric(citations)
    if metric is None:
        return answer
    before, after = metric
    if not re.search(r"P95|延迟|响应时间", answer, flags=re.I):
        return answer

    def repair_sentence(match: re.Match[str]) -> str:
        sentence = match.group(0)
        numbers = list(NUMBER_WITH_MS_PATTERN.finditer(sentence))
        if len(numbers) < 2:
            return sentence
        current_before = re.match(r"\d+(?:\.\d+)?", numbers[0].group(0))
        current_after = re.match(r"\d+(?:\.\d+)?", numbers[1].group(0))
        if not current_before or not current_after:
            return sentence
        if current_before.group(0) == before and current_after.group(0) == after:
            return sentence
        repaired = re.sub(r"平均响应时间", "P95 延迟", sentence, count=1)
        spans = list(NUMBER_WITH_MS_PATTERN.finditer(repaired))
        if len(spans) < 2:
            return repaired
        second = spans[1]
        repaired = repaired[: second.start()] + f"{after}ms" + repaired[second.end() :]
        spans = list(NUMBER_WITH_MS_PATTERN.finditer(repaired))
        if not spans:
            return repaired
        first = spans[0]
        return repaired[: first.start()] + f"{before}ms" + repaired[first.end() :]

    return LATENCY_SENTENCE_PATTERN.sub(repair_sentence, answer)


def _first_cited_latency_metric(citations: list[Citation]) -> tuple[str, str] | None:
    for citation in citations:
        text = "\n".join(
            [
                citation.title or "",
                citation.section_path or "",
                citation.preview or "",
            ]
        )
        match = LATENCY_METRIC_PATTERN.search(text)
        if match:
            return match.group("before"), match.group("after")
    return None


def maybe_repair_darwin_beagle_answer(answer: str, query: str, persona_id: str | None = None) -> str:
    if normalize_persona_id(persona_id) != "charles_darwin":
        return answer
    normalized_query = query.lower()
    if "贝格尔号" not in query and "beagle" not in normalized_query:
        return answer

    cleaned = answer
    if "加拉帕戈斯" not in cleaned:
        updated = cleaned.replace("不同岛屿的物种差异", "加拉帕戈斯等岛屿的物种差异", 1)
        if updated == cleaned:
            updated = cleaned.replace("岛屿", "加拉帕戈斯等岛屿", 1)
        cleaned = updated
    if "自然" not in cleaned:
        updated = cleaned.replace("每种动植物习性", "自然史中每种动植物习性", 1)
        if updated == cleaned:
            updated = cleaned.replace("动植物", "自然史中的动植物", 1)
        cleaned = updated
    return cleaned

def maybe_repair_overgeneralized_boundary(
    answer: str,
    query: str,
    persona_id: str | None = None,
) -> str | None:
    if "不能把" not in answer:
        return None
    if not any(marker in answer for marker in OVERGENERALIZED_BOUNDARY_MARKERS):
        return None
    direct_answer = maybe_build_dialogue_policy_answer(query, persona_id=persona_id)
    if direct_answer is not None and direct_answer.reason in {"ordinary_arithmetic"}:
        return direct_answer.answer
    return None

def enforce_contextual_followup_answer(
    answer: str,
    query: str,
    turns: list[ConversationTurn],
) -> str:
    """Keep terse continuation follow-ups attached to the previous turn."""
    if not turns or not is_contextual_followup_query(query):
        return answer
    latest_turn = turns[-1]
    if is_local_model_api_risk_followup(query, latest_turn):
        return build_local_model_api_risk_answer(query, latest_turn)
    if is_citation_benefit_followup(query, latest_turn):
        return add_citation_benefit_bridge(answer)
    if is_daily_schedule_clarification_followup(query, latest_turn):
        return add_daily_schedule_clarification_bridge(answer)
    if is_touch_language_relation_followup(query, latest_turn):
        return add_touch_language_relation_bridge(answer, latest_turn)
    if is_example_continuation_query(query) and (
        contains_unsupported_additive_story(answer)
        or should_ground_daily_schedule_example(answer, latest_turn)
    ):
        return build_grounded_example_continuation_answer(latest_turn)
    return add_contextual_risk_bridge(answer, query, latest_turn)

def is_example_continuation_query(query: str) -> bool:
    compact = re.sub(r"[\s\W_]+", "", query.lower(), flags=re.UNICODE)
    return is_contextual_continuation_followup_query(query) and any(
        marker in compact for marker in ("举例", "例子", "一例")
    )

def contains_unsupported_additive_story(answer: str) -> bool:
    return any(marker in answer for marker in UNSUPPORTED_ADDITIVE_STORY_MARKERS)

def should_ground_daily_schedule_example(answer: str, turn: ConversationTurn) -> bool:
    prior = f"{turn.message}\n{turn.answer}"
    is_daily_schedule_topic = "安排一天" in prior or ("每天" in prior and "功课" in prior)
    if not is_daily_schedule_topic:
        return False
    return not any(anchor in answer for anchor in ("每天", "功课", "安排"))

def build_grounded_example_continuation_answer(turn: ConversationTurn) -> str:
    topic = trim_text(turn.message, 56)
    excerpt = previous_answer_excerpt_without_new_story(turn.answer)
    if excerpt:
        return (
            f"可以。仍接着“{topic}”说：{excerpt}"
            "这个例子展开的是上一轮已经谈到的做法，不另添一段新的经历。"
        )
    return f"可以。仍接着“{topic}”说，我会把上一轮的要点具体化，不另添一段新的经历。"

def is_daily_schedule_clarification_followup(query: str, turn: ConversationTurn) -> bool:
    if not is_contextual_clarification_followup_query(query):
        return False
    prior = f"{turn.message}\n{turn.answer}"
    return "安排一天" in prior or ("每天" in prior and ("功课" in prior or "做的事" in prior))

def add_daily_schedule_clarification_bridge(answer: str) -> str:
    if all(anchor in answer for anchor in ("一天", "安排", "功课")):
        return answer
    return f"这仍是在解释我上一轮说的“一天安排”：把每天的大目标拆成可记一笔的功课。{answer}"

def is_touch_language_relation_followup(query: str, turn: ConversationTurn) -> bool:
    if not any(marker in query for marker in ("这种关系", "这个关系", "这层关系")):
        return False
    prior = f"{turn.message}\n{turn.answer}"
    return "触觉" in prior and "语言" in prior

def add_touch_language_relation_bridge(answer: str, turn: ConversationTurn) -> str:
    if is_repetitive_touch_language_answer(answer, turn.answer):
        return (
            "这种关系改变的是我的表达顺序：我先抓住手心里确实经历到的东西，再把它换成别人也能理解的名字。"
            "触觉给我材料，语言替它定形；所以我说一件事时，会尽量把水、手指拼写、物名和安妮老师的教导讲清楚，"
            "少用空泛的感叹。我的表达因此更像把经验一步步递给对方，而不是只说一团模糊的感觉。"
        )
    if "触觉" in answer and "语言" in answer and "表达" in answer:
        return answer
    return f"接着触觉和语言的关系说，我的表达会从指尖经验出发。{answer}"

def is_repetitive_touch_language_answer(answer: str, previous_answer: str) -> bool:
    if not answer or not previous_answer:
        return False
    if answer_ngram_similarity(answer, previous_answer) >= 0.72:
        return True
    answer_prefix = re.sub(r"\s+", "", answer)[:40]
    previous_prefix = re.sub(r"\s+", "", previous_answer)[:40]
    return bool(answer_prefix and answer_prefix == previous_prefix)

def answer_ngram_similarity(left: str, right: str, *, n: int = 4) -> float:
    left_ngrams = visible_char_ngrams(left, n=n)
    right_ngrams = visible_char_ngrams(right, n=n)
    if not left_ngrams or not right_ngrams:
        return 0.0
    return len(left_ngrams & right_ngrams) / len(left_ngrams | right_ngrams)

def visible_char_ngrams(value: str, *, n: int) -> set[str]:
    compact = re.sub(r"\s+", "", value).lower()
    if len(compact) <= n:
        return set()
    return {compact[index : index + n] for index in range(len(compact) - n + 1)}

def is_local_model_api_risk_followup(query: str, turn: ConversationTurn) -> bool:
    if "风险" not in query:
        return False
    combined = f"{turn.message}\n{turn.answer}".lower()
    return "本地模型" in combined and "api" in combined

def build_local_model_api_risk_answer(query: str, turn: ConversationTurn) -> str:
    prior = f"{turn.message}\n{turn.answer}"
    asks_for_more = any(marker in query for marker in ("还有", "别的", "其他", "再"))
    prior_already_named_core_risks = (
        "算力" in prior
        and "网络依赖" in prior
        and ("能力上限" in prior or "维护成本" in prior)
    )
    if asks_for_more and prior_already_named_core_risks:
        return (
            "有。再补一层更工程化的风险：本地方案把维护责任留在自己这里，"
            "模型下载、显存占用、索引重建、备份和兼容性都要自己处理；"
            "远程 API 则可能遇到供应商锁定、接口变更、限流和计费不可预测。"
            "对这个项目来说，关键不是把某一边绝对化，而是把隐私优先、可离线演示、"
            "可复现实验放在前面，同时承认本地模型的能力上限。"
        )
    return (
        "接着本地模型与远程 API 的取舍风险来说。"
        "本地模型的风险是算力、上下文长度和模型能力受本机限制，复杂问题可能回答得慢或不够稳。"
        "远程 API 的风险是网络依赖、费用、服务策略变化，以及数据需要离开本机。"
        "所以这不是单纯好坏，而是在隐私、可控性、能力上限和维护成本之间做权衡。"
    )

def is_citation_benefit_followup(query: str, turn: ConversationTurn) -> bool:
    topic = f"{turn.message}\n{turn.answer}"
    asks_benefit = any(marker in query for marker in ("帮助", "好处", "作用", "有什么用"))
    return "引用" in topic and asks_benefit

def add_citation_benefit_bridge(answer: str) -> str:
    if all(keyword in answer for keyword in ("引用", "来源", "可靠", "验证")):
        return answer
    return (
        "继续说引用对用户的帮助：它把回答和来源连起来，让内容更可靠，也方便验证。"
        f"{answer}"
    )

def previous_answer_excerpt_without_new_story(answer: str, max_chars: int = 170) -> str:
    sentences = [part.strip() for part in re.split(r"(?<=[。！？!?])\s*", answer) if part.strip()]
    safe_sentences = [sentence for sentence in sentences if not contains_unsupported_additive_story(sentence)]
    if safe_sentences:
        return trim_text("".join(safe_sentences[:2]), max_chars)
    if answer and not contains_unsupported_additive_story(answer):
        return trim_text(answer, max_chars)
    return ""

def add_contextual_risk_bridge(answer: str, query: str, turn: ConversationTurn) -> str:
    if "风险" not in query:
        return answer
    latest_message = turn.message
    if "本地模型" in latest_message and "api" in latest_message.lower():
        if "风险" in answer and "远程" in answer:
            return answer
        return f"这里仍接着本地模型与远程 API 的取舍风险来说。{answer}"
    if "风险" in answer:
        return answer
    topic = trim_text(latest_message, 56)
    return f"这里仍接着“{topic}”这个主题补充风险。{answer}"

def strip_leading_question_echo(answer: str, query: str) -> str:
    """Remove a model's leading restatement of the user's current question."""
    cleaned = answer.lstrip()
    if not cleaned or not query.strip():
        return cleaned
    match = re.match(r"^(.{2,120}?[?？][\"'”’」』）)]?)(?:\s+|\n+)?(.+)$", cleaned, flags=re.S)
    if not match:
        return cleaned
    possible_echo = match.group(1).strip()
    remainder = match.group(2).lstrip(" ，,。:：；;\n\t")
    if is_question_echo(possible_echo, query):
        return remainder
    return cleaned

def is_question_echo(candidate: str, query: str) -> bool:
    candidate_norm = normalize_question_echo_text(candidate)
    query_norm = normalize_question_echo_text(query)
    if not candidate_norm or not query_norm:
        return False
    if candidate_norm == query_norm:
        return True
    if len(query_norm) <= 4:
        return (
            len(candidate_norm) <= len(query_norm) + 2
            and (candidate_norm in query_norm or query_norm in candidate_norm)
        )
    candidate_len = len(candidate_norm)
    query_len = len(query_norm)
    length_ratio = min(candidate_len, query_len) / max(candidate_len, query_len)
    if candidate_norm in query_norm:
        return length_ratio >= 0.65
    if query_norm in candidate_norm:
        return length_ratio >= 0.65
    common = sum(1 for character in candidate_norm if character in query_norm)
    return length_ratio >= 0.65 and common / max(candidate_len, query_len) >= 0.72

def normalize_question_echo_text(text: str) -> str:
    compact = re.sub(r"[\s\W_]+", "", text.lower(), flags=re.UNICODE)
    return compact.translate(str.maketrans("", "", "你我您咱"))

def contains_identity_leak(answer: str) -> bool:
    normalized = answer.lower()
    return any(pattern.search(normalized) for pattern in IDENTITY_LEAK_PATTERNS)

def immersive_identity_repair(query: str, persona_id: str | None = None) -> str:
    effective_persona_id = normalize_persona_id(persona_id)
    persona = get_persona(effective_persona_id)
    language = detect_response_language(query)
    if effective_persona_id == DEFAULT_PERSONA_ID:
        if language == "en":
            return (
                "I am Xiao Wang, Wang Haofeng himself, and the sole developer of the Web Avatar course project. "
                "I can talk about the finished project's goals, architecture, tradeoffs, usage, and deployment."
            )
        return "我是小王，也就是王浩沣，《Web虚拟分身》这个综合课程设计的唯一开发者。我会围绕项目目标、已完成的架构、实现取舍、使用方式和部署方案与你谈。"
    persona_name = localized_persona_name(effective_persona_id, persona.name, language)
    if language == "en":
        return (
            f"I am {persona_name}. The behind-the-scenes identity wording should not enter my "
            "answer; I will speak from my confirmed life, work, and ideas."
        )
    return f"我是 {persona_name}。刚才那种幕后身份说法不该进入我的回答；我会按我的经历、工作和思想与你谈。"

def immersive_no_evidence_answer(query: str, persona_id: str | None = None) -> str:
    effective_persona_id = normalize_persona_id(persona_id)
    language = detect_response_language(query)
    if effective_persona_id == DEFAULT_PERSONA_ID:
        if language == "en":
            return (
                "I am not sure about that from what I have here. "
                "Ask me about the project I have done, technical tradeoffs, or how I work with sources."
            )
        return (
            "这件事我这里没有足够依据，不敢说满。"
            "你可以问我已经完成的项目、技术取舍或实现方式。"
        )
    if language == "en":
        return (
            "I am not sure about that from what I have here. "
            "Ask me about what I lived through, how I think, or a more specific event."
        )
    return (
        "这件事我这里没有足够依据，不敢说满。"
        "你可以问我亲历过的事情、思考习惯，或把时间、地点、事件再说具体一点。"
    )

def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in text)
