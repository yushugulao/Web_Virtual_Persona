from dataclasses import dataclass
import os
from pathlib import Path
from functools import lru_cache


def _load_project_dotenv() -> None:
    project_root = Path(__file__).resolve().parents[3]
    env_path = Path(".env")
    if not env_path.exists():
        env_path = project_root / ".env"
    if not env_path.exists():
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


def _csv_env(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _optional_bool_env(name: str, default: bool | None = None) -> bool | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _optional_int_env(name: str, default: int | None = None) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _string_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    env: str
    host: str
    port: int
    corpus_dir: Path
    data_dir: Path
    sqlite_path: Path
    model_provider: str
    ollama_base_url: str
    ollama_models_dir: Path
    generation_model: str
    quality_generation_model: str
    quality_generation_min_effort: str
    quality_generation_think: bool | None
    quality_generation_refinement_passes: int | None
    model_timeout_seconds: float
    model_keep_alive: str
    model_think: bool
    model_num_predict: int
    model_temperature: float
    model_top_p: float
    boundary_fast_path_enabled: bool
    embedding_model: str
    embedding_timeout_seconds: float
    sparse_retriever: str
    retrieval_mode: str
    retrieval_first_stage_top_k: int
    retrieval_rrf_k: int
    query_rewrite_enabled: bool
    query_rewrite_max_queries: int
    query_rewrite_dense: bool
    local_reranker_enabled: bool
    source_selector_enabled: bool
    source_selector_intent_filter_enabled: bool
    source_selector_top_k: int
    vector_index_path: Path
    reranker_backend: str
    reranker_model: str
    reranker_hf_model: str
    reranker_hf_cache_dir: Path
    reranker_device: str
    reranker_batch_size: int
    reranker_enabled: bool
    reranker_top_n: int
    reranker_timeout_seconds: float
    cors_origins: list[str]
    eval_questions_path: Path
    judge_model: str = "qwen3:8b"
    judge_timeout_seconds: float = 180
    judge_threshold: float = 0.7
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-pro"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_timeout_seconds: float = 300
    web_research_enabled: bool = True
    web_research_provider: str = "autosearch"
    web_research_max_queries: int = 24
    web_research_max_sources: int = 80
    web_research_max_included_sources: int = 30
    crawler_provider: str = "crawl4ai"
    crawl_timeout_seconds: float = 60
    followup_model: str = "qwen3.5:9b"
    followup_think: bool = False
    followup_num_predict: int = 384
    followup_timeout_seconds: float = 20
    post_persona_alignment_enabled: bool = True
    persona_first_enabled: bool = True
    llama_cpp_base_url: str = "http://127.0.0.1:8080"
    llama_cpp_model: str = "qwen3-8b-gguf"
    low_generation_model: str = ""
    medium_generation_model: str = ""
    high_generation_model: str = ""
    low_generation_think: bool | None = None
    medium_generation_think: bool | None = None
    high_generation_think: bool | None = None
    low_generation_thinking_budget: int | None = None
    medium_generation_thinking_budget: int | None = None
    high_generation_thinking_budget: int | None = None
    low_generation_refinement_passes: int | None = None
    medium_generation_refinement_passes: int | None = None
    high_generation_refinement_passes: int | None = None
    auth_required: bool = False
    auth_token_ttl_hours: float = 72
    auth_trust_proxy_headers: bool = True
    auth_max_active_login_ips: int = 3
    auth_challenge_required: bool = True
    auth_challenge_mode: str = "slider"
    auth_challenge_difficulty: int = 3
    auth_challenge_ttl_seconds: int = 180
    auth_challenge_min_elapsed_ms: int = 800
    auth_admin_username: str = "admin"
    auth_admin_email: str = "admin@local.persona-rag"
    auth_admin_password: str = "change_me_in_local_env"
    email_verification_ttl_minutes: int = 10
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_security: str = "ssl"
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    document_reader_enable_docling: bool = True
    document_reader_enable_marker_surya: bool = True
    document_reader_enable_paddleocr_vl: bool = False
    document_reader_enable_granite_docling: bool = False
    document_reader_enable_mineru: bool = False
    document_reader_enable_olmocr: bool = False
    document_reader_model_cache_dir: Path = Path("models/document_reader")
    document_reader_marker_surya_python: str = ""
    document_reader_marker_surya_device: str = "auto"
    document_reader_marker_surya_timeout_seconds: float = 900
    document_reader_paddleocr_vl_mode: str = "worker"
    document_reader_paddleocr_vl_python: str = ""
    document_reader_paddleocr_vl_endpoint: str = ""
    document_reader_paddleocr_vl_device: str = "auto"
    document_reader_paddleocr_vl_timeout_seconds: float = 900


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_project_dotenv()
    return Settings(
        env=os.getenv("PERSONA_RAG_ENV", "dev"),
        host=os.getenv("PERSONA_RAG_HOST", "127.0.0.1"),
        port=int(os.getenv("PERSONA_RAG_PORT", "8000")),
        corpus_dir=Path(os.getenv("PERSONA_RAG_CORPUS_DIR", "corpus")),
        data_dir=Path(os.getenv("PERSONA_RAG_DATA_DIR", "data")),
        sqlite_path=Path(os.getenv("PERSONA_RAG_SQLITE_PATH", "data/sqlite/persona_rag.sqlite3")),
        model_provider=os.getenv("PERSONA_RAG_MODEL_PROVIDER", "ollama"),
        ollama_base_url=os.getenv("PERSONA_RAG_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        ollama_models_dir=Path(os.getenv("PERSONA_RAG_OLLAMA_MODELS_DIR", "models/ollama")),
        llama_cpp_base_url=os.getenv("PERSONA_RAG_LLAMA_CPP_BASE_URL", "http://127.0.0.1:8080"),
        llama_cpp_model=os.getenv("PERSONA_RAG_LLAMA_CPP_MODEL", "qwen3-8b-gguf"),
        generation_model=os.getenv("PERSONA_RAG_GENERATION_MODEL", "qwen3:8b"),
        quality_generation_model=os.getenv("PERSONA_RAG_QUALITY_GENERATION_MODEL", "").strip(),
        quality_generation_min_effort=os.getenv("PERSONA_RAG_QUALITY_GENERATION_MIN_EFFORT", "high"),
        quality_generation_think=_optional_bool_env("PERSONA_RAG_QUALITY_GENERATION_THINK"),
        quality_generation_refinement_passes=_optional_int_env(
            "PERSONA_RAG_QUALITY_GENERATION_REFINE_PASSES"
        ),
        model_timeout_seconds=float(os.getenv("PERSONA_RAG_MODEL_TIMEOUT_SECONDS", "480")),
        model_keep_alive=os.getenv("PERSONA_RAG_MODEL_KEEP_ALIVE", "30s"),
        model_think=_bool_env("PERSONA_RAG_MODEL_THINK", True),
        model_num_predict=int(os.getenv("PERSONA_RAG_MODEL_NUM_PREDICT", "1280")),
        model_temperature=float(os.getenv("PERSONA_RAG_MODEL_TEMPERATURE", "0.2")),
        model_top_p=float(os.getenv("PERSONA_RAG_MODEL_TOP_P", "0.9")),
        boundary_fast_path_enabled=_bool_env("PERSONA_RAG_BOUNDARY_FAST_PATH_ENABLED", True),
        embedding_model=os.getenv("PERSONA_RAG_EMBEDDING_MODEL", "qwen3-embedding:0.6b"),
        embedding_timeout_seconds=float(os.getenv("PERSONA_RAG_EMBEDDING_TIMEOUT_SECONDS", "120")),
        sparse_retriever=os.getenv("PERSONA_RAG_SPARSE_RETRIEVER", "sqlite_fts5"),
        retrieval_mode=os.getenv("PERSONA_RAG_RETRIEVAL_MODE", "hybrid"),
        retrieval_first_stage_top_k=int(os.getenv("PERSONA_RAG_RETRIEVAL_FIRST_STAGE_TOP_K", "40")),
        retrieval_rrf_k=int(os.getenv("PERSONA_RAG_RETRIEVAL_RRF_K", "60")),
        query_rewrite_enabled=_bool_env("PERSONA_RAG_QUERY_REWRITE_ENABLED", True),
        query_rewrite_max_queries=int(os.getenv("PERSONA_RAG_QUERY_REWRITE_MAX_QUERIES", "3")),
        query_rewrite_dense=_bool_env("PERSONA_RAG_QUERY_REWRITE_DENSE", False),
        local_reranker_enabled=_bool_env("PERSONA_RAG_LOCAL_RERANKER_ENABLED", True),
        source_selector_enabled=_bool_env("PERSONA_RAG_SOURCE_SELECTOR_ENABLED", True),
        source_selector_intent_filter_enabled=_bool_env(
            "PERSONA_RAG_SOURCE_SELECTOR_INTENT_FILTER_ENABLED",
            True,
        ),
        source_selector_top_k=int(os.getenv("PERSONA_RAG_SOURCE_SELECTOR_TOP_K", "12")),
        vector_index_path=Path(
            os.getenv(
                "PERSONA_RAG_VECTOR_INDEX_PATH",
                "data/indexes/dense_qwen3_embedding_0_6b.json",
            )
        ),
        reranker_backend=os.getenv("PERSONA_RAG_RERANKER_BACKEND", "ollama_generate"),
        reranker_model=os.getenv(
            "PERSONA_RAG_RERANKER_MODEL",
            "dengcao/Qwen3-Reranker-0.6B:Q8_0",
        ),
        reranker_hf_model=os.getenv("PERSONA_RAG_RERANKER_HF_MODEL", "Qwen/Qwen3-Reranker-0.6B"),
        reranker_hf_cache_dir=Path(
            os.getenv("PERSONA_RAG_RERANKER_HF_CACHE_DIR", "models/huggingface")
        ),
        reranker_device=os.getenv("PERSONA_RAG_RERANKER_DEVICE", "auto"),
        reranker_batch_size=int(os.getenv("PERSONA_RAG_RERANKER_BATCH_SIZE", "8")),
        reranker_enabled=_bool_env("PERSONA_RAG_RERANKER_ENABLED", False),
        reranker_top_n=int(os.getenv("PERSONA_RAG_RERANKER_TOP_N", "12")),
        reranker_timeout_seconds=float(os.getenv("PERSONA_RAG_RERANKER_TIMEOUT_SECONDS", "120")),
        eval_questions_path=Path(
            os.getenv("PERSONA_RAG_EVAL_QUESTIONS_PATH", "evals/questions/smoke_questions.json")
        ),
        judge_model=os.getenv("PERSONA_RAG_JUDGE_MODEL", "qwen3:8b"),
        judge_timeout_seconds=float(os.getenv("PERSONA_RAG_JUDGE_TIMEOUT_SECONDS", "180")),
        judge_threshold=float(os.getenv("PERSONA_RAG_JUDGE_THRESHOLD", "0.7")),
        deepseek_api_key=os.getenv("PERSONA_RAG_DEEPSEEK_API_KEY", "").strip(),
        deepseek_model=_string_env("PERSONA_RAG_DEEPSEEK_MODEL", "deepseek-v4-pro"),
        deepseek_base_url=_string_env("PERSONA_RAG_DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_timeout_seconds=float(os.getenv("PERSONA_RAG_DEEPSEEK_TIMEOUT_SECONDS", "300")),
        web_research_enabled=_bool_env("PERSONA_RAG_WEB_RESEARCH_ENABLED", True),
        web_research_provider=_string_env("PERSONA_RAG_WEB_RESEARCH_PROVIDER", "autosearch"),
        web_research_max_queries=int(os.getenv("PERSONA_RAG_WEB_RESEARCH_MAX_QUERIES", "24")),
        web_research_max_sources=int(os.getenv("PERSONA_RAG_WEB_RESEARCH_MAX_SOURCES", "80")),
        web_research_max_included_sources=int(
            os.getenv("PERSONA_RAG_WEB_RESEARCH_MAX_INCLUDED_SOURCES", "30")
        ),
        crawler_provider=_string_env("PERSONA_RAG_CRAWLER_PROVIDER", "crawl4ai"),
        crawl_timeout_seconds=float(os.getenv("PERSONA_RAG_CRAWL_TIMEOUT_SECONDS", "60")),
        followup_model=_string_env("PERSONA_RAG_FOLLOWUP_MODEL", "qwen3.5:9b"),
        followup_think=_bool_env("PERSONA_RAG_FOLLOWUP_THINK", False),
        followup_num_predict=int(os.getenv("PERSONA_RAG_FOLLOWUP_NUM_PREDICT", "384")),
        followup_timeout_seconds=float(os.getenv("PERSONA_RAG_FOLLOWUP_TIMEOUT_SECONDS", "20")),
        cors_origins=_csv_env(
            "PERSONA_RAG_CORS_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173",
        ),
        post_persona_alignment_enabled=_bool_env("PERSONA_RAG_POST_PERSONA_ALIGNMENT_ENABLED", True),
        persona_first_enabled=_bool_env("PERSONA_RAG_PERSONA_FIRST_ENABLED", True),
        low_generation_model=_string_env("PERSONA_RAG_LOW_GENERATION_MODEL", "qwen3.5:9b"),
        medium_generation_model=_string_env("PERSONA_RAG_MEDIUM_GENERATION_MODEL", "qwen3.5:9b"),
        high_generation_model=_string_env(
            "PERSONA_RAG_HIGH_GENERATION_MODEL",
            "qwen3.5:9b",
        ),
        low_generation_think=_optional_bool_env("PERSONA_RAG_LOW_GENERATION_THINK", True),
        medium_generation_think=_optional_bool_env("PERSONA_RAG_MEDIUM_GENERATION_THINK", True),
        high_generation_think=_optional_bool_env("PERSONA_RAG_HIGH_GENERATION_THINK", True),
        low_generation_thinking_budget=_optional_int_env(
            "PERSONA_RAG_LOW_GENERATION_THINKING_BUDGET",
            600,
        ),
        medium_generation_thinking_budget=_optional_int_env(
            "PERSONA_RAG_MEDIUM_GENERATION_THINKING_BUDGET",
            2000,
        ),
        high_generation_thinking_budget=_optional_int_env(
            "PERSONA_RAG_HIGH_GENERATION_THINKING_BUDGET",
            4000,
        ),
        low_generation_refinement_passes=_optional_int_env(
            "PERSONA_RAG_LOW_GENERATION_REFINE_PASSES",
            0,
        ),
        medium_generation_refinement_passes=_optional_int_env(
            "PERSONA_RAG_MEDIUM_GENERATION_REFINE_PASSES",
            0,
        ),
        high_generation_refinement_passes=_optional_int_env(
            "PERSONA_RAG_HIGH_GENERATION_REFINE_PASSES",
            0,
        ),
        auth_required=_bool_env("PERSONA_RAG_AUTH_REQUIRED", False),
        auth_token_ttl_hours=float(os.getenv("PERSONA_RAG_AUTH_TOKEN_TTL_HOURS", "72")),
        auth_trust_proxy_headers=_bool_env("PERSONA_RAG_AUTH_TRUST_PROXY_HEADERS", True),
        auth_max_active_login_ips=int(os.getenv("PERSONA_RAG_AUTH_MAX_ACTIVE_LOGIN_IPS", "3")),
        auth_challenge_required=_bool_env("PERSONA_RAG_AUTH_CHALLENGE_REQUIRED", True),
        auth_challenge_mode=_string_env("PERSONA_RAG_AUTH_CHALLENGE_MODE", "slider").lower(),
        auth_challenge_difficulty=int(os.getenv("PERSONA_RAG_AUTH_CHALLENGE_DIFFICULTY", "3")),
        auth_challenge_ttl_seconds=int(os.getenv("PERSONA_RAG_AUTH_CHALLENGE_TTL_SECONDS", "180")),
        auth_challenge_min_elapsed_ms=int(os.getenv("PERSONA_RAG_AUTH_CHALLENGE_MIN_ELAPSED_MS", "800")),
        auth_admin_username=_string_env("PERSONA_RAG_AUTH_ADMIN_USERNAME", "admin"),
        auth_admin_email=_string_env("PERSONA_RAG_AUTH_ADMIN_EMAIL", "admin@local.persona-rag"),
        auth_admin_password=os.getenv("PERSONA_RAG_AUTH_ADMIN_PASSWORD", "change_me_in_local_env"),
        email_verification_ttl_minutes=int(
            os.getenv("PERSONA_RAG_EMAIL_VERIFICATION_TTL_MINUTES", "10")
        ),
        smtp_host=_string_env("PERSONA_RAG_SMTP_HOST", ""),
        smtp_port=int(os.getenv("PERSONA_RAG_SMTP_PORT", "465")),
        smtp_security=_string_env("PERSONA_RAG_SMTP_SECURITY", "ssl"),
        smtp_username=_string_env("PERSONA_RAG_SMTP_USERNAME", ""),
        smtp_password=os.getenv("PERSONA_RAG_SMTP_PASSWORD", "").strip(),
        smtp_from=_string_env("PERSONA_RAG_SMTP_FROM", ""),
        document_reader_enable_docling=_bool_env("DOCUMENT_READER_ENABLE_DOCLING", True),
        document_reader_enable_marker_surya=_bool_env(
            "DOCUMENT_READER_ENABLE_MARKER_SURYA",
            True,
        ),
        document_reader_enable_paddleocr_vl=_bool_env(
            "DOCUMENT_READER_ENABLE_PADDLEOCR_VL", False
        ),
        document_reader_enable_granite_docling=_bool_env(
            "DOCUMENT_READER_ENABLE_GRANITE_DOCLING", False
        ),
        document_reader_enable_mineru=_bool_env("DOCUMENT_READER_ENABLE_MINERU", False),
        document_reader_enable_olmocr=_bool_env("DOCUMENT_READER_ENABLE_OLMOCR", False),
        document_reader_model_cache_dir=Path(
            os.getenv("DOCUMENT_READER_MODEL_CACHE_DIR", "models/document_reader")
        ),
        document_reader_marker_surya_python=_string_env(
            "DOCUMENT_READER_MARKER_SURYA_PYTHON",
            "",
        ),
        document_reader_marker_surya_device=_string_env(
            "DOCUMENT_READER_MARKER_SURYA_DEVICE",
            "auto",
        ).lower(),
        document_reader_marker_surya_timeout_seconds=float(
            os.getenv("DOCUMENT_READER_MARKER_SURYA_TIMEOUT_SECONDS", "900")
        ),
        document_reader_paddleocr_vl_mode=_string_env(
            "DOCUMENT_READER_PADDLEOCR_VL_MODE",
            "worker",
        ).lower(),
        document_reader_paddleocr_vl_python=_string_env(
            "DOCUMENT_READER_PADDLEOCR_VL_PYTHON",
            "",
        ),
        document_reader_paddleocr_vl_endpoint=_string_env(
            "DOCUMENT_READER_PADDLEOCR_VL_ENDPOINT",
            "",
        ),
        document_reader_paddleocr_vl_device=_string_env(
            "DOCUMENT_READER_PADDLEOCR_VL_DEVICE",
            "auto",
        ).lower(),
        document_reader_paddleocr_vl_timeout_seconds=float(
            os.getenv("DOCUMENT_READER_PADDLEOCR_VL_TIMEOUT_SECONDS", "900")
        ),
    )
