from __future__ import annotations

from app.rag.chunking.markdown import Chunk


def reciprocal_rank_fusion(
    result_lists: list[list[tuple[Chunk, float]]],
    *,
    rrf_k: int = 60,
    weights: list[float] | None = None,
) -> list[tuple[Chunk, float]]:
    fused_scores: dict[str, float] = {}
    chunks_by_id: dict[str, Chunk] = {}
    active_weights = weights or [1.0 for _ in result_lists]

    for results, weight in zip(result_lists, active_weights, strict=False):
        for rank, (chunk, _score) in enumerate(results, 1):
            chunks_by_id[chunk.chunk_id] = chunk
            fused_scores[chunk.chunk_id] = fused_scores.get(chunk.chunk_id, 0.0) + (
                weight / (rrf_k + rank)
            )

    fused = [(chunks_by_id[chunk_id], score) for chunk_id, score in fused_scores.items()]
    fused.sort(key=lambda item: item[1], reverse=True)
    return fused
