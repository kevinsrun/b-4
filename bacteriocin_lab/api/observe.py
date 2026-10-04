"""Observe a discovery run step by step, without changing how it runs.

The workflow engine has no observer hook and returns its trace only when the
run is over, which is no use to a live view. Rather than reach into the engine,
this wraps each agent in the registry with a proxy that delegates ``run(state)``
untouched and reports what happened around the call.

What is reported is taken from the run, never composed here:

* the agent that was dispatched and the iteration it ran in;
* the ``output_ids`` the agent itself returned;
* the entries the engine appended to ``state.scientific_history`` -- the loop's
  own audit log, with its own summaries;
* the exception text, if the agent raised.

The engine reverts to a pre-dispatch snapshot when an agent fails, so a failure
emits no state: the state the proxy can still see at that moment is the one the
engine is about to discard.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

Sink = Callable[[dict[str, Any]], None]

#: The roles the engine dispatches, in the order the loop visits them.
ROLES = ("evidence", "candidate", "planner", "simulation", "analysis", "critic", "knowledge")


class ObservedAgent:
    """Delegates to one specialist and reports the call to a sink."""

    def __init__(self, role: str, inner: Any, sink: Sink) -> None:
        self.role = role
        self._inner = inner
        self._sink = sink
        # Some engine code reads ``agent.name``; keep whatever the real agent exposes.
        self.name = getattr(inner, "name", role)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._inner, item)

    def run(self, state: Any) -> dict[str, Any]:
        history_before = len(getattr(state, "scientific_history", ()) or ())
        iteration = getattr(state, "iteration", 0)
        started = time.time()
        self._sink(
            {
                "type": "agent_started",
                "agent": self.role,
                "iteration": iteration,
            }
        )
        try:
            payload = self._inner.run(state)
        except Exception as exc:
            self._sink(
                {
                    "type": "agent_failed",
                    "agent": self.role,
                    "iteration": iteration,
                    "duration_ms": round((time.time() - started) * 1000, 1),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            raise
        history = getattr(state, "scientific_history", ()) or ()
        self._sink(
            {
                "type": "agent_finished",
                "agent": self.role,
                "iteration": iteration,
                "duration_ms": round((time.time() - started) * 1000, 1),
                "output_ids": list(payload.get("output_ids", []))
                if isinstance(payload, dict)
                else [],
                "events": [_event_dict(e) for e in history[history_before:]],
                "state": _state_dict(state),
            }
        )
        return payload


def _event_dict(event: Any) -> dict[str, Any]:
    if hasattr(event, "model_dump"):
        return event.model_dump(mode="json")
    return dict(event) if isinstance(event, dict) else {"summary": str(event)}


def _state_dict(state: Any) -> dict[str, Any]:
    to_dict = getattr(state, "to_dict", None)
    return to_dict() if callable(to_dict) else {}


def observed_registry(registry: Any, sink: Sink) -> Any:
    """Wrap every agent in ``registry`` so its dispatches are reported.

    Mutates the registry that is handed in, which is the per-run registry the
    caller just built; the roles and their behaviour are unchanged.
    """
    for role in ROLES:
        try:
            agent = registry.get(role)
        except KeyError:
            continue
        registry.register(role, ObservedAgent(role, agent, sink))
    return registry


class EventLog:
    """A thread-safe, append-only buffer of run events, read by index.

    The run executes on a worker thread while HTTP handlers read from the event
    loop thread, and a reader that has seen *n* events only ever asks for what
    came after them, so indexed reads are enough and no reader can miss one.
    """

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._seq = 0

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._seq += 1
            stamped = {"seq": self._seq, "ts": time.time(), **event}
            self._events.append(stamped)
            return stamped

    def since(self, index: int) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events[max(0, index) :])

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)
