"""TEST 12: Provenance preservation.

Verifies that literature-derived evidence and simulation-derived ExperimentResult
are distinctly maintained in state, and simulation output is never relabeled as wet-lab.
"""

from __future__ import annotations

import pytest

from orchestration import ResearchObjective, run_discovery
from orchestration.registry import AgentRegistry
from orchestration.types import (
    EvidenceType,
    ExperimentResult,
    Measurement,
)


def test_provenance_preservation_and_wet_lab_guard() -> None:
    objective = ResearchObjective(
        goal="Verify provenance preservation.",
        target={"species": "Listeria monocytogenes"},
    )

    result = run_discovery(
        objective=objective,
        max_iterations=1,
        registry=AgentRegistry.fixture(),
        seed=999,
    )

    final_state = result.final_state

    # 1. Assert results are simulation-derived and NOT wet-lab
    results = final_state.get("results", [])
    assert len(results) >= 1
    for r in results:
        assert r["evidence_type"] == "simulation-derived"
        assert r["validated_experimentally"] is False
        assert r["evidence_type"] != "wet-lab-derived"

    # 2. Assert literature / hypothesis claims are preserved with distinct types
    history = final_state.get("scientific_history", [])
    event_types = {e["event_type"] for e in history}
    assert "campaign_started" in event_types
    assert "candidate_proposed" in event_types
    assert "experiment_executed" in event_types

    # 3. Direct schema enforcement: attempting to label a simulation result as wet-lab raises an error
    with pytest.raises(ValueError, match="must not label results as wet-lab-derived"):
        ExperimentResult(
            result_id="res_bad",
            experiment_id="exp_bad",
            candidate_id="cand_test",
            measurement=Measurement(predicted_inhibition_fraction=0.9),
            evidence_type=EvidenceType.WET_LAB,  # Attempting violation!
            backend="simulation",
        )
