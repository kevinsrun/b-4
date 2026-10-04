"""Mandatory tests for simulator parameter override validation and fail-closed safety.

Tests 1 to 7 verify that:
1. Valid override passes automatic selftest and produces an ExperimentResult.
2. Invalid override fails closed without producing an ExperimentResult.
3. Failed result never enters ResearchState or generates findings/reviews.
4. Multiple failed invariants are all preserved and reported.
5. Default parameters are unaffected and incur zero validation overhead.
6. Valid overrides produce reproducible results.
7. System never silently falls back to defaults when overrides are invalid.
"""

from __future__ import annotations

import pytest
from bacteriocin_sim import (
    EvidenceType,
    ExperimentResult,
    InvariantViolationError,
    SimulationAgent,
    run_experiment,
    run_experiments,
)
from bacteriocin_sim.selftest import spec
from orchestration import ResearchObjective, run_discovery
from orchestration.types import Candidate, Hypothesis, ResearchState

VALID_OVERRIDE = {
    "targets": {
        "listeria monocytogenes": {"log10_mic_um_base": 1.5}
    }
}

SINGLE_INVALID_OVERRIDE = {
    "targets": {
        "escherichia coli": {"log10_mic_um_base": -2.0},
        "listeria monocytogenes": {"log10_mic_um_base": 4.0},
    }
}

MULTI_INVALID_OVERRIDE = {
    "targets": {
        "escherichia coli": {"log10_mic_um_base": -2.0},
        "listeria monocytogenes": {"log10_mic_um_base": 4.0},
    },
    "classes": {
        "class_IIa_pediocin_like": {"mannose_pts_sensitization": 0.0}
    },
}


def test_1_valid_override_passes() -> None:
    """TEST 1: Valid override runs selftest automatically and produces ExperimentResult."""
    result = run_experiment(spec(), parameter_overrides=VALID_OVERRIDE)

    assert result is not None
    assert isinstance(result, ExperimentResult)
    assert result.status == "ok"
    assert result.evidence_type == EvidenceType.SIMULATION
    assert result.validated_experimentally is False
    assert result.measurement.predicted_mic_um is not None
    assert result.measurement.predicted_mic_um > 0.0


def test_2_invalid_override_fails_closed() -> None:
    """TEST 2: Invalid override fails closed, raising InvariantViolationError without result."""
    with pytest.raises(InvariantViolationError) as exc_info:
        run_experiment(spec(), parameter_overrides=SINGLE_INVALID_OVERRIDE)

    err = exc_info.value
    assert err.code == "invariant_violation"
    assert "gram_negative_is_less_susceptible" in err.failed_invariants
    assert "gram_negative_is_less_susceptible" in err.details["failed_invariants"]
    assert err.details["model_version"]
    assert err.details["parameter_overrides"] == SINGLE_INVALID_OVERRIDE


def test_3_failed_result_never_enters_research_state() -> None:
    """TEST 3: Invariant failure in orchestration preserves state and never adds results."""
    objective = ResearchObjective(
        goal="Test invalid override rejection in workflow",
        target={"species": "Listeria monocytogenes"},
        constraints={"parameter_overrides": SINGLE_INVALID_OVERRIDE},
    )

    initial_state = ResearchState(
        objective=objective,
        candidates=[
            Candidate(
                candidate_id="cand_test_nisin",
                name="Nisin Test",
                sequence="ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            )
        ],
        hypotheses=[
            Hypothesis(
                hypothesis_id="hyp_test_1",
                statement="Nisin inhibits Listeria.",
                status="open",
            )
        ],
    )

    result = run_discovery(
        objective=objective,
        initial_state=initial_state,
        max_iterations=2,
        max_failures=1,
    )

    # 1. State must not have accepted any results
    assert len(result.final_state.get("results", [])) == 0
    # 2. No finding or review should have been generated from an invalid experiment
    assert len(result.final_state.get("findings", [])) == 0
    assert len(result.final_state.get("reviews", [])) == 0
    # 3. Hypotheses must remain open
    assert result.final_state.get("hypotheses", [])[0]["status"] == "open"
    # 4. Candidates must remain intact (including initial candidate)
    candidates = result.final_state.get("candidates", [])
    assert any(c.get("candidate_id") == "cand_test_nisin" for c in candidates)
    # 5. Execution trace must record failure explicitly
    sim_traces = [t for t in result.execution_trace if t.get("agent") == "simulation"]
    assert len(sim_traces) >= 1
    assert sim_traces[0].get("status") == "failure"
    assert "invariant" in str(sim_traces[0].get("error", "")).lower()
    assert len(sim_traces[0].get("output_ids", [])) == 0


def test_4_multiple_failed_invariants() -> None:
    """TEST 4: Multiple failing invariants are all recorded in error details."""
    with pytest.raises(InvariantViolationError) as exc_info:
        run_experiment(spec(), parameter_overrides=MULTI_INVALID_OVERRIDE)

    err = exc_info.value
    failed = set(err.failed_invariants)
    assert "gram_negative_is_less_susceptible" in failed
    assert "class_IIa_needs_the_mannose_pts_receptor" in failed
    assert len(failed) >= 2
    assert err.details["n_failed"] >= 2


def test_5_default_parameters_unaffected() -> None:
    """TEST 5: Normal simulator execution with default parameters remains intact and fast."""
    result = run_experiment(spec())
    assert result.status == "ok"
    assert result.evidence_type == EvidenceType.SIMULATION
    assert result.measurement.predicted_inhibition_fraction is not None

    # Batch execution with no overrides works normally
    batch = run_experiments([spec(), spec(conditions={"ph": 5.5})])
    assert len(batch) == 2
    assert all(r.status == "ok" for r in batch)


def test_6_reproducibility() -> None:
    """TEST 6: Same valid overrides produce identical results."""
    run1 = run_experiment(spec(), parameter_overrides=VALID_OVERRIDE).to_json_dict()
    run2 = run_experiment(spec(), parameter_overrides=VALID_OVERRIDE).to_json_dict()

    run1.pop("created_at", None)
    run2.pop("created_at", None)

    assert run1 == run2


def test_7_no_silent_fallback() -> None:
    """TEST 7: System never falls back to defaults or emits warnings instead of failing."""
    # Single experiment must raise, not return a result
    with pytest.raises(InvariantViolationError):
        run_experiment(spec(), parameter_overrides=SINGLE_INVALID_OVERRIDE)

    # Batch experiments must raise, not return a result
    with pytest.raises(InvariantViolationError):
        run_experiments([spec()], parameter_overrides=SINGLE_INVALID_OVERRIDE)

    # SimulationAgent.selftest classmethod also detects violations explicitly
    report = SimulationAgent.selftest(parameter_overrides=SINGLE_INVALID_OVERRIDE)
    assert report["passed"] is False
    failed_checks = [c["check"] for c in report["checks"] if not c["passed"]]
    assert "gram_negative_is_less_susceptible" in failed_checks
