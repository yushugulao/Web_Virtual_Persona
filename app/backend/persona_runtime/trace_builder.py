from __future__ import annotations

from app.backend.core.config import get_settings
from app.backend.persona_runtime.context_builder import (
    GenerationContext,
    build_context_trace_note,
    citations_for_generation_context,
)
from app.backend.schemas.retrieval import RetrieveResponse
from app.backend.services.metadata_store import MetadataStore


def add_thinking_effort_trace_note(
    retrieval_response: RetrieveResponse,
    thinking_effort: str,
    timeout_seconds: float,
    num_predict: int,
    refinement_passes: int,
    generation_model: str,
    generation_think: bool,
    thinking_budget: int | None = None,
) -> None:
    effort_labels = {
        "low": "低",
        "medium": "中",
        "high": "高",
    }
    label = effort_labels.get(thinking_effort, "低")
    refine_text = "不追加自检改写" if refinement_passes <= 0 else f"追加 {refinement_passes} 轮本地自检改写"
    think_text = "开启模型 thinking" if generation_think else "关闭模型 thinking"
    thinking_budget_text = (
        f"，thinking 预算 {thinking_budget} token" if generation_think and thinking_budget else ""
    )
    retrieval_response.trace.notes.insert(
        0,
        (
            f"思考努力：{label}；模型 {generation_model}；{think_text}；"
            f"最长等待 {timeout_seconds:g} 秒，生成预算 {num_predict} token{thinking_budget_text}，{refine_text}。"
        ),
    )

def add_context_trace_note(
    retrieval_response: RetrieveResponse,
    generation_context: GenerationContext,
) -> None:
    note = build_context_trace_note(
        generation_context,
        total_citation_count=len(retrieval_response.citations),
    )
    if note:
        retrieval_response.trace.notes.append(note)
    typed_cards = typed_evidence_metadata_for_context(generation_context)
    if typed_cards:
        source_titles = sorted({card["source_title"] for card in typed_cards if card.get("source_title")})
        tags = sorted(
            {
                tag
                for card in typed_cards
                for tag in card.get("tags", [])[:3]
                if isinstance(tag, str) and tag
            }
        )
        retrieval_response.trace.notes.append(
            "Typed evidence cards: "
            f"{len(typed_cards)} matched; sources={', '.join(source_titles[:4]) or 'unknown'}; "
            f"tags={', '.join(tags[:8]) or 'unknown'}."
        )

def typed_evidence_metadata_for_context(generation_context: GenerationContext) -> list[dict]:
    chunk_ids = [card.chunk_id for card in generation_context.evidence_cards]
    if not chunk_ids:
        return []
    try:
        return MetadataStore(get_settings().sqlite_path).evidence_cards_for_chunk_ids(chunk_ids)
    except Exception:
        return []

def apply_generation_context_selection(
    retrieval_response: RetrieveResponse,
    generation_context: GenerationContext,
) -> None:
    selected_citations = citations_for_generation_context(
        retrieval_response.citations,
        generation_context,
    )
    if not selected_citations:
        return
    retrieval_response.citations = selected_citations
    retrieval_response.trace.selected_chunk_ids = [
        citation.chunk_id for citation in selected_citations
    ]

def apply_citation_budget(
    retrieval_response: RetrieveResponse,
    max_citations: int,
) -> None:
    if max_citations <= 0 or len(retrieval_response.citations) <= max_citations:
        return
    original_count = len(retrieval_response.citations)
    retrieval_response.citations = retrieval_response.citations[:max_citations]
    retrieval_response.trace.selected_chunk_ids = [
        citation.chunk_id for citation in retrieval_response.citations
    ]
    retrieval_response.trace.notes.append(
        f"证据预算：非生成路径返回 {max_citations}/{original_count} 个片段。"
    )
