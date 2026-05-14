import socket
from urllib.parse import urlparse

import httpx

from app.backend.core.config import Settings
from app.backend.memory.memory_store import MemoryStore
from app.backend.schemas.status import StatusResponse
from app.backend.services.metadata_store import MetadataStore
from app.backend.services.model_service import (
    THINKING_EFFORTS,
    display_thinking_budget_for_effort,
    list_loaded_ollama_models_snapshot,
    model_for_effort,
    num_predict_for_effort,
    refinement_passes_for_request,
    think_for_effort,
    thinking_budget_for_effort,
    timeout_seconds_for_effort,
)
from app.backend.services.model_diagnostics import active_generation_snapshot
from app.backend.services.resource_monitor import build_resource_usage
from app.rag.indexes.memory_store import load_corpus


def build_status(settings: Settings) -> StatusResponse:
    documents, chunks = load_corpus(str(settings.corpus_dir))
    store = MetadataStore(settings.sqlite_path)
    counts = store.counts()
    memory_counts = MemoryStore(settings.sqlite_path).counts()
    post_persona_alignment_stats = store.post_persona_alignment_stats()
    persona_first_stats = store.persona_first_stats()
    return StatusResponse(
        env=settings.env,
        model_provider=settings.model_provider,
        generation_model=settings.generation_model,
        quality_generation_model=settings.quality_generation_model or None,
        quality_generation_min_effort=settings.quality_generation_min_effort,
        quality_generation_think=settings.quality_generation_think,
        quality_generation_refinement_passes=settings.quality_generation_refinement_passes,
        model_timeout_seconds=settings.model_timeout_seconds,
        model_keep_alive=settings.model_keep_alive,
        model_think=settings.model_think,
        model_num_predict=settings.model_num_predict,
        model_temperature=settings.model_temperature,
        model_top_p=settings.model_top_p,
        effort_runtime_plans=build_effort_runtime_plans(settings),
        active_generation=active_generation_snapshot(),
        loaded_ollama_models=list_loaded_ollama_models_snapshot(settings),
        post_persona_alignment_enabled=settings.post_persona_alignment_enabled,
        post_persona_alignment_event_rows=post_persona_alignment_stats["event_rows"],
        post_persona_alignment_reason_counts=post_persona_alignment_stats["reason_counts"],
        persona_first_enabled=settings.persona_first_enabled,
        persona_first_event_rows=persona_first_stats["event_rows"],
        persona_first_mode_counts=persona_first_stats["mode_counts"],
        embedding_model=settings.embedding_model,
        retrieval_mode=settings.retrieval_mode,
        query_rewrite_enabled=settings.query_rewrite_enabled,
        local_reranker_enabled=settings.local_reranker_enabled,
        source_selector_enabled=settings.source_selector_enabled,
        source_selector_intent_filter_enabled=settings.source_selector_intent_filter_enabled,
        source_selector_top_k=settings.source_selector_top_k,
        reranker_backend=settings.reranker_backend,
        reranker_model=settings.reranker_model,
        reranker_hf_model=settings.reranker_hf_model,
        reranker_enabled=settings.reranker_enabled,
        judge_model=settings.judge_model,
        judge_threshold=settings.judge_threshold,
        deepseek_api_key_configured=bool(settings.deepseek_api_key),
        ollama_base_url=settings.ollama_base_url,
        ollama_models_dir=str(settings.ollama_models_dir),
        llama_cpp_base_url=settings.llama_cpp_base_url,
        llama_cpp_model=settings.llama_cpp_model,
        llama_cpp_server_ready=is_llama_cpp_ready(settings.llama_cpp_base_url),
        model_server_ready=is_model_server_ready(settings),
        generation_model_ready=is_generation_model_available(settings, settings.generation_model),
        quality_generation_model_ready=(
            is_generation_model_available(settings, settings.quality_generation_model)
            if settings.quality_generation_model
            else False
        ),
        embedding_model_ready=is_ollama_model_available(settings, settings.embedding_model),
        reranker_model_ready=is_ollama_model_available(settings, settings.reranker_model),
        corpus_dir=str(settings.corpus_dir),
        data_dir=str(settings.data_dir),
        sqlite_path=str(settings.sqlite_path),
        corpus_ready=bool(documents),
        index_ready=bool(chunks),
        dense_index_ready=settings.vector_index_path.exists(),
        metadata_store_ready=settings.sqlite_path.exists(),
        document_rows=counts["documents"],
        chunk_rows=counts["chunks"],
        session_rows=counts["sessions"],
        retrieval_event_rows=counts["retrieval_events"],
        chat_event_rows=counts["chat_events"],
        eval_run_rows=counts["eval_runs"],
        eval_case_result_rows=counts["eval_case_results"],
        evidence_card_rows=counts["evidence_cards"],
        evidence_card_audit_rows=counts["evidence_card_audit"],
        memory_item_rows=memory_counts["memory_items"],
        memory_audit_event_rows=memory_counts["memory_audit_events"],
        resource_usage=build_resource_usage(
            data_dir=settings.data_dir,
            model_dir=settings.ollama_models_dir,
        ),
)


def build_effort_runtime_plans(settings: Settings) -> dict[str, dict[str, object]]:
    plans: dict[str, dict[str, object]] = {}
    for effort in THINKING_EFFORTS:
        model = model_for_effort(settings, effort)
        plans[effort] = {
            "model": model,
            "model_ready": is_generation_model_available(settings, model),
            "timeout_seconds": timeout_seconds_for_effort(settings.model_timeout_seconds, effort),
            "num_predict": num_predict_for_effort(settings.model_num_predict, effort),
            "think": think_for_effort(settings, effort),
            "thinking_budget": thinking_budget_for_effort(settings, effort),
            "display_thinking_budget": display_thinking_budget_for_effort(settings, effort),
            "refinement_passes": refinement_passes_for_request(settings, effort),
        }
    return plans


def is_model_server_ready(settings: Settings) -> bool:
    if settings.model_provider == "llama_cpp":
        return is_llama_cpp_ready(settings.llama_cpp_base_url)
    return is_ollama_ready(settings.ollama_base_url)


def is_generation_model_available(settings: Settings, model_name: str) -> bool:
    if settings.model_provider == "llama_cpp":
        server_models = {settings.llama_cpp_model, settings.generation_model}
        return bool(model_name) and model_name in server_models and is_llama_cpp_ready(
            settings.llama_cpp_base_url
        )
    return is_ollama_model_available(settings, model_name)


def is_ollama_ready(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 11434
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def is_llama_cpp_ready(base_url: str) -> bool:
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/health", timeout=2.0)
        if response.status_code == 200:
            data = response.json()
            return data.get("status") == "ok"
        return False
    except Exception:
        return False


def is_ollama_model_available(settings: Settings, model_name: str) -> bool:
    if not is_ollama_ready(settings.ollama_base_url):
        return False
    try:
        response = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=2.0)
        response.raise_for_status()
    except Exception:
        return False
    models = response.json().get("models", [])
    available_names = {item.get("name") for item in models if isinstance(item, dict)}
    if model_name in available_names:
        return True
    if ":" not in model_name:
        return f"{model_name}:latest" in available_names
    return False
