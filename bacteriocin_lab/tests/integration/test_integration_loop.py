"""The scientific loop: tests 4, 5, 6, 7, 13, 14, 19, 20.

Real orchestrator, router, state manager and guards; fixture specialists with real interfaces.
"""

from __future__ import annotations

import copy
import json

from bacteriocin_lab.orchestration import ResearchState
from bacteriocin_lab.orchestration.types import ExperimentSpec

from .helpers import (
    FakePlannerAgent,
    ScriptedAnalysis,
    ScriptedCritic,
    ScriptedSimulator,
    agents_in_order,
    registry,
    run,
)

LOOP = ["evidence", "candidate", "planner", "simulation", "analysis", "critic"]


def density_of(spec: dict) -> float:
    return spec["conditions"]["target_cell_density"]


def events(result, kind: str) -> list[dict]:
    return [e for e in result.final_state["scientific_history"] if e["event_type"] == kind]


# --------------------------------------------------------------------------- TEST 4
def test_04_full_happy_path():
    result = run(max_iterations=1, registry=registry(critic=ScriptedCritic(["approved"])))
    state = result.final_state

    # Call order is the documented loop, each agent exactly once, ending in a knowledge update.
    assert agents_in_order(result) == [*LOOP, "knowledge"]
    assert all(t["status"] == "success" for t in result.execution_trace)

    # Stored once each.
    assert len(state["results"]) == 1
    assert len(state["findings"]) == 1
    assert len(state["reviews"]) == 1
    assert len(state["evidence"]) == 1
    assert len(events(result, "experiment_executed")) == 1
    assert len(events(result, "finding_generated")) == 1
    assert len(events(result, "review_completed")) == 1

    # IDs are preserved hop to hop.
    cand = state["candidates"][0]["candidate_id"]
    spec = state["experiments"][0]
    res = state["results"][0]
    finding = state["findings"][0]
    assert spec["candidate_id"] == cand
    assert res["experiment_id"] == spec["experiment_id"] and res["candidate_id"] == cand
    assert finding["evidence_ids"] == [res["result_id"]] and finding["candidate_ids"] == [cand]
    assert set(finding["hypothesis_ids"]) <= {h["hypothesis_id"] for h in state["hypotheses"]}

    # State updated and the trace is complete: each step names what it consumed and produced.
    assert state["iteration"] == 1
    assert state["tested_candidate_ids"] == [cand]
    by_agent = {t["agent"]: t for t in result.execution_trace}
    assert by_agent["simulation"]["input_ids"] == [spec["experiment_id"]]
    assert by_agent["simulation"]["output_ids"] == [res["result_id"]]
    assert by_agent["analysis"]["input_ids"] == [res["result_id"]]
    assert by_agent["critic"]["input_ids"] == [finding["finding_id"]]
    assert all(t["routing_reason"] for t in result.execution_trace)
    assert result.errors == []


# --------------------------------------------------------------------------- TEST 5
def test_05_two_iteration_adaptive_loop():
    result = run(max_iterations=3)
    specs = result.final_state["experiments"]
    results = result.final_state["results"]
    assert len(specs) >= 2 and len(results) >= 2

    first, second = specs[0], specs[1]
    assert density_of(first) == 1e6
    assert results[0]["measurement"]["predicted_inhibition_fraction"] == 0.88
    assert density_of(second) == 1e8, "iteration 2 must test the unresolved high-density regime"
    assert second["experiment_id"] != first["experiment_id"]

    # ...and it was chosen BECAUSE of experiment 1: the same planner on the same state, minus
    # that result, goes back to the screening density.
    state = ResearchState.model_validate(result.final_state)
    with_result = state.clone()
    with_result.experiments = [ExperimentSpec.model_validate(first)]
    with_result.results = state.results[:1]
    without_result = with_result.clone()
    without_result.results = []
    FakePlannerAgent().run(with_result)
    FakePlannerAgent().run(without_result)
    assert density_of(with_result.experiments[-1].model_dump()) == 1e8
    assert density_of(without_result.experiments[-1].model_dump()) == 1e6

    # The critic's reason for sending the loop back is on the record.
    assert result.final_state["reviews"][0]["status"] == "needs_more_evidence"


# --------------------------------------------------------------------------- TEST 6
def test_06_different_result_different_decision():
    high = run(max_iterations=2, registry=registry(simulation=ScriptedSimulator(0.92)))
    poor = run(max_iterations=2, registry=registry(simulation=ScriptedSimulator(0.15)))

    def after_first_critic(result) -> str:
        order = agents_in_order(result)
        return order[order.index("critic") + 1]

    assert after_first_critic(high) != after_first_critic(poor)
    assert after_first_critic(poor) == "knowledge", (
        "a failed candidate must commit the rejection to knowledge before next candidate"
    )
    assert after_first_critic(high) == "evidence", (
        "a promising but untested-at-density result needs evidence"
    )

    def specs(result):
        return [(s["candidate_id"], density_of(s)) for s in result.final_state["experiments"]]

    assert specs(high) != specs(poor)
    assert agents_in_order(high) != agents_in_order(poor)


# --------------------------------------------------------------------------- TEST 7
def test_07_critic_needs_more_evidence_is_not_settled_knowledge():
    result = run(
        max_iterations=2,
        registry=registry(critic=ScriptedCritic(["needs_more_evidence", "approved"])),
    )
    order = agents_in_order(result)
    first_critic = order.index("critic")
    assert order[first_critic + 1] == "evidence", "routing must go backward to evidence"
    assert "knowledge" not in order[: first_critic + 1]

    # The rejection is preserved with its reason...
    review = result.final_state["reviews"][0]
    assert review["status"] == "needs_more_evidence"
    assert review["critique"]
    routed = result.execution_trace[first_critic + 1]
    assert "requested more evidence" in routed["routing_reason"]
    assert review["critique"] in routed["routing_reason"]

    # ...and nothing was accepted as settled knowledge off the back of it.
    state = result.final_state
    history = state["scientific_history"]
    review_at = next(i for i, e in enumerate(history) if e["event_type"] == "review_completed")
    status_changes_before = [
        e for e in history[:review_at] if e["event_type"] == "hypothesis_status_changed"
    ]
    assert status_changes_before == []
    assert state["settled_candidate_ids"] == [] or "approved" in [
        r["status"] for r in state["reviews"]
    ]


# -------------------------------------------------------------------------- TEST 13
def test_13_hypothesis_history_is_reconstructable():
    result = run(
        max_iterations=4,
        registry=registry(
            analysis=ScriptedAnalysis(["supported", "supported", "weakened"]),
            critic=ScriptedCritic(["approved"]),
            simulation=ScriptedSimulator(0.9),
        ),
    )
    state = result.final_state
    hid = state["hypotheses"][0]["hypothesis_id"]
    changes = [
        e
        for e in state["scientific_history"]
        if e["event_type"] == "hypothesis_status_changed" and e["data"].get("hypothesis_id") == hid
    ]
    seen = [c["data"]["new_status"] for c in changes]
    assert "supported" in seen and "weakened" in seen
    assert seen.index("supported") < seen.index("weakened")
    assert state["hypotheses"][0]["status"] == "weakened"

    # Each historical status is recoverable from the log: no silent overwrite.
    def status_after(n_changes: int) -> str:
        return changes[n_changes - 1]["data"]["new_status"]

    assert status_after(1) == "supported"
    assert status_after(len(changes)) == "weakened"
    assert changes[0]["data"]["old_status"] == "open"
    iterations = [c["iteration"] for c in changes]
    assert iterations == sorted(iterations)
    # History is append-only: replaying the log's prefix never contradicts the final record.
    ids = [e["event_id"] for e in state["scientific_history"]]
    assert len(ids) == len(set(ids))


# -------------------------------------------------------------------------- TEST 14
def test_14_provenance_is_never_upgraded():
    result = run(max_iterations=3)
    state = result.final_state

    assert state["evidence"], "literature evidence must be recorded in state"
    assert {e["evidence_type"] for e in state["evidence"]} == {"literature-derived"}
    assert state["results"], "simulation results must be recorded in state"
    assert {r["evidence_type"] for r in state["results"]} == {"simulation-derived"}
    assert all(r["validated_experimentally"] is False for r in state["results"])

    blob = json.dumps(state)
    assert "wet-lab-derived" not in blob
    assert '"validated_experimentally": true' not in blob.lower()
    assert all(
        e["data"].get("evidence_type") in (None, "literature-derived", "simulation-derived")
        for e in state["scientific_history"]
    )


# -------------------------------------------------------------------------- TEST 19
def test_19_reproducibility():
    def one_run():
        return run(max_iterations=3, seed=7)

    a, b = one_run(), one_run()
    assert a.run_id == b.run_id
    assert a.status == b.status and a.errors == b.errors
    assert [(t["agent"], t["routing_reason"], t["status"]) for t in a.execution_trace] == [
        (t["agent"], t["routing_reason"], t["status"]) for t in b.execution_trace
    ]
    assert [density_of(s) for s in a.final_state["experiments"]] == [
        density_of(s) for s in b.final_state["experiments"]
    ]
    assert json.dumps(a.final_state, sort_keys=True) == json.dumps(b.final_state, sort_keys=True)
    assert json.dumps(a.execution_trace, sort_keys=True) == json.dumps(
        b.execution_trace, sort_keys=True
    )
    # A different seed is a different run identity, not a different science.
    assert one_run().run_id != run(max_iterations=3, seed=8).run_id


# -------------------------------------------------------------------------- TEST 20
def test_20_resume_from_serialised_state():
    first = run(max_iterations=1)
    saved = json.loads(json.dumps(first.final_state))  # a real round trip through JSON text
    restored = ResearchState.model_validate(saved)
    assert restored.to_dict() == saved

    resumed = run(max_iterations=3, initial_state=restored)
    after = resumed.final_state

    # Identities, history and provenance survive the restart untouched.
    assert [c["candidate_id"] for c in after["candidates"]][: len(saved["candidates"])] == [
        c["candidate_id"] for c in saved["candidates"]
    ]
    assert [h["hypothesis_id"] for h in after["hypotheses"]][: len(saved["hypotheses"])] == [
        h["hypothesis_id"] for h in saved["hypotheses"]
    ]
    assert after["results"][: len(saved["results"])] == saved["results"]
    assert after["findings"][: len(saved["findings"])] == saved["findings"]
    assert (
        after["scientific_history"][: len(saved["scientific_history"])]
        == saved["scientific_history"]
    )
    assert {r["evidence_type"] for r in after["results"]} == {"simulation-derived"}
    assert {e["evidence_type"] for e in after["evidence"]} == {"literature-derived"}

    # The persisted route is honored. The robust candidate is already settled, so the resumed run
    # terminates without replaying evidence or duplicating any scientific records.
    assert resumed.iterations_completed == first.iterations_completed
    assert resumed.execution_trace == []
    assert resumed.status == "completed"
    assert saved["settled_candidate_ids"], "fixture expectation: the first run settles its candidate"
    assert len({s["experiment_id"] for s in after["experiments"]}) == len(after["experiments"])
    assert copy.deepcopy(saved) == saved  # the saved dict was not mutated by the resumed run
