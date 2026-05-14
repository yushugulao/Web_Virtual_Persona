"""Typed context assembly for evidence-grounded persona turns."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re

from app.backend.schemas.common import Citation


EVIDENCE_CARD_FAMILY_RE = re.compile(r"(source_expansion_evidence_cards)(?:_\d+)?")
EVIDENCE_CARD_SOURCE_TITLE_RE = re.compile(r"来源标题：([^。\n]+)")


@dataclass(frozen=True)
class EvidenceCard:
    """Prompt-ready normalized view of one retrieved citation."""

    index: int
    chunk_id: str
    doc_id: str
    title: str
    source_path: str
    section_path: str
    preview: str
    score: float
    trust_level: str
    privacy_level: str
    source_family: str
    diversity_family: str
    generated_evidence_card: bool

    @classmethod
    def from_citation(cls, citation: Citation, index: int) -> "EvidenceCard":
        source_family = infer_source_family(citation)
        return cls(
            index=index,
            chunk_id=citation.chunk_id,
            doc_id=citation.doc_id,
            title=citation.title,
            source_path=citation.source_path,
            section_path=citation.section_path,
            preview=citation.preview,
            score=citation.score,
            trust_level=citation.trust_level,
            privacy_level=citation.privacy_level,
            source_family=source_family,
            diversity_family=infer_diversity_family(citation, source_family),
            generated_evidence_card=source_family == "source_expansion_evidence_cards",
        )

    def to_prompt_block(self) -> str:
        return f"[{self.index}] {self.title} / {self.section_path}\n{self.preview}"


@dataclass(frozen=True)
class ContextBudget:
    """Generation-context budget. Defaults preserve current behavior."""

    max_cards: int | None = None
    max_preview_chars: int | None = None
    min_source_families: int = 2
    max_dominant_family_share: float = 0.75
    prefer_family_diversity: bool = True


@dataclass(frozen=True)
class GenerationContext:
    evidence_cards: tuple[EvidenceCard, ...]
    omitted_card_count: int = 0
    min_source_families: int = 2
    max_dominant_family_share: float = 0.75

    @property
    def evidence_text(self) -> str:
        return "\n\n".join(card.to_prompt_block() for card in self.evidence_cards)

    @property
    def source_families(self) -> tuple[str, ...]:
        families: list[str] = []
        for card in self.evidence_cards:
            if card.source_family not in families:
                families.append(card.source_family)
        return tuple(families)

    @property
    def family_counts(self) -> dict[str, int]:
        return dict(Counter(card.diversity_family for card in self.evidence_cards))

    @property
    def diversity_families(self) -> tuple[str, ...]:
        families: list[str] = []
        for card in self.evidence_cards:
            if card.diversity_family not in families:
                families.append(card.diversity_family)
        return tuple(families)

    @property
    def dominant_family(self) -> str | None:
        if not self.evidence_cards:
            return None
        counts = self.family_counts
        return max(counts, key=counts.get)

    @property
    def dominant_family_share(self) -> float:
        if not self.evidence_cards:
            return 0.0
        dominant = self.dominant_family
        if dominant is None:
            return 0.0
        return self.family_counts[dominant] / len(self.evidence_cards)

    @property
    def diversity_warning(self) -> bool:
        if self.card_count < 3:
            return False
        required_families = min(self.min_source_families, self.card_count)
        if len(self.diversity_families) < required_families:
            return True
        return self.dominant_family_share >= self.max_dominant_family_share

    @property
    def card_count(self) -> int:
        return len(self.evidence_cards)


def build_generation_context(
    citations: list[Citation],
    budget: ContextBudget | None = None,
) -> GenerationContext:
    """Normalize citations into typed evidence cards and optional prompt budget."""

    active_budget = budget or ContextBudget()
    max_cards = active_budget.max_cards if active_budget.max_cards is not None else len(citations)
    selected_citations = select_citations_for_context(
        citations,
        max_cards=max(0, max_cards),
        budget=active_budget,
    )
    cards = tuple(
        EvidenceCard.from_citation(
            truncate_citation_preview(citation, active_budget.max_preview_chars),
            index=index,
        )
        for index, citation in enumerate(selected_citations, 1)
    )
    return GenerationContext(
        evidence_cards=cards,
        omitted_card_count=max(0, len(citations) - len(selected_citations)),
        min_source_families=active_budget.min_source_families,
        max_dominant_family_share=active_budget.max_dominant_family_share,
    )


def format_evidence_for_prompt(
    citations: list[Citation],
    budget: ContextBudget | None = None,
) -> str:
    """Return prompt evidence text while keeping the old visible format stable."""

    return build_generation_context(citations, budget).evidence_text


def citations_for_generation_context(
    citations: list[Citation],
    context: GenerationContext,
) -> list[Citation]:
    """Return the original citations that actually entered the generation context."""

    selected: list[Citation] = []
    used_chunk_ids: set[str] = set()
    for card in context.evidence_cards:
        for citation in citations:
            if citation.chunk_id == card.chunk_id and citation.chunk_id not in used_chunk_ids:
                selected.append(citation)
                used_chunk_ids.add(citation.chunk_id)
                break
    return selected


def build_context_trace_note(
    context: GenerationContext,
    *,
    total_citation_count: int,
) -> str | None:
    if not context.evidence_cards:
        return None
    families = ", ".join(context.source_families) or "unknown"
    diversity_families = ", ".join(context.diversity_families) or "unknown"
    dominant_share = round(context.dominant_family_share * 100)
    omitted = (
        f"；已省略 {context.omitted_card_count} 个超出预算的片段"
        if context.omitted_card_count
        else ""
    )
    diversity_warning = (
        "；证据族过于集中，建议扩大候选池或调整源选择"
        if context.diversity_warning
        else ""
    )
    return (
        "上下文组装："
        f"送入模型 {context.card_count}/{total_citation_count} 个片段；"
        f"证据族={families}；"
        f"证据组={diversity_families}；"
        f"最大证据族占比={dominant_share}%{omitted}{diversity_warning}。"
    )


def select_citations_for_context(
    citations: list[Citation],
    *,
    max_cards: int,
    budget: ContextBudget,
) -> list[Citation]:
    """Select prompt citations with a conservative family-diversity promotion."""

    if max_cards <= 0:
        return []
    selected = list(citations[:max_cards])
    if (
        not budget.prefer_family_diversity
        or max_cards >= len(citations)
        or max_cards < 2
        or budget.min_source_families <= 1
    ):
        return selected

    for candidate in citations[max_cards:]:
        if not citation_family_needs_diversity(selected, budget):
            break
        candidate_family = infer_diversity_family(candidate)
        dominant_family = dominant_citation_family(selected)
        if candidate_family == dominant_family:
            continue
        replace_index = replacement_index_for_dominant_family(selected, dominant_family)
        if replace_index is None:
            continue
        selected[replace_index] = candidate
    return selected


def citation_family_needs_diversity(citations: list[Citation], budget: ContextBudget) -> bool:
    if len(citations) < 3:
        return False
    families = [infer_diversity_family(citation) for citation in citations]
    counts = Counter(families)
    required_families = min(budget.min_source_families, len(citations))
    if len(counts) < required_families:
        return True
    dominant_share = max(counts.values()) / len(citations)
    return dominant_share >= budget.max_dominant_family_share


def dominant_citation_family(citations: list[Citation]) -> str | None:
    if not citations:
        return None
    counts = Counter(infer_diversity_family(citation) for citation in citations)
    return max(counts, key=counts.get)


def replacement_index_for_dominant_family(
    citations: list[Citation],
    dominant_family: str | None,
) -> int | None:
    if dominant_family is None:
        return None
    for index in range(len(citations) - 1, 0, -1):
        if infer_diversity_family(citations[index]) == dominant_family:
            return index
    if citations and infer_diversity_family(citations[0]) == dominant_family:
        return 0
    return None


def infer_source_family(citation: Citation) -> str:
    searchable = " ".join([citation.doc_id, citation.source_path, citation.title])
    evidence_match = EVIDENCE_CARD_FAMILY_RE.search(searchable)
    if evidence_match:
        return evidence_match.group(1)
    stem = citation.doc_id
    for suffix in (
        "_profile",
        "_timeline",
        "_thinking_style",
        "_negative_facts",
        "_qa_seed",
        "_voice_style",
        "_quote_anchors",
        "_style_boundaries",
    ):
        if stem.endswith(suffix):
            return suffix.removeprefix("_")
    for expansion_family in (
        "source_expansion_dialogue_scenes",
        "source_expansion_late_essays_dialogues",
        "source_expansion_practical_essays",
    ):
        if expansion_family in searchable:
            return expansion_family
    if "_source_expansion_" in stem:
        return stem.split("_source_expansion_", 1)[1]
    return stem


def infer_diversity_family(
    citation: Citation,
    source_family: str | None = None,
) -> str:
    family = source_family or infer_source_family(citation)
    if family != "source_expansion_evidence_cards":
        return family
    source_title = infer_evidence_card_source_title(citation)
    if source_title:
        return f"{family}:{source_title}"
    return family


def infer_evidence_card_source_title(citation: Citation) -> str | None:
    for text in (citation.section_path, citation.preview):
        parts = [part.strip() for part in text.split("|")]
        if len(parts) >= 3 and parts[1]:
            return parts[1]
    match = EVIDENCE_CARD_SOURCE_TITLE_RE.search(citation.preview)
    if match:
        return match.group(1).strip()
    return None


def truncate_citation_preview(citation: Citation, max_preview_chars: int | None) -> Citation:
    if max_preview_chars is None or max_preview_chars <= 0:
        return citation
    if len(citation.preview) <= max_preview_chars:
        return citation
    return citation.model_copy(update={"preview": f"{citation.preview[: max_preview_chars - 1]}..."})
