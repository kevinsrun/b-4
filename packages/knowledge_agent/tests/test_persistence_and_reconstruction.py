"""Persistence, and the property the whole design exists for: the state can always be reconstructed."""

from __future__ import annotations

import json

import pytest
from knowledge_helpers import analysis, candidate_envelope, clock, finding, result, spec

from knowledge_agent import (
    JsonFileStateStore,
    ResearchStateManager,
    StateConflict,
    StateIntegrityError,
    get_hypothesis_history,
    replay,
    summarize_current_state,
)

H = "hyp_cand_a"


def run_campaign(mgr: ResearchStateManager) -> list:
    """A four-turn campaign; returns the state snapshot taken at the end of each turn."""
    mgr.initialize({"goal": "does density reduce inhibition?"})
    mgr.register_candidates(candidate_envelope("cand_a", "cand_b"))
    snapshots = []
    script = [
        ("supported", "moderate", [finding("target_cell_density", "negative")]),
        ("inconclusive", "none", []),
        ("weakened", "moderate", [finding("target_cell_density", "positive", effect=0.2)]),
        ("weakened", "strong", []),
    ]
    for n, (status, strength, findings) in enumerate(script, start=1):
        eid = f"exp_{n}"
        mgr.record_experiment_plan(spec(eid))
        mgr.update_state(
            analysis(eid, status, strength=strength, findings=findings),
            result=result(f"res_{eid}", eid, inhibition=0.9 - 0.2 * n),
        )
        snapshots.append(mgr.state())
    return snapshots


def test_state_reconstruction_from_the_event_log_alone(tmp_path):
    mgr = ResearchStateManager(JsonFileStateStore(tmp_path), clock=clock)
    snapshots = run_campaign(mgr)
    final = mgr.state()

    (tmp_path / "state.json").unlink()  # the snapshot is derived: lose it and nothing is lost
    rebuilt = ResearchStateManager(JsonFileStateStore(tmp_path), clock=clock).state()
    assert rebuilt == final

    from_scratch = replay(JsonFileStateStore(tmp_path).events())
    assert from_scratch == final and from_scratch.model_dump_json() == final.model_dump_json()

    # Every past turn is recoverable, byte for byte, as it was when that turn closed.
    for turn, snapshot in enumerate(snapshots, start=1):
        assert mgr.state_at_iteration(turn).model_dump_json() == snapshot.model_dump_json(), (
            f"turn {turn}"
        )


def test_the_state_can_be_rebuilt_as_of_any_single_event(tmp_path):
    mgr = ResearchStateManager(JsonFileStateStore(tmp_path), clock=clock)
    run_campaign(mgr)
    events = mgr.store.events()
    assert mgr.state_at_event(0).event_count == 0 and mgr.state_at_event(len(events)) == mgr.state()
    first_update = next(e for e in events if e.event == "hypothesis_update")
    before = mgr.state_at_event(first_update.seq - 1)
    after = mgr.state_at_event(first_update.seq)
    assert (
        before.hypotheses[H].status == "open" and after.hypotheses[H].status == "supported"
    )  # the belief change itself, isolated


def test_what_it_believed_and_why_can_be_read_back_for_any_turn(tmp_path):
    mgr = ResearchStateManager(JsonFileStateStore(tmp_path), clock=clock)
    run_campaign(mgr)
    after_turn_1 = mgr.state_at_iteration(1)
    after_turn_3 = mgr.state_at_iteration(3)
    assert (
        after_turn_1.hypotheses[H].status == "supported"
        and after_turn_3.hypotheses[H].status == "weakened"
    )
    assert mgr.state().hypotheses[H].status == "rejected"
    history = get_hypothesis_history(mgr.state(), H)
    assert [(c["from"], c["to"]) for c in history["timeline"] if c["type"] == "status_change"] == [
        (None, "open"),
        ("open", "supported"),
        ("supported", "weakened"),
        ("weakened", "rejected"),
    ]
    assert all(
        c["triggered_by"]
        for c in history["timeline"]
        if c["type"] == "status_change" and c["from"] is not None
    )
    assert (
        summarize_current_state(after_turn_1)["hypotheses"][0]["status"] == "supported"
    )  # the old belief is still answerable


def test_a_new_manager_instance_sees_the_whole_history(tmp_path):
    run_campaign(ResearchStateManager(JsonFileStateStore(tmp_path), clock=clock))
    again = ResearchStateManager(JsonFileStateStore(tmp_path), clock=clock)
    assert again.state().event_count == len(again.store.events()) and again.verify_integrity() == []
    assert len(again.get_experiment_history()) == 4


def test_the_log_is_append_only_across_updates(tmp_path):
    store = JsonFileStateStore(tmp_path)
    mgr = ResearchStateManager(store, clock=clock)
    mgr.initialize({"goal": "g"})
    first = store.events_path.read_text()
    mgr.register_candidates(candidate_envelope("cand_a"))
    assert store.events_path.read_text().startswith(first)


def test_tampering_with_the_log_is_detected_and_refuses_to_load(tmp_path):
    store = JsonFileStateStore(tmp_path)
    run_campaign(ResearchStateManager(store, clock=clock))
    assert store.verify() == []
    lines = store.events_path.read_text().splitlines()
    event = json.loads(lines[0])
    event["objective"] = {"goal": "quietly rewritten"}
    lines[0] = json.dumps(event)
    store.events_path.write_text("\n".join(lines) + "\n")
    assert any("edited" in p for p in store.verify())
    with pytest.raises(StateIntegrityError):
        store.load()


def test_removing_an_event_from_the_log_is_detected(tmp_path):
    store = JsonFileStateStore(tmp_path)
    run_campaign(ResearchStateManager(store, clock=clock))
    lines = store.events_path.read_text().splitlines()
    del lines[5]
    store.events_path.write_text("\n".join(lines) + "\n")
    assert store.verify()
    with pytest.raises(StateIntegrityError):
        store.load()


def test_an_edited_snapshot_cannot_change_beliefs_and_is_reported(tmp_path):
    store = JsonFileStateStore(tmp_path)
    mgr = ResearchStateManager(store, clock=clock)
    run_campaign(mgr)
    snap = json.loads(store.state_path.read_text())
    snap["hypotheses"][H]["status"] = (
        "supported"  # try to revive a rejected hypothesis by editing the derived file
    )
    store.state_path.write_text(json.dumps(snap))
    assert mgr.state().hypotheses[H].status == "rejected"  # the log wins
    assert any("state.json differs" in p for p in store.verify())


def test_concurrent_writers_cannot_interleave_silently(tmp_path):
    a = ResearchStateManager(JsonFileStateStore(tmp_path), clock=clock)
    b = ResearchStateManager(JsonFileStateStore(tmp_path), clock=clock)
    a.initialize({"goal": "g"})
    a.register_candidates(candidate_envelope("cand_a"))
    seen = a.state().event_count
    b.record_experiment_plan(spec("exp_1"))  # b commits first
    with pytest.raises(StateConflict, match="moved since it was read"):
        a.update_state(
            analysis("exp_1", "supported"), result=result("r", "exp_1"), expected_event_count=seen
        )
    a.update_state(
        analysis("exp_1", "supported"),
        result=result("r", "exp_1"),
        expected_event_count=a.state().event_count,
    )  # re-read, then fine


def test_the_store_itself_rejects_a_stale_commit(tmp_path):
    store = JsonFileStateStore(tmp_path)
    mgr = ResearchStateManager(store, clock=clock)
    mgr.initialize({"goal": "g"})
    updated = mgr.register_candidates(candidate_envelope("cand_a"))
    with pytest.raises(StateConflict):
        store.commit(
            updated.new_events, updated.state, expected_event_count=0
        )  # the log is longer than the writer thinks


def test_a_failed_update_leaves_the_files_untouched(tmp_path):
    store = JsonFileStateStore(tmp_path)
    mgr = ResearchStateManager(store, clock=clock)
    mgr.initialize({"goal": "g"})
    before = (store.events_path.read_text(), store.state_path.read_text())
    with pytest.raises(Exception):  # noqa: B017
        mgr.update_state({"decision": {"hypothesis_status": "supported"}})
    assert (store.events_path.read_text(), store.state_path.read_text()) == before


def test_empty_store_loads_as_a_fresh_state(tmp_path):
    state = JsonFileStateStore(tmp_path / "nothing_yet").load()
    assert state.event_count == 0 and state.iteration == 1 and state.hypotheses == {}
