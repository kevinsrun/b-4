"""Agent envelope tests: the interface Omnigent actually calls."""

from __future__ import annotations

from bacteriocin_lab.agents.simulator import AgentOutput, run_agent
from bacteriocin_lab.agents.simulator.agent import SimulationBackendAgent
from bacteriocin_lab.agents.simulator.selftest import NISIN_A, spec

CONTRACT_OUTPUT_FIELDS = {
    "agent",
    "decision",
    "evidence",
    "confidence",
    "uncertainties",
    "artifacts",
    "warnings",
    "recommended_next_action",
}


def test_output_has_every_contract_field() -> None:
    assert CONTRACT_OUTPUT_FIELDS <= set(AgentOutput.model_fields)


def test_common_envelope_is_accepted_even_when_mostly_empty() -> None:
    output = run_agent(
        {
            "research_objective": {"goal": "find a Listeria-active bacteriocin"},
            "research_state": {},
            "constraints": {},
            "previous_results": [],
            "evidence": [],
            "metadata": {"iteration": 3},
            "experiment_specs": [spec(experiment_id="exp-1")],
        }
    )
    assert output.agent == "simulation_experiment_backend"
    assert output.decision["n_executed"] == 1
    assert 0.0 <= output.confidence <= 1.0


def test_a_singular_experiment_spec_key_is_tolerated() -> None:
    output = run_agent({"experiment_spec": spec(experiment_id="exp-1")})
    assert output.decision["n_executed"] == 1


def test_no_specs_yields_a_clear_recommendation_not_an_error() -> None:
    output = run_agent({})
    assert output.decision["action"] == "no_experiments_executed"
    assert output.recommended_next_action["action"] == "request_experiment_plan"
    assert output.confidence == 0.0


def test_invalid_envelope_is_reported_structurally() -> None:
    output = run_agent({"experiment_specs": "not a list"})
    assert output.decision["action"] == "rejected_input"
    assert output.warnings


def test_evidence_records_preserve_provenance() -> None:
    output = run_agent({"experiment_specs": [spec(experiment_id="exp-1")]})
    record = output.evidence[0]
    assert record.evidence_type.value == "simulation-derived"
    assert record.validated_experimentally is False
    assert record.experiment_id == "exp-1"
    assert record.result_id
    assert record.model_version
    assert "model prediction" in record.statement


def test_evidence_ids_are_stable_for_a_deterministic_rerun() -> None:
    a = run_agent({"experiment_specs": [spec(experiment_id="exp-1")]})
    b = run_agent({"experiment_specs": [spec(experiment_id="exp-1")]})
    assert [e.evidence_id for e in a.evidence] == [e.evidence_id for e in b.evidence]


def test_max_experiments_constraint_is_honoured() -> None:
    specs = [spec(experiment_id=f"exp-{i}") for i in range(5)]
    output = run_agent({"experiment_specs": specs, "constraints": {"max_experiments": 2}})
    assert output.decision["n_requested"] == 2
    assert any("max_experiments" in w for w in output.warnings)


def test_missing_sequence_drives_the_recommendation() -> None:
    output = run_agent(
        {
            "experiment_specs": [
                {
                    "experiment_id": "exp-1",
                    "candidate_id": "cand-mystery",
                    "target": {"species": "Listeria monocytogenes"},
                    "conditions": {
                        "bacteriocin_concentration": {"value": 1.0, "unit": "uM"}
                    },
                }
            ]
        }
    )
    assert output.recommended_next_action["action"] == "resolve_candidate_sequences"
    assert "cand-mystery" in output.recommended_next_action["candidate_ids"]


def test_unspecified_influential_conditions_drive_the_recommendation() -> None:
    output = run_agent(
        {
            "experiment_specs": [
                {
                    "experiment_id": "exp-1",
                    "candidate": {"sequence": NISIN_A},
                    "target": {"species": "Listeria monocytogenes"},
                }
            ]
        }
    )
    assert output.recommended_next_action["action"] == "specify_influential_conditions"


def test_fully_specified_run_recommends_a_sweep() -> None:
    output = run_agent({"experiment_specs": [spec(experiment_id="exp-1")]})
    action = output.recommended_next_action
    assert action["action"] == "refine_with_condition_sweep"
    assert action["suggested_factor"]
    assert len(action["suggested_values"]) == 5


def test_failures_are_surfaced_in_the_decision() -> None:
    output = run_agent(
        {
            "experiment_specs": [
                spec(experiment_id="good"),
                {"experiment_id": "bad", "conditions": {"ph": 99.0}},
            ]
        }
    )
    assert output.decision["n_executed"] == 1
    assert output.decision["n_failed"] == 1
    assert output.decision["failures"][0]["experiment_id"] == "bad"


def test_agent_keeps_no_state_between_calls() -> None:
    agent = SimulationBackendAgent()
    first = agent.run({"experiment_specs": [spec(experiment_id="exp-1")]})
    second = agent.run({"experiment_specs": [spec(experiment_id="exp-1")]})
    assert first.to_json_dict()["evidence"] == second.to_json_dict()["evidence"]
    assert not [a for a in vars(agent)]


def test_describe_exposes_schemas_and_boundaries() -> None:
    described = SimulationBackendAgent().describe()
    assert described["agent"] == "simulation_experiment_backend"
    assert "generate hypotheses" in " ".join(described["does_not"])
    assert described["input_schema"]["title"] == "AgentInput"
    assert described["backends"]["simulation"]["available"] is True


def test_output_is_json_serialisable() -> None:
    import json

    output = run_agent({"experiment_specs": [spec(experiment_id="exp-1")]})
    assert json.loads(json.dumps(output.to_json_dict()))["agent"]


def test_every_result_warns_that_it_is_simulated() -> None:
    output = run_agent({"experiment_specs": [spec(experiment_id="exp-1")]})
    assert any("SIMULATION-DERIVED" in w for w in output.warnings)
    assert output.decision["validated_experimentally"] is False
