import time
from pathlib import Path
import re

from app.backend.core.config import get_settings
from app.backend.core.logging import new_request_id
from app.backend.schemas.common import Citation, TimingBreakdown
from app.backend.schemas.retrieval import RetrieveRequest, RetrieveResponse, RetrievalTrace
from app.backend.services.metadata_store import MetadataStore
from app.backend.services.persona_service import (
    DEFAULT_PERSONA_ID,
    is_known_persona_id,
    named_persona_retrieval_prefixes,
    normalize_persona_id,
    persona_retrieval_prefixes,
)
from app.rag.chunking.markdown import Chunk
from app.rag.embeddings.ollama import OllamaEmbeddingClient
from app.rag.indexes.memory_store import load_corpus
from app.rag.indexes.vector_store import (
    DenseVectorIndex,
    chunk_embedding_text,
    corpus_fingerprint,
)
from app.rag.retrieval.fusion import reciprocal_rank_fusion
from app.rag.retrieval.fts import SqliteFtsRetriever
from app.rag.retrieval.lexical import LexicalRetriever
from app.rag.retrieval.local_reranker import LocalIntentReranker
from app.rag.retrieval.query_rewrite import build_query_plan
from app.rag.retrieval.reranker import ConfiguredModelReranker
from app.rag.retrieval.source_prior import apply_source_priors
from app.rag.retrieval.source_selector import select_sources


_DENSE_INDEX_CACHE: dict[tuple[str, str, str], DenseVectorIndex] = {}


def retrieve(request: RetrieveRequest) -> RetrieveResponse:
    retrieval_id = new_request_id()
    start = time.perf_counter()
    settings = get_settings()
    store = MetadataStore(settings.sqlite_path)
    _, chunks = load_corpus(str(settings.corpus_dir))
    persona_id = normalize_persona_id(request.persona_id)
    chunks = filter_chunks_for_persona(chunks, persona_id)
    effective_include_private = request.include_private or can_read_private_persona_corpus(
        persona_id=persona_id,
        user_id=request.user_id,
        store=store,
    )
    first_stage_top_k = max(request.top_k, settings.retrieval_first_stage_top_k)
    query_plan = build_active_query_plan(settings, request.query)
    sparse_result_lists = [
        sparse_search(
            settings,
            chunks,
            query,
            top_k=first_stage_top_k,
            include_private=effective_include_private,
        )
        for query in query_plan.queries
    ]
    sparse_results = fuse_query_results(sparse_result_lists, settings.retrieval_rrf_k)

    notes = [
        f"检索模式：{settings.retrieval_mode}。",
        f"关键词检索：{settings.sparse_retriever}。",
        f"对象过滤：{persona_id}；可用片段={len(chunks)}。",
    ]
    if not is_known_persona_id(request.persona_id):
        notes.append(
            f"未知 persona_id '{request.persona_id}'，已回退到 {DEFAULT_PERSONA_ID}。"
        )
    if effective_include_private and not request.include_private:
        notes.append("用户分身私有资料：当前用户可访问，已纳入检索。")
    if query_plan.rewritten_queries:
        notes.append(f"问题改写已启用：{len(query_plan.rewritten_queries)} 个扩展查询。")
    results = sparse_results
    dense_results: list[tuple[object, float]] = []
    if settings.retrieval_mode in {"hybrid", "dense"}:
        try:
            dense_index = get_or_build_dense_index(settings, chunks, persona_id=persona_id)
            embedding_client = OllamaEmbeddingClient(settings)
            dense_queries = (
                query_plan.queries
                if settings.query_rewrite_dense
                else [query_plan.original_query]
            )
            dense_result_lists = [
                dense_index.search(
                    query_vector=embedding_client.embed_query(query),
                    chunks=chunks,
                    top_k=first_stage_top_k,
                    include_private=effective_include_private,
                )
                for query in dense_queries
            ]
            dense_results = fuse_query_results(dense_result_lists, settings.retrieval_rrf_k)
            notes.append(
                f"语义检索已启用：{settings.embedding_model}；"
                f"索引条目={len(dense_index.entries)}，维度={dense_index.dimension}。"
            )
        except Exception as exc:
            dense_results = []
            notes.append(f"语义检索不可用，已使用关键词回退。原因：{exc}")

    if settings.retrieval_mode == "dense" and dense_results:
        results = dense_results
    elif settings.retrieval_mode == "hybrid" and dense_results:
        results = reciprocal_rank_fusion(
            [sparse_results, dense_results],
            rrf_k=settings.retrieval_rrf_k,
            weights=[1.0, 1.2],
        )
        notes.append("关键词候选与语义候选已用 RRF 倒数排名融合。")

    rerank_start = time.perf_counter()
    rerank_ms = 0.0
    if results:
        outcome = ConfiguredModelReranker(settings).rerank(
            request.query,
            results,
            top_k=request.top_k,
        )
        results = outcome.results
        notes.append(outcome.note)
        if settings.reranker_enabled:
            rerank_ms = (time.perf_counter() - rerank_start) * 1000
    else:
        results = results[: request.top_k]

    results, prior_note = apply_source_priors(request.query, results)
    if prior_note:
        notes.append(prior_note)

    local_outcome = LocalIntentReranker(settings).rerank(request.query, results)
    results = local_outcome.results
    notes.append(local_outcome.note)

    if settings.source_selector_enabled and results:
        selected_top_k = min(request.top_k, settings.source_selector_top_k)
        results, source_note = select_sources(
            results,
            max_results=selected_top_k,
            min_results=min(1, request.top_k),
            query=request.query,
            intent_filter_enabled=settings.source_selector_intent_filter_enabled,
        )
        notes.append(source_note)
    else:
        results = results[: request.top_k]
    retrieval_ms = (time.perf_counter() - start) * 1000

    citations = [
        Citation(
            chunk_id=chunk.chunk_id,
            doc_id=chunk.doc_id,
            title=chunk.title,
            source_path=chunk.source_path,
            section_path=chunk.section_path,
            preview=preview(chunk.text),
            score=round(score, 4),
            trust_level=chunk.trust_level,
            privacy_level=chunk.privacy_level,
        )
        for chunk, score in results
    ]
    trace = RetrievalTrace(
        original_query=request.query,
        persona_id=persona_id,
        requested_persona_id=request.persona_id,
        rewritten_queries=query_plan.rewritten_queries,
        candidates=citations,
        selected_chunk_ids=[citation.chunk_id for citation in citations],
        notes=notes,
    )
    timings = TimingBreakdown(
        retrieval_ms=round(retrieval_ms, 2),
        rerank_ms=round(rerank_ms, 2),
        total_ms=round(retrieval_ms, 2),
    )
    response = RetrieveResponse(
        retrieval_id=retrieval_id,
        query=request.query,
        citations=citations,
        trace=trace,
        timings=timings,
    )
    store.record_retrieval(
        retrieval_id=retrieval_id,
        request=request,
        response=response,
        session_id=request.session_id,
    )
    return response


def build_active_query_plan(settings, query: str):
    if not settings.query_rewrite_enabled:
        return build_query_plan(query, max_rewrites=0)
    return build_query_plan(
        query,
        max_rewrites=max(0, settings.query_rewrite_max_queries - 1),
    )


def fuse_query_results(result_lists, rrf_k: int):
    active_lists = [results for results in result_lists if results]
    if not active_lists:
        return []
    if len(active_lists) == 1:
        return active_lists[0]
    weights = [1.0] + [0.85 for _ in active_lists[1:]]
    return reciprocal_rank_fusion(active_lists, rrf_k=rrf_k, weights=weights)


def sparse_search(settings, chunks, query: str, top_k: int, include_private: bool):
    if settings.sparse_retriever == "sqlite_fts5":
        try:
            return SqliteFtsRetriever(chunks).search(
                query,
                top_k=top_k,
                include_private=include_private,
            )
        except Exception:
            pass
    return LexicalRetriever(chunks).search(
        query,
        top_k=top_k,
        include_private=include_private,
    )


def can_read_private_persona_corpus(
    *,
    persona_id: str,
    user_id: str | None,
    store: MetadataStore,
) -> bool:
    row = store.get_user_persona(persona_id)
    if row is None or row.get("runtime_status") != "ready":
        return False
    return bool(row.get("is_public")) or (bool(user_id) and row.get("owner_user_id") == user_id)


def filter_chunks_for_persona(chunks: list[Chunk], persona_id: str) -> list[Chunk]:
    normalized = normalize_persona_id(persona_id)
    if normalized == DEFAULT_PERSONA_ID:
        named_prefixes = named_persona_retrieval_prefixes()
        return [
            chunk
            for chunk in chunks
            if not source_path_matches_any_prefix(chunk.source_path, named_prefixes)
        ]

    prefixes = persona_retrieval_prefixes(normalized)
    return [
        chunk
        for chunk in chunks
        if source_path_matches_any_prefix(chunk.source_path, prefixes)
        or chunk.doc_id == "safety_policy_main"
    ]


def source_path_matches_any_prefix(source_path: str, prefixes: list[str]) -> bool:
    normalized = normalized_source_path(source_path)
    return any(normalized.startswith(prefix) for prefix in prefixes)


def normalized_source_path(source_path: str) -> str:
    return source_path.replace("\\", "/")


def vector_index_path_for_persona(base_path: Path, persona_id: str) -> Path:
    normalized = normalize_persona_id(persona_id)
    if normalized == DEFAULT_PERSONA_ID:
        return base_path
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", normalized)
    return base_path.with_name(f"{base_path.stem}_{safe_id}{base_path.suffix}")


def get_or_build_dense_index(settings, chunks, persona_id: str = DEFAULT_PERSONA_ID) -> DenseVectorIndex:
    fingerprint = corpus_fingerprint(chunks)
    index_path = vector_index_path_for_persona(settings.vector_index_path, persona_id)
    cache_key = (str(index_path), settings.embedding_model, fingerprint)
    cached = _DENSE_INDEX_CACHE.get(cache_key)
    if cached:
        return cached

    if index_path.exists():
        loaded = DenseVectorIndex.load(index_path)
        if loaded.is_current(model=settings.embedding_model, chunks=chunks):
            _DENSE_INDEX_CACHE[cache_key] = loaded
            return loaded

    embedding_client = OllamaEmbeddingClient(settings)
    embeddings = embedding_client.embed_documents([chunk_embedding_text(chunk) for chunk in chunks])
    index = DenseVectorIndex.build(
        model=settings.embedding_model,
        chunks=chunks,
        embeddings=embeddings,
    )
    index.save(index_path)
    _DENSE_INDEX_CACHE.clear()
    _DENSE_INDEX_CACHE[cache_key] = index
    return index


def preview(text: str, limit: int = 240) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else f"{clean[: limit - 1]}..."
