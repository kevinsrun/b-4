"""TEST 9 & TEST 10: Loop guards, cycle detection, and max_iterations."""

from __future__ import annotations

from orchestration import ResearchObjective, Route, run_discovery
from orchestration.fakes import (
    FakeAnalysisAgent,
    FakeCandidateAgent,
    FakeCriticAgent,
    FakeEvidenceAgent,
    FakeKnowledgeAgent,
    FakePlannerAgent,
    FakeSimulatorAgent,
)
from orchestration.loop_guards import CycleDetector
from orchestration.registry import AgentRegistry


def test_max_iterations_terminates_cleanly() -> None:
    """TEST 10: Run with max_iterations=2 cleanly terminates after 2 iterations."""
    objective = ResearchObjective(
        goal="Screen bacteriocins.",
        target={"species": "Listeria monocytogenes"},
    )

    registry = AgentRegistry(
        evidence=FakeEvidenceAgent(),
        candidate=FakeCandidateAgent(),
        planner=FakePlannerAgent(),
        simulation=FakeSimulatorAgent(),
        analysis=FakeAnalysisAgent(),
        critic=FakeCriticAgent(forced_status="approved"),
        knowledge=FakeKnowledgeAgent(),
    )

    result = run_discovery(
        objective=objective,
        max_iterations=2,
        registry=registry,
        seed=1,
    )

    # Assert exactly 2 iterations
    assert result.status == "max_iterations"
    assert result.iterations_completed == 2
    assert result.final_state["iteration"] == 2
    assert len(result.errors) == 0


def test_infinite_loop_protection_cycle_detection() -> None:
    """TEST 9: Recurring route cycle (critic -> planner -> critic -> planner...) is caught by loop guards."""
    detector = CycleDetector(max_cycle_repeats=2)

    route_critic = Route(next_agent="critic", reason="Critique findings")
    route_planner = Route(next_agent="planner", reason="Re-plan experiment")

    # Step 1: critic
    detector.record_route(route_critic)
    assert not detector.is_cycle_detected()[0]

    # Step 2: planner
    detector.record_route(route_planner)
    assert not detector.is_cycle_detected()[0]

    # Step 3: critic
    detector.record_route(route_critic)
    assert not detector.is_cycle_detected()[0]

    # Step 4: planner (cycle repeats twice: critic -> planner -> critic -> planner)
    detector.record_route(route_planner)
    is_cycle, reason = detector.is_cycle_detected()
    assert is_cycle
    assert "recurring cycle" in reason.lower()


def test_orchestrator_terminates_on_repeated_cycle() -> None:
    """Ensure that the workflow engine stops when a tight repeated route is forced."""
    objective = ResearchObjective(
        goal="Screen bacteriocins.",
        target={"species": "Listeria monocytogenes"},
    )

    # Force an oscillating cycle between critic and planner:
    # Critic always says experiment_inconclusive -> routes to planner -> simulation -> analysis -> critic...
    critic = FakeCriticAgent(forced_status="experiment_inconclusive")

    registry = AgentRegistry(
        evidence=FakeEvidenceAgent(),
        candidate=FakeCandidateAgent(),
        planner=FakePlannerAgent(),
        simulation=FakeSimulatorAgent(),
        analysis=FakeAnalysisAgent(),
        critic=critic,
        knowledge=FakeKnowledgeAgent(),
    )

    result = run_discovery(
        objective=objective,
        max_iterations=10,  # High iteration ceiling
        registry=registry,
        seed=42,
    )

    # Workflow must terminate before reaching 10 iterations due to cycle detection or per-iteration visit limit
    assert result.status == "stopped"
    assert result.iterations_completed < 10
    assert any(
        "cycle" in e.lower() or "exceeded maximum visits" in e.lower() for e in result.errors
    )
