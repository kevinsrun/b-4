"""Deterministic demo demonstrating adaptive bacteriocin discovery loop execution."""

from __future__ import annotations

import sys

from .registry import AgentRegistry
from .types import ResearchObjective
from .workflow import run_discovery


def run_demo() -> int:
    """Execute the canonical adaptive discovery demo."""
    print("=" * 70)
    print(" B-4 AUTONOMOUS BACTERIOCIN DISCOVERY LAB - ORCHESTRATION DEMO")
    print("=" * 70)

    objective = ResearchObjective(
        goal="Find a bacteriocin candidate robust against high-density Listeria monocytogenes.",
        target={"species": "Listeria monocytogenes", "gram": "positive"},
        desired_behavior={"high_inhibition": True, "target_cell_density": 1e8, "ph": 7.0},
        constraints={"max_candidates": 3},
    )

    print(f"Goal: {objective.goal}")
    print(f"Target: {objective.species} (gram: {objective.gram})")
    print("Desired conditions: high cell density (1e8 CFU/mL)\n")

    registry = AgentRegistry.fixture()

    result = run_discovery(
        objective=objective,
        max_iterations=4,
        max_failures=3,
        seed=42,
        registry=registry,
    )

    print(f"Run ID: {result.run_id}")
    print(f"Status: {result.status}")
    print(f"Iterations completed: {result.iterations_completed}\n")

    print("Execution Trace Log:")
    print("-" * 70)
    for i, step in enumerate(result.execution_trace):
        agent = step.get("agent")
        iteration = step.get("iteration")
        reason = step.get("routing_reason", "")
        status = step.get("status")
        out_ids = step.get("output_ids", [])
        print(
            f"[{i + 1:02d}] iter={iteration} agent={agent:<12} status={status:<8} reason={reason[:45]}"
        )
        if out_ids:
            print(f"     outputs: {out_ids}")
    print("-" * 70)

    final_state = result.final_state
    print("\nScientific History (Append-Only Audit Log):")
    for event in final_state.get("scientific_history", []):
        print(
            f"  * [iter {event.get('iteration')}] {event.get('event_type')}: {event.get('summary')}"
        )

    print("\nSummary Metrics:")
    for k, v in result.summary.items():
        print(f"  {k}: {v}")

    print("=" * 70)
    print(" DEMO COMPLETED SUCCESSFULLY")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(run_demo())
