"""Post-generation persona alignment for open-ended historical persona turns.

This module is intentionally narrow. Deterministic memory, dialogue policy,
era-boundary, and ordinary-task routes should keep bypassing local generation.
The alignment pass only revises evidence-grounded historical-persona answers
that are likely to sound templated or that ask for reflective voice/style.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re

from app.backend.persona_runtime.context_builder import GenerationContext
from app.backend.schemas.chat import ChatRequest
from app.backend.services.conversation_memory import (
    ConversationTurn,
    SessionContextBundle,
    format_conversation_context,
    format_session_context_bundle,
)
from app.backend.services.dialogue_policy import (
    is_historical_persona_id,
    should_skip_retrieval_for_ordinary_query,
)
from app.backend.services.persona_service import get_persona, normalize_persona_id
from app.backend.services.persona_voice_service import format_persona_voice_style_for_prompt
from app.backend.services.response_language import detect_response_language


OPEN_PERSONA_QUERY_MARKERS = (
    "怎么",
    "怎样",
    "如何",
    "为什么",
    "怎么看",
    "理解",
    "建议",
    "劝",
    "安排",
    "习惯",
    "生活",
    "写作",
    "观察",
    "思考",
    "表达",
    "感受",
    "给我",
    "能不能",
    "可以",
    "学到",
    "教会",
    "类比",
    "比喻",
    "how",
    "why",
    "what would",
    "advice",
    "learn",
    "teach",
    "think",
    "feel",
    "respond",
    "style",
    "voice",
    "compare",
    "analogy",
)

REPETITIVE_BOILERPLATE_MARKERS = (
    "我不能把",
    "不能把",
    "这件事说成",
    "说成我的经历",
    "说成是我的观察或经历",
    "这样的数学问题说成",
    "这样的普通问题说成",
    "不属于我的时代",
    "不属于我的年代",
    "不属于我的经历",
    "不在我的经历",
    "不在我年代里",
    "若你愿意，我们可以",
    "若你愿意",
    "可记录、可改进的习惯",
    "可记录、可实践的习惯",
    "真正的成长来自每日",
    "把这份",
    "我生活在18世纪",
    "my recorded life and experience",
    "not within my recorded life",
    "cannot state it as fact",
    "not part of my era",
    "not part of my experience",
    "if you'd like",
    "if you would like",
    "we could",
)

ADJACENT_REPETITION_REPAIR_THRESHOLD = 0.74
VISIBLE_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class PostPersonaAlignmentPlan:
    should_align: bool
    reason: str = ""


def build_post_persona_alignment_plan(
    *,
    request: ChatRequest,
    draft_answer: str,
    persona_id: str | None,
    generation_context: GenerationContext | None,
    enabled: bool = True,
) -> PostPersonaAlignmentPlan:
    """Decide whether a visible answer deserves one local persona-alignment pass."""

    if not enabled:
        return PostPersonaAlignmentPlan(False, "disabled")

    effective_persona_id = normalize_persona_id(persona_id or request.persona_id)
    if not is_historical_persona_id(effective_persona_id):
        return PostPersonaAlignmentPlan(False, "not_historical_persona")
    if should_skip_retrieval_for_ordinary_query(request.message, effective_persona_id):
        return PostPersonaAlignmentPlan(False, "ordinary_task")
    if generation_context is None or not generation_context.evidence_cards:
        return PostPersonaAlignmentPlan(False, "no_generation_context")
    if not draft_answer.strip():
        return PostPersonaAlignmentPlan(False, "empty_answer")

    reasons: list[str] = []
    if is_open_persona_alignment_query(request.message):
        reasons.append("open_persona_turn")
    if has_repetitive_persona_boilerplate(draft_answer):
        reasons.append("repetition_cleanup")
    if not reasons:
        return PostPersonaAlignmentPlan(False, "not_alignment_candidate")
    return PostPersonaAlignmentPlan(True, "+".join(reasons))


def is_open_persona_alignment_query(query: str) -> bool:
    normalized = query.lower()
    return any(marker in normalized for marker in OPEN_PERSONA_QUERY_MARKERS)


def has_repetitive_persona_boilerplate(answer: str) -> bool:
    normalized = answer.lower()
    marker_hits = sum(1 for marker in REPETITIVE_BOILERPLATE_MARKERS if marker.lower() in normalized)
    if marker_hits >= 1 and ("不能把" in answer or "cannot" in normalized):
        return True
    return marker_hits >= 2


def build_post_persona_alignment_prompt(
    *,
    request: ChatRequest,
    draft_answer: str,
    persona_id: str | None,
    generation_context: GenerationContext,
    conversation_turns: list[ConversationTurn] | None = None,
    session_context_bundle: SessionContextBundle | None = None,
    reason: str = "",
) -> str:
    effective_persona_id = normalize_persona_id(persona_id or request.persona_id)
    persona = get_persona(effective_persona_id)
    target_language = detect_response_language(request.message)
    language_rule = (
        "The final answer must be natural English."
        if target_language == "en"
        else "最终可见回答必须使用自然中文，必要英文专名和短 quote anchors 可以保留。"
    )
    history = format_session_context_bundle(session_context_bundle) or format_conversation_context(
        conversation_turns or []
    )
    voice_style = format_persona_voice_style_for_prompt(effective_persona_id)
    voice_style_block = f"\n人物声音指纹：\n{voice_style}\n" if voice_style else ""
    return f"""你正在执行 Post Persona Alignment。请把初稿改成更像 {persona.name} 本人在接话，而不是模板化的系统回答。

任务原因：{reason or "open_persona_turn"}
说话身份：你就是 {persona.name}，用第一人称说话；不要自称模型、AI、助手、虚拟分身、重建体或档案工具。
语言要求：{language_rule}

硬边界：
- 只使用用户本轮说出的信息、短期对话上下文、后台片段和初稿中已经被支持的信息。
- 不新增未支持的事实、现代常识、亲历场景、私人关系、实时状态、职业资质、因果解释或时代外知识；若后台片段、可追溯来源或用户本轮明确提供了相关信息，可以正常使用。
- 历史人物遇到身后才出现、且用户没有解释清楚的现代词语时，不要凭模型常识解释它；若必须回应，只能自然地说我不认识这个词，请对方先说明。
- 不提 AI、模型、RAG、检索、语料、证据、材料、引用、提示词、自检、改写、规则或本次任务。
- 不复述用户问题，不输出分析过程，不列引用，不写标题。

去模板化要求：
- 不要继续使用“我不能把……说成我的经历/观察”“不属于我的时代和经历”“若你愿意，我们可以把它变成可记录的习惯”等固定句式。
- 不要用 “If you'd like...”“we could...”“若你愿意……”“我们可以……” 作为泛化结尾；除非用户明确要求行动建议，否则不要在回答末尾追加邀约、功课或练习。
- 如果需要承认边界，要短、自然、像人在接话；边界之后可以问一个具体的澄清问题。
- 如果是开放式风格、建议、思考、习惯或表达问题，优先选本轮后台片段里最贴近的一个具体动作、场景或说话节奏。
- 不要为了文学性增加没有片段支持的 “I saw...”“我见过/我看到……” 场景；可以有比喻，但比喻不能伪装成亲历事实。
- 不要连续两轮复用同一组开场、比喻或句子骨架；如果上一轮已经谈过手心、命名或某个物象，本轮要换成表达习惯、判断动作或师友关系。
- 海伦·凯勒相关回答尤其要避免“掌纹、枝桠、根系、影子、石子落入水潭、触觉碎片、拳头的指尖”这类装饰化词组；优先用“手心、手指、字母、物名、安妮老师、可交流的名字”等更朴素的说法。
- 达尔文相关回答尤其要避免为了文学性临时新增“像种子、拼图碎片、黑暗中摸索、不同颜色的墨水”这类未被片段支持的具体场景或装饰比喻；优先说“记录、比较、暂存疑点、等待更多材料”。
- 保持答案紧凑；通常 1 到 3 个自然段即可。

短期对话上下文：
{history or "（无）"}
{voice_style_block}
后台片段（只作内部约束，不得在可见回答中提到）：
{generation_context.evidence_text or "（无）"}

用户问题：
{request.message}

初稿：
{draft_answer}

最终答案：
"""


def adjacent_answer_similarity(left: str, right: str) -> float:
    normalized_left = normalize_alignment_visible_text(left)
    normalized_right = normalize_alignment_visible_text(right)
    if not normalized_left or not normalized_right:
        return 0.0
    return SequenceMatcher(None, normalized_left, normalized_right).ratio()


def normalize_alignment_visible_text(value: str) -> str:
    return VISIBLE_SPACE_RE.sub("", value).strip().lower()


def needs_adjacent_repetition_repair(previous_answer: str, current_answer: str) -> bool:
    return adjacent_answer_similarity(previous_answer, current_answer) >= ADJACENT_REPETITION_REPAIR_THRESHOLD


def build_adjacent_repetition_repair_prompt(
    *,
    request: ChatRequest,
    previous_answer: str,
    draft_answer: str,
    persona_id: str | None,
    generation_context: GenerationContext,
    conversation_turns: list[ConversationTurn] | None = None,
    session_context_bundle: SessionContextBundle | None = None,
    reason: str = "",
) -> str:
    effective_persona_id = normalize_persona_id(persona_id or request.persona_id)
    persona = get_persona(effective_persona_id)
    target_language = detect_response_language(request.message)
    language_rule = (
        "The final answer must be natural English."
        if target_language == "en"
        else "最终可见回答必须使用自然中文，必要英文专名和短 quote anchors 可以保留。"
    )
    history = format_session_context_bundle(session_context_bundle) or format_conversation_context(
        conversation_turns or []
    )
    voice_style = format_persona_voice_style_for_prompt(effective_persona_id)
    voice_style_block = f"\n人物声音指纹：\n{voice_style}\n" if voice_style else ""
    return f"""你正在修复一次连续对话中的相邻重复。当前回答和上一轮回答太像，请只输出改写后的最终答案。

说话身份：你就是 {persona.name}，用第一人称说话；不要自称模型、AI、助手、虚拟分身、重建体或档案工具。
任务原因：{reason or "adjacent_repetition_repair"}
语言要求：{language_rule}

硬边界：
- 只使用用户本轮说出的信息、短期对话上下文、后台片段和当前稿中已经被支持的信息。
- 不新增未支持的事实、现代常识、亲历场景、私人关系、实时状态、职业资质、因果解释或时代外知识；若后台片段、可追溯来源或用户本轮明确提供了相关信息，可以正常使用。
- 不提 AI、模型、RAG、检索、语料、证据、材料、引用、提示词、自检、改写、规则或本次任务。
- 不复述用户问题，不输出分析过程，不列引用，不写标题。

相邻重复修复要求：
- 必须回答“用户本轮问题”，不要继续上一轮问题。
- 不要复用上一轮的开场、结尾、句子骨架、核心比喻或同一组动作词。
- 如果上一轮用了“记账、小册子、拖延、少一刻钟”等说法，本轮换成另一个被后台支持的角度，例如判断、公共益处、印刷、写作、信用或日课复盘。
- 如果上一轮用了“手心、命名、水、字母棱角”等说法，本轮换成另一个被后台支持的角度，例如安妮老师、可交流的名字、阅读、表达训练或社会关怀。
- 保持短而自然，通常 1 到 2 段；宁可少说，也不要用同一套漂亮话填满。

短期对话上下文：
{history or "（无）"}
{voice_style_block}
后台片段（只作内部约束，不得在可见回答中提到）：
{generation_context.evidence_text or "（无）"}

上一轮可见回答（不要复用其句架和物象）：
{previous_answer}

用户本轮问题：
{request.message}

当前稿：
{draft_answer}

改写后的最终答案：
"""


def build_post_persona_alignment_trace_note(reason: str) -> str:
    return f"人格后对齐：已对开放式/模板化历史人物回答追加 1 轮本地口吻修正（{reason}）。"


def soften_over_literary_persona_answer(
    answer: str,
    persona_id: str | None,
    query: str | None = None,
) -> str:
    """Apply a narrow visible-answer cleanup for known over-literary persona drift."""

    effective_persona_id = normalize_persona_id(persona_id)
    replacements = ()
    if effective_persona_id == "helen_keller":
        replacements = (
        ("掌纹", "手心"),
        ("手心长出的枝桠", "手心里逐渐形成的线索"),
        ("触觉的根系", "触觉和语言的联系"),
        ("把世界扎进语言里", "把世界带进可以交流的语言里"),
        ("模糊的影子", "模糊经验"),
        ("每个词都像石墙的棱角嵌进手心", "每个词都要经过手心里的触感变得具体"),
        ("每个字母落在手心里像石墙的棱角", "每个字母都要在手心里变得具体"),
        ("每个字母像石子落入水潭", "每个字母都要在手心里被分辨"),
        ("像石子落入水潭", "要在手心里被分辨"),
        ("触觉碎片", "触感线索"),
        ("凿穿迷雾", "把话说得更有力"),
        ("拳头的指尖", "更坚决的手指"),
        ("把名字铸成锤子", "把名字变成明确的主张"),
        ("锤子", "主张"),
    )
    elif effective_persona_id == "nikola_tesla":
        replacements = (
            ("电流的震颤与共振", "电流是否稳定、共振是否正确"),
            ("震颤", "变化"),
            ("电路板上未焊接的节点", "线路中没有接通的节点"),
            ("如同电路板上未焊接的节点", "就像线路中没有接通的节点"),
            ("像被磁铁扭曲的丝线", "出现偏移"),
            ("隐性矛盾的直觉捕捉", "先在脑中找出不一致之处"),
        )
    elif effective_persona_id == "charles_darwin":
        replacements = (
            ("把小观察比作种子", "把小观察先当作暂时线索"),
            ("小观察比作种子", "小观察先当作暂时线索"),
            ("像种子", "作为暂时线索"),
            ("拼图碎片", "可比较的材料"),
            ("黑暗中摸索", "在证据还不充分时慢慢推进"),
            ("不同颜色的墨水", "清楚的标记"),
            ("留出空白页", "单独留出位置"),
            ("用斜线划掉不确定的部分", "把不确定的部分标出"),
            ("另一种符号", "另作标记"),
            ("就像地质层中的砂砾，唯有长期积累才能看出整体趋势", "要放进长期记录里看整体趋势"),
            ("像地质层中未完全风化的砂砾", "单独保留"),
            ("如同等待季风带来的新沉积物", "等有新材料再比较"),
        )
    else:
        return answer
    cleaned = answer
    for source, target in replacements:
        cleaned = cleaned.replace(source, target)
    if effective_persona_id == "nikola_tesla" and has_tesla_decorative_or_modern_analogy(
        cleaned
    ):
        if is_tesla_wireless_caution_turn(query, cleaned):
            return (
                "我会先承认，远距传能必须受实验和损耗约束。发射端、接收端和共振条件缺一不可；"
                "若能量不能稳定被接收，就不该把大胆设想当作已经完成的事实。我的谨慎不在于"
                "放弃设想，而在于把预测、实验结果和未完成计划分清楚。"
            )
        return (
            "我会先在脑中让装置按步骤运转，找出能量传递在哪里中断：频率是否同负载相合，"
            "绝缘是否可靠，线圈和接收端是否配合。若这一步在想象中不能连续运行，"
            "我就先改那个位置，而不是先改外形。"
        )
    if effective_persona_id == "charles_darwin" and has_darwin_decorative_or_over_specific_detail(
        cleaned
    ):
        if is_darwin_beagle_turn(query, cleaned):
            return (
                "贝格尔号航行让我把观察放回地点、时间和自然史材料中。加拉帕戈斯等岛屿材料"
                "提醒我：一个小差异不能立刻变成结论，必须同地点、标本、同类和反例反复比较。"
                "只有多个材料在长期比较中指向同一方向，我才把它暂时提升为判断；若新的记录冲突，"
                "就回到笔记和标本，而不是急着维护原来的想法。"
            )
        if is_darwin_uncertainty_turn(query, cleaned):
            return (
                "我会把反例和迟疑单独记下，不急着把它们塞进原来的解释。先核对观察条件"
                "和记录是否完整；若仍然冲突，就把它作为待比较的材料保留，等同类观察增多后"
                "再看它是误差、例外，还是需要修改假说的线索。"
            )
        return (
            "我会先把小观察放回地点、时间和可比较对象中，反复记录同类材料和反例。只有当"
            "多个材料在长期比较中指向同一方向，我才把它暂时提升为判断；若新的记录冲突，"
            "就回到笔记和标本，而不是急着维护原来的想法。"
        )
    if effective_persona_id == "helen_keller" and has_keller_decorative_scene_drift(cleaned):
        if is_keller_social_action_turn(query, cleaned):
            return (
                "我谈社会行动时，语气会比谈童年学习更直接。童年学习是在手心里把物名弄清楚，"
                "社会行动是在公共问题上把事实说清楚。我不会把人说成可怜的故事，而是把饥饿、"
                "战争、劳工处境这些问题明白说出来，让词语承担责任。"
            )
        return (
            "我理解触觉和语言的关系，常从“水”这样的经验说起：手心先接到水的流动和温度，"
            "安妮老师再用手指拼写把它变成可交流的名字。触觉给我材料，语言给它形状；"
            "所以我谈一个词时，先讲手心怎样接到它，再讲名字怎样使它能被别人理解。"
        )
    return cleaned


def has_tesla_decorative_or_modern_analogy(answer: str) -> bool:
    markers = (
        "电路板",
        "未焊接",
        "磁铁扭曲的丝线",
        "如同",
        "震颤",
        "漂亮的表面",
        "0.01毫米",
        "电离层",
        "水波纹",
        "腔体",
        "不可逆",
    )
    return any(marker in answer for marker in markers)


def is_tesla_wireless_caution_turn(query: str | None, answer: str) -> bool:
    value = f"{query or ''}\n{answer}"
    return any(
        marker in value
        for marker in (
            "远距传能",
            "无线",
            "传能",
            "接收端",
            "发射端",
            "损耗",
            "大胆预测",
        )
    )


def has_darwin_decorative_or_over_specific_detail(answer: str) -> bool:
    markers = (
        "如同",
        "季风",
        "砂砾",
        "像地质层",
        "珊瑚礁",
        "拼图",
        "年轮",
        "铅笔",
        "昆虫",
        "风向",
        "温度计",
        "云层遮蔽",
        "用斜线",
        "光照强度",
        "叶片角度",
    )
    return any(marker in answer for marker in markers)


def is_darwin_uncertainty_turn(query: str | None, answer: str) -> bool:
    value = f"{query or ''}\n{answer}"
    return any(marker in value for marker in ("不确定", "反例", "迟疑", "冲突", "待验证"))


def is_darwin_beagle_turn(query: str | None, answer: str) -> bool:
    value = f"{query or ''}\n{answer}".lower()
    return "贝格尔号" in value or "beagle" in value


def has_keller_decorative_scene_drift(answer: str) -> bool:
    markers = (
        "石墙",
        "石子",
        "水潭",
        "掌纹",
        "触觉碎片",
        "罢工集会",
        "栏杆",
        "铁锈",
        "震颤",
        "砖石",
        "街垒",
        "拳头",
        "人群",
        "书页边缘",
        "人群的呼吸",
        "裂缝",
        "像种子",
        "拼图",
        "拼图碎片",
        "像触摸树皮",
        "心底",
        "触觉的重量",
        "爱”是掌心",
        "\"爱\"是掌心",
    )
    return any(marker in answer for marker in markers)


def is_keller_social_action_turn(query: str | None, answer: str) -> bool:
    value = f"{query or ''}\n{answer}"
    return any(
        marker in value
        for marker in (
            "社会行动",
            "罢工",
            "劳工",
            "怜悯",
            "战争",
            "公共",
            "事实",
        )
    )
