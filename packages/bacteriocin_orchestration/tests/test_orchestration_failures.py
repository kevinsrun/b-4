"""TEST 7: Agent failure mid-run.

Verifies that when an agent raises an exception:
- Prior state remains intact
- Failure is logged with sanitized error
- Candidate/hypothesis history is preserved
- Consecutive failure counter stops gracefully after max_failures
"""

from __future__ import annotations

from orchestration import ResearchObjective, run_discovery
from orchestration.fakes import (
    FakeAnalysisAgent,
    FakeCandidateAgent,
    FakeCriticAgent,
    FakeEvidenceAgent,
    FakeKnowledgeAgent,
    FakePlannerAgent,
    FakeSimulatorAgent,
)
from orchestration.registry import AgentRegistry


def test_agent_failure_mid_run() -> None:
    # Set simulator to raise an unhandled exception
    simulator = FakeSimulatorAgent(should_fail=True)

    registry = AgentRegistry(
        evidence=FakeEvidenceAgent(),
        candidate=FakeCandidateAgent(),
        planner=FakePlannerAgent(),
        simulation=simulator,
        analysis=FakeAnalysisAgent(),
        critic=FakeCriticAgent(),
        knowledge=FakeKnowledgeAgent(),
    )

    objective = ResearchObjective(
        goal="Discover a bacteriocin candidate.",
        target={"species": "Listeria monocytogenes"},
    )

    max_failures = 2
    result = run_discovery(
        objective=objective,
        max_iterations=5,
        max_failures=max_failures,
        registry=registry,
        seed=77,
    )

    # 1. Workflow stopped gracefully with status failed
    assert result.status == "failed"

    # 2. Prior state (candidates, hypotheses, experiments) remains intact
    final_state = result.final_state
    assert len(final_state["candidates"]) >= 1, (
        "Candidates must not be lost upon simulation failure"
    )
    assert len(final_state["hypotheses"]) >= 1, (
        "Hypotheses must not be lost upon simulation failure"
    )
    assert len(final_state["experiments"]) >= 1, "Planned experiment spec must not be lost"
    # No partial/invalid result was committed
    assert len(final_state["results"]) == 0

    # 3. Failure is recorded in execution trace
    sim_traces = [t for t in result.execution_trace if t["agent"] == "simulation"]
    assert len(sim_traces) >= 1
    assert sim_traces[0]["status"] == "failure"
    assert "convergence failure" in sim_traces[0]["error"]

    # 4. Errors are recorded in result.errors
    assert any("Simulation engine encountered ODE convergence failure" in e for e in result.errors)
    assert any("max consecutive failures" in e for e in result.errors)
