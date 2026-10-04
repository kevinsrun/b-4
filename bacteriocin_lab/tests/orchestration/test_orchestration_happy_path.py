"""TEST 3: Happy-path end-to-end loop.

Verifies the canonical execution sequence:
Evidence -> Candidate -> Planner -> Simulator -> Analysis -> Critic -> Knowledge.
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


def test_happy_path_end_to_end_loop() -> None:
    # Set up deterministic fixture agents with approval from critic
    registry = AgentRegistry(
        evidence=FakeEvidenceAgent(),
        candidate=FakeCandidateAgent(),
        planner=FakePlannerAgent(),
        simulation=FakeSimulatorAgent(),
        analysis=FakeAnalysisAgent(),
        critic=FakeCriticAgent(forced_status="approved"),
        knowledge=FakeKnowledgeAgent(),
    )

    objective = ResearchObjective(
        goal="Find a promising bacteriocin candidate against Target X.",
        target={"species": "Listeria monocytogenes", "gram": "positive"},
        desired_behavior={"high_inhibition": True},
    )

    # Stop after 1 full cycle (when iteration reaches 1)
    result = run_discovery(
        objective=objective,
        max_iterations=1,
        registry=registry,
        seed=100,
    )

    # 1. Assert status
    assert result.status in ("completed", "max_iterations")
    assert result.iterations_completed == 1

    # 2. Assert agent execution order in trace
    executed_agents = [
        item["agent"] for item in result.execution_trace if item["status"] == "success"
    ]
    expected_prefix = [
        "evidence",
        "candidate",
        "planner",
        "simulation",
        "analysis",
        "critic",
        "knowledge",
    ]
    assert executed_agents[:7] == expected_prefix

    # 3. Assert final state content
    final_state = result.final_state
    assert len(final_state["candidates"]) >= 1
    assert len(final_state["hypotheses"]) >= 1
    assert len(final_state["experiments"]) >= 1
    assert len(final_state["results"]) >= 1
    assert len(final_state["findings"]) >= 1
    assert len(final_state["reviews"]) >= 1

    # Check IDs and data flow
    cand_id = final_state["candidates"][0]["candidate_id"]
    exp = final_state["experiments"][0]
    res = final_state["results"][0]
    finding = final_state["findings"][0]
    review = final_state["reviews"][0]

    assert exp["candidate_id"] == cand_id
    assert res["experiment_id"] == exp["experiment_id"]
    assert cand_id in finding["candidate_ids"]
    assert review["status"] == "approved"
