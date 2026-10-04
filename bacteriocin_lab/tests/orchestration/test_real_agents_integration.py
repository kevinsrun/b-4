"""Integration test verifying end-to-end execution with real specialist agents from the repository."""

from __future__ import annotations

from bacteriocin_lab.orchestration import ResearchObjective, run_discovery
from bacteriocin_lab.orchestration.registry import AgentRegistry


def test_real_agents_discovery_turn() -> None:
    """Runs a single discovery turn using the real specialist agents (Literature, Candidate, Planner, Sim)."""
    registry = AgentRegistry.default()

    objective = ResearchObjective(
        goal="Discover a bacteriocin against Listeria monocytogenes.",
        target={"species": "Listeria monocytogenes", "gram": "positive"},
        desired_behavior={"high_inhibition": True, "target_cell_density": 1e6},
        constraints={"max_candidates": 2},
    )

    # Execute 1 turn with real agents
    result = run_discovery(
        objective=objective,
        max_iterations=1,
        registry=registry,
        seed=42,
    )

    # Verify execution
    assert result.status in ("completed", "max_iterations")
    assert result.iterations_completed >= 1

    final_state = result.final_state
    assert len(final_state["candidates"]) >= 1
    assert len(final_state["experiments"]) >= 1
    assert len(final_state["results"]) >= 1
    assert len(final_state["findings"]) >= 1
    assert len(final_state["reviews"]) >= 1

    # Verify simulation result properties
    res = final_state["results"][0]
    assert res["evidence_type"] == "simulation-derived"
    assert res["validated_experimentally"] is False
    assert res["measurement"]["predicted_inhibition_fraction"] is not None
