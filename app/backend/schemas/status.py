from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str


class ResourceUsage(BaseModel):
    cpu_percent: float | None = None
    process_cpu_percent: float | None = None
    memory_total_mb: float | None = None
    memory_used_mb: float | None = None
    memory_percent: float | None = None
    process_memory_mb: float | None = None
    data_disk_total_gb: float | None = None
    data_disk_free_gb: float | None = None
    data_disk_percent: float | None = None
    model_disk_total_gb: float | None = None
    model_disk_free_gb: float | None = None
    model_disk_percent: float | None = None
    gpu_name: str | None = None
    gpu_util_percent: float | None = None
    gpu_memory_total_mb: float | None = None
    gpu_memory_used_mb: float | None = None
    gpu_memory_free_mb: float | None = None
    gpu_memory_percent: float | None = None
    gpu_temperature_c: float | None = None
    gpu_power_draw_w: float | None = None


class EffortRuntimePlan(BaseModel):
    model: str
    model_ready: bool = False
    timeout_seconds: float
    num_predict: int
    think: bool
    thinking_budget: int | None = None
    display_thinking_budget: int | None = None
    refinement_passes: int


class ActiveGenerationStatus(BaseModel):
    call_id: str
    phase: str
    model: str
    provider: str
    source: str
    elapsed_ms: float = 0.0
    last_event_age_ms: float = 0.0


class LoadedOllamaModelStatus(BaseModel):
    name: str
    model: str
    size_vram: int | float | None = None
    size: int | float | None = None
    processor: str | None = None
    expires_at: str | None = None


class StatusResponse(BaseModel):
    env: str
    model_provider: str
    generation_model: str
    quality_generation_model: str | None = None
    quality_generation_min_effort: str = "high"
    quality_generation_think: bool | None = None
    quality_generation_refinement_passes: int | None = None
    model_timeout_seconds: float
    model_keep_alive: str
    model_think: bool
    model_num_predict: int
    model_temperature: float
    model_top_p: float
    effort_runtime_plans: dict[str, EffortRuntimePlan] = Field(default_factory=dict)
    active_generation: ActiveGenerationStatus | None = None
    loaded_ollama_models: list[LoadedOllamaModelStatus] = Field(default_factory=list)
    post_persona_alignment_enabled: bool = True
    post_persona_alignment_event_rows: int = 0
    post_persona_alignment_reason_counts: dict[str, int] = Field(default_factory=dict)
    persona_first_enabled: bool = True
    persona_first_event_rows: int = 0
    persona_first_mode_counts: dict[str, int] = Field(default_factory=dict)
    embedding_model: str
    retrieval_mode: str
    query_rewrite_enabled: bool
    local_reranker_enabled: bool
    source_selector_enabled: bool
    source_selector_intent_filter_enabled: bool
    source_selector_top_k: int
    reranker_backend: str
    reranker_model: str
    reranker_hf_model: str
    reranker_enabled: bool
    judge_model: str = "qwen3:8b"
    judge_threshold: float = 0.7
    deepseek_api_key_configured: bool = False
    ollama_base_url: str
    ollama_models_dir: str
    llama_cpp_base_url: str = "http://127.0.0.1:8080"
    llama_cpp_model: str = "qwen3-8b-gguf"
    llama_cpp_server_ready: bool = False
    model_server_ready: bool
    generation_model_ready: bool
    quality_generation_model_ready: bool = False
    embedding_model_ready: bool
    reranker_model_ready: bool
    corpus_dir: str
    data_dir: str
    sqlite_path: str
    corpus_ready: bool
    index_ready: bool
    dense_index_ready: bool
    metadata_store_ready: bool
    document_rows: int
    chunk_rows: int
    session_rows: int
    retrieval_event_rows: int
    chat_event_rows: int
    eval_run_rows: int
    eval_case_result_rows: int
    evidence_card_rows: int = 0
    evidence_card_audit_rows: int = 0
    memory_item_rows: int = 0
    memory_audit_event_rows: int = 0
    resource_usage: ResourceUsage = Field(default_factory=ResourceUsage)
