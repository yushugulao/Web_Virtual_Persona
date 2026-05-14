from __future__ import annotations

import math
import os
from dataclasses import dataclass

import httpx

from app.backend.core.config import Settings
from app.rag.chunking.markdown import Chunk


RERANK_INSTRUCTION = (
    "Given a question about a person's resume, projects, values, work style, or "
    "course-design materials, decide whether the document chunk contains evidence "
    "that helps answer the question."
)


@dataclass(frozen=True)
class RerankOutcome:
    results: list[tuple[Chunk, float]]
    note: str


_CROSS_ENCODER_CACHE: dict[tuple[str, str, str], object] = {}


class ConfiguredModelReranker:
    def __init__(self, settings: Settings):
        self.settings = settings

    def rerank(self, query: str, candidates: list[tuple[Chunk, float]], top_k: int) -> RerankOutcome:
        backend = self.settings.reranker_backend.strip().lower()
        if backend in {"sentence_transformers", "cross_encoder", "transformers"}:
            return SentenceTransformersReranker(self.settings).rerank(query, candidates, top_k)
        return OllamaGenerateReranker(self.settings).rerank(query, candidates, top_k)


class OllamaGenerateReranker:
    def __init__(self, settings: Settings):
        self.settings = settings

    def rerank(self, query: str, candidates: list[tuple[Chunk, float]], top_k: int) -> RerankOutcome:
        if not candidates:
            return RerankOutcome(results=[], note="排序复核器已跳过：没有候选片段。")
        if not self.settings.reranker_enabled:
            return RerankOutcome(results=candidates, note="排序复核器已由配置关闭。")

        rerank_pool = candidates[: self.settings.reranker_top_n]
        try:
            scored = []
            usable_scores = 0
            for chunk, first_stage_score in rerank_pool:
                rerank_score = self._score_pair(query, chunk)
                if rerank_score is None:
                    rerank_score = 0.5
                else:
                    usable_scores += 1
                scored.append((chunk, rerank_score, first_stage_score))
        except Exception as exc:
            return RerankOutcome(
                results=candidates,
                note=f"排序复核器不可用，已保留融合顺序。原因：{exc}",
            )

        if usable_scores == 0:
            return RerankOutcome(
                results=candidates,
                note=(
                    "排序复核器未通过 Ollama generate/logprobs 适配器产生可用的 yes/no "
                    "相关性信号，已保留融合顺序。"
                ),
            )

        scored.sort(key=lambda item: (item[1], item[2]), reverse=True)
        reranked_ids = {chunk.chunk_id for chunk, _score, _first_stage in scored}
        tail = [(chunk, score) for chunk, score in candidates if chunk.chunk_id not in reranked_ids]
        combined = [(chunk, score) for chunk, score, _first_stage in scored] + tail
        return RerankOutcome(
            results=combined,
            note=(
                f"已用 {self.settings.reranker_model} 通过 Ollama generate/logprobs "
                f"适配器复核前 {len(rerank_pool)} 个候选片段。"
            ),
        )

    def _score_pair(self, query: str, chunk: Chunk) -> float | None:
        prompt = (
            f"<Instruct>: {RERANK_INSTRUCTION}\n"
            f"<Query>: {query}\n"
            f"<Document>: {chunk.title}\n{chunk.section_path}\n{chunk.text}\n"
            "Answer only yes or no."
        )
        timeout = httpx.Timeout(self.settings.reranker_timeout_seconds, connect=10.0)
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{self.settings.ollama_base_url.rstrip('/')}/api/generate",
                json={
                    "model": self.settings.reranker_model,
                    "prompt": prompt,
                    "stream": False,
                    "think": False,
                    "raw": False,
                    "keep_alive": self.settings.model_keep_alive,
                    "options": {
                        "temperature": 0,
                        "num_predict": 1,
                    },
                    "logprobs": True,
                    "top_logprobs": 8,
                },
            )
            response.raise_for_status()
            data = response.json()

        token_score = score_from_logprobs(data)
        if token_score is not None:
            return token_score
        return score_from_response_text(str(data.get("response", "")))


class SentenceTransformersReranker:
    def __init__(self, settings: Settings):
        self.settings = settings

    def rerank(self, query: str, candidates: list[tuple[Chunk, float]], top_k: int) -> RerankOutcome:
        if not candidates:
            return RerankOutcome(results=[], note="排序复核器已跳过：没有候选片段。")
        if not self.settings.reranker_enabled:
            return RerankOutcome(results=candidates, note="排序复核器已由配置关闭。")

        rerank_pool = candidates[: self.settings.reranker_top_n]
        try:
            scores = self._score_pairs(query, [chunk for chunk, _score in rerank_pool])
        except Exception as exc:
            return RerankOutcome(
                results=candidates,
                note=f"SentenceTransformers 排序复核器不可用，已保留融合顺序。原因：{exc}",
            )

        scored = [
            (chunk, sigmoid(float(score)), first_stage_score)
            for (chunk, first_stage_score), score in zip(rerank_pool, scores, strict=False)
        ]
        if not scored:
            return RerankOutcome(
                results=candidates,
                note="SentenceTransformers 排序复核器没有产生分数，已保留融合顺序。",
            )

        scored.sort(key=lambda item: (item[1], item[2]), reverse=True)
        reranked_ids = {chunk.chunk_id for chunk, _score, _first_stage in scored}
        tail = [(chunk, score) for chunk, score in candidates if chunk.chunk_id not in reranked_ids]
        combined = [(chunk, score) for chunk, score, _first_stage in scored] + tail
        return RerankOutcome(
            results=combined,
            note=(
                f"已用 {self.settings.reranker_hf_model} 通过 sentence-transformers CrossEncoder "
                f"复核前 {len(rerank_pool)} 个候选片段，并使用 sigmoid 归一化 logits。"
            ),
        )

    def _score_pairs(self, query: str, chunks: list[Chunk]) -> list[float]:
        model = load_cross_encoder(self.settings)
        pairs = [(query, reranker_document_text(chunk)) for chunk in chunks]
        scores = model.predict(
            pairs,
            batch_size=self.settings.reranker_batch_size,
            show_progress_bar=False,
        )
        return [float(score) for score in scores]


def load_cross_encoder(settings: Settings):
    cache_dir = settings.reranker_hf_cache_dir.resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(cache_dir))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    key = (
        settings.reranker_hf_model,
        settings.reranker_device,
        str(cache_dir),
    )
    cached = _CROSS_ENCODER_CACHE.get(key)
    if cached is not None:
        return cached

    from sentence_transformers import CrossEncoder

    device_kwargs = {}
    if settings.reranker_device.strip().lower() != "auto":
        device_kwargs["device"] = settings.reranker_device
    try:
        model = CrossEncoder(
            settings.reranker_hf_model,
            prompts={"persona": RERANK_INSTRUCTION},
            default_prompt_name="persona",
            **device_kwargs,
        )
    except TypeError:
        model = CrossEncoder(settings.reranker_hf_model, **device_kwargs)
    _CROSS_ENCODER_CACHE[key] = model
    return model


def reranker_document_text(chunk: Chunk) -> str:
    return f"{chunk.title}\n{chunk.section_path}\n{chunk.text}"


def score_from_response_text(text: str) -> float | None:
    normalized = text.strip().lower()
    if normalized.startswith(("yes", "y", "relevant", "\u662f")):
        return 1.0
    if normalized.startswith(("no", "n", "irrelevant", "\u5426")):
        return 0.0
    return None


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def score_from_logprobs(data: dict) -> float | None:
    raw_logprobs = data.get("logprobs")
    if not raw_logprobs:
        return None

    first = raw_logprobs[0] if isinstance(raw_logprobs, list) and raw_logprobs else None
    if not isinstance(first, dict):
        return None

    candidates = first.get("top_logprobs") or [first]
    yes_logprob = None
    no_logprob = None
    for item in candidates:
        if not isinstance(item, dict):
            continue
        token = _normalize_relevance_token(item.get("token", ""))
        logprob = item.get("logprob")
        if not isinstance(logprob, (int, float)):
            continue
        if token in {"yes", "y", "relevant", "\u662f"}:
            yes_logprob = float(logprob)
        elif token in {"no", "n", "irrelevant", "\u5426"}:
            no_logprob = float(logprob)

    if yes_logprob is None or no_logprob is None:
        return None
    yes = math.exp(yes_logprob)
    no = math.exp(no_logprob)
    denominator = yes + no
    if denominator == 0:
        return None
    return yes / denominator


def _normalize_relevance_token(token: object) -> str:
    return (
        str(token)
        .strip()
        .lower()
        .replace("\u2581", "")
        .replace("\u0120", "")
        .strip()
    )
