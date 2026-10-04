"""TEST 5: Branching on different result.

Proves that workflow routing and scientific decisions depend on evidence outcomes,
not on a hard-coded sequence.
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


def test_branching_on_different_simulation_outcomes() -> None:
    objective = ResearchObjective(
        goal="Discover an active bacteriocin.",
        target={"species": "Listeria monocytogenes"},
    )

    # Scenario A: High inhibition -> Critic requests density follow-up -> Routes to Planner / Evidence
    registry_a = AgentRegistry(
        evidence=FakeEvidenceAgent(),
        candidate=FakeCandidateAgent(),
        planner=FakePlannerAgent(),
        simulation=FakeSimulatorAgent(outcome_fn=lambda spec: (0.95, 0.02)),  # High inhibition
        analysis=FakeAnalysisAgent(),
        critic=FakeCriticAgent(),  # Natural critic evaluates high inhibition
        knowledge=FakeKnowledgeAgent(),
    )

    result_a = run_discovery(
        objective=objective,
        max_iterations=1,
        registry=registry_a,
        seed=1,
    )

    # Scenario B: Low inhibition -> Finding contradicted -> Critic rejects candidate -> Routes to candidate
    registry_b = AgentRegistry(
        evidence=FakeEvidenceAgent(),
        candidate=FakeCandidateAgent(),
        planner=FakePlannerAgent(),
        simulation=FakeSimulatorAgent(outcome_fn=lambda spec: (0.15, 0.05)),  # Low inhibition
        analysis=FakeAnalysisAgent(),
        critic=FakeCriticAgent(),  # Natural critic rejects contradicted candidate
        knowledge=FakeKnowledgeAgent(),
    )

    result_b = run_discovery(
        objective=objective,
        max_iterations=1,
        registry=registry_b,
        seed=1,
    )

    # Inspect traces and reviews
    trace_a = [t["agent"] for t in result_a.execution_trace]
    trace_b = [t["agent"] for t in result_b.execution_trace]

    # Verify that the two runs produced distinct scientific routes or findings
    reviews_a = result_a.final_state.get("reviews", [])
    reviews_b = result_b.final_state.get("reviews", [])

    assert reviews_a and reviews_b
    status_a = reviews_a[0]["status"]
    status_b = reviews_b[0]["status"]

    assert status_a != status_b, f"Scenario A and B should diverge: got {status_a} vs {status_b}"
    # Scenario A was approved or needs_more_evidence; Scenario B was rejected
    assert status_b == "rejected"

    # Execution traces must differ in routing decisions or subsequent agents
    assert trace_a != trace_b or [t["routing_reason"] for t in result_a.execution_trace] != [
        t["routing_reason"] for t in result_b.execution_trace
    ]
