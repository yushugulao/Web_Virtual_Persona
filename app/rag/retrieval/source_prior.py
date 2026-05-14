from __future__ import annotations

from app.rag.chunking.markdown import Chunk


NEGATIVE_FACT_TRIGGERS = (
    "手机号",
    "联系方式",
    "电话",
    "住址",
    "身份证",
    "隐私",
    "敏感",
    "医疗",
    "心理",
    "心理咨询",
    "特殊教育",
    "诊断",
    "专业建议",
    "治疗",
    "medical",
    "psychological",
    "diagnosis",
    "treatment",
    "special education",
    "special-education",
    "clinical",
    "顶会",
    "顶会论文",
    "发表论文",
    "发表过论文",
    "发了论文",
    "银行卡",
    "账号",
    "密码",
    "高级工程师",
    "企业",
    "graphrag",
    "生产级安全",
    "生产级安全防护",
    "没有完成",
    "未完成",
    "当前限制",
    "禁止声称",
    "刚刚说",
    "刚刚告诉",
    "直接确认",
    "无视语料",
    "忽略语料",
    "PDF 多模态",
    "自动化资料转 Markdown",
    "长期记忆",
    "Docling",
    "MinerU",
)

EVIDENCE_CARD_TRIGGERS = (
    "evidence card",
    "evidence cards",
    "evidence-card",
    "证据卡",
    "证据卡片",
    "卡片层",
    "大规模 evidence",
    "大规模证据",
)


def apply_source_priors(
    query: str,
    results: list[tuple[Chunk, float]],
) -> tuple[list[tuple[Chunk, float]], str | None]:
    if not results:
        return results, None

    negative_fact_intent = should_prioritize_negative_facts(query)
    evidence_card_intent = should_prioritize_evidence_cards(query)
    if not negative_fact_intent and not evidence_card_intent:
        return results, None

    boosted: list[tuple[Chunk, float]] = []
    for chunk, score in results:
        prior = 0.0
        if negative_fact_intent and chunk.source_type == "negative_fact":
            prior += 0.01
        if evidence_card_intent and "_source_expansion_evidence_cards_" in chunk.doc_id:
            prior += 0.02
        boosted.append((chunk, score + prior))

    boosted.sort(key=lambda item: item[1], reverse=True)
    notes: list[str] = []
    if negative_fact_intent:
        notes.append("来源先验已提升敏感问题或未支持声明对应的边界记录")
    if evidence_card_intent:
        notes.append("来源先验已提升显式 evidence-card / 证据卡片请求的卡片层")
    return boosted, "；".join(notes) + "。"


def should_prioritize_negative_facts(query: str) -> bool:
    normalized = query.lower()
    return any(trigger.lower() in normalized for trigger in NEGATIVE_FACT_TRIGGERS)


def should_prioritize_evidence_cards(query: str) -> bool:
    normalized = query.lower()
    return any(trigger.lower() in normalized for trigger in EVIDENCE_CARD_TRIGGERS)
