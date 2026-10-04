"""Trace recorder for capturing every agent invocation in the discovery loop."""

from __future__ import annotations

from typing import Any

from .types import ExecutionTraceItem, content_id


class TraceRecorder:
    """Maintains an auditable, deterministic execution trace of all agent calls."""

    def __init__(self) -> None:
        self._trace: list[ExecutionTraceItem] = []
        self._seq: int = 0

    def record_start(
        self,
        iteration: int,
        agent: str,
        routing_reason: str,
        input_ids: list[str] | None = None,
    ) -> str:
        """Create a placeholder trace item returning its trace_id."""
        self._seq += 1
        trace_id = content_id(
            "run",
            {"seq": self._seq, "iteration": iteration, "agent": agent},
        )
        item = ExecutionTraceItem(
            trace_id=trace_id,
            iteration=iteration,
            agent=agent,
            input_ids=list(input_ids or []),
            output_ids=[],
            routing_reason=routing_reason,
            status="success",
            error=None,
        )
        self._trace.append(item)
        return trace_id

    def record_success(
        self,
        trace_id: str,
        output_ids: list[str] | None = None,
    ) -> None:
        """Mark an ongoing invocation as successful with emitted output IDs."""
        for item in self._trace:
            if item.trace_id == trace_id:
                item.status = "success"
                item.output_ids = list(output_ids or [])
                return

    def record_failure(
        self,
        trace_id: str,
        error: str,
    ) -> None:
        """Mark an ongoing invocation as failed with a sanitized error message."""
        for item in self._trace:
            if item.trace_id == trace_id:
                item.status = "failure"
                item.error = str(error)
                return

    def record_skipped(
        self,
        iteration: int,
        agent: str,
        reason: str,
    ) -> str:
        """Record a skipped step."""
        self._seq += 1
        trace_id = content_id(
            "run",
            {"seq": self._seq, "iteration": iteration, "agent": agent, "skipped": True},
        )
        item = ExecutionTraceItem(
            trace_id=trace_id,
            iteration=iteration,
            agent=agent,
            input_ids=[],
            output_ids=[],
            routing_reason=reason,
            status="skipped",
            error=None,
        )
        self._trace.append(item)
        return trace_id

    def all_items(self) -> list[ExecutionTraceItem]:
        """Return a copy of all trace items."""
        return list(self._trace)

    def to_dicts(self) -> list[dict[str, Any]]:
        """Return JSON-serializable list of trace records."""
        return [item.model_dump(exclude_none=False) for item in self._trace]
