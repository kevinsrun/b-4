"""TEST 11: Reproducibility test.

Verifies that identical inputs, seeds, and objectives produce identical routing
sequences, experiment specs, and result payloads.
"""

from __future__ import annotations

from bacteriocin_lab.orchestration import ResearchObjective, run_discovery
from bacteriocin_lab.orchestration.registry import AgentRegistry


def test_reproducibility_identical_runs() -> None:
    objective = ResearchObjective(
        goal="Discover a bacteriocin candidate for Listeria.",
        target={"species": "Listeria monocytogenes", "gram": "positive"},
        desired_behavior={"high_inhibition": True, "target_cell_density": 1e8},
    )

    run_1 = run_discovery(
        objective=objective,
        max_iterations=2,
        seed=12345,
        registry=AgentRegistry.fixture(),
    )

    run_2 = run_discovery(
        objective=objective,
        max_iterations=2,
        seed=12345,
        registry=AgentRegistry.fixture(),
    )

    # 1. Assert identical status and iteration count
    assert run_1.status == run_2.status
    assert run_1.iterations_completed == run_2.iterations_completed

    # 2. Assert identical routing sequence
    trace_1 = [(t["agent"], t["routing_reason"], t["status"]) for t in run_1.execution_trace]
    trace_2 = [(t["agent"], t["routing_reason"], t["status"]) for t in run_2.execution_trace]
    assert trace_1 == trace_2

    # 3. Assert identical experiment specs
    specs_1 = [
        (e["experiment_id"], e["conditions"]) for e in run_1.final_state.get("experiments", [])
    ]
    specs_2 = [
        (e["experiment_id"], e["conditions"]) for e in run_2.final_state.get("experiments", [])
    ]
    assert specs_1 == specs_2

    # 4. Assert identical results
    res_1 = [
        (r["result_id"], r["measurement"]["predicted_inhibition_fraction"])
        for r in run_1.final_state.get("results", [])
    ]
    res_2 = [
        (r["result_id"], r["measurement"]["predicted_inhibition_fraction"])
        for r in run_2.final_state.get("results", [])
    ]
    assert res_1 == res_2
