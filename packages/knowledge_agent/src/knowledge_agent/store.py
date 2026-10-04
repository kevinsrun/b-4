"""Persistence abstraction.

The **event log is the only authoritative record.** ``load()`` always rebuilds the state by
replaying it, so a stale, truncated or hand-edited snapshot can never change what the system
believes; ``state.json`` is a derived convenience for humans and other tools, and
``verify()`` reports it if it has drifted from the log.

``JsonFileStateStore`` is the hackathon MVP: one directory, an append-only ``events.jsonl``
and a derived ``state.json``. A database would implement the same four methods
(``events``, ``commit``, ``verify``, plus the inherited ``load``/``reconstruct``); the agents
never see the difference.
"""

from __future__ import annotations

import contextlib
import json
import os
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

from bacteriocin_shared import ResearchState, StateEvent

from .errors import StateConflict, StateIntegrityError
from .events import verify_chain
from .reducer import replay


class StateStore(ABC):
    @abstractmethod
    def events(self) -> list[StateEvent]:
        """Every event ever committed, in order."""

    @abstractmethod
    def commit(
        self, new_events: list[StateEvent], new_state: ResearchState, *, expected_event_count: int
    ) -> None:
        """Append ``new_events``. Must raise :class:`StateConflict` if the log is not exactly ``expected_event_count`` long."""

    def load(self) -> ResearchState:
        return replay(self.events())

    def reconstruct(
        self, upto_iteration: int | None = None, upto_event_count: int | None = None
    ) -> ResearchState:
        """The state as of the end of loop turn ``upto_iteration`` / after ``upto_event_count`` events, from the log alone."""
        return replay(
            self.events(), upto_iteration=upto_iteration, upto_event_count=upto_event_count
        )

    def verify(self) -> list[str]:
        """Every problem found in the log (empty when intact). Never raises: diagnosing damage is its job."""
        try:
            events = self.events()
        except StateIntegrityError as exc:
            return [str(exc)]
        problems = verify_chain(events)
        if not problems:
            try:
                self.load()
            except StateIntegrityError as exc:
                problems.append(str(exc))
        return problems


class InMemoryStateStore(StateStore):
    def __init__(self) -> None:
        self._events: list[StateEvent] = []

    def events(self) -> list[StateEvent]:
        return list(self._events)

    def commit(
        self, new_events: list[StateEvent], new_state: ResearchState, *, expected_event_count: int
    ) -> None:
        if len(self._events) != expected_event_count:
            raise StateConflict(
                f"the log has {len(self._events)} events, expected {expected_event_count}; reload and retry"
            )
        self._events.extend(new_events)


class JsonFileStateStore(StateStore):
    """``<dir>/events.jsonl`` (authoritative) and ``<dir>/state.json`` (derived)."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self.events_path = self.directory / "events.jsonl"
        self.state_path = self.directory / "state.json"
        self._lock_path = self.directory / ".lock"

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        """Serialise writers across processes (best effort: a no-op where ``fcntl`` is unavailable)."""
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            import fcntl
        except ImportError:  # pragma: no cover - non-POSIX
            yield
            return
        with self._lock_path.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def events(self) -> list[StateEvent]:
        if not self.events_path.is_file():
            return []
        out: list[StateEvent] = []
        with self.events_path.open(encoding="utf-8") as handle:
            for n, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    out.append(StateEvent.model_validate(json.loads(line)))
                except ValueError as exc:
                    raise StateIntegrityError(
                        f"{self.events_path.name} line {n} is not a valid event: {exc}"
                    ) from exc
        return out

    def commit(
        self, new_events: list[StateEvent], new_state: ResearchState, *, expected_event_count: int
    ) -> None:
        if not new_events:
            return
        with self._locked():
            current = len(self.events())
            if current != expected_event_count:
                raise StateConflict(
                    f"the log has {current} events, expected {expected_event_count}; another writer committed first — reload and retry"
                )
            with self.events_path.open("a", encoding="utf-8") as handle:
                for ev in new_events:
                    handle.write(
                        json.dumps(
                            ev.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
                        )
                        + "\n"
                    )
                handle.flush()
                os.fsync(handle.fileno())
            tmp = self.state_path.with_suffix(".json.tmp")
            tmp.write_text(new_state.model_dump_json(indent=2), encoding="utf-8")
            os.replace(tmp, self.state_path)

    def verify(self) -> list[str]:
        problems = super().verify()
        if not problems and self.state_path.is_file():
            try:
                snapshot = ResearchState.model_validate_json(
                    self.state_path.read_text(encoding="utf-8")
                )
                if snapshot != self.load():
                    problems.append(
                        "state.json differs from the state replayed from events.jsonl (the snapshot was edited or is stale; the log wins)"
                    )
            except ValueError as exc:
                problems.append(f"state.json is unreadable: {exc}")
        return problems


__all__ = ["InMemoryStateStore", "JsonFileStateStore", "StateStore"]
