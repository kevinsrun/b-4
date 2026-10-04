"""A unit of work: events are sequenced, sealed and applied to a working copy of the state.

Builders (``ingest.py``) read ``session.state`` -- which already reflects the events they
emitted earlier in the same operation -- and ``emit`` new ones. Nothing touches the caller's
state or the store until the operation finishes, so a failure part-way leaves no trace.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from bacteriocin_lab.shared import ResearchState, StateEvent

from .events import event_id_for, seal
from .policy import DEFAULT_POLICY, StatePolicy
from .reducer import apply_event

Clock = Callable[[], str]


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class Session:
    def __init__(
        self,
        state: ResearchState | None,
        *,
        clock: Clock | None = None,
        policy: StatePolicy | None = None,
    ) -> None:
        self.state: ResearchState = (state or ResearchState()).model_copy(deep=True)
        self.start_event_count = self.state.event_count
        self.clock = clock or utc_now
        self.policy = policy or DEFAULT_POLICY
        self.events: list[StateEvent] = []
        self.warnings: list[str] = []

    def emit(
        self,
        event: str,
        *,
        triggered_by: list[str] | None = None,
        iteration: int | None = None,
        **fields: Any,
    ) -> StateEvent:
        seq = self.state.event_count + 1
        sealed = seal(
            {
                "event_id": event_id_for(seq),
                "seq": seq,
                "iteration": self.state.iteration if iteration is None else iteration,
                "timestamp": self.clock(),
                "event": event,
                "triggered_by": list(triggered_by or []),
                **fields,
            },
            prev_hash=self.state.last_event_hash,
        )
        apply_event(self.state, sealed)  # validates against the evolving state
        self.events.append(sealed)
        return sealed

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def transitions(self, event_type: str) -> list[dict[str, Any]]:
        return [e.model_dump(mode="json") for e in self.events if e.event == event_type]


__all__ = ["Clock", "Session", "utc_now"]
