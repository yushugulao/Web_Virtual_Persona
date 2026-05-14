import asyncio
import json
import re
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path

import httpx

from app.backend.core.config import Settings
from app.backend.services.model_diagnostics import (
    current_model_diagnostic_phase,
    current_model_diagnostics,
    finish_active_model_call,
    start_active_model_call,
    touch_active_model_call,
)

THINKING_EFFORT_TIMEOUT_MULTIPLIERS = {
    "low": 1,
    "medium": 2,
    "high": 10,
}
THINKING_EFFORT_NUM_PREDICT_MULTIPLIERS = {
    "low": 1.0,
    "medium": 1.4,
    "high": 2.0,
}
THINKING_EFFORT_REFINE_PASSES = {
    "low": 0,
    "medium": 0,
    "high": 2,
}
THINKING_EFFORT_RANK = {
    "low": 0,
    "medium": 1,
    "high": 2,
}
THINKING_EFFORTS = ("low", "medium", "high")
MODEL_NO_PROGRESS_TIMEOUT_SECONDS = 45.0
QWEN_THINKING_EARLY_STOP_TEXT = "思考预算已用完。请立即结束内部推理，基于已有思路准备最终可见回答。"
QWEN_THINKING_FINAL_PROMPT = (
    "/no_think\n\n"
    "内部 thinking 已经结束。现在只输出用户可见的最终回答正文。"
    "如果上一条 assistant 在 </think> 后已经开始写最终回答，请自然续写剩余部分；"
    "如果还没有开始最终回答，请从第一句话开始写完整回答。"
    "不要写 thinking、分析、规则、草稿说明或过程说明。"
)
QWEN_THINKING_BUDGET_PROMPT_SUFFIX = (
    "\n\n[内部 thinking 阶段]\n"
    "这是仅供模型内部规划的 thinking 阶段。请围绕用户问题和当前角色完成必要分析，"
    "先规划回答结构，再整理最终回答要点。尽量接近但不要明显超过 {budget} token 的 thinking 预算。"
    "不要在 thinking 阶段输出最终可见正文；最终正文会在下一阶段单独生成。"
)
THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
FINAL_MARKER_RE = re.compile(r"^\s*FINAL_ANSWER\s*:\s*", re.IGNORECASE)
SCRATCHPAD_PREAMBLE_RE = re.compile(
    r"^\s*(okay|let's|we need|we are given|i need|the user|first,|hmm)\b",
    re.IGNORECASE,
)
CJK_RE = re.compile(r"[\u3400-\u9fff]")
LATIN_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
NON_SPACE_RE = re.compile(r"\S")


def _compact_visible_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


@lru_cache(maxsize=1)
def _load_local_qwen_tokenizer():
    """Best-effort local Qwen tokenizer loader for budget accounting.

    The project already keeps optional Hugging Face assets under `models/huggingface`. If a Qwen
    tokenizer is unavailable in the local cache, budget enforcement falls back to a stable estimate.
    This function never downloads model files.
    """

    try:
        from tokenizers import Tokenizer
    except Exception:
        return None
    cache_root = Path("models/huggingface")
    if not cache_root.exists():
        return None
    try:
        candidates = sorted(
            path
            for path in cache_root.rglob("tokenizer.json")
            if "models--Qwen--" in str(path)
        )
    except OSError:
        return None
    for path in candidates:
        try:
            return Tokenizer.from_file(str(path))
        except Exception:
            continue
    return None
RAG_SYSTEM_MESSAGE = (
    "请为沉浸式第一人称对话写出用户可见回复。"
    "不得暴露说话者是 AI、模型、助手、模拟体、虚拟分身、RAG 系统、检索流水线、提示词、规则集或证据审阅过程。"
    "涉及说话者本人履历、亲历、身份、成就、关系和时代知识时，只使用提供的幕后上下文；引用和证据面板由界面在回答之外处理。"
    "普通算术、自然常识、语言任务、用户本轮给出的假设、情绪回应和开放建议可以直接回答；"
    "先回答问题本身；始终保持当前说话者的第一人称身份，但数学和自然常识不要添加未支持的亲历尾句。"
    "不要为了人物气质新增个人经历、习惯或亲历场景。"
    "不要伪装成经历边界问题。"
    "匹配用户问题的语言；如果问题包含中文，请用中文回答。"
)


def timeout_seconds_for_effort(base_timeout_seconds: float, thinking_effort: str) -> float:
    multiplier = THINKING_EFFORT_TIMEOUT_MULTIPLIERS.get(thinking_effort, 1)
    return base_timeout_seconds * multiplier


def num_predict_for_effort(base_num_predict: int, thinking_effort: str) -> int:
    multiplier = THINKING_EFFORT_NUM_PREDICT_MULTIPLIERS.get(thinking_effort, 1.0)
    return max(1, int(round(base_num_predict * multiplier)))


def refinement_passes_for_effort(thinking_effort: str) -> int:
    return THINKING_EFFORT_REFINE_PASSES.get(thinking_effort, 0)


def refinement_passes_for_request(settings: Settings, thinking_effort: str) -> int:
    effort_override = _refinement_passes_override(settings, thinking_effort)
    if effort_override is not None:
        return max(0, effort_override)
    selected_model = model_for_effort(settings, thinking_effort)
    if (
        selected_model == settings.quality_generation_model
        and settings.quality_generation_refinement_passes is not None
    ):
        return max(0, settings.quality_generation_refinement_passes)
    return refinement_passes_for_effort(thinking_effort)


def thinking_budget_for_effort(settings: Settings, thinking_effort: str) -> int | None:
    """Return the Qwen thinking-budget token cap for an effort level."""

    if thinking_effort not in THINKING_EFFORTS:
        return None
    value = getattr(settings, f"{thinking_effort}_generation_thinking_budget", None)
    if isinstance(value, int) and value > 0:
        return value
    return None


def display_thinking_budget_for_effort(settings: Settings, thinking_effort: str) -> int | None:
    """Return the whole-turn thinking progress budget shown in the UI."""

    budget = thinking_budget_for_effort(settings, thinking_effort)
    if budget is None:
        return None
    if thinking_effort in {"low", "medium", "high"}:
        return budget * 2
    return budget


def model_for_effort(settings: Settings, thinking_effort: str) -> str:
    effort_model = _model_override(settings, thinking_effort)
    if effort_model:
        return effort_model
    if settings.model_provider == "llama_cpp" and settings.llama_cpp_model.strip():
        return settings.llama_cpp_model
    if not settings.quality_generation_model.strip():
        return settings.generation_model
    min_rank = THINKING_EFFORT_RANK.get(settings.quality_generation_min_effort, THINKING_EFFORT_RANK["high"])
    effort_rank = THINKING_EFFORT_RANK.get(thinking_effort, THINKING_EFFORT_RANK["low"])
    if effort_rank >= min_rank:
        return settings.quality_generation_model
    return settings.generation_model


def think_for_effort(settings: Settings, thinking_effort: str) -> bool:
    effort_think = _think_override(settings, thinking_effort)
    if effort_think is not None:
        return effort_think
    selected_model = model_for_effort(settings, thinking_effort)
    if (
        selected_model == settings.quality_generation_model
        and settings.quality_generation_think is not None
    ):
        return settings.quality_generation_think
    return settings.model_think


def should_send_ollama_think(model_name: str, think: bool) -> bool:
    """Some Ollama reasoning models need their default thinking behavior."""

    normalized = model_name.strip().lower()
    if normalized.startswith("gpt-oss") and not think:
        return False
    return True


def supports_qwen_thinking_budget(model_name: str) -> bool:
    """Qwen3 / Qwen3.5 support the official thinking-budget continuation protocol."""

    normalized = model_name.strip().lower()
    return (
        (
            normalized.startswith("qwen3:")
            or normalized.startswith("qwen3-")
            or normalized.startswith("qwen3.5")
        )
        and "instruct" not in normalized
    )


async def release_ollama_model(settings: Settings, model_name: str) -> bool:
    """Best-effort unload for a model kept resident by Ollama keep_alive."""

    selected_model = model_name.strip()
    if settings.model_provider != "ollama" or not selected_model:
        return False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            response = await client.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/generate",
                json={"model": selected_model, "keep_alive": 0},
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                return True
            unload_accepted = data.get("done_reason") == "unload" or data.get("done") is True
            if not unload_accepted:
                return False
            for _ in range(20):
                if not await _is_ollama_model_loaded(client, settings, selected_model):
                    return True
                await asyncio.sleep(0.25)
    except Exception:
        return False
    return False


async def _is_ollama_model_loaded(client: httpx.AsyncClient, settings: Settings, model_name: str) -> bool:
    response = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/ps")
    response.raise_for_status()
    data = response.json()
    models = data.get("models", []) if isinstance(data, dict) else []
    normalized = model_name.strip().lower()
    for item in models:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("model") or "").strip().lower()
        if name == normalized:
            return True
    return False


async def release_model_for_effort(settings: Settings, thinking_effort: str) -> tuple[bool, str]:
    model_name = model_for_effort(settings, thinking_effort)
    return await release_ollama_model(settings, model_name), model_name


async def release_runtime_models(
    settings: Settings,
    *,
    thinking_effort: str | None = None,
    include_embedding: bool = False,
    include_all_generation_models: bool = False,
) -> dict:
    started = asyncio.get_running_loop().time()
    target_models = _runtime_release_targets(
        settings,
        thinking_effort=thinking_effort,
        include_embedding=include_embedding,
        include_all_generation_models=include_all_generation_models,
    )
    released_models: list[str] = []
    for model_name in target_models:
        if await release_ollama_model(settings, model_name):
            released_models.append(model_name)
    still_loaded_models = await loaded_release_targets(settings, target_models)
    return {
        "released_models": released_models,
        "still_loaded_models": still_loaded_models,
        "attempted_models": target_models,
        "elapsed_ms": round((asyncio.get_running_loop().time() - started) * 1000, 2),
        "ok": not still_loaded_models,
    }


def _runtime_release_targets(
    settings: Settings,
    *,
    thinking_effort: str | None,
    include_embedding: bool,
    include_all_generation_models: bool,
) -> list[str]:
    candidates: list[str] = []
    if include_all_generation_models:
        candidates.extend(
            [
                settings.generation_model,
                settings.quality_generation_model,
                settings.low_generation_model,
                settings.medium_generation_model,
                settings.high_generation_model,
            ]
        )
    elif thinking_effort:
        candidates.append(model_for_effort(settings, thinking_effort))
    else:
        candidates.append(settings.generation_model)
    if include_embedding:
        candidates.append(settings.embedding_model)
    seen: set[str] = set()
    targets: list[str] = []
    for model_name in candidates:
        normalized = (model_name or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        targets.append(normalized)
    return targets


async def loaded_release_targets(settings: Settings, target_models: list[str]) -> list[str]:
    if settings.model_provider != "ollama" or not target_models:
        return []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
            still_loaded: list[str] = []
            for model_name in target_models:
                if await _is_ollama_model_loaded(client, settings, model_name):
                    still_loaded.append(model_name)
            return still_loaded
    except Exception:
        return target_models


def list_loaded_ollama_models_snapshot(settings: Settings) -> list[dict]:
    if settings.model_provider != "ollama":
        return []
    try:
        response = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/api/ps", timeout=2.0)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []
    models = data.get("models", []) if isinstance(data, dict) else []
    snapshots: list[dict] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        snapshots.append(
            {
                "name": str(item.get("name") or item.get("model") or ""),
                "model": str(item.get("model") or item.get("name") or ""),
                "size_vram": item.get("size_vram"),
                "size": item.get("size"),
                "processor": str(item.get("processor") or ""),
                "expires_at": str(item.get("expires_at") or item.get("until") or ""),
            }
        )
    return snapshots


def _model_override(settings: Settings, thinking_effort: str) -> str:
    if thinking_effort not in THINKING_EFFORTS:
        return ""
    return str(getattr(settings, f"{thinking_effort}_generation_model", "") or "").strip()


def _think_override(settings: Settings, thinking_effort: str) -> bool | None:
    if thinking_effort not in THINKING_EFFORTS:
        return None
    value = getattr(settings, f"{thinking_effort}_generation_think", None)
    return value if isinstance(value, bool) else None


def _refinement_passes_override(settings: Settings, thinking_effort: str) -> int | None:
    if thinking_effort not in THINKING_EFFORTS:
        return None
    value = getattr(settings, f"{thinking_effort}_generation_refinement_passes", None)
    return value if isinstance(value, int) else None


class ModelNoProgressError(RuntimeError):
    """Raised when a streamed local model call stops producing observable progress."""


class LocalModelClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def generate(
        self,
        prompt: str,
        *,
        timeout_seconds: float | None = None,
        num_predict: int | None = None,
        model_name: str | None = None,
        think: bool | None = None,
        thinking_budget: int | None = None,
    ) -> tuple[str, str]:
        if self.settings.model_provider not in {"ollama", "llama_cpp"}:
            return self._fallback_answer(), "fallback"

        diagnostics = current_model_diagnostics()
        diagnostic_event_id = ""
        selected_model = model_name or self.settings.generation_model
        if self.settings.model_provider == "llama_cpp":
            selected_model = self._llama_cpp_model_name(model_name)
        active_call_id = start_active_model_call(
            phase=current_model_diagnostic_phase(),
            model=selected_model,
            provider=self.settings.model_provider,
            source="generate",
        )
        if diagnostics is not None and diagnostics.enabled:
            diagnostic_event_id = diagnostics.start_call(
                phase=current_model_diagnostic_phase(),
                model=selected_model,
                provider=self.settings.model_provider,
            )
        try:
            timeout = self._request_timeout(timeout_seconds)
            async with httpx.AsyncClient(timeout=timeout) as client:
                if self.settings.model_provider == "llama_cpp":
                    response = await client.post(
                        f"{self.settings.llama_cpp_base_url.rstrip('/')}/v1/chat/completions",
                        json=self._openai_chat_payload(
                            prompt,
                            stream=False,
                            num_predict=num_predict,
                            model_name=selected_model,
                            think=think,
                        ),
                    )
                else:
                    selected_think = self.settings.model_think if think is None else think
                    if self._should_use_thinking_budget(
                        selected_model,
                        selected_think,
                        thinking_budget,
                    ):
                        answer = await self._generate_ollama_with_qwen_thinking_budget(
                            client,
                            prompt,
                            selected_model=selected_model,
                            timeout_seconds=timeout_seconds,
                            num_predict=num_predict,
                            thinking_budget=thinking_budget,
                            diagnostic_event_id=diagnostic_event_id,
                        )
                        if answer:
                            return answer, selected_model
                        return self._no_visible_answer(), f"{selected_model}+no_visible_answer"
                    answer = await self._generate_ollama_streamed_for_generate(
                        client,
                        prompt,
                        selected_model=selected_model,
                        timeout_seconds=timeout_seconds,
                        num_predict=num_predict,
                        think=think,
                        diagnostic_event_id=diagnostic_event_id,
                    )
                    if not answer and selected_think:
                        retry_answer = await self._retry_ollama_visible_answer(
                            client,
                            prompt,
                            selected_model=selected_model,
                            timeout_seconds=timeout_seconds,
                            num_predict=num_predict,
                        )
                        if retry_answer:
                            return retry_answer, selected_model
                    if answer:
                        return answer, selected_model
                    return self._no_visible_answer(), f"{selected_model}+no_visible_answer"
                response.raise_for_status()
                data = response.json()
                if diagnostic_event_id:
                    self._record_response_diagnostics(diagnostic_event_id, data)
                if self.settings.model_provider == "llama_cpp":
                    answer = self._content_from_openai_chat_response(data)
                    if answer:
                        return answer, str(data.get("model") or selected_model)
                    return self._no_visible_answer(), f"{data.get('model') or selected_model}+no_visible_answer"
                answer = self._content_from_chat_response(data)
                selected_think = self.settings.model_think if think is None else think
                if not answer and selected_think:
                    retry_answer = await self._retry_ollama_visible_answer(
                        client,
                        prompt,
                        selected_model=selected_model,
                        timeout_seconds=timeout_seconds,
                        num_predict=num_predict,
                    )
                    if retry_answer:
                        return retry_answer, selected_model
                if answer:
                    return answer, selected_model
                return self._no_visible_answer(), f"{selected_model}+no_visible_answer"
        except ModelNoProgressError:
            await release_ollama_model(self.settings, selected_model)
            return self._no_progress_answer(), selected_model
        except Exception:
            return self._fallback_answer(), "fallback"
        finally:
            finish_active_model_call(active_call_id)
            if diagnostics is not None and diagnostic_event_id:
                diagnostics.finish_call(diagnostic_event_id)

    async def _generate_ollama_streamed_for_generate(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        *,
        selected_model: str,
        timeout_seconds: float | None,
        num_predict: int | None,
        think: bool | None,
        diagnostic_event_id: str,
    ) -> str:
        raw_text = ""
        thinking_length = 0
        visible_length = 0
        visible_draft_event_id = ""
        active_call_id = start_active_model_call(
            phase=current_model_diagnostic_phase(),
            model=selected_model,
            provider=self.settings.model_provider,
            source="generate_streamed",
        )
        async with client.stream(
            "POST",
            f"{self.settings.ollama_base_url.rstrip('/')}/api/chat",
            json=self._chat_payload(
                prompt,
                stream=True,
                num_predict=num_predict,
                model_name=selected_model,
                think=think,
            ),
            timeout=self._request_timeout(timeout_seconds),
        ) as response:
            try:
                response.raise_for_status()
                async for line in self._aiter_lines_with_watchdog(response, active_call_id):
                    if not line:
                        continue
                    data = json.loads(line)
                    self._record_stream_diagnostics(diagnostic_event_id, data)
                    token = self._content_from_stream_chunk(data)
                    if token:
                        raw_text += token
                        thinking_text = self._partial_think_text(raw_text)
                        if len(thinking_text) > thinking_length:
                            diagnostics = current_model_diagnostics()
                            if diagnostics is not None:
                                diagnostics.append(
                                    diagnostic_event_id,
                                    thinking_text[thinking_length:],
                                    source="think_block",
                                )
                            thinking_length = len(thinking_text)
                        visible_text = self._visible_stream_text(raw_text)
                        delta = visible_text[visible_length:]
                        if delta:
                            visible_draft_event_id = self._record_visible_draft_diagnostics(
                                visible_draft_event_id,
                                delta,
                                selected_model=selected_model,
                            )
                            visible_length = len(visible_text)
                    if data.get("done"):
                        break
            finally:
                finish_active_model_call(active_call_id)
        return self._clean_response(raw_text)

    def _should_use_thinking_budget(
        self,
        selected_model: str,
        selected_think: bool,
        thinking_budget: int | None,
    ) -> bool:
        return (
            selected_think
            and thinking_budget is not None
            and thinking_budget > 0
            and self.settings.model_provider == "ollama"
            and supports_qwen_thinking_budget(selected_model)
        )

    async def _generate_ollama_with_qwen_thinking_budget(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        *,
        selected_model: str,
        timeout_seconds: float | None,
        num_predict: int | None,
        thinking_budget: int | None,
        diagnostic_event_id: str,
    ) -> str:
        first_phase = await self._run_qwen_thinking_budget_phase(
            client,
            prompt,
            selected_model=selected_model,
            timeout_seconds=timeout_seconds,
            thinking_budget=thinking_budget,
            diagnostic_event_id=diagnostic_event_id,
        )
        raw_text = ""
        visible_length = 0
        visible_draft_event_id = ""
        active_call_id = start_active_model_call(
            phase=f"{current_model_diagnostic_phase()}:qwen_thinking_budget_final",
            model=selected_model,
            provider=self.settings.model_provider,
            source="qwen_thinking_budget_final_visible",
        )
        final_event_id = ""
        diagnostics = current_model_diagnostics()
        if diagnostics is not None and diagnostics.enabled:
            final_event_id = diagnostics.start_call(
                phase=f"{current_model_diagnostic_phase()}:qwen_thinking_budget_final",
                model=selected_model,
                provider=self.settings.model_provider,
                source="qwen_thinking_budget_final_visible",
            )
        try:
            async with client.stream(
                "POST",
                f"{self.settings.ollama_base_url.rstrip('/')}/api/chat",
                json=self._qwen_thinking_budget_final_payload(
                    prompt,
                    first_phase["assistant_seed"],
                    num_predict=num_predict,
                    model_name=selected_model,
                ),
                timeout=self._request_timeout(timeout_seconds),
            ) as response:
                response.raise_for_status()
                async for line in self._aiter_lines_with_watchdog(response, active_call_id):
                    if not line:
                        continue
                    data = json.loads(line)
                    if final_event_id:
                        self._record_stream_diagnostics(final_event_id, data)
                    token = self._content_from_stream_chunk(data)
                    if token:
                        raw_text += token
                        visible_text = self._visible_stream_text(raw_text)
                        delta = visible_text[visible_length:]
                        if delta:
                            visible_draft_event_id = self._record_visible_draft_diagnostics(
                                visible_draft_event_id,
                                delta,
                                selected_model=selected_model,
                                source="qwen_thinking_budget_final_visible",
                            )
                            visible_length = len(visible_text)
                    if data.get("done"):
                        break
        finally:
            finish_active_model_call(active_call_id)
            diagnostics = current_model_diagnostics()
            if diagnostics is not None and final_event_id:
                diagnostics.finish_call(final_event_id)
        final_answer = self._merge_visible_prefix_and_continuation(
            str(first_phase["visible_answer"]),
            self._clean_response(raw_text),
        )
        if final_answer:
            return final_answer
        return str(first_phase["visible_answer"])

    async def _stream_ollama_with_qwen_thinking_budget(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        *,
        selected_model: str,
        timeout_seconds: float | None,
        num_predict: int | None,
        thinking_budget: int | None,
        diagnostic_event_id: str,
    ) -> AsyncIterator[tuple[str, str]]:
        first_phase = await self._run_qwen_thinking_budget_phase(
            client,
            prompt,
            selected_model=selected_model,
            timeout_seconds=timeout_seconds,
            thinking_budget=thinking_budget,
            diagnostic_event_id=diagnostic_event_id,
        )
        if first_phase["diagnostic_appended"]:
            yield "", selected_model
        first_visible = str(first_phase["visible_answer"])

        raw_text = ""
        visible_length = 0
        visible_draft_event_id = ""
        active_call_id = start_active_model_call(
            phase=f"{current_model_diagnostic_phase()}:qwen_thinking_budget_final",
            model=selected_model,
            provider=self.settings.model_provider,
            source="qwen_thinking_budget_final_visible",
        )
        final_event_id = ""
        diagnostics = current_model_diagnostics()
        if diagnostics is not None and diagnostics.enabled:
            final_event_id = diagnostics.start_call(
                phase=f"{current_model_diagnostic_phase()}:qwen_thinking_budget_final",
                model=selected_model,
                provider=self.settings.model_provider,
                source="qwen_thinking_budget_final_visible",
            )
        try:
            async with client.stream(
                "POST",
                f"{self.settings.ollama_base_url.rstrip('/')}/api/chat",
                json=self._qwen_thinking_budget_final_payload(
                    prompt,
                    first_phase["assistant_seed"],
                    num_predict=num_predict,
                    model_name=selected_model,
                ),
                timeout=self._request_timeout(timeout_seconds),
            ) as response:
                response.raise_for_status()
                async for line in self._aiter_lines_with_watchdog(response, active_call_id):
                    if not line:
                        continue
                    data = json.loads(line)
                    diagnostic_appended = False
                    if final_event_id:
                        diagnostic_appended = self._record_stream_diagnostics(final_event_id, data)
                    token = self._content_from_stream_chunk(data)
                    if token:
                        raw_text += token
                        visible_text = self._visible_stream_text(raw_text)
                        delta = visible_text[visible_length:]
                        if delta:
                            visible_length = len(visible_text)
                            visible_draft_event_id = self._record_visible_draft_diagnostics(
                                visible_draft_event_id,
                                delta,
                                selected_model=selected_model,
                                source="qwen_thinking_budget_final_visible",
                            )
                    elif diagnostic_appended:
                        yield "", selected_model
                    if data.get("done"):
                        break
        finally:
            finish_active_model_call(active_call_id)
            diagnostics = current_model_diagnostics()
            if diagnostics is not None and final_event_id:
                diagnostics.finish_call(final_event_id)
        final_answer = self._merge_visible_prefix_and_continuation(
            first_visible,
            self._clean_response(raw_text),
        )
        if final_answer:
            if first_visible and self._clean_response(raw_text):
                self._record_visible_draft_diagnostics(
                    "",
                    final_answer,
                    selected_model=selected_model,
                    source="qwen_thinking_budget_merged_visible",
                )
            yield final_answer, selected_model

    async def _run_qwen_thinking_budget_phase(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        *,
        selected_model: str,
        timeout_seconds: float | None,
        thinking_budget: int | None,
        diagnostic_event_id: str,
    ) -> dict[str, object]:
        raw_text = ""
        structured_thinking = ""
        content_thinking_length = 0
        thinking_tokens_observed = 0
        stop_reason = "stream_done"
        visible_length = 0
        visible_draft_event_id = ""
        diagnostic_appended = False
        budget_prompt = self._qwen_thinking_budget_prompt(prompt, thinking_budget)
        active_call_id = start_active_model_call(
            phase=f"{current_model_diagnostic_phase()}:qwen_thinking_budget",
            model=selected_model,
            provider=self.settings.model_provider,
            source="qwen_thinking_budget",
        )
        try:
            async with client.stream(
                "POST",
                f"{self.settings.ollama_base_url.rstrip('/')}/api/chat",
                json=self._chat_payload(
                    budget_prompt,
                    stream=True,
                    num_predict=thinking_budget,
                    model_name=selected_model,
                    think=True,
                ),
                timeout=self._request_timeout(timeout_seconds),
            ) as response:
                response.raise_for_status()
                async for line in self._aiter_lines_with_watchdog(response, active_call_id):
                    if not line:
                        continue
                    data = json.loads(line)
                    if diagnostic_event_id:
                        diagnostic_appended = (
                            self._record_stream_diagnostics(diagnostic_event_id, data)
                            or diagnostic_appended
                        )
                    thinking = self._thinking_from_chat_response(data)
                    if thinking:
                        structured_thinking += thinking
                        thinking_tokens_observed += self._estimate_thinking_tokens(thinking)
                        self._record_thinking_budget_progress(
                            thinking_budget,
                            thinking_tokens_observed,
                            stop_reason=None,
                            progress_key=active_call_id,
                        )
                    token = self._content_from_stream_chunk(data)
                    if token:
                        raw_text += token
                        content_thinking = self._complete_or_partial_think_text(raw_text)
                        if len(content_thinking) > content_thinking_length:
                            delta_thinking = content_thinking[content_thinking_length:]
                            thinking_tokens_observed += self._estimate_thinking_tokens(delta_thinking)
                            content_thinking_length = len(content_thinking)
                            self._record_thinking_budget_progress(
                                thinking_budget,
                                thinking_tokens_observed,
                                stop_reason=None,
                                progress_key=active_call_id,
                            )
                        visible_text = self._visible_stream_text(raw_text)
                        delta = visible_text[visible_length:]
                        if delta:
                            visible_draft_event_id = self._record_visible_draft_diagnostics(
                                visible_draft_event_id,
                                delta,
                                selected_model=selected_model,
                                source="qwen_thinking_budget_initial_visible",
                            )
                            visible_length = len(visible_text)
                    thinking_closed = "</think>" in raw_text.lower() or "</think>" in structured_thinking.lower()
                    if thinking_closed:
                        stop_reason = "think_closed"
                        break
                    if thinking_budget and thinking_tokens_observed >= thinking_budget:
                        stop_reason = "budget_reached"
                        break
                    if data.get("done"):
                        break
        finally:
            finish_active_model_call(active_call_id)

        visible_answer = self._clean_response(raw_text)
        thinking_ended = "</think>" in raw_text.lower() or "</think>" in structured_thinking.lower()
        if not thinking_ended and stop_reason == "stream_done":
            stop_reason = "budget_reached" if thinking_budget else "stream_done"
        self._record_thinking_budget_progress(
            thinking_budget,
            thinking_tokens_observed,
            stop_reason=stop_reason,
            progress_key=active_call_id,
        )
        assistant_seed = self._qwen_thinking_budget_assistant_seed(
            raw_text=raw_text,
            structured_thinking=structured_thinking,
            thinking_ended=thinking_ended,
        )
        return {
            "raw_text": raw_text,
            "structured_thinking": structured_thinking,
            "visible_answer": visible_answer if thinking_ended else "",
            "assistant_seed": assistant_seed,
            "diagnostic_appended": diagnostic_appended,
            "thinking_tokens_observed": thinking_tokens_observed,
            "stop_reason": stop_reason,
        }

    async def stream_generate(
        self,
        prompt: str,
        *,
        timeout_seconds: float | None = None,
        num_predict: int | None = None,
        model_name: str | None = None,
        think: bool | None = None,
        thinking_budget: int | None = None,
    ) -> AsyncIterator[tuple[str, str]]:
        if self.settings.model_provider not in {"ollama", "llama_cpp"}:
            yield self._fallback_answer(), "fallback"
            return

        timeout = self._request_timeout(timeout_seconds)
        selected_model = (
            self._llama_cpp_model_name(model_name)
            if self.settings.model_provider == "llama_cpp"
            else model_name or self.settings.generation_model
        )
        diagnostics = current_model_diagnostics()
        diagnostic_event_id = ""
        if diagnostics is not None and diagnostics.enabled:
            diagnostic_event_id = diagnostics.start_call(
                phase=current_model_diagnostic_phase(),
                model=selected_model,
                provider=self.settings.model_provider,
            )
        active_call_id = start_active_model_call(
            phase=current_model_diagnostic_phase(),
            model=selected_model,
            provider=self.settings.model_provider,
            source="stream_generate",
        )
        raw_text = ""
        visible_length = 0
        thinking_length = 0
        visible_draft_event_id = ""
        yielded_any = False
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                selected_think = self.settings.model_think if think is None else think
                if (
                    self.settings.model_provider == "ollama"
                    and self._should_use_thinking_budget(
                        selected_model,
                        selected_think,
                        thinking_budget,
                    )
                ):
                    yielded_any = False
                    async for token, token_model in self._stream_ollama_with_qwen_thinking_budget(
                        client,
                        prompt,
                        selected_model=selected_model,
                        timeout_seconds=timeout_seconds,
                        num_predict=num_predict,
                        thinking_budget=thinking_budget,
                        diagnostic_event_id=diagnostic_event_id,
                    ):
                        if token:
                            yielded_any = True
                        yield token, token_model
                    if not yielded_any:
                        yield self._no_visible_answer(), selected_model
                    return
                url = f"{self.settings.ollama_base_url.rstrip('/')}/api/chat"
                payload = self._chat_payload(
                    prompt,
                    stream=True,
                    num_predict=num_predict,
                    model_name=model_name,
                    think=think,
                )
                if self.settings.model_provider == "llama_cpp":
                    url = f"{self.settings.llama_cpp_base_url.rstrip('/')}/v1/chat/completions"
                    payload = self._openai_chat_payload(
                        prompt,
                        stream=True,
                        num_predict=num_predict,
                        model_name=selected_model,
                        think=think,
                    )
                async with client.stream(
                    "POST",
                    url,
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in self._aiter_lines_with_watchdog(response, active_call_id):
                        if not line:
                            continue
                        diagnostic_appended = False
                        if self.settings.model_provider == "llama_cpp":
                            if not line.startswith("data:"):
                                continue
                            event = line.removeprefix("data:").strip()
                            if event == "[DONE]":
                                break
                            data = json.loads(event)
                            token = self._content_from_openai_stream_chunk(data)
                        else:
                            data = json.loads(line)
                            diagnostic_appended = False
                            if diagnostic_event_id:
                                diagnostic_appended = self._record_stream_diagnostics(diagnostic_event_id, data)
                            token = self._content_from_stream_chunk(data)
                        if token:
                            raw_text += token
                            if diagnostic_event_id:
                                thinking_text = self._partial_think_text(raw_text)
                                if len(thinking_text) > thinking_length:
                                    diagnostics = current_model_diagnostics()
                                    if diagnostics is not None:
                                        diagnostics.append(
                                            diagnostic_event_id,
                                            thinking_text[thinking_length:],
                                            source="think_block",
                                        )
                                    thinking_length = len(thinking_text)
                            visible_text = self._visible_stream_text(raw_text)
                            delta = visible_text[visible_length:]
                            if delta:
                                visible_length = len(visible_text)
                                visible_draft_event_id = self._record_visible_draft_diagnostics(
                                    visible_draft_event_id,
                                    delta,
                                    selected_model=selected_model,
                                )
                                yielded_any = True
                                yield delta, selected_model
                        elif diagnostic_appended:
                            yield "", selected_model
                        if self.settings.model_provider == "ollama" and data.get("done"):
                            break
            if not yielded_any:
                selected_think = self.settings.model_think if think is None else think
                retry_answer = ""
                if selected_think and self.settings.model_provider == "ollama":
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        retry_answer = await self._retry_ollama_visible_answer(
                            client,
                            prompt,
                            selected_model=selected_model,
                            timeout_seconds=timeout_seconds,
                            num_predict=num_predict,
                        )
                yield retry_answer or self._no_visible_answer(), selected_model
        except ModelNoProgressError:
            await release_ollama_model(self.settings, selected_model)
            yield self._no_progress_answer(), selected_model
        except Exception:
            yield self._fallback_answer(), "fallback"
        finally:
            finish_active_model_call(active_call_id)
            diagnostics = current_model_diagnostics()
            if diagnostics is not None and diagnostic_event_id:
                diagnostics.finish_call(diagnostic_event_id)

    async def _retry_ollama_visible_answer(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        *,
        selected_model: str,
        timeout_seconds: float | None,
        num_predict: int | None,
    ) -> str:
        retry_budget = self._expanded_thinking_budget(num_predict)
        candidate_prompt = self._visible_answer_recovery_prompt(prompt)
        raw_text = ""
        thinking_length = 0
        visible_length = 0
        visible_draft_event_id = ""
        diagnostics = current_model_diagnostics()
        recovery_event_id = ""
        if diagnostics is not None and diagnostics.enabled:
            recovery_event_id = diagnostics.start_call(
                phase=f"{current_model_diagnostic_phase()}:visible_answer_recovery",
                model=selected_model,
                provider=self.settings.model_provider,
                source="visible_answer_recovery_no_think",
            )
        active_call_id = start_active_model_call(
            phase=f"{current_model_diagnostic_phase()}:visible_answer_recovery",
            model=selected_model,
            provider=self.settings.model_provider,
            source="visible_answer_recovery",
        )
        try:
            async with client.stream(
                "POST",
                f"{self.settings.ollama_base_url.rstrip('/')}/api/chat",
                json=self._chat_payload(
                    candidate_prompt,
                    stream=True,
                    num_predict=retry_budget,
                    model_name=selected_model,
                    think=False,
                ),
                timeout=self._request_timeout(timeout_seconds),
            ) as response:
                response.raise_for_status()
                async for line in self._aiter_lines_with_watchdog(response, active_call_id):
                    if not line:
                        continue
                    data = json.loads(line)
                    if recovery_event_id:
                        self._record_stream_diagnostics(recovery_event_id, data)
                    token = self._content_from_stream_chunk(data)
                    if token:
                        raw_text += token
                        if recovery_event_id:
                            thinking_text = self._partial_think_text(raw_text)
                            if len(thinking_text) > thinking_length:
                                diagnostics = current_model_diagnostics()
                                if diagnostics is not None:
                                    diagnostics.append(
                                        recovery_event_id,
                                        thinking_text[thinking_length:],
                                        source="think_block",
                                    )
                                thinking_length = len(thinking_text)
                        visible_text = self._visible_stream_text(raw_text)
                        delta = visible_text[visible_length:]
                        if delta:
                            visible_draft_event_id = self._record_visible_draft_diagnostics(
                                visible_draft_event_id,
                                delta,
                                selected_model=selected_model,
                                source="visible_answer_recovery_no_think",
                            )
                            visible_length = len(visible_text)
                    if data.get("done"):
                        break
        finally:
            finish_active_model_call(active_call_id)
            diagnostics = current_model_diagnostics()
            if diagnostics is not None and recovery_event_id:
                diagnostics.finish_call(recovery_event_id)
        answer = self._clean_response(raw_text)
        if answer:
            return answer
        return ""

    def _expanded_thinking_budget(self, num_predict: int | None) -> int:
        current = num_predict or self.settings.model_num_predict
        return min(max(current * 2, self.settings.model_num_predict * 2), 8192)

    def _merge_visible_prefix_and_continuation(self, prefix: str, continuation: str) -> str:
        prefix = self._clean_response(prefix)
        continuation = self._clean_response(continuation)
        if not prefix:
            return continuation
        if not continuation:
            return prefix
        compact_prefix = _compact_visible_text(prefix)
        compact_continuation = _compact_visible_text(continuation)
        if compact_prefix and compact_prefix in compact_continuation:
            return continuation
        if compact_continuation and compact_continuation in compact_prefix:
            return prefix
        max_overlap = min(len(prefix), len(continuation))
        for size in range(max_overlap, 0, -1):
            if prefix[-size:] == continuation[:size]:
                return f"{prefix}{continuation[size:]}"
        return f"{prefix.rstrip()}{continuation.lstrip()}"

    def _qwen_thinking_budget_prompt(self, prompt: str, thinking_budget: int | None) -> str:
        if not thinking_budget or thinking_budget <= 0:
            return prompt
        return f"{prompt}{QWEN_THINKING_BUDGET_PROMPT_SUFFIX.format(budget=thinking_budget)}"

    def _record_thinking_budget_progress(
        self,
        thinking_budget: int | None,
        tokens_observed: int,
        *,
        stop_reason: str | None,
        progress_key: str | None = None,
    ) -> None:
        diagnostics = current_model_diagnostics()
        if diagnostics is not None:
            diagnostics.record_thinking_budget_progress(
                budget=thinking_budget,
                observed=tokens_observed,
                stop_reason=stop_reason,
                progress_key=progress_key,
            )

    def _estimate_thinking_tokens(self, text: str) -> int:
        """Stable local estimate for Qwen thinking budget enforcement.

        Ollama does not expose per-chunk token counts for `message.thinking`, so this intentionally
        over-counts a little for Chinese and mixed text. The budget remains approximate, but the
        first thinking phase no longer runs unbounded after the configured cap is reached.
        """

        cleaned = str(text or "")
        if not cleaned.strip():
            return 0
        tokenizer = _load_local_qwen_tokenizer()
        if tokenizer is not None:
            try:
                return max(1, len(tokenizer.encode(cleaned).ids))
            except Exception:
                pass
        cjk_count = len(CJK_RE.findall(cleaned))
        latin_units = sum(max(1, (len(item) + 3) // 4) for item in LATIN_TOKEN_RE.findall(cleaned))
        non_space_count = len(NON_SPACE_RE.findall(cleaned))
        punctuation_units = max(0, non_space_count - cjk_count) * 0.08
        return max(1, int(round(cjk_count + latin_units + punctuation_units)))

    def _visible_answer_recovery_prompt(self, prompt: str) -> str:
        return (
            "这是最终回复重试通道。只输出用户能看到的最终中文回复；"
            "请从第一句话开始，完整写出用户能看到的最终中文回复；"
            "不要只接续上一段的后半部分。不要写分析、草稿、规则、后台说明或过程说明。"
            "输出格式：FINAL_ANSWER: <最终中文回复>\n\n"
            f"原始任务如下：\n{prompt}"
        )

    def _chat_payload(
        self,
        prompt: str,
        stream: bool,
        *,
        num_predict: int | None = None,
        model_name: str | None = None,
        think: bool | None = None,
    ) -> dict:
        selected_model = model_name or self.settings.generation_model
        selected_think = self.settings.model_think if think is None else think
        payload = {
            "model": selected_model,
            "messages": [
                {"role": "system", "content": RAG_SYSTEM_MESSAGE},
                {"role": "user", "content": self._prompt_for_model(prompt, selected_model, selected_think)},
            ],
            "stream": stream,
            "keep_alive": self.settings.model_keep_alive,
        }
        if should_send_ollama_think(selected_model, selected_think):
            payload["think"] = selected_think
        options: dict[str, float | int] = {
            "num_predict": num_predict or self.settings.model_num_predict,
            "temperature": self.settings.model_temperature,
            "top_p": self.settings.model_top_p,
        }
        payload["options"] = options
        return payload

    def _chat_payload_from_messages(
        self,
        messages: list[dict[str, str]],
        stream: bool,
        *,
        num_predict: int | None = None,
        model_name: str | None = None,
        think: bool | None = None,
    ) -> dict:
        selected_model = model_name or self.settings.generation_model
        selected_think = self.settings.model_think if think is None else think
        payload = {
            "model": selected_model,
            "messages": messages,
            "stream": stream,
            "keep_alive": self.settings.model_keep_alive,
        }
        if should_send_ollama_think(selected_model, selected_think):
            payload["think"] = selected_think
        payload["options"] = {
            "num_predict": num_predict or self.settings.model_num_predict,
            "temperature": self.settings.model_temperature,
            "top_p": self.settings.model_top_p,
        }
        return payload

    def _qwen_thinking_budget_final_payload(
        self,
        prompt: str,
        assistant_seed: str,
        *,
        num_predict: int | None = None,
        model_name: str | None = None,
    ) -> dict:
        selected_model = model_name or self.settings.generation_model
        return self._chat_payload_from_messages(
            [
                {"role": "system", "content": RAG_SYSTEM_MESSAGE},
                {"role": "user", "content": self._prompt_for_model(prompt, selected_model, True)},
                {"role": "assistant", "content": assistant_seed},
                {"role": "user", "content": QWEN_THINKING_FINAL_PROMPT},
            ],
            stream=True,
            num_predict=num_predict,
            model_name=selected_model,
            think=False,
        )

    def _qwen_thinking_budget_assistant_seed(
        self,
        *,
        raw_text: str,
        structured_thinking: str,
        thinking_ended: bool,
    ) -> str:
        if thinking_ended and raw_text.strip():
            return raw_text
        seed = structured_thinking.strip() or self._complete_or_partial_think_text(raw_text).strip()
        if not seed:
            seed = raw_text.strip()
        if "<think>" in raw_text.lower():
            return f"{raw_text.rstrip()}\n\n{QWEN_THINKING_EARLY_STOP_TEXT}\n</think>\n"
        return f"<think>\n{seed}\n\n{QWEN_THINKING_EARLY_STOP_TEXT}\n</think>\n"

    def _openai_chat_payload(
        self,
        prompt: str,
        stream: bool,
        *,
        num_predict: int | None = None,
        model_name: str | None = None,
        think: bool | None = None,
    ) -> dict:
        selected_model = self._llama_cpp_model_name(model_name)
        selected_think = self.settings.model_think if think is None else think
        return {
            "model": selected_model,
            "messages": [
                {"role": "system", "content": RAG_SYSTEM_MESSAGE},
                {"role": "user", "content": self._prompt_for_model(prompt, selected_model, selected_think)},
            ],
            "stream": stream,
            "max_tokens": num_predict or self.settings.model_num_predict,
            "temperature": self.settings.model_temperature,
            "top_p": self.settings.model_top_p,
        }

    def _llama_cpp_model_name(self, model_name: str | None = None) -> str:
        return model_name or self.settings.llama_cpp_model or self.settings.generation_model

    def _request_timeout(self, timeout_seconds: float | None = None) -> httpx.Timeout:
        return httpx.Timeout(timeout_seconds or self.settings.model_timeout_seconds, connect=10.0)

    async def _aiter_lines_with_watchdog(
        self,
        response: httpx.Response,
        active_call_id: str,
    ) -> AsyncIterator[str]:
        line_iterator = response.aiter_lines().__aiter__()
        while True:
            try:
                line = await asyncio.wait_for(
                    line_iterator.__anext__(),
                    timeout=MODEL_NO_PROGRESS_TIMEOUT_SECONDS,
                )
            except StopAsyncIteration:
                return
            except TimeoutError as exc:
                raise ModelNoProgressError(
                    f"local model produced no stream progress for {MODEL_NO_PROGRESS_TIMEOUT_SECONDS:g}s"
                ) from exc
            touch_active_model_call(active_call_id)
            yield line

    def _prompt_for_model(self, prompt: str, model_name: str | None = None, think: bool | None = None) -> str:
        model = (model_name or self.settings.generation_model).lower()
        selected_think = self.settings.model_think if think is None else think
        if (
            (model.startswith("qwen3:") or model.startswith("qwen3-") or model.startswith("qwen3.5"))
            and "instruct" not in model
            and not selected_think
        ):
            return f"/no_think\n\n{prompt}"
        return prompt

    def _content_from_chat_response(self, data: dict) -> str:
        message = data.get("message")
        if isinstance(message, dict):
            return self._clean_response(str(message.get("content", "")))
        return self._clean_response(str(data.get("response", "")))

    def _content_from_stream_chunk(self, data: dict) -> str:
        message = data.get("message")
        if isinstance(message, dict):
            return str(message.get("content", "") or "")
        return str(data.get("response", "") or "")

    def _content_from_openai_chat_response(self, data: dict) -> str:
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict):
                return self._clean_response(str(message.get("content", "")))
        return ""

    def _content_from_openai_stream_chunk(self, data: dict) -> str:
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
            if isinstance(delta, dict):
                return str(delta.get("content", "") or "")
        return ""

    def _record_response_diagnostics(self, event_id: str, data: dict) -> None:
        diagnostics = current_model_diagnostics()
        if diagnostics is None or not diagnostics.enabled:
            return
        thinking = self._thinking_from_chat_response(data)
        if thinking:
            diagnostics.replace(event_id, thinking, source="message.thinking")
            return
        content = self._raw_content_from_chat_response(data)
        think_text = self._complete_or_partial_think_text(content)
        if think_text:
            diagnostics.replace(event_id, think_text, source="think_block")

    def _record_stream_diagnostics(self, event_id: str, data: dict) -> bool:
        diagnostics = current_model_diagnostics()
        if diagnostics is None or not diagnostics.enabled:
            return False
        message = data.get("message")
        if isinstance(message, dict):
            thinking = message.get("thinking")
            if isinstance(thinking, str) and thinking:
                diagnostics.append(event_id, thinking, source="message.thinking")
                return True
        return False

    def _record_visible_draft_diagnostics(
        self,
        event_id: str,
        delta: str,
        *,
        selected_model: str,
        source: str = "visible_draft",
    ) -> str:
        diagnostics = current_model_diagnostics()
        if diagnostics is None or not diagnostics.enabled or not delta:
            return event_id
        phase = current_model_diagnostic_phase()
        diagnostics.record_visible_answer_source(
            phase=phase,
            model=selected_model,
            source=source,
            text=delta,
        )
        active_event_id = event_id or diagnostics.start_call(
            phase=f"{phase}:visible_draft",
            model=selected_model,
            provider=self.settings.model_provider,
            source=source,
        )
        diagnostics.append(active_event_id, delta, source=source)
        return active_event_id

    def _thinking_from_chat_response(self, data: dict) -> str:
        message = data.get("message")
        if isinstance(message, dict):
            thinking = message.get("thinking")
            if isinstance(thinking, str):
                return thinking
        return ""

    def _raw_content_from_chat_response(self, data: dict) -> str:
        message = data.get("message")
        if isinstance(message, dict):
            return str(message.get("content", "") or "")
        return str(data.get("response", "") or "")

    def _complete_or_partial_think_text(self, text: str) -> str:
        complete = THINK_BLOCK_RE.findall(text)
        if complete:
            return "\n\n".join(
                re.sub(r"</?think>", "", block, flags=re.IGNORECASE).strip()
                for block in complete
            ).strip()
        return self._partial_think_text(text)

    def _partial_think_text(self, text: str) -> str:
        lower = text.lower()
        start = lower.rfind("<think>")
        if start < 0:
            return ""
        end = lower.find("</think>", start)
        content_start = start + len("<think>")
        if end >= 0:
            return text[content_start:end]
        return text[content_start:]

    def _clean_response(self, text: str) -> str:
        return self._visible_stream_text(text, force=True).strip()

    def _visible_stream_text(self, text: str, force: bool = False) -> str:
        lower = text.lower()
        if "<think>" in lower and "</think>" not in lower and not force:
            return ""
        if SCRATCHPAD_PREAMBLE_RE.search(text) and "</think>" not in lower and not force:
            return ""

        cleaned = THINK_BLOCK_RE.sub("", text)
        if "</think>" in cleaned.lower():
            cleaned = re.split(r"</think>", cleaned, flags=re.IGNORECASE)[-1]
        elif "<think>" in cleaned.lower():
            cleaned = re.split(r"<think>", cleaned, flags=re.IGNORECASE)[0]
        return FINAL_MARKER_RE.sub("", cleaned, count=1).lstrip()

    def _no_visible_answer(self) -> str:
        return "这轮没有生成出可见回复。请重试一次，或先切到低一点的思考强度。"

    def _no_progress_answer(self) -> str:
        return (
            "本地模型超过 45 秒没有产生新的可观察进展，系统已中断并尝试释放模型。"
            "请缩短问题、降低努力程度，或稍后重试。"
        )

    def _fallback_answer(self) -> str:
        return (
            "本地模型服务尚未连接。后端已经完成相关档案检索，并返回这个兜底回答，"
            "以便测试界面和检索轨迹。"
        )
