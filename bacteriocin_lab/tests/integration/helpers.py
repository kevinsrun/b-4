"""Deterministic fixtures for the system-reliability tests.

The orchestrator, router, state manager and loop guards under test are the real ones. Only the
specialist agents are fixtures, and they implement the real interface: ``run(state) -> dict``.
"""

from __future__ import annotations

from typing import Any

from bacteriocin_lab.orchestration import ResearchObjective, ResearchState
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
from bacteriocin_lab.orchestration.workflow import run_discovery

__all__ = [
    "FakeAnalysisAgent",
    "FakeCandidateAgent",
    "FakeCriticAgent",
    "FakeEvidenceAgent",
    "FakeKnowledgeAgent",
    "FakePlannerAgent",
    "FakeSimulatorAgent",
    "ScientificSnapshot",
    "ScriptedAnalysis",
    "ScriptedCritic",
    "ScriptedSimulator",
    "agents_in_order",
    "make_objective",
    "registry",
    "run",
]


def make_objective(density: float = 1e8) -> ResearchObjective:
    return ResearchObjective(
        goal="Find a bacteriocin predicted to stay effective against high-density Listeria monocytogenes.",
        target={"species": "Listeria monocytogenes", "gram": "positive"},
        desired_behavior={"high_inhibition": True, "target_cell_density": density, "ph": 7.0},
        constraints={"max_candidates": 3},
    )


def registry(**overrides: Any) -> AgentRegistry:
    return AgentRegistry.fixture(**overrides)


def run(**kwargs: Any):
    kwargs.setdefault("max_iterations", 4)
    kwargs.setdefault("seed", 42)
    objective = kwargs.pop("objective", None) or make_objective()
    reg = kwargs.pop("registry", None) or registry()
    return run_discovery(objective=objective, registry=reg, **kwargs)


def agents_in_order(result) -> list[str]:
    return [t["agent"] for t in result.execution_trace]


class ScriptedCritic(FakeCriticAgent):
    """Critic whose verdict follows a script (the last entry repeats)."""

    def __init__(self, script: list[str]) -> None:
        super().__init__()
        self.script = script

    def run(self, state: ResearchState) -> dict[str, Any]:
        self.forced_status = self.script[min(self.call_count, len(self.script) - 1)]
        return super().run(state)


class ScriptedAnalysis(FakeAnalysisAgent):
    """Analysis whose finding status follows a script (the last entry repeats)."""

    def __init__(self, script: list[str]) -> None:
        super().__init__()
        self.script = script

    def run(self, state: ResearchState) -> dict[str, Any]:
        self.override_finding_status = self.script[min(self.call_count, len(self.script) - 1)]
        return super().run(state)


class ScriptedSimulator(FakeSimulatorAgent):
    """Simulator returning a fixed inhibition fraction for every experiment."""

    def __init__(self, inhibition: float, uncertainty: float = 0.04) -> None:
        super().__init__(outcome_fn=lambda _spec: (inhibition, uncertainty))


SCIENTIFIC_FIELDS = (
    "evidence",
    "candidates",
    "hypotheses",
    "experiments",
    "results",
    "findings",
    "reviews",
    "knowledge_gaps",
    "uncertainties",
    "iteration",
    "tested_candidate_ids",
    "settled_candidate_ids",
)


class ScientificSnapshot:
    """The part of a state that may only change through an accepted scientific event."""

    def __init__(self, state: dict[str, Any]) -> None:
        self.fields = {k: state[k] for k in SCIENTIFIC_FIELDS}
        self.history = list(state["scientific_history"])

    def assert_unchanged_in(
        self, state: dict[str, Any], *, allow_history_events: tuple[str, ...] = ()
    ):
        for k in SCIENTIFIC_FIELDS:
            assert state[k] == self.fields[k], f"scientific field {k!r} changed"
        assert state["scientific_history"][: len(self.history)] == self.history, (
            "history was rewritten"
        )
        extra = state["scientific_history"][len(self.history) :]
        assert [e["event_type"] for e in extra if e["event_type"] not in allow_history_events] == []
