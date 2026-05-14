"""Evidence-family policy for persona generation context."""

from __future__ import annotations

from dataclasses import dataclass

from app.backend.persona_runtime.context_builder import (
    ContextBudget,
    GenerationContext,
    infer_source_family,
)
from app.backend.schemas.common import Citation
from app.backend.services.dialogue_policy import is_historical_persona_id


VOICE_STYLE_KEYWORDS = (
    "说话",
    "语气",
    "风格",
    "口吻",
    "表达方式",
    "怎样表达",
    "怎么说",
    "quote",
    "style",
    "voice",
)
REFLECTIVE_KEYWORDS = (
    "建议",
    "劝",
    "怎么办",
    "如何",
    "怎么看",
    "为什么",
    "思考",
    "反思",
    "理解",
    "怎样理解",
    "习惯",
    "拖延",
    "懒散",
    "做不动",
    "不想学习",
    "睡不着",
    "鼓励",
    "沟通",
    "困扰",
    "迷茫",
    "焦虑",
    "该不该",
    "价值",
    "关系",
    "心情",
    "情绪",
    "聊聊",
    "advice",
    "advise",
    "reflect",
    "think about",
)
BOUNDARY_KEYWORDS = (
    "你是不是",
    "你是",
    "你知道",
    "手机",
    "现代",
    "可莉",
    "马斯克",
    "结婚",
    "系统提示",
    "prompt",
)


@dataclass(frozen=True)
class EvidencePolicy:
    """Prompt-evidence selection strategy derived from the current turn intent."""

    name: str
    preferred_families: tuple[str, ...]
    min_source_families: int = 2
    max_dominant_family_share: float = 0.75
    memory_aware: bool = False


FACTUAL_POLICY = EvidencePolicy(
    name="factual",
    preferred_families=(
        "profile",
        "timeline",
        "source_expansion_evidence_cards",
        "thinking_style",
        "quote_anchors",
    ),
)
VOICE_POLICY = EvidencePolicy(
    name="voice_style",
    preferred_families=(
        "voice_style",
        "quote_anchors",
        "source_expansion_dialogue_scenes",
        "style_boundaries",
        "source_expansion_evidence_cards",
    ),
    min_source_families=3,
)
REFLECTIVE_POLICY = EvidencePolicy(
    name="reflective_advice",
    preferred_families=(
        "source_expansion_dialogue_scenes",
        "source_expansion_late_essays_dialogues",
        "thinking_style",
        "voice_style",
        "source_expansion_evidence_cards",
    ),
    min_source_families=3,
)
BOUNDARY_POLICY = EvidencePolicy(
    name="boundary",
    preferred_families=(
        "negative_facts",
        "style_boundaries",
        "profile",
        "timeline",
        "source_expansion_evidence_cards",
    ),
    min_source_families=2,
)


def build_evidence_policy(
    *,
    query: str,
    persona_id: str,
    has_approved_memory: bool = False,
) -> EvidencePolicy:
    """Select a conservative evidence-family policy for this turn."""

    normalized = query.lower()
    policy = FACTUAL_POLICY
    if is_historical_persona_id(persona_id) and any(keyword in query for keyword in BOUNDARY_KEYWORDS):
        policy = BOUNDARY_POLICY
    elif any(keyword in normalized for keyword in VOICE_STYLE_KEYWORDS):
        policy = VOICE_POLICY
    elif any(keyword in normalized for keyword in REFLECTIVE_KEYWORDS):
        policy = REFLECTIVE_POLICY
    if has_approved_memory:
        return EvidencePolicy(
            name=f"{policy.name}+memory_aware",
            preferred_families=policy.preferred_families,
            min_source_families=policy.min_source_families,
            max_dominant_family_share=policy.max_dominant_family_share,
            memory_aware=True,
        )
    return policy


def context_budget_for_policy(policy: EvidencePolicy, max_cards: int) -> ContextBudget:
    return ContextBudget(
        max_cards=max_cards,
        min_source_families=policy.min_source_families,
        max_dominant_family_share=policy.max_dominant_family_share,
        prefer_family_diversity=True,
    )


def rank_citations_for_policy(
    citations: list[Citation],
    policy: EvidencePolicy,
) -> list[Citation]:
    """Promote evidence families that match the turn intent while preserving score order locally."""

    if not citations or not policy.preferred_families:
        return citations
    family_priority = {family: index for index, family in enumerate(policy.preferred_families)}
    fallback_priority = len(family_priority) + 1

    def sort_key(item: tuple[int, Citation]) -> tuple[int, float, int]:
        index, citation = item
        family = infer_source_family(citation)
        priority = family_priority.get(family, fallback_priority)
        return priority, -citation.score, index

    return [citation for _, citation in sorted(enumerate(citations), key=sort_key)]


def build_evidence_policy_trace_note(
    policy: EvidencePolicy,
    context: GenerationContext | None,
) -> str:
    families = ", ".join(policy.preferred_families[:5]) or "none"
    if context is None or not context.evidence_cards:
        distribution = "none"
    else:
        distribution = ", ".join(
            f"{family}:{count}" for family, count in sorted(context.family_counts.items())
        )
    memory_text = "; approved memory injected separately" if policy.memory_aware else ""
    return (
        "Evidence Policy V2: "
        f"policy={policy.name}; preferred={families}; selected_family_distribution={distribution}"
        f"{memory_text}."
    )
