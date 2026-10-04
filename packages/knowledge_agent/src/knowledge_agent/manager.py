"""The research-state manager: operations over a state, optionally persisted.

Two ways in, one behaviour:

* **Pure functions** (``update_state(previous_state, analysis_result, ...)`` and friends) take a
  state (or ``None``) and return an :class:`UpdatedResearchState`. Nothing is written anywhere.
* **``ResearchStateManager``** wraps a :class:`StateStore`: it loads the state from the log,
  runs the same function, and commits the new events atomically with an optimistic
  ``expected_event_count`` check so two writers cannot silently interleave.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from bacteriocin_shared import ResearchState, UpdatedResearchState

from . import ingest, queries
from .errors import StateConflict
from .policy import StatePolicy
from .reducer import DECISIVE_RELATIONSHIPS
from .session import Clock, Session
from .store import StateStore


def _coerce(previous_state: ResearchState | dict[str, Any] | None) -> ResearchState:
    if previous_state is None:
        return ResearchState()
    if isinstance(previous_state, ResearchState):
        return previous_state
    return ResearchState.model_validate(previous_state)


def _run(
    previous_state: ResearchState | dict[str, Any] | None,
    work: Callable[[Session], Any],
    *,
    clock: Clock | None,
    policy: StatePolicy | None,
    expected_event_count: int | None = None,
) -> UpdatedResearchState:
    state = _coerce(previous_state)
    if expected_event_count is not None and state.event_count != expected_event_count:
        raise StateConflict(
            f"the state has {state.event_count} events, expected {expected_event_count}; it moved since it was read"
        )
    session = Session(state, clock=clock, policy=policy)
    work(session)
    changed = []
    for e in session.events:
        extra = e.model_extra or {}
        if (
            e.event != "relationship_observed"
            or extra.get("relationship") not in DECISIVE_RELATIONSHIPS
        ):
            continue
        if extra.get("previous_relationship") != extra.get(
            "relationship"
        ):  # a first answer, or a changed one
            changed.append(e.model_dump(mode="json"))
    return UpdatedResearchState(
        state=session.state,
        new_events=session.events,
        hypothesis_transitions=session.transitions("hypothesis_update"),
        candidate_transitions=session.transitions("candidate_status_update"),
        relationship_changes=changed,
        warnings=session.warnings,
        previous_event_count=session.start_event_count,
    )


# ---------------------------------------------------------------------------
# Pure operations
# ---------------------------------------------------------------------------


def initialize_state(
    objective: dict[str, Any],
    previous_state: ResearchState | dict[str, Any] | None = None,
    *,
    clock: Clock | None = None,
    policy: StatePolicy | None = None,
) -> UpdatedResearchState:
    return _run(
        previous_state, lambda s: ingest.set_objective(s, objective), clock=clock, policy=policy
    )


def register_candidates(
    previous_state: ResearchState | dict[str, Any] | None,
    candidate_output: dict[str, Any],
    *,
    clock: Clock | None = None,
    policy: StatePolicy | None = None,
) -> UpdatedResearchState:
    return _run(
        previous_state,
        lambda s: ingest.register_candidates(s, candidate_output),
        clock=clock,
        policy=policy,
    )


def record_experiment_plan(
    previous_state: ResearchState | dict[str, Any] | None,
    plan: Any,
    *,
    clock: Clock | None = None,
    policy: StatePolicy | None = None,
) -> UpdatedResearchState:
    return _run(
        previous_state, lambda s: ingest.record_experiment_plan(s, plan), clock=clock, policy=policy
    )


def register_evidence(
    previous_state: ResearchState | dict[str, Any] | None,
    evidence: list[dict[str, Any]],
    *,
    clock: Clock | None = None,
    policy: StatePolicy | None = None,
) -> UpdatedResearchState:
    return _run(
        previous_state, lambda s: ingest.register_evidence(s, evidence), clock=clock, policy=policy
    )


def update_state(
    previous_state: ResearchState | dict[str, Any] | None,
    analysis_result: dict[str, Any],
    *,
    result: dict[str, Any] | None = None,
    spec: dict[str, Any] | None = None,
    hypothesis: dict[str, Any] | None = None,
    candidate: dict[str, Any] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    advance_iteration: bool = True,
    clock: Clock | None = None,
    policy: StatePolicy | None = None,
    expected_event_count: int | None = None,
) -> UpdatedResearchState:
    """Fold one Result Analysis output into the state. Never overwrites: a changed belief is a transition event."""
    return _run(
        previous_state,
        lambda s: ingest.record_analysis(
            s,
            analysis_result,
            result=result,
            spec=spec,
            hypothesis=hypothesis,
            candidate=candidate,
            evidence=evidence,
            advance_iteration=advance_iteration,
        ),
        clock=clock,
        policy=policy,
        expected_event_count=expected_event_count,
    )


def reject_candidate(
    previous_state: ResearchState | dict[str, Any] | None,
    candidate_id: str,
    reason: str,
    *,
    triggered_by: list[str] | None = None,
    clock: Clock | None = None,
    policy: StatePolicy | None = None,
) -> UpdatedResearchState:
    return _run(
        previous_state,
        lambda s: ingest.reject_candidate(s, candidate_id, reason, triggered_by),
        clock=clock,
        policy=policy,
    )


def close_question(
    previous_state: ResearchState | dict[str, Any] | None,
    question_id: str,
    reason: str,
    *,
    triggered_by: list[str] | None = None,
    clock: Clock | None = None,
    policy: StatePolicy | None = None,
) -> UpdatedResearchState:
    return _run(
        previous_state,
        lambda s: ingest.close_question(s, question_id, reason, triggered_by),
        clock=clock,
        policy=policy,
    )


# ---------------------------------------------------------------------------
# Persisted operations
# ---------------------------------------------------------------------------


class ResearchStateManager:
    """The same operations, loading from and committing to a :class:`StateStore`."""

    def __init__(
        self, store: StateStore, *, clock: Clock | None = None, policy: StatePolicy | None = None
    ) -> None:
        self.store, self.clock, self.policy = store, clock, policy

    def state(self) -> ResearchState:
        return self.store.load()

    def _persist(
        self,
        op: Callable[..., UpdatedResearchState],
        *args: Any,
        expected_event_count: int | None = None,
        **kwargs: Any,
    ) -> UpdatedResearchState:
        current = self.store.load()
        if expected_event_count is not None and current.event_count != expected_event_count:
            raise StateConflict(
                f"the state has {current.event_count} events, expected {expected_event_count}; it moved since it was read"
            )
        updated = op(current, *args, clock=self.clock, policy=self.policy, **kwargs)
        self.store.commit(
            updated.new_events, updated.state, expected_event_count=current.event_count
        )
        updated.persisted = True
        return updated

    def initialize(self, objective: dict[str, Any]) -> UpdatedResearchState:
        current = self.store.load()
        updated = initialize_state(objective, current, clock=self.clock, policy=self.policy)
        self.store.commit(
            updated.new_events, updated.state, expected_event_count=current.event_count
        )
        updated.persisted = True
        return updated

    def register_candidates(self, candidate_output: dict[str, Any]) -> UpdatedResearchState:
        return self._persist(register_candidates, candidate_output)

    def record_experiment_plan(self, plan: Any) -> UpdatedResearchState:
        return self._persist(record_experiment_plan, plan)

    def register_evidence(self, evidence: list[dict[str, Any]]) -> UpdatedResearchState:
        return self._persist(register_evidence, evidence)

    def update_state(
        self,
        analysis_result: dict[str, Any],
        *,
        expected_event_count: int | None = None,
        **context: Any,
    ) -> UpdatedResearchState:
        return self._persist(
            update_state, analysis_result, expected_event_count=expected_event_count, **context
        )

    def reject_candidate(
        self, candidate_id: str, reason: str, *, triggered_by: list[str] | None = None
    ) -> UpdatedResearchState:
        return self._persist(reject_candidate, candidate_id, reason, triggered_by=triggered_by)

    def close_question(
        self, question_id: str, reason: str, *, triggered_by: list[str] | None = None
    ) -> UpdatedResearchState:
        return self._persist(close_question, question_id, reason, triggered_by=triggered_by)

    # -- queries ------------------------------------------------------------
    def get_candidate_history(self, candidate_id: str) -> dict[str, Any]:
        return queries.get_candidate_history(self.state(), candidate_id)

    def get_hypothesis_history(self, hypothesis_id: str) -> dict[str, Any]:
        return queries.get_hypothesis_history(self.state(), hypothesis_id)

    def get_experiment_history(self, **filters: str | None) -> list[dict[str, Any]]:
        return queries.get_experiment_history(self.state(), **filters)

    def get_open_questions(self) -> list[dict[str, Any]]:
        return queries.get_open_questions(self.state())

    def summarize_current_state(self) -> dict[str, Any]:
        return queries.summarize_current_state(self.state())

    def verify_integrity(self) -> list[str]:
        return self.store.verify()

    def state_at_iteration(self, iteration: int) -> ResearchState:
        """The state as it was when loop turn ``iteration`` closed."""
        return self.store.reconstruct(upto_iteration=iteration)

    def state_at_event(self, event_count: int) -> ResearchState:
        """The state after exactly the first ``event_count`` events."""
        return self.store.reconstruct(upto_event_count=event_count)


__all__ = [
    "ResearchStateManager",
    "close_question",
    "initialize_state",
    "record_experiment_plan",
    "register_candidates",
    "register_evidence",
    "reject_candidate",
    "update_state",
]
