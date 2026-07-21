from __future__ import annotations

from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from time import perf_counter
from uuid import uuid4


@dataclass(frozen=True)
class TraceSpan:
    trace_id: str
    span_id: str
    name: str
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    parent_span_id: str | None = None
    span_kind: str = "internal"
    ended_at: str | None = None
    duration_ms: int = 0
    error_code: str = ""


class TraceRecorder:
    """Small in-process trace recorder.

    Production can replace this with Langfuse while keeping the call sites stable.
    """

    def __init__(self) -> None:
        self._default_trace_id = self._new_trace_id()
        self._trace_id: ContextVar[str] = ContextVar("smart_data_agent_trace_id", default=self._default_trace_id)
        self._spans: ContextVar[list[TraceSpan] | None] = ContextVar("smart_data_agent_trace_spans", default=None)
        self._active_span_id: ContextVar[str | None] = ContextVar("smart_data_agent_active_span_id", default=None)
        self._span_sequence: ContextVar[int] = ContextVar("smart_data_agent_span_sequence", default=0)

    @property
    def trace_id(self) -> str:
        return self._trace_id.get()

    @trace_id.setter
    def trace_id(self, value: str) -> None:
        self._trace_id.set(value)

    def start_trace(self) -> str:
        trace_id = self._new_trace_id()
        self._trace_id.set(trace_id)
        self._spans.set([])
        self._span_sequence.set(0)
        return trace_id

    def add_span(
        self,
        name: str,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        status: str = "ok",
        parent_span_id: str | None = None,
        duration_ms: int = 0,
        error_code: str = "",
    ) -> TraceSpan:
        spans = self._current_spans()
        span = TraceSpan(
            trace_id=self.trace_id,
            span_id=self._next_span_id(),
            name=name,
            inputs=inputs or {},
            outputs=outputs or {},
            status=status,
            parent_span_id=parent_span_id if parent_span_id is not None else self._active_span_id.get(),
            ended_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=max(0, int(duration_ms)),
            error_code=str(error_code or "")[:100],
        )
        spans.append(span)
        return span

    @contextmanager
    def span(self, name: str, inputs: dict[str, Any] | None = None):
        parent_span_id = self._active_span_id.get()
        span_id = self._next_span_id()
        token = self._active_span_id.set(span_id)
        started = perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        outputs: dict[str, Any] = {}
        status = "ok"
        error_code = ""
        try:
            yield outputs
        except Exception as exc:
            status = "error"
            error_code = type(exc).__name__[:100]
            raise
        finally:
            ended_at = datetime.now(timezone.utc).isoformat()
            self._current_spans().append(
                TraceSpan(
                    trace_id=self.trace_id,
                    span_id=span_id,
                    name=name,
                    inputs=inputs or {},
                    outputs=outputs,
                    status=status,
                    created_at=started_at,
                    parent_span_id=parent_span_id,
                    ended_at=ended_at,
                    duration_ms=max(0, round((perf_counter() - started) * 1000)),
                    error_code=error_code,
                )
            )
            self._active_span_id.reset(token)

    def spans(self) -> list[TraceSpan]:
        return list(self._current_spans())

    def _current_spans(self) -> list[TraceSpan]:
        spans = self._spans.get()
        if spans is None:
            spans = []
            self._spans.set(spans)
        return spans

    @staticmethod
    def _new_trace_id() -> str:
        return f"trace_{uuid4().hex[:12]}"

    def _next_span_id(self) -> str:
        sequence = self._span_sequence.get() + 1
        self._span_sequence.set(sequence)
        return f"span_{sequence:04d}"
