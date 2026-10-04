"""The event log and reducer: hash chain, tamper detection, and validated transitions."""

from __future__ import annotations

import pytest
from knowledge_helpers import analysis, candidate_envelope, clock, result, spec

from knowledge_agent import (
    InMemoryStateStore,
    ResearchStateManager,
    StateIntegrityError,
    initialize_state,
    record_experiment_plan,
    register_candidates,
    replay,
    update_state,
    verify_chain,
)
from knowledge_agent.events import seal
from knowledge_agent.reducer import apply_event


def build():
    u = initialize_state({"goal": "test"}, clock=clock)
    u = register_candidates(u.state, candidate_envelope("cand_a"), clock=clock)
    events = list(initialize_state({"goal": "test"}, clock=clock).new_events) + list(u.new_events)
    return u.state, events


def test_every_event_is_chained_sequenced_and_hashed():
    state, events = build()
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert events[0].prev_hash is None and events[1].prev_hash == events[0].event_hash
    assert verify_chain(events) == []
    assert state.event_count == len(events) and state.last_event_hash == events[-1].event_hash


def test_replay_reproduces_the_state_exactly():
    state, events = build()
    assert replay(events) == state


def test_editing_a_past_event_is_detected():
    _, events = build()
    tampered = events[0].model_copy(update={"objective": {"goal": "rewritten"}})
    problems = verify_chain([tampered, *events[1:]])
    assert any("edited" in p for p in problems)
    with pytest.raises(StateIntegrityError):
        replay([tampered, *events[1:]])


def test_deleting_or_reordering_events_is_detected():
    _, events = build()
    assert any("gap" in p or "altered" in p for p in verify_chain(events[1:]))
    assert verify_chain([events[0], events[2], events[1], *events[3:]])
    with pytest.raises(StateIntegrityError):
        replay([events[0], events[2], events[1], *events[3:]])


def test_reducer_rejects_a_transition_from_the_wrong_previous_status():
    state, _ = build()
    bad = seal(
        {
            "event_id": "evt_x",
            "seq": state.event_count + 1,
            "iteration": 1,
            "timestamp": clock(),
            "event": "hypothesis_update",
            "hypothesis_id": "hyp_cand_a",
            "previous_status": "supported",
            "new_status": "weakened",
        },
        prev_hash=state.last_event_hash,
    )
    with pytest.raises(StateIntegrityError, match="history is inconsistent"):
        apply_event(state.model_copy(deep=True), bad)


def test_reducer_rejects_double_registration_unknown_events_and_bad_sequence():
    state, _ = build()
    prev = state.last_event_hash

    def ev(**kw):
        return seal(
            {
                "event_id": "evt_x",
                "seq": state.event_count + 1,
                "iteration": 1,
                "timestamp": clock(),
                **kw,
            },
            prev_hash=prev,
        )

    with pytest.raises(StateIntegrityError, match="already registered"):
        apply_event(
            state.model_copy(deep=True), ev(event="candidate_registered", candidate_id="cand_a")
        )
    with pytest.raises(StateIntegrityError, match="unknown event type"):
        apply_event(state.model_copy(deep=True), ev(event="made_up"))
    skipped = seal(
        {
            "event_id": "evt_x",
            "seq": state.event_count + 5,
            "iteration": 1,
            "timestamp": clock(),
            "event": "objective_set",
            "objective": {"a": 1},
        },
        prev_hash=prev,
    )
    with pytest.raises(StateIntegrityError, match="expected seq"):
        apply_event(state.model_copy(deep=True), skipped)


def test_result_for_an_unplanned_experiment_is_rejected_by_the_reducer():
    state, _ = build()
    bad = seal(
        {
            "event_id": "evt_x",
            "seq": state.event_count + 1,
            "iteration": 1,
            "timestamp": clock(),
            "event": "result_recorded",
            "result_id": "r",
            "experiment_id": "nope",
        },
        prev_hash=state.last_event_hash,
    )
    with pytest.raises(StateIntegrityError, match="unrecorded experiment"):
        apply_event(state.model_copy(deep=True), bad)


def test_previous_state_object_is_never_mutated():
    state, _ = build()
    before = state.model_dump_json()
    update_state(
        state,
        analysis("exp_1", "supported"),
        result=result("res_exp_1", "exp_1"),
        spec=spec("exp_1"),
        clock=clock,
    )
    record_experiment_plan(state, spec("exp_9"), clock=clock)
    assert state.model_dump_json() == before


def test_a_failed_operation_commits_nothing():
    mgr = ResearchStateManager(InMemoryStateStore(), clock=clock)
    mgr.register_candidates(candidate_envelope("cand_a"))
    count = len(mgr.store.events())
    with pytest.raises(Exception):  # noqa: B017 - any error; the point is atomicity
        mgr.update_state(
            {
                "decision": {
                    "experiment_id": "e",
                    "result_id": "r",
                    "candidate_id": "cand_a",
                    "hypothesis_status": "nonsense",
                }
            }
        )
    assert len(mgr.store.events()) == count
