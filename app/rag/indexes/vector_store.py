from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

from app.rag.chunking.markdown import Chunk


@dataclass(frozen=True)
class VectorEntry:
    chunk_id: str
    vector: list[float]


class DenseVectorIndex:
    def __init__(
        self,
        *,
        model: str,
        corpus_fingerprint: str,
        dimension: int,
        entries: list[VectorEntry],
    ):
        self.model = model
        self.corpus_fingerprint = corpus_fingerprint
        self.dimension = dimension
        self.entries = entries

    @classmethod
    def build(
        cls,
        *,
        model: str,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> "DenseVectorIndex":
        if len(chunks) != len(embeddings):
            raise ValueError("Chunk and embedding counts do not match.")
        dimension = len(embeddings[0]) if embeddings else 0
        entries = [
            VectorEntry(chunk_id=chunk.chunk_id, vector=normalize_vector(vector))
            for chunk, vector in zip(chunks, embeddings, strict=True)
        ]
        return cls(
            model=model,
            corpus_fingerprint=corpus_fingerprint(chunks),
            dimension=dimension,
            entries=entries,
        )

    @classmethod
    def load(cls, path: Path) -> "DenseVectorIndex":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            model=data["model"],
            corpus_fingerprint=data["corpus_fingerprint"],
            dimension=int(data["dimension"]),
            entries=[
                VectorEntry(chunk_id=entry["chunk_id"], vector=entry["vector"])
                for entry in data["entries"]
            ],
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": self.model,
            "corpus_fingerprint": self.corpus_fingerprint,
            "dimension": self.dimension,
            "entries": [
                {"chunk_id": entry.chunk_id, "vector": entry.vector}
                for entry in self.entries
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def is_current(self, *, model: str, chunks: list[Chunk]) -> bool:
        return self.model == model and self.corpus_fingerprint == corpus_fingerprint(chunks)

    def search(
        self,
        *,
        query_vector: list[float],
        chunks: list[Chunk],
        top_k: int,
        include_private: bool = False,
    ) -> list[tuple[Chunk, float]]:
        normalized_query = normalize_vector(query_vector)
        chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        scored: list[tuple[Chunk, float]] = []
        for entry in self.entries:
            chunk = chunks_by_id.get(entry.chunk_id)
            if chunk is None:
                continue
            if not include_private and chunk.privacy_level != "public":
                continue
            score = dot_product(normalized_query, entry.vector)
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]


def corpus_fingerprint(chunks: list[Chunk]) -> str:
    digest = hashlib.sha256()
    for chunk in sorted(chunks, key=lambda item: item.chunk_id):
        digest.update(chunk.chunk_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(chunk.text.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def chunk_embedding_text(chunk: Chunk) -> str:
    return f"{chunk.title}\n{chunk.section_path}\n{chunk.text}"


def normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def dot_product(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))

