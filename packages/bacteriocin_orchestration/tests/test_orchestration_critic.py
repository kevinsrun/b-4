"""TEST 6: Critic rejects result.

Verifies that when the Critic returns needs_more_evidence (or rejection),
the workflow backtracks rather than proceeding directly to knowledge acceptance.
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


def test_critic_rejects_result_triggers_backtrack() -> None:
    critic_agent = FakeCriticAgent(forced_status="needs_more_evidence")

    registry = AgentRegistry(
        evidence=FakeEvidenceAgent(),
        candidate=FakeCandidateAgent(),
        planner=FakePlannerAgent(),
        simulation=FakeSimulatorAgent(),
        analysis=FakeAnalysisAgent(),
        critic=critic_agent,
        knowledge=FakeKnowledgeAgent(),
    )

    objective = ResearchObjective(
        goal="Find a bacteriocin candidate.",
        target={"species": "Listeria monocytogenes"},
    )

    result = run_discovery(
        objective=objective,
        max_iterations=1,
        registry=registry,
        seed=12,
    )

    # 1. Assert workflow did NOT proceed directly to knowledge acceptance after first critic rejection
    trace = result.execution_trace
    critic_indices = [i for i, step in enumerate(trace) if step["agent"] == "critic"]
    assert critic_indices, "Critic was not invoked"

    first_critic_idx = critic_indices[0]
    next_step = trace[first_critic_idx + 1]

    # Expected routing: back to Evidence Agent or Planner
    assert next_step["agent"] in ("evidence", "planner"), (
        f"Expected backtrack to evidence/planner, got {next_step['agent']}"
    )
    assert "more evidence" in next_step["routing_reason"].lower()

    # 2. State remains valid and rejection is preserved
    reviews = result.final_state.get("reviews", [])
    assert any(r["status"] == "needs_more_evidence" for r in reviews)

    # 3. Route is logged in execution trace
    assert next_step["status"] == "success"
