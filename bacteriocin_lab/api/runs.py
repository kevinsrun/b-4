"""In-process registry of discovery runs.

A run is :func:`bacteriocin_lab.orchestration.run_discovery` executed on a
worker thread with its registry wrapped by :mod:`.observe`. This module holds
the event log, the most recent state snapshot and the final ``DiscoveryResult``
for each run, and answers questions about them. It decides nothing about the
science and rewrites nothing the loop produced.

Runs live in memory for the lifetime of the server process: the durable record
of a campaign is the knowledge agent's event-log store, not this.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from bacteriocin_lab.orchestration import AgentRegistry, run_discovery

from .observe import EventLog, observed_registry

#: Guardrails on what a web client may ask for, so one request cannot occupy
#: the process indefinitely. The loop's own limits are unchanged.
MAX_ITERATIONS_LIMIT = 12
MAX_CONCURRENT_RUNS = 4

_LIST_FIELDS = (
    "candidates",
    "hypotheses",
    "experiments",
    "results",
    "findings",
    "reviews",
    "scientific_history",
    "tested_candidate_ids",
    "settled_candidate_ids",
    "knowledge_gaps",
    "uncertainties",
)


def state_digest(state: dict[str, Any]) -> dict[str, Any]:
    """Counts only, so a stream event stays small while the full state is fetched once."""
    digest: dict[str, Any] = {
        key: len(state.get(key) or ()) for key in _LIST_FIELDS
    }
    digest["iteration"] = state.get("iteration", 0)
    return digest


@dataclass
class RunRecord:
    run_id: str
    request: dict[str, Any]
    status: str = "running"
    events: EventLog = field(default_factory=EventLog)
    state: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    engine_run_id: str | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "engine_run_id": self.engine_run_id,
            "status": self.status,
            "request": self.request,
            "digest": state_digest(self.state),
            "n_events": len(self.events),
            "error": self.error,
            # The loop's own classification of how it ended, kept distinct from
            # ``status``, which also covers "still running".
            "engine_status": (self.result or {}).get("status"),
            "summary": (self.result or {}).get("summary") or {},
            "errors": (self.result or {}).get("errors") or [],
        }


class RunManager:
    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    # -- queries -------------------------------------------------------
    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._runs.get(run_id)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            records = [self._runs[r] for r in reversed(self._order)]
        return [r.summary() for r in records]

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for r in self._runs.values() if r.status == "running")

    # -- execution -----------------------------------------------------
    def start(self, request: dict[str, Any]) -> RunRecord:
        if self.active_count() >= MAX_CONCURRENT_RUNS:
            raise RuntimeError(
                f"{MAX_CONCURRENT_RUNS} runs are already in flight; wait for one to finish"
            )
        record = RunRecord(run_id=uuid.uuid4().hex[:12], request=request)
        with self._lock:
            self._runs[record.run_id] = record
            self._order.append(record.run_id)
        threading.Thread(target=self._execute, args=(record,), daemon=True).start()
        return record

    def _sink(self, record: RunRecord):
        def sink(event: dict[str, Any]) -> None:
            # The full state travels once, into the record; the stream carries counts.
            state = event.pop("state", None)
            if isinstance(state, dict) and state:
                record.state = state
                event["digest"] = state_digest(state)
            record.events.append(event)

        return sink

    def _execute(self, record: RunRecord) -> None:
        req = record.request
        sink = self._sink(record)
        record.events.append({"type": "run_started", "request": req})
        try:
            registry = observed_registry(AgentRegistry.default(), sink)
            result = run_discovery(
                objective={
                    "goal": req["goal"],
                    "target": req["target"],
                    "desired_behavior": req["desired_behavior"],
                    "constraints": req["constraints"],
                },
                max_iterations=req["max_iterations"],
                max_failures=req["max_failures"],
                seed=req["seed"],
                registry=registry,
            )
        except Exception as exc:  # the engine isolates agent failures; this is the engine itself
            record.status = "error"
            record.error = f"{type(exc).__name__}: {exc}"
            record.events.append({"type": "run_failed", "error": record.error})
            return

        payload = result.to_dict()
        record.result = payload
        record.state = payload["final_state"]
        record.engine_run_id = payload["run_id"]
        record.status = "finished"
        record.events.append(
            {
                "type": "run_finished",
                "engine_run_id": payload["run_id"],
                "engine_status": payload["status"],
                "iterations_completed": payload["iterations_completed"],
                "errors": payload["errors"],
                "summary": payload["summary"],
                "digest": state_digest(record.state),
            }
        )
