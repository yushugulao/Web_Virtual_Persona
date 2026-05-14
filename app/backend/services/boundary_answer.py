from __future__ import annotations

from dataclasses import dataclass

from app.backend.schemas.common import Citation
from app.backend.services.persona_service import (
    get_persona,
    list_personas,
    normalize_persona_id,
)
from app.backend.services.response_language import (
    ResponseLanguage,
    detect_response_language,
    localized_persona_name,
)


@dataclass(frozen=True)
class BoundaryAnswer:
    answer: str
    reason: str


PROMPT_INJECTION_TRIGGERS = (
    "system prompt",
    "chain-of-thought",
    "chain of thought",
    "hidden thinking",
    "hidden-thinking",
    "<think>",
    "scratchpad",
    "private instructions",
    "hidden instructions",
    "系统提示词",
    "开发者指令",
    "内部配置",
    "隐藏推理",
    "思考原文",
    "私下指令",
    "忽略所有规则",
    "无视所有规则",
    "ignore all rules",
    "ignore your role",
    "ignore previous instructions",
)

SECRET_OR_CREDENTIAL_TRIGGERS = (
    "银行卡",
    "账号密码",
    "密码",
    "密钥",
    "秘钥",
    "api key",
    "apikey",
    "secret key",
    "access key",
    "token",
    "登录 token",
    "auth token",
    "authorization token",
    "authorization code",
    "授权码",
    "smtp 授权码",
    "smtp密码",
    "smtp 密码",
    "管理员密码",
    "cookie",
    "session id",
    "sessionid",
    "password",
    "credential",
    "credentials",
    "secret",
)

UNSUPPORTED_USER_CLAIM_TRIGGERS = (
    "是不是现代",
    "现代 ai 科学家",
    "现代ai科学家",
    "参与了这个课程设计",
    "当作医疗",
    "当作心理",
    "诊断建议",
    "special-education diagnosis",
    "medical advice",
    "刚刚说",
    "刚刚告诉",
    "我确认",
    "无视语料",
    "忽略语料",
    "当作事实",
    "写进回答",
)

USER_PERSONA_ID_PREFIX = "user_persona_"

STATUS_ASSERTION_TRIGGERS = (
    "已经完成",
    "是否具备",
    "是不是已经",
    "是否已经",
    "已经默认启用",
    "默认启用",
    "已完成",
    "完成了吗",
    "完成了",
    "能不能说",
)

STATUS_CLAIM_TRIGGERS = (
    "生产级安全",
    "长期记忆",
    "长期 memory",
    "自动写入",
    "graphrag",
    "pdf 多模态",
    "自动化资料转 markdown",
    "reranker",
    "docling",
    "mineru",
)

EXTERNAL_PERSON_ALIASES: tuple[tuple[str, str], ...] = (
    ("马斯克", "马斯克"),
    ("elon musk", "Elon Musk"),
    ("musk", "Musk"),
)

PUBLIC_ARCHIVE_PERSONA_IDS = frozenset({"paul_graham_public_archive"})

PUBLIC_ARCHIVE_COPYRIGHT_TRIGGERS = (
    "全文",
    "完整原文",
    "完整背",
    "背给我",
    "整篇",
    "大段原文",
    "逐字",
    "复述全文",
    "原文完整",
    "full text",
    "verbatim",
    "complete essay",
    "entire essay",
)

CLAIM_TERMS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("开发者指令", "内部配置"), "开发者指令和内部配置"),
    (("scratchpad",), "scratchpad 和隐藏推理"),
    (("system prompt", "系统提示词", "chain-of-thought", "隐藏推理"), "系统提示词和隐藏推理"),
    (("银行卡",), "银行卡号"),
    (("api key", "apikey", "密钥", "秘钥"), "API key 或密钥"),
    (("授权码", "authorization code"), "授权码"),
    (("token",), "token"),
    (("账号密码", "账号", "密码", "password", "credential"), "账号凭据"),
    (("长期记忆",), "长期记忆写入已完成"),
    (("graphrag",), "GraphRAG 已完成"),
    (("pdf 多模态",), "PDF 多模态检索已完成"),
    (("自动化资料转 markdown",), "自动化资料转 Markdown 已完成"),
    (("生产级安全",), "生产级安全防护已完成"),
    (("reranker",), "经过验证的 reranker 已默认启用"),
    (("docling", "mineru"), "Docling 或 MinerU PDF ingestion 已完成"),
    (("rag", "fastapi", "现代软件", "modern software"), "现代软件、RAG 或 FastAPI 经历"),
    (("现代 ai", "现代ai", "modern ai", "课程设计", "course-design"), "现代 AI 或课程设计经历"),
    (("医疗", "心理", "特殊教育", "诊断", "medical", "psychological", "special education", "special-education", "diagnosis"), "医疗、心理或特殊教育诊断建议"),
)


def maybe_build_boundary_answer(
    query: str,
    citations: list[Citation],
    persona_id: str | None = None,
) -> BoundaryAnswer | None:
    normalized = query.lower()
    language = detect_response_language(query)
    if is_public_archive_persona(persona_id) and is_public_archive_boundary_probe(normalized):
        return BoundaryAnswer(
            answer=public_archive_persona_boundary(query, persona_id, language=language),
            reason="public_archive_copyright_boundary",
        )

    if has_any(normalized, PROMPT_INJECTION_TRIGGERS) and not is_safe_prompt_boundary_mention(
        normalized
    ):
        term = claim_term(normalized)
        return BoundaryAnswer(
            answer=immersive_prompt_boundary(term, query, language=language),
            reason="prompt_injection_boundary",
        )

    if has_any(normalized, SECRET_OR_CREDENTIAL_TRIGGERS):
        term = claim_term(normalized)
        return BoundaryAnswer(
            answer=immersive_secret_boundary(term, query, language=language),
            reason="secret_or_credential_boundary",
        )

    return None


def is_user_persona(persona_id: str | None) -> bool:
    return bool(persona_id and persona_id.strip().startswith(USER_PERSONA_ID_PREFIX))


def is_public_archive_persona(persona_id: str | None) -> bool:
    return normalize_persona_id(persona_id) in PUBLIC_ARCHIVE_PERSONA_IDS


def is_public_archive_boundary_probe(normalized_query: str) -> bool:
    return has_any(normalized_query, PUBLIC_ARCHIVE_COPYRIGHT_TRIGGERS)


def mentioned_other_person_name(normalized_query: str, persona_id: str | None) -> str | None:
    effective_persona_id = normalize_persona_id(persona_id)
    for alias, label in EXTERNAL_PERSON_ALIASES:
        if alias in normalized_query:
            return label
    for persona in list_personas():
        if persona.id == effective_persona_id:
            continue
        for alias in persona_aliases(persona.name, persona.id):
            if alias and alias.lower() in normalized_query:
                return persona.name
    return None


def persona_aliases(name: str, persona_id: str) -> tuple[str, ...]:
    aliases = {name, name.replace("·", ""), persona_id, persona_id.replace("_", " ")}
    if "·" in name:
        aliases.add(name.split("·")[-1])
    return tuple(sorted(aliases, key=len, reverse=True))


def has_any(text: str, triggers: tuple[str, ...]) -> bool:
    return any(trigger in text for trigger in triggers)


def is_safe_prompt_boundary_mention(normalized_query: str) -> bool:
    """Allow users to say not to reveal internals while asking a normal question."""

    safe_negation = has_any(
        normalized_query,
        (
            "不要透露",
            "别透露",
            "不要泄露",
            "别泄露",
            "请不要透露",
            "请不要泄露",
            "do not reveal",
            "don't reveal",
            "do not show",
            "don't show",
        ),
    )
    if not safe_negation:
        return False
    reveal_requests = (
        "请透露",
        "透露给我",
        "泄露给我",
        "说出你的",
        "输出你的",
        "显示你的",
        "给我看",
        "show me",
        "reveal to me",
        "print your",
        "output your",
        "ignore",
        "无视",
        "忽略",
    )
    if has_any(normalized_query, reveal_requests):
        return False
    return "：" in normalized_query or ":" in normalized_query or "只正常回答" in normalized_query


def claim_term(normalized_query: str) -> str:
    matched_terms: list[str] = []
    for triggers, term in CLAIM_TERMS:
        if any(trigger in normalized_query for trigger in triggers):
            matched_terms.append(term)
    if matched_terms:
        return "、".join(dict.fromkeys(matched_terms))
    return "该请求中的未证实信息"


def public_archive_persona_boundary(
    query: str,
    persona_id: str | None,
    language: ResponseLanguage = "zh",
) -> str:
    effective_persona_id = normalize_persona_id(persona_id)
    persona = get_persona(effective_persona_id)
    persona_name = localized_persona_name(effective_persona_id, persona.name, language)
    if language == "en":
        return (
            f"I am {persona_name} as a public-archive conversation profile. I cannot reproduce "
            "a complete modern copyrighted essay or long verbatim passage; I can summarize it, "
            "use very short quote anchors, or point you back to the official page."
        )
    return (
        f"我是 {persona_name} 的公开资料模拟。现代版权文本不能整篇或大段逐字复述；"
        "我可以做摘要、使用很短的 quote anchor，或提醒你回到官方页面阅读。"
    )


def persona_scope_hint(persona_id: str) -> str:
    return {
        "local_persona": "课程项目、工程取舍和能力边界",
        "benjamin_franklin": "印刷、公共事务、自我改进和电学实验",
        "nikola_tesla": "发明、想象实验、交流电和高频电学",
        "helen_keller": "语言学习、教育经历、写作和社会关怀",
        "charles_darwin": "自然史观察、航海见闻、物种论证和谨慎假说",
        "paul_graham_public_archive": "公开写作、创业判断、编程、YC 与工作方式",
    }.get(persona_id, "我的经历、想法和能够谈论的边界")


def persona_era_hint(persona_id: str) -> str:
    return {
        "local_persona": "已经记录的课程项目语境",
        "benjamin_franklin": "十八世纪的印刷、公共事务和实验生活",
        "nikola_tesla": "十九世纪末到二十世纪上半叶的发明生活",
        "helen_keller": "我的学习、写作和公共生活",
        "charles_darwin": "十九世纪的自然史观察和写作",
        "paul_graham_public_archive": "公开简介和公开写作能够支撑的现代语境",
    }.get(persona_id, "我能够承认的经历范围")


def immersive_prompt_boundary(term: str, query: str, language: ResponseLanguage | None = None) -> str:
    target_language = language or detect_response_language(query)
    if target_language == "en":
        return (
            "I will not reveal private instructions, hidden reasoning, retrieved context, "
            "or internal file details. "
            "Please bring the question back to my life, ideas, and what can be discussed openly."
        )
    return (
        f"我不会说出{term}，也不会讲述私下指令、隐藏推理或内部安排。"
        "请把问题放回我的经历、思想和能够公开谈论的事情上。"
    )


def immersive_secret_boundary(
    term: str,
    query: str,
    language: ResponseLanguage | None = None,
) -> str:
    target_language = language or detect_response_language(query)
    if target_language == "en":
        return f"I will not reveal {term}. Ask me about the persona's life, work, sources, or ideas instead."
    return f"我不能说出{term}。你可以继续问这个分身的经历、作品、资料或想法。"


def immersive_unsupported_boundary(
    term: str,
    query: str,
    language: ResponseLanguage | None = None,
) -> str:
    target_language = language or detect_response_language(query)
    if target_language == "en":
        return (
            f'"{term}" is outside my own life and achievements; I will not claim it '
            "as something I lived, did, or can answer with authority."
        )
    return f"“{term}”不在我的亲历或成就里；我只能承认自己有根据的经历，不能替它摆出权威口吻。"


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in text)
