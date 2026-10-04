"""Failure handling and state integrity: tests 8-12, 15-18, 21-26.

The failure paths are exercised through the real engine (``run_discovery``) with fixture specialists
that fail in realistic ways. Nothing in the orchestrator itself is mocked.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bacteriocin_lab.agents.simulator import InvariantViolationError
from bacteriocin_lab.agents.simulator.schemas import Conditions, ExperimentSpec, Target
from bacteriocin_lab.orchestration import ResearchState
from bacteriocin_lab.orchestration import routing as routing_module
from bacteriocin_lab.orchestration.agent_adapters import (
    LiteratureAgentAdapter,
    SimulationAgentAdapter,
)
from bacteriocin_lab.orchestration.state import ResearchStateManager
from bacteriocin_lab.orchestration.types import (
    Candidate,
    Evidence,
    EvidenceType,
    ExperimentResult,
    Finding,
    Hypothesis,
    Measurement,
    ResearchObjective,
    Review,
    Route,
)

from .helpers import (
    FakeAnalysisAgent,
    FakeCandidateAgent,
    FakeCriticAgent,
    FakeEvidenceAgent,
    FakePlannerAgent,
    FakeSimulatorAgent,
    ScientificSnapshot,
    ScriptedCritic,
    agents_in_order,
    make_objective,
    registry,
    run,
)

UNSAFE_OVERRIDES = {
    "targets": {
        "escherichia coli": {"log10_mic_um_base": -2.0},
        "listeria monocytogenes": {"log10_mic_um_base": 4.0},
    }
}
SEQ = "KYYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC"


class Counting:
    """Mixin recording how often an agent was dispatched."""

    calls = 0


def result_fixture(rid: str = "res_1", eid: str = "exp_1", **kw) -> ExperimentResult:
    return ExperimentResult(
        result_id=rid,
        experiment_id=eid,
        candidate_id="cand_1",
        measurement=Measurement(predicted_inhibition_fraction=0.5),
        **kw,
    )


# --------------------------------------------------------------------------- TEST 8
def test_08_simulator_invariant_failure_fails_closed():
    analysis, critic = FakeAnalysisAgent(), FakeCriticAgent()
    result = run(
        max_iterations=3,
        max_failures=1,
        registry=registry(
            simulation=SimulationAgentAdapter(parameter_overrides=UNSAFE_OVERRIDES),
            analysis=analysis,
            critic=critic,
        ),
    )
    state = result.final_state

    assert result.status == "failed"
    assert state["results"] == [], "an ExperimentResult entered state despite unsafe overrides"
    assert analysis.call_count == 0, "analysis consumed a result that must not exist"
    assert critic.call_count == 0, "the critic reviewed a result that must not exist"
    assert not any(e["event_type"] == "experiment_executed" for e in state["scientific_history"])

    # Prior state is preserved: the plan that led here is still on record.
    assert len(state["experiments"]) == 1 and state["candidates"]

    # The failure itself is recorded, with the reason, and nothing ran after it.
    sim_failures = [t for t in result.execution_trace if t["agent"] == "simulation"]
    assert [t["status"] for t in sim_failures] == ["failure"]
    assert "invariant" in sim_failures[0]["error"].lower()
    assert any("invariant" in e.lower() for e in result.errors)
    assert agents_in_order(result)[-1] == "simulation"


# --------------------------------------------------------------------------- TEST 9
def test_09_agent_exception_mid_run():
    sim = FakeSimulatorAgent(should_fail=True)
    result = run(max_iterations=3, max_failures=3, registry=registry(simulation=sim))

    assert result.status == "failed"
    assert sim.call_count == 3, "failure counter must equal the configured max_failures"
    failures = [t for t in result.execution_trace if t["status"] == "failure"]
    assert len(failures) == 3 and all(t["agent"] == "simulation" for t in failures)
    assert all("ODE convergence failure" in t["error"] for t in failures)
    assert sum("ODE convergence failure" in e for e in result.errors) == 3

    # The trace stays readable: every entry has the full set of fields.
    for t in result.execution_trace:
        assert {
            "trace_id",
            "iteration",
            "agent",
            "input_ids",
            "output_ids",
            "routing_reason",
            "status",
        } <= set(t)
    # No partial scientific event was accepted, and everything before the failure survived.
    state = result.final_state
    assert state["results"] == [] and state["findings"] == [] and state["reviews"] == []
    assert not any(e["event_type"] == "experiment_executed" for e in state["scientific_history"])
    assert len(state["experiments"]) == 1


# -------------------------------------------------------------------------- TEST 10
class NotADict(FakeAnalysisAgent):
    def run(self, state):
        return "analysis complete"


class MalformedFlag(FakeAnalysisAgent):
    def run(self, state):
        return {"agent": "analysis", "malformed": True}


class ConfidenceOutOfRange(FakeAnalysisAgent):
    def run(self, state):
        Finding(finding_id="find_x", statement="s", confidence=1.5)  # raises
        return {"agent": "analysis", "output_ids": ["find_x"]}


class EmptyIdBypassingValidation(FakeAnalysisAgent):
    def run(self, state):
        bad = Finding.model_construct(
            finding_id="",
            statement="s",
            status="supported",
            confidence=0.5,
            candidate_ids=[],
            hypothesis_ids=[],
            evidence_ids=[],
            factor_sensitivities={},
            recommendations=[],
        )
        state.findings.append(bad)
        return {"agent": "analysis", "output_ids": ["x"]}


class InvalidStatusBypassingValidation(FakeAnalysisAgent):
    def run(self, state):
        state.findings.append(
            Finding.model_construct(
                finding_id="find_bogus",
                statement="s",
                status="PROVEN",
                confidence=9.9,
                candidate_ids=[],
                hypothesis_ids=[],
                evidence_ids=[],
                factor_sensitivities={},
                recommendations=[],
            )
        )
        return {"agent": "analysis", "output_ids": ["find_bogus"]}


class DanglingCandidateId(FakeAnalysisAgent):
    def run(self, state):
        ResearchStateManager(state).add_finding(
            Finding(
                finding_id="find_d",
                statement="s",
                status="supported",
                confidence=0.5,
                candidate_ids=["cand_does_not_exist"],
                hypothesis_ids=[],
                evidence_ids=[],
            )
        )
        return {"agent": "analysis", "output_ids": ["find_d"]}


class DanglingEvidenceId(FakeAnalysisAgent):
    def run(self, state):
        ResearchStateManager(state).add_finding(
            Finding(
                finding_id="find_e",
                statement="s",
                status="supported",
                confidence=0.5,
                candidate_ids=[state.candidates[0].candidate_id],
                hypothesis_ids=[],
                evidence_ids=["res_that_was_never_run"],
            )
        )
        return {"agent": "analysis", "output_ids": ["find_e"]}


class WetLabProvenanceFromNowhere(FakeAnalysisAgent):
    def run(self, state):
        ResearchStateManager(state).add_evidence(
            Evidence(
                evidence_id="ev_wl", evidence_type="wet-lab-derived", claim="measured at the bench"
            )
        )
        return {"agent": "analysis", "output_ids": ["ev_wl"]}


class SimulatorMissingExperimentId(FakeSimulatorAgent):
    def run(self, state):
        ExperimentResult.model_validate({"result_id": "res_x", "candidate_id": "c"})  # raises
        return {"agent": "simulation", "output_ids": ["res_x"]}


MALFORMED = {
    "analysis returns a string": ("analysis", NotADict),
    "analysis flags its own payload malformed": ("analysis", MalformedFlag),
    "confidence 1.5": ("analysis", ConfidenceOutOfRange),
    "empty finding_id slipped past validation": ("analysis", EmptyIdBypassingValidation),
    "invalid status and confidence slipped past validation": (
        "analysis",
        InvalidStatusBypassingValidation,
    ),
    "finding cites an unknown candidate_id": ("analysis", DanglingCandidateId),
    "finding cites a result that does not exist": ("analysis", DanglingEvidenceId),
    "wet-lab provenance with no wet-lab adapter": ("analysis", WetLabProvenanceFromNowhere),
    "simulation result missing experiment_id": ("simulation", SimulatorMissingExperimentId),
}


@pytest.mark.parametrize("label", MALFORMED)
def test_10_malformed_output_cannot_corrupt_state(label):
    role, agent_cls = MALFORMED[label]
    result = run(max_iterations=2, max_failures=1, registry=registry(**{role: agent_cls()}))
    state = result.final_state

    assert result.status == "failed", f"{label}: the run should stop, got {result.status}"
    assert result.errors, f"{label}: no error recorded"
    bad = [t for t in result.execution_trace if t["status"] == "failure"]
    assert bad and bad[-1]["agent"] == role

    # Whatever the agent tried to write was rolled back: state is still wholly valid.
    assert ResearchState.model_validate(state).to_dict() == state
    assert all(
        f["finding_id"] and f["status"] in {"supported", "contradicted", "weakened", "inconclusive"}
        for f in state["findings"]
    )
    assert all(0.0 <= f["confidence"] <= 1.0 for f in state["findings"])
    assert not any(e["evidence_type"] == "wet-lab-derived" for e in state["evidence"])


# -------------------------------------------------------------------------- TEST 11
def test_11_duplicate_result_is_stored_once():
    state = ResearchState(objective=ResearchObjective(goal="g", target={"species": "L"}))
    mgr = ResearchStateManager(state)
    assert mgr.add_experiment_result(result_fixture()) is True
    snapshot = state.clone()
    assert mgr.add_experiment_result(result_fixture()) is False
    assert len(state.results) == 1
    assert len([e for e in state.scientific_history if e.event_type == "experiment_executed"]) == 1
    assert state.model_dump() == snapshot.model_dump(), "a duplicate submission changed state"

    finding = Finding(finding_id="f1", statement="s", confidence=0.5)
    review = Review(review_id="r1")
    evidence = Evidence(evidence_id="e1", evidence_type="literature-derived", claim="c")
    for add, item in (
        (mgr.add_finding, finding),
        (mgr.add_review, review),
        (mgr.add_evidence, evidence),
    ):
        assert add(item) is True
        assert add(item) is False
    assert (len(state.findings), len(state.reviews), len(state.evidence)) == (1, 1, 1)


def test_11_replicates_are_kept_and_distinguishable():
    """Documented policy: a result is identified by result_id. Two results for one experiment
    are two measurements (replicates), not a duplicate; resubmitting the same result_id is a no-op."""
    state = ResearchState(objective=ResearchObjective(goal="g", target={"species": "L"}))
    mgr = ResearchStateManager(state)
    assert mgr.add_experiment_result(result_fixture("res_a", "exp_1"))
    assert mgr.add_experiment_result(result_fixture("res_b", "exp_1"))
    assert [r.result_id for r in state.results] == ["res_a", "res_b"]
    assert not mgr.add_experiment_result(result_fixture("res_a", "exp_1"))


def test_11_failed_results_are_never_evidence():
    state = ResearchState(objective=ResearchObjective(goal="g", target={"species": "L"}))
    failed = ExperimentResult(
        result_id="res_f",
        experiment_id="exp_f",
        candidate_id="c",
        status="failed",
        error={"error_code": "backend_unavailable"},
    )
    with pytest.raises(ValueError, match="failed runs are recorded"):
        ResearchStateManager(state).add_experiment_result(failed)
    assert state.results == []


# -------------------------------------------------------------------------- TEST 12
class AckLostAfterComputing(FakeSimulatorAgent):
    """Computes and writes the result, then the tool layer dies before acknowledging (once)."""

    def run(self, state):
        out = super().run(state)
        if self.call_count == 1:
            raise ConnectionError("tool layer dropped the acknowledgement")
        return out


def test_12_retry_after_lost_acknowledgement_does_not_duplicate():
    sim = AckLostAfterComputing()
    result = run(max_iterations=1, max_failures=3, registry=registry(simulation=sim))
    state = result.final_state

    sim_trace = [t["status"] for t in result.execution_trace if t["agent"] == "simulation"]
    assert sim_trace[:2] == ["failure", "success"], sim_trace
    first_exp = state["experiments"][0]["experiment_id"]
    for_first = [r for r in state["results"] if r["experiment_id"] == first_exp]
    assert len(for_first) == 1, "the retried experiment produced duplicate evidence"
    executed = [
        e
        for e in state["scientific_history"]
        if e["event_type"] == "experiment_executed" and e["data"]["experiment_id"] == first_exp
    ]
    assert len(executed) == 1
    assert len({r["result_id"] for r in state["results"]}) == len(state["results"])


def test_12_real_simulator_result_ids_are_content_derived():
    """The basis for retry safety with the real backend: the same spec yields the same result_id."""
    from bacteriocin_lab.agents.simulator import run_experiment
    from bacteriocin_lab.agents.simulator.selftest import spec

    assert run_experiment(spec()).result_id == run_experiment(spec()).result_id


# -------------------------------------------------------------------------- TEST 15
def test_15_unknown_agent_route_is_a_structured_failure(monkeypatch):
    original = routing_module.Router.determine_next_route

    def hijack(self, state, last_agent=None, last_route=None):
        if last_agent == "candidate":
            return Route(next_agent="quantum_oracle", reason="router bug")
        return original(self, state, last_agent, last_route)

    monkeypatch.setattr(routing_module.Router, "determine_next_route", hijack)
    planner = FakePlannerAgent()
    result = run(max_iterations=3, max_failures=3, registry=registry(planner=planner))

    assert result.status == "failed"
    assert any("Routing error" in e and "quantum_oracle" in e for e in result.errors)
    failed = [t for t in result.execution_trace if t["status"] == "failure"]
    assert [t["agent"] for t in failed] == ["quantum_oracle"], "a routing error must not be retried"
    assert "quantum_oracle" in failed[0]["error"]
    assert planner.call_count == 0
    # Run information is intact: what happened before the bad route is still there.
    assert result.final_state["candidates"] and result.final_state["scientific_history"]
    assert agents_in_order(result)[:2] == ["evidence", "candidate"]


# -------------------------------------------------------------------------- TEST 16
def test_16_missing_required_input_is_rejected_before_dispatch(monkeypatch):
    original = routing_module.Router.determine_next_route

    def straight_to_planner(self, state, last_agent=None, last_route=None):
        if last_agent is None:
            return Route(next_agent="planner", reason="skipped candidate generation")
        return original(self, state, last_agent, last_route)

    monkeypatch.setattr(routing_module.Router, "determine_next_route", straight_to_planner)
    planner = FakePlannerAgent()
    result = run(max_iterations=1, registry=registry(planner=planner))

    first = result.execution_trace[0]
    assert first["agent"] == "candidate", "planner was dispatched without any candidate"
    assert any("Route validation error" in e and "candidates" in e.lower() for e in result.errors)
    # The planner only ran after candidates existed.
    order = agents_in_order(result)
    assert order.index("candidate") < order.index("planner")


# -------------------------------------------------------------------------- TEST 17
@pytest.mark.parametrize(
    "verdict, expected_reason",
    [("experiment_inconclusive", "recurring cycle"), ("needs_more_evidence", "maximum visits")],
)
def test_17_routing_loops_are_cut_off(verdict, expected_reason):
    result = run(max_iterations=10, registry=registry(critic=ScriptedCritic([verdict])))

    assert result.status in {"stopped", "failed", "max_iterations"}
    assert result.status != "completed"
    assert any(expected_reason in e for e in result.errors), result.errors
    assert len(result.execution_trace) < 40, "guard fired far too late"
    # State is still valid and readable after the forced stop.
    assert ResearchState.model_validate(result.final_state).to_dict() == result.final_state


def test_17_max_iterations_is_a_hard_ceiling():
    result = run(max_iterations=2, registry=registry(critic=ScriptedCritic(["approved"])))
    assert result.status == "max_iterations" and result.iterations_completed == 2


# -------------------------------------------------------------------------- TEST 18
@pytest.mark.parametrize("max_failures", [1, 2, 5])
def test_18_max_failures_is_honoured_exactly(max_failures):
    sim = FakeSimulatorAgent(should_fail=True)
    result = run(max_iterations=10, max_failures=max_failures, registry=registry(simulation=sim))

    assert result.status == "failed"
    assert sim.call_count == max_failures
    assert any(f"({max_failures}/{max_failures})" in e for e in result.errors)
    assert not any("cycle" in e for e in result.errors), "retries must not be reported as a cycle"
    assert len([t for t in result.execution_trace if t["status"] == "failure"]) == max_failures


def test_18_a_success_resets_the_consecutive_failure_count():
    class FlakyThenFine(FakeSimulatorAgent):
        def run(self, state):
            if self.call_count in (0, 1):  # fail twice, then recover
                self.call_count += 1
                raise RuntimeError("transient")
            return super().run(state)

    result = run(max_iterations=1, max_failures=3, registry=registry(simulation=FlakyThenFine()))
    assert result.status != "failed", result.errors
    assert result.final_state["results"]


# -------------------------------------------------------------------------- TEST 21
def planned_state(*specs: ExperimentSpec) -> ResearchState:
    return ResearchState(
        objective=ResearchObjective(goal="g", target={"species": "Listeria monocytogenes"}),
        candidates=[Candidate(candidate_id="cand_ok", name="ok", sequence=SEQ)],
        experiments=list(specs),
    )


def spec(eid: str, density: float = 1e6, domain: str = "simulated_in_vitro") -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id=eid,
        candidate_id="cand_ok",
        target=Target(species="Listeria monocytogenes"),
        conditions=Conditions(
            bacteriocin_concentration=10.0,
            target_cell_density=density,
            ph=7.0,
            temperature_c=37.0,
            assay_domain=domain,
        ),
    )


def test_21_batch_maps_results_to_experiments_and_isolates_failures():
    state = planned_state(spec("e1"), spec("e2_wet", domain="wet_lab_in_vitro"), spec("e3", 1e8))
    out = SimulationAgentAdapter().run(state)

    assert out["status"] == "partial" and out["failed"] == 1
    assert [r.experiment_id for r in state.results] == ["e1", "e3"], (
        "results mapped to wrong experiments"
    )
    assert all(r.status == "ok" and r.measurement for r in state.results)
    assert "e2_wet" not in {r.experiment_id for r in state.results}
    failed = [e for e in state.scientific_history if e.event_type == "experiment_failed"]
    assert [e.data["experiment_id"] for e in failed] == ["e2_wet"]
    assert ResearchState.model_validate(state.model_dump(mode="json"))


def test_21_batch_where_everything_fails_is_a_failed_dispatch():
    state = planned_state(
        spec("w1", domain="wet_lab_in_vitro"), spec("w2", domain="wet_lab_in_vitro")
    )
    with pytest.raises(RuntimeError, match="no valid result"):
        SimulationAgentAdapter().run(state)
    assert state.results == []


def test_21_unsafe_configuration_produces_no_accepted_output_for_any_member():
    state = planned_state(spec("e1"), spec("e2", 1e8), spec("e3", 1e7))
    with pytest.raises(InvariantViolationError):
        SimulationAgentAdapter(parameter_overrides=UNSAFE_OVERRIDES).run(state)
    assert state.results == [] and state.findings == [] and state.reviews == []
    assert not any(e.event_type == "experiment_executed" for e in state.scientific_history)


# -------------------------------------------------------------------------- TEST 22
def test_22_empty_evidence_is_a_knowledge_gap_not_a_crash():
    """The real literature adapter, offline: retrieval disabled -> a valid, empty response."""
    result = run(max_iterations=1, registry=registry(evidence=LiteratureAgentAdapter()))
    state = result.final_state

    assert result.status != "failed", result.errors
    assert state["evidence"] == []
    assert any("Sparse published" in g for g in state["knowledge_gaps"]), state["knowledge_gaps"]
    first = result.execution_trace[0]
    assert first["agent"] == "evidence" and first["status"] == "success"
    assert state["candidates"], "the loop must carry on from a knowledge gap"


# -------------------------------------------------------------------------- TEST 23
def test_23_no_candidate_never_reaches_the_simulator():
    class NoViableCandidates(FakeCandidateAgent):
        def run(self, state):
            self.call_count += 1
            return {"agent": "candidate", "status": "success", "output_ids": []}

    sim = FakeSimulatorAgent()
    planner = FakePlannerAgent()
    result = run(
        max_iterations=5,
        registry=registry(candidate=NoViableCandidates(), simulation=sim, planner=planner),
    )

    assert sim.call_count == 0 and planner.call_count == 0
    assert result.final_state["candidates"] == [] and result.final_state["results"] == []
    order = agents_in_order(result)
    assert order[:3] == ["evidence", "candidate", "evidence"], "must route back to evidence"
    assert "No viable candidates" in result.execution_trace[2]["routing_reason"]
    assert result.status == "stopped" and any("cycle" in e for e in result.errors)


# -------------------------------------------------------------------------- TEST 24
def test_24_no_useful_experiment_reroutes_then_terminates():
    class NothingToPlan(FakePlannerAgent):
        def run(self, state):
            self.call_count += 1
            return {"agent": "planner", "status": "success", "output_ids": []}

    sim = FakeSimulatorAgent()
    result = run(max_iterations=5, registry=registry(planner=NothingToPlan(), simulation=sim))

    assert sim.call_count == 0, "simulator ran with no experiment to run"
    assert result.final_state["experiments"] == []
    order = agents_in_order(result)
    assert order[order.index("planner") + 1] == "candidate"
    assert (
        "no specs" in result.execution_trace[order.index("planner") + 1]["routing_reason"].lower()
    )
    assert result.status in {"stopped", "failed"} and result.errors


# -------------------------------------------------------------------------- TEST 25
def test_25_failed_dispatch_does_not_mutate_scientific_state():
    class WritesThenCrashes(FakeEvidenceAgent):
        def run(self, state):
            super().run(state)  # writes evidence and a knowledge gap into the live state...
            state.candidates.append(Candidate(candidate_id="cand_half_written"))
            state.iteration += 5
            raise RuntimeError("crashed after partially writing")

    base = run(max_iterations=1)
    before = ScientificSnapshot(base.final_state)
    prior = ResearchState.model_validate(base.final_state)

    result = run(
        max_iterations=3,
        max_failures=1,
        initial_state=prior,
        registry=registry(evidence=WritesThenCrashes()),
    )

    assert result.status == "failed"
    before.assert_unchanged_in(result.final_state, allow_history_events=("campaign_started",))
    assert [t["status"] for t in result.execution_trace] == ["failure"]
    assert result.errors


# -------------------------------------------------------------------------- TEST 26
INVALID_VALUES = [
    (Candidate, {"candidate_id": "c", "confidence": -0.1}),
    (Candidate, {"candidate_id": "c", "confidence": 1.5}),
    (Candidate, {"candidate_id": "c", "confidence": "high"}),
    (Hypothesis, {"hypothesis_id": "h", "statement": "s", "prior_plausibility": 1.2}),
    (Hypothesis, {"hypothesis_id": "h", "statement": "s", "posterior_probability": -0.5}),
    (Finding, {"finding_id": "f", "statement": "s", "confidence": 2.0}),
    (Finding, {"finding_id": "f", "statement": "s", "status": "proven"}),
    (Review, {"review_id": "r", "confidence": -3}),
    (Review, {"review_id": "r", "status": "looks_fine"}),
    (Measurement, {"predicted_inhibition_fraction": 1.7}),
    (Measurement, {"predicted_inhibition_fraction": -0.2}),
    (Measurement, {"predicted_inhibition_fraction": 0.5, "uncertainty": "very"}),
    (
        Evidence,
        {
            "evidence_id": "e",
            "evidence_type": "literature-derived",
            "claim": "c",
            "confidence": 1.5,
        },
    ),
    (Evidence, {"evidence_id": "e", "evidence_type": "hearsay", "claim": "c"}),
]


@pytest.mark.parametrize(("model", "kwargs"), INVALID_VALUES, ids=lambda v: str(v)[:60])
def test_26_out_of_range_or_mistyped_values_are_rejected(model, kwargs):
    with pytest.raises(ValidationError):
        model(**kwargs)


def test_26_assignment_is_validated_too():
    finding = Finding(finding_id="f", statement="s", confidence=0.5)
    with pytest.raises(ValidationError):
        finding.confidence = 3.0
    assert finding.confidence == 0.5


def test_26_boundaries_are_inclusive():
    Candidate(candidate_id="c", confidence=0.0)
    Candidate(candidate_id="c", confidence=1.0)
    Finding(finding_id="f", statement="s", confidence=1.0)


def test_26_real_critic_contract_rejects_bad_confidence():
    from bacteriocin_lab.agents.critic import ClaimUnderReview

    with pytest.raises(ValidationError):
        ClaimUnderReview(claim_id="c", statement="s", asserted_confidence=-0.1)
    with pytest.raises(ValidationError):
        ClaimUnderReview(claim_id="c", statement="s", asserted_confidence=1.5)


def test_provenance_guard_does_not_depend_on_the_backend_label():
    """A result that merely carries a different `backend` string still cannot claim validation."""
    with pytest.raises(ValueError):
        ResearchStateManager(ResearchState(objective=make_objective())).add_experiment_result(
            result_fixture(evidence_type=EvidenceType.WET_LAB, backend="mystery_box")
        )
