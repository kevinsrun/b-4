"""TEST 4: Critical adaptivity test.

Verifies that experiment 1's result directly drives the selection of a DIFFERENT,
targeted condition in experiment 2.
"""

from __future__ import annotations

from orchestration import ResearchObjective, run_discovery
from orchestration.registry import AgentRegistry


def test_result_changes_next_experiment() -> None:
    """Experiment 1 (low density, high inhibition) causes Experiment 2 to test high density."""
    objective = ResearchObjective(
        goal="Find a bacteriocin robust against high-density Target X.",
        target={"species": "Listeria monocytogenes", "gram": "positive"},
        desired_behavior={"high_inhibition": True, "target_cell_density": 1e8},
    )

    registry = AgentRegistry.fixture()

    # Run for 2 experiment executions (1 cycle with backtrack or 2 iterations)
    result = run_discovery(
        objective=objective,
        max_iterations=2,
        registry=registry,
        seed=42,
    )

    experiments = result.final_state.get("experiments", [])
    assert len(experiments) >= 2, f"Expected at least 2 planned experiments, got {len(experiments)}"

    exp1 = experiments[0]
    exp2 = experiments[1]

    d1 = exp1["conditions"]["target_cell_density"]
    d2 = exp2["conditions"]["target_cell_density"]

    # Assert that experiment 2 is DIFFERENT from experiment 1
    assert exp1["experiment_id"] != exp2["experiment_id"]
    assert d1 != d2, f"Expected different cell densities, got {d1} and {d2}"

    # Assert that experiment 1 was LOW density and experiment 2 adapted to HIGH density
    assert d1 == 1e6, f"Expected initial density 1e6, got {d1}"
    assert d2 == 1e8, f"Expected adaptive follow-up density 1e8, got {d2}"
    assert d2 > d1

    # Assert that the reason for experiment 2 explicitly reflects the density adaptation
    assert (
        "target cell density" in exp2.get("notes", "").lower()
        or "density" in exp2.get("notes", "").lower()
    )
