"""The append-only, hash-chained event log.

Every fact the state ever learns is an event. Each event carries the hash of its
predecessor, so the log is a chain: editing, deleting or reordering a past event
changes every later hash and is detected by :func:`verify_chain`. The state is only
ever a projection of this log (see ``reducer.py``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from bacteriocin_lab.shared import StateEvent

#: Fields that identify an event but are not part of its content hash's input.
_HASH_EXCLUDED = {"event_hash"}


def canonical(obj: Any) -> str:
    """Stable JSON: equal content always yields equal bytes."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=True)


def hash_event(fields: dict[str, Any]) -> str:
    body = {k: v for k, v in fields.items() if k not in _HASH_EXCLUDED}
    return hashlib.sha256(canonical(body).encode()).hexdigest()


def seal(fields: dict[str, Any], *, prev_hash: str | None) -> StateEvent:
    """Chain ``fields`` onto ``prev_hash`` and stamp its own hash.

    The hash is taken over the *normalised* model (defaults filled in), which is exactly what
    :func:`verify_chain` and the reducer recompute, so an event built with or without optional
    fields verifies the same way.
    """
    draft = StateEvent.model_validate({**fields, "prev_hash": prev_hash, "event_hash": ""})
    return draft.model_copy(update={"event_hash": hash_event(draft.model_dump(mode="json"))})


def event_id_for(seq: int) -> str:
    return f"evt_{seq:06d}"


def verify_chain(events: Iterable[StateEvent]) -> list[str]:
    """Return a list of problems (empty when the log is a valid, gap-free chain)."""
    problems: list[str] = []
    prev: str | None = None
    for i, ev in enumerate(events, start=1):
        if ev.seq != i:
            problems.append(f"event at position {i} has seq {ev.seq} (a gap or reordering)")
        if ev.prev_hash != prev:
            problems.append(
                f"{ev.event_id}: prev_hash does not match the preceding event (history was altered)"
            )
        expected = hash_event(ev.model_dump(mode="json"))
        if ev.event_hash != expected:
            problems.append(f"{ev.event_id}: content does not match its hash (event was edited)")
        prev = ev.event_hash
    return problems


__all__ = ["canonical", "event_id_for", "hash_event", "seal", "verify_chain"]
