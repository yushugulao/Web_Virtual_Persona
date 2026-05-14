from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.backend.api import (
    admin,
    auth,
    chat,
    corpus,
    evals,
    evidence,
    feedback,
    health,
    ingest,
    memory,
    persona_catalog,
    personas,
    retrieval,
    traces,
)
from app.backend.auth.auth_store import AuthStore
from app.backend.core.config import get_settings
from app.backend.memory.memory_store import MemoryStore
from app.backend.services.evidence_card_service import rebuild_evidence_cards_from_corpus
from app.backend.services.metadata_store import MetadataStore
from app.rag.indexes.memory_store import load_corpus


settings = get_settings()

app = FastAPI(
    title="Local Persona-RAG",
    version="0.1.0",
    description="Local evidence-grounded persona assistant backend.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(chat.router)
app.include_router(ingest.router)
app.include_router(retrieval.router)
app.include_router(corpus.router)
app.include_router(evals.router)
app.include_router(evidence.router)
app.include_router(memory.router)
app.include_router(feedback.router)
app.include_router(traces.router)
app.include_router(personas.router)
app.include_router(persona_catalog.router)


@app.on_event("startup")
def initialize_metadata_store() -> None:
    documents, chunks = load_corpus(str(settings.corpus_dir))
    store = MetadataStore(settings.sqlite_path)
    store.upsert_corpus(documents, chunks)
    rebuild_evidence_cards_from_corpus(
        corpus_dir=settings.corpus_dir,
        store=store,
        chunks=chunks,
    )
    MemoryStore(settings.sqlite_path).initialize()
    AuthStore(settings.sqlite_path).bootstrap_admin(
        username=settings.auth_admin_username,
        email=settings.auth_admin_email,
        password=settings.auth_admin_password,
    )
