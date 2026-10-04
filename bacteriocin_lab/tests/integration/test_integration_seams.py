"""Agent-to-agent seams exercised with REAL agents and real payloads (no fixtures for the thing under test).

Each test pins a defect that single-agent test suites could not see: every agent passed its own tests
while the pair failed. See docs/integration-report.md.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from bacteriocin_lab.agents.evidence.models import LiteratureResponse
from bacteriocin_lab.agents.planner import run_agent as plan
from bacteriocin_lab.agents.planner.adapters import normalize_candidate, plain_conditions
from bacteriocin_lab.agents.simulator import run_experiment
from bacteriocin_lab.agents.simulator.selftest import spec as sim_spec
from bacteriocin_lab.orchestration import ResearchObjective, ResearchState, run_discovery
from bacteriocin_lab.orchestration.agent_adapters import LiteratureAgentAdapter
from bacteriocin_lab.orchestration.registry import AgentRegistry
from bacteriocin_lab.shared.compat import contract_result_dict

EVIDENCE_OUTPUT = (
    Path(__file__).parents[2]
    / "evaluation"
    / "examples"
    / "evidence"
    / "output_nisin_listeria.json"
)


def real_objective() -> ResearchObjective:
    return ResearchObjective(
        goal="Discover a bacteriocin against Listeria monocytogenes.",
        target={"species": "Listeria monocytogenes", "gram": "positive"},
        desired_behavior={
            "high_inhibition": True,
            "target_cell_density": 1e8,
            "ph_range": [6.0, 7.5],
        },
        constraints={"max_candidates": 2},
    )


def test_real_agents_survive_multiple_iterations():
    """Regression: with the real planner, iteration 2 used to die with 'must be real number, not dict'
    because simulator results carry unit-bearing quantities. One iteration never exercised it."""
    result = run_discovery(
        real_objective(), max_iterations=3, max_failures=3, seed=1, registry=AgentRegistry.default()
    )
    assert result.errors == [], result.errors
    assert result.iterations_completed == 3
    assert all(t["status"] == "success" for t in result.execution_trace)
    state = result.final_state
    assert len(state["results"]) >= 3
    assert {r["evidence_type"] for r in state["results"]} == {"simulation-derived"}
    assert ResearchState.model_validate(state).to_dict() == state


def test_planner_accepts_real_simulator_results_directly():
    result = run_experiment(sim_spec()).to_json_dict()
    assert isinstance(
        result["conditions"]["bacteriocin_concentration"], dict
    )  # the shape that broke it
    out = plan(
        {
            "research_objective": {
                "target": {"species": "Listeria monocytogenes"},
                "desired_behavior": {"ph_range": [6.0, 7.5]},
            },
            "candidates": [
                {"candidate_id": result["candidate_id"], "name": "n", "confidence": 0.5}
            ],
            "hypotheses": [
                {"hypothesis_id": "h1", "template": "ph_window", "prior_plausibility": 0.5}
            ],
            "previous_experiments": [result],
            "budget": {"remaining_experiments": 5},
        }
    )
    assert out["decision"]["status"] == "propose_experiment", out["warnings"]
    assert out["artifacts"]["candidate_experiment_counts"][result["candidate_id"]] == 1


def test_planner_flattens_quantities_to_numbers():
    flat, notes = plain_conditions(
        {
            "bacteriocin_concentration": {"value": 2.0, "unit": "uM"},
            "target_cell_density": {"value": 8.0, "unit": "log10_cfu_per_ml"},
            "ph": 6.5,
        }
    )
    assert flat == {"bacteriocin_concentration": 2.0, "target_cell_density": 1e8, "ph": 6.5}
    assert notes == []


def test_planner_reads_the_candidate_agents_feature_names():
    mapped = normalize_candidate(
        {
            "candidate_id": "c",
            "features": {
                "computed": {"net_charge": 2.7, "sequence_length": 43},
                "known_stability": {"ph_stable_range": [2.0, 9.0]},
                "receptor": "mannose phosphotransferase system (Man-PTS)",
            },
        }
    )["features"]
    assert mapped["net_charge_at_target_ph"] == 2.7
    assert mapped["stability"]["ph_activity_window"] == [2.0, 9.0]
    assert "Man-PTS" in mapped["mechanism"]
    # Native values are never overwritten.
    native = normalize_candidate(
        {
            "candidate_id": "c",
            "features": {"net_charge_at_target_ph": 9.0, "computed": {"net_charge": 1.0}},
        }
    )
    assert native["features"]["net_charge_at_target_ph"] == 9.0


def test_critic_reads_real_simulator_results_instead_of_dropping_them(caplog):
    """Regression: the critic validated results against the shared contract, rejected the simulator's
    shape ('skipping unparseable result') and then blamed the claim for a missing citation."""
    from bacteriocin_lab.agents.critic import run_agent as critic

    result = run_experiment(sim_spec()).to_json_dict()
    claim = {
        "claim_id": "c1",
        "statement": "The candidate inhibits the target.",
        "result_ids": [result["result_id"]],
        "candidate_id": result["candidate_id"],
        "asserted_confidence": 0.5,
    }
    with caplog.at_level(logging.WARNING):
        review = critic({"claims": [claim], "previous_results": [result]}).model_dump(mode="json")
    assert "unparseable" not in caplog.text
    issues = {i["type"] for i in review["artifacts"]["review"]["issues"]}
    assert "missing_citation" not in issues, "the critic could not see the result it was handed"

    unseen = critic({"claims": [claim], "previous_results": []}).model_dump(mode="json")
    assert "missing_citation" in {i["type"] for i in unseen["artifacts"]["review"]["issues"]}


def test_contract_normaliser_changes_representation_only():
    raw = run_experiment(sim_spec()).to_json_dict()
    fixed = contract_result_dict(raw)
    for key in (
        "result_id",
        "experiment_id",
        "candidate_id",
        "evidence_type",
        "validated_experimentally",
        "measurement",
        "model_version",
    ):
        assert fixed.get(key) == raw.get(key), f"{key} must pass through untouched"
    assert fixed["evidence_type"] == "simulation-derived"
    assert contract_result_dict("not a dict") == "not a dict"


class StubLiterature:
    """The real LiteratureEvidenceAgent response type, served from a committed example (no network)."""

    def run(self, request):
        return LiteratureResponse.model_validate(json.loads(EVIDENCE_OUTPUT.read_text()))


def test_literature_adapter_actually_records_evidence():
    """Regression: the adapter's loop body was `append(...) if False else None`, so literature
    evidence was fetched, counted, and then discarded: it never reached the research state."""
    state = ResearchState(objective=real_objective())
    out = LiteratureAgentAdapter(agent=StubLiterature()).run(state)

    assert out["evidence_count"] >= 1
    assert len(state.evidence) == out["evidence_count"] == len(out["output_ids"])
    assert {e.evidence_type for e in state.evidence} == {"literature-derived"}
    assert [e.evidence_id for e in state.evidence] == out["output_ids"]
    added = [e for e in state.scientific_history if e.event_type == "evidence_added"]
    assert len(added) == len(state.evidence)

    # Idempotent: asking again adds nothing new.
    again = LiteratureAgentAdapter(agent=StubLiterature()).run(state)
    assert again["output_ids"] == [] and len(state.evidence) == out["evidence_count"]


def test_history_labels_provenance_with_the_contract_vocabulary():
    """Regression: the audit log recorded 'EvidenceType.SIMULATION' instead of 'simulation-derived'."""
    result = run_discovery(
        real_objective(), max_iterations=1, seed=1, registry=AgentRegistry.default()
    )
    labels = {
        e["data"]["evidence_type"]
        for e in result.final_state["scientific_history"]
        if e["event_type"] == "experiment_executed"
    }
    assert labels == {"simulation-derived"}
