from __future__ import annotations

import httpx

from app.backend.core.config import Settings


QUERY_INSTRUCTION = (
    "Instruct: Given a question about a person's resume, projects, values, work style, "
    "or course-design materials, retrieve the most relevant evidence chunk.\nQuery: "
)


class OllamaEmbeddingClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([f"{QUERY_INSTRUCTION}{query}"])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_texts(texts)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        timeout = httpx.Timeout(self.settings.embedding_timeout_seconds, connect=10.0)
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{self.settings.ollama_base_url.rstrip('/')}/api/embed",
                json={
                    "model": self.settings.embedding_model,
                    "input": texts,
                    "keep_alive": self.settings.model_keep_alive,
                },
            )
            response.raise_for_status()
            data = response.json()
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise RuntimeError("Ollama embedding response did not contain the expected embeddings.")
        return embeddings

