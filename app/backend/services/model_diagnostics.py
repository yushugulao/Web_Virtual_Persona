from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from app.backend.schemas.chat import ChatDiagnostics, HiddenThinkingEvent, VisibleAnswerSource


_current_collector: ContextVar["ModelDiagnosticsCollector | None"] = ContextVar(
    "persona_rag_model_diagnostics",
    default=None,
)
_current_phase: ContextVar[str] = ContextVar("persona_rag_model_diagnostic_phase", default="model_call")
_active_model_calls: dict[str, "_ActiveModelCall"] = {}


@dataclass(slots=True)
class _ActiveModelCall:
    call_id: str
    phase: str
    model: str
    provider: str
    source: str
    started_at: float
    last_event_at: float

    def to_snapshot(self) -> dict:
        now = time.perf_counter()
        return {
            "call_id": self.call_id,
            "phase": self.phase,
            "model": self.model,
            "provider": self.provider,
            "source": self.source,
            "elapsed_ms": round((now - self.started_at) * 1000, 2),
            "last_event_age_ms": round((now - self.last_event_at) * 1000, 2),
        }


@dataclass(slots=True)
class _MutableThinkingEvent:
    event_id: str
    phase: str
    model: str
    provider: str
    source: str
    content: str
    started_at: float
    updated_at: float
    sequence: int

    def to_schema(self) -> HiddenThinkingEvent:
        return HiddenThinkingEvent(
            event_id=self.event_id,
            phase=self.phase,
            model=self.model,
            provider=self.provider,
            source=self.source,
            content=self.content,
            elapsed_ms=round((self.updated_at - self.started_at) * 1000, 2),
            sequence=self.sequence,
        )


@dataclass(slots=True)
class _MutableVisibleAnswerSource:
    phase: str
    model: str
    source: str
    content: str
    started_at: float
    updated_at: float

    def append(self, text: str) -> None:
        self.content += text
        self.updated_at = time.perf_counter()

    def to_schema(self) -> VisibleAnswerSource:
        preview = " ".join(self.content.strip().split())
        if len(preview) > 180:
            preview = preview[:179].rstrip() + "…"
        return VisibleAnswerSource(
            phase=self.phase,
            model=self.model,
            source=self.source,
            preview=preview,
            elapsed_ms=round((self.updated_at - self.started_at) * 1000, 2),
        )


class ModelDiagnosticsCollector:
    """Per-request role-gated hidden-thinking collector.

    This collector intentionally stores only model-returned hidden thinking. It does not collect
    prompts, system messages, developer instructions, secrets, retrieved context, or citations.
    """

    def __init__(self, *, enabled: bool, live_stream: bool = False, include_hidden: bool = True) -> None:
        self.enabled = enabled
        self.live_stream = live_stream
        self.include_hidden = include_hidden
        self._events: list[_MutableThinkingEvent] = []
        self._events_by_id: dict[str, _MutableThinkingEvent] = {}
        self._visible_sources: list[_MutableVisibleAnswerSource] = []
        self._visible_sources_by_key: dict[tuple[str, str, str], _MutableVisibleAnswerSource] = {}
        self._final_answer_source: str | None = None
        self._thinking_budget: int | None = None
        self._thinking_tokens_observed: int | None = None
        self._thinking_budget_stop_reason: str | None = None
        self._thinking_budget_overshoot_tokens: int | None = None
        self._thinking_budget_by_call: dict[str, int] = {}
        self._thinking_tokens_by_call: dict[str, int] = {}
        self._queue: asyncio.Queue[dict] | None = asyncio.Queue() if enabled and live_stream else None
        self._sequence = 0

    def start_call(self, *, phase: str, model: str, provider: str, source: str = "message.thinking") -> str:
        if not self.enabled or not self.include_hidden:
            return ""
        self._sequence += 1
        event_id = str(uuid.uuid4())
        now = time.perf_counter()
        event = _MutableThinkingEvent(
            event_id=event_id,
            phase=phase or "model_call",
            model=model or "unknown",
            provider=provider or "unknown",
            source=source,
            content="",
            started_at=now,
            updated_at=now,
            sequence=self._sequence,
        )
        self._events.append(event)
        self._events_by_id[event_id] = event
        self._emit_status(
            kind="phase_started",
            event_id=event_id,
            phase=event.phase,
            model=event.model,
            provider=event.provider,
            source=event.source,
            delta=f"{event.phase} started",
            started_at=event.started_at,
            sequence=event.sequence,
        )
        return event_id

    def append(self, event_id: str, text: str, *, source: str | None = None) -> None:
        if not self.enabled or not self.include_hidden or not event_id or not text:
            return
        event = self._events_by_id.get(event_id)
        if event is None:
            return
        event.content += text
        if source:
            event.source = source
        event.updated_at = time.perf_counter()
        self._emit_delta(event, text)

    def replace(self, event_id: str, text: str, *, source: str | None = None) -> None:
        if not self.enabled or not self.include_hidden or not event_id or not text:
            return
        event = self._events_by_id.get(event_id)
        if event is None:
            return
        delta = text if not event.content else text[len(event.content) :]
        event.content = text
        if source:
            event.source = source
        event.updated_at = time.perf_counter()
        self._emit_delta(event, delta or text)

    def finish_call(self, event_id: str) -> None:
        if not self.enabled or not self.include_hidden or not event_id:
            return
        event = self._events_by_id.get(event_id)
        if event is not None:
            event.updated_at = time.perf_counter()
            self._emit_status(
                kind="phase_finished",
                event_id=event_id,
                phase=event.phase,
                model=event.model,
                provider=event.provider,
                source=event.source,
                delta=f"{event.phase} finished",
                started_at=event.started_at,
                sequence=event.sequence,
            )

    def emit_heartbeat(self, snapshot: dict) -> None:
        if not self.enabled or not self.include_hidden or self._queue is None or not snapshot:
            return
        self._queue.put_nowait(
            {
                "kind": "heartbeat",
                "event_id": f"heartbeat:{snapshot.get('call_id', 'model')}",
                "phase": str(snapshot.get("phase") or "model_call"),
                "model": str(snapshot.get("model") or "unknown"),
                "provider": str(snapshot.get("provider") or "unknown"),
                "source": "runtime_heartbeat",
                "delta": (
                    f"{snapshot.get('phase') or 'model_call'} still running; "
                    f"last model event {round(float(snapshot.get('last_event_age_ms') or 0) / 1000, 1)}s ago"
                ),
                "elapsed_ms": float(snapshot.get("elapsed_ms") or 0.0),
                "sequence": self._sequence + 1,
            }
        )

    def record_visible_answer_source(
        self,
        *,
        phase: str,
        model: str,
        source: str,
        text: str,
    ) -> None:
        if not self.enabled or not self.include_hidden or not text:
            return
        key = (phase or "model_call", model or "unknown", source or "visible")
        item = self._visible_sources_by_key.get(key)
        if item is None:
            now = time.perf_counter()
            item = _MutableVisibleAnswerSource(
                phase=key[0],
                model=key[1],
                source=key[2],
                content="",
                started_at=now,
                updated_at=now,
            )
            self._visible_sources_by_key[key] = item
            self._visible_sources.append(item)
        item.append(text)

    def mark_final_answer_source(self, source: str) -> None:
        if not self.enabled or not self.include_hidden or not source:
            return
        self._final_answer_source = source
        self._emit_status(
            kind="final_answer_selected",
            event_id=f"final:{source}",
            phase=source,
            model="runtime",
            provider="persona_rag",
            source="final_answer_source",
            delta=f"final answer selected from {source}",
            started_at=time.perf_counter(),
            sequence=self._sequence + 1,
        )

    def record_thinking_budget_progress(
        self,
        *,
        budget: int | None,
        observed: int,
        stop_reason: str | None = None,
        progress_key: str | None = None,
    ) -> None:
        if not self.enabled or not budget or budget <= 0:
            return
        safe_observed = max(0, int(observed))
        key = progress_key or current_model_diagnostic_phase() or "model_call"
        self._thinking_budget_by_call[key] = int(budget)
        self._thinking_tokens_by_call[key] = safe_observed
        self._thinking_budget = sum(self._thinking_budget_by_call.values())
        self._thinking_tokens_observed = sum(self._thinking_tokens_by_call.values())
        if stop_reason:
            self._thinking_budget_stop_reason = stop_reason
        self._thinking_budget_overshoot_tokens = max(
            0,
            int(self._thinking_tokens_observed or 0) - int(self._thinking_budget or 0),
        )
        if self._queue is not None:
            ratio = (
                (self._thinking_tokens_observed / self._thinking_budget)
                if self._thinking_budget
                else 0.0
            )
            self._queue.put_nowait(
                {
                    "kind": "thinking_budget_progress",
                    "event_id": "thinking-budget-progress",
                    "phase": current_model_diagnostic_phase(),
                    "model": "runtime",
                    "provider": "persona_rag",
                    "source": stop_reason or "thinking_budget_progress",
                    "delta": "",
                    "elapsed_ms": 0.0,
                    "sequence": self._sequence + 1,
                    "thinking_budget": self._thinking_budget,
                    "thinking_tokens_observed": self._thinking_tokens_observed,
                    "thinking_budget_ratio": ratio,
                    "thinking_budget_stop_reason": stop_reason,
                    "thinking_budget_overshoot_tokens": self._thinking_budget_overshoot_tokens,
                }
            )

    def infer_final_answer_source(self, answer: str, default: str) -> str:
        """Best-effort mapping from the final visible answer back to its visible channel."""

        if not self.include_hidden:
            return default
        matched = self.find_visible_answer_source(answer)
        return matched or default

    def find_visible_answer_source(self, answer: str) -> str | None:
        """Return the visible source whose text matches the final answer, if one exists."""

        if not self.include_hidden:
            return None
        answer_normalized = _compact_text(answer)
        if not answer_normalized:
            return None
        for item in reversed(self._visible_sources):
            source_normalized = _compact_text(item.content)
            if not source_normalized:
                continue
            if answer_normalized in source_normalized or source_normalized in answer_normalized:
                return f"{item.phase}:{item.source}"
        return None

    def ensure_final_answer_visible_source(self, answer: str, *, model: str = "runtime") -> str:
        """Ensure diagnostics include a visible source whose preview matches the product answer."""

        if not self.include_hidden:
            return "final_answer:final_response_visible"
        matched = self.find_visible_answer_source(answer)
        if matched:
            return matched
        self.record_visible_answer_source(
            phase="final_answer",
            model=model or "runtime",
            source="final_response_visible",
            text=answer,
        )
        return "final_answer:final_response_visible"

    async def next_live_payload(self, timeout_seconds: float = 0.15) -> dict | None:
        if self._queue is None:
            return None
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout_seconds)
        except TimeoutError:
            return None

    def drain_live_payloads(self) -> list[dict]:
        if self._queue is None:
            return []
        drained: list[dict] = []
        while True:
            try:
                drained.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                return drained

    def to_diagnostics(self) -> ChatDiagnostics | None:
        if not self.enabled:
            return None
        if not self.include_hidden:
            if self._thinking_budget is None and self._thinking_tokens_observed is None:
                return None
            return ChatDiagnostics(
                enabled=False,
                hidden_thinking_events=[],
                visible_answer_sources=[],
                thinking_budget=self._thinking_budget,
                thinking_tokens_observed=self._thinking_tokens_observed,
                thinking_budget_ratio=(
                    self._thinking_tokens_observed / self._thinking_budget
                    if self._thinking_budget and self._thinking_tokens_observed is not None
                    else None
                ),
                thinking_budget_stop_reason=self._thinking_budget_stop_reason,
                thinking_budget_overshoot_tokens=self._thinking_budget_overshoot_tokens,
            )
        events = [event.to_schema() for event in self._events if event.content.strip()]
        visible_sources = [item.to_schema() for item in self._visible_sources if item.content.strip()]
        return ChatDiagnostics(
            enabled=True,
            hidden_thinking_events=events,
            final_answer_source=self._final_answer_source,
            visible_answer_sources=visible_sources,
            thinking_budget=self._thinking_budget,
            thinking_tokens_observed=self._thinking_tokens_observed,
            thinking_budget_ratio=(
                self._thinking_tokens_observed / self._thinking_budget
                if self._thinking_budget and self._thinking_tokens_observed is not None
                else None
            ),
            thinking_budget_stop_reason=self._thinking_budget_stop_reason,
            thinking_budget_overshoot_tokens=self._thinking_budget_overshoot_tokens,
        )

    def _emit_delta(self, event: _MutableThinkingEvent, delta: str) -> None:
        if self._queue is None or not delta:
            return
        self._queue.put_nowait(
            {
                "kind": "hidden_thinking_delta",
                "event_id": event.event_id,
                "phase": event.phase,
                "model": event.model,
                "provider": event.provider,
                "source": event.source,
                "delta": delta,
                "elapsed_ms": round((event.updated_at - event.started_at) * 1000, 2),
                "sequence": event.sequence,
            }
        )

    def _emit_status(
        self,
        *,
        kind: str,
        event_id: str,
        phase: str,
        model: str,
        provider: str,
        source: str,
        delta: str,
        started_at: float,
        sequence: int,
    ) -> None:
        if self._queue is None:
            return
        self._queue.put_nowait(
            {
                "kind": kind,
                "event_id": event_id,
                "phase": phase,
                "model": model,
                "provider": provider,
                "source": source,
                "delta": delta,
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "sequence": sequence,
            }
        )


def current_model_diagnostics() -> ModelDiagnosticsCollector | None:
    return _current_collector.get()


def _compact_text(text: str) -> str:
    return "".join(str(text or "").split())


def current_model_diagnostic_phase() -> str:
    return _current_phase.get()


def start_active_model_call(*, phase: str, model: str, provider: str, source: str) -> str:
    call_id = str(uuid.uuid4())
    now = time.perf_counter()
    _active_model_calls[call_id] = _ActiveModelCall(
        call_id=call_id,
        phase=phase or "model_call",
        model=model or "unknown",
        provider=provider or "unknown",
        source=source or "model_call",
        started_at=now,
        last_event_at=now,
    )
    return call_id


def touch_active_model_call(call_id: str) -> None:
    call = _active_model_calls.get(call_id)
    if call is not None:
        call.last_event_at = time.perf_counter()


def finish_active_model_call(call_id: str) -> None:
    if call_id:
        _active_model_calls.pop(call_id, None)


def active_generation_snapshot() -> dict | None:
    if not _active_model_calls:
        return None
    latest = max(_active_model_calls.values(), key=lambda item: item.started_at)
    return latest.to_snapshot()


@contextmanager
def model_diagnostics_scope(collector: ModelDiagnosticsCollector | None) -> Iterator[None]:
    token = _current_collector.set(collector)
    try:
        yield
    finally:
        _current_collector.reset(token)


@contextmanager
def model_diagnostic_phase(phase: str) -> Iterator[None]:
    token = _current_phase.set(phase)
    try:
        yield
    finally:
        _current_phase.reset(token)
