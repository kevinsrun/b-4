"""TEST 8: Malformed agent output.

Verifies that schema validation catches malformed output, prevents corrupting
ResearchState, and returns structured errors.
"""

from __future__ import annotations

from bacteriocin_lab.orchestration import ResearchObjective, run_discovery
from bacteriocin_lab.orchestration.fakes import (
    FakeAnalysisAgent,
    FakeCandidateAgent,
    FakeCriticAgent,
    FakeEvidenceAgent,
    FakeKnowledgeAgent,
    FakePlannerAgent,
    FakeSimulatorAgent,
)
from bacteriocin_lab.orchestration.registry import AgentRegistry


def test_malformed_agent_output_caught_by_validation() -> None:
    # Set simulator to return malformed output missing required attributes
    simulator = FakeSimulatorAgent(malformed_output=True)

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

    result = run_discovery(
        objective=objective,
        max_iterations=3,
        max_failures=1,
        registry=registry,
        seed=88,
    )

    # 1. Status indicates failure due to malformed output
    assert result.status == "failed"

    # 2. No corrupt/invalid result object was written to ResearchState
    assert len(result.final_state.get("results", [])) == 0

    # 3. Trace records failure with schema validation detail
    sim_traces = [t for t in result.execution_trace if t["agent"] == "simulation"]
    assert len(sim_traces) >= 1
    assert sim_traces[0]["status"] == "failure"
    assert "malformed" in sim_traces[0]["error"].lower()

    # 4. Structured error is returned in result.errors
    assert any("malformed" in e.lower() for e in result.errors)
    assert result.error_details[0].error_type == "agent_execution"
    assert result.error_details[0].retryable is True
    assert sim_traces[0]["error_info"]["error_type"] == "agent_execution"
