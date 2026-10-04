"""Agent registry enabling clean dependency injection of real and fixture specialist agents."""

from __future__ import annotations

from typing import Any, ClassVar

from .agent_adapters import (
    CandidateAgentAdapter,
    KnowledgeAgent,
    LiteratureAgentAdapter,
    PlannerAgentAdapter,
    ResultAnalysisAgent,
    ScientificCriticAgent,
    SimulationAgentAdapter,
)
from .fakes import (
    FakeAnalysisAgent,
    FakeCandidateAgent,
    FakeCriticAgent,
    FakeEvidenceAgent,
    FakeKnowledgeAgent,
    FakePlannerAgent,
    FakeSimulatorAgent,
)


class AgentRegistry:
    """Holds and resolves callable specialist agents for each step of the discovery loop."""

    def __init__(
        self,
        evidence: Any = None,
        candidate: Any = None,
        planner: Any = None,
        simulation: Any = None,
        analysis: Any = None,
        critic: Any = None,
        knowledge: Any = None,
    ) -> None:
        self._agents: dict[str, Any] = {
            "evidence": evidence,
            "candidate": candidate,
            "planner": planner,
            "simulation": simulation,
            "analysis": analysis,
            "critic": critic,
            "knowledge": knowledge,
        }

    def register(self, role: str, agent: Any) -> None:
        self._agents[role] = agent

    _ALIASES: ClassVar[dict[str, str]] = {
        "literature_evidence": "evidence",
        "literature": "evidence",
        "candidate_generation": "candidate",
        "candidate_agent": "candidate",
        "experiment_planner": "planner",
        "simulation_runner": "simulation",
        "simulation_agent": "simulation",
        "result_analysis": "analysis",
        "scientific_critic": "critic",
        "research_state": "knowledge",
    }

    def canonical_role(self, role: str) -> str:
        return self._ALIASES.get(role, role)

    def has(self, role: str) -> bool:
        """True if an agent is registered for ``role`` (aliases accepted)."""
        return self._agents.get(self.canonical_role(role)) is not None

    def get(self, role: str) -> Any:
        canonical = self.canonical_role(role)
        agent = self._agents.get(canonical)
        if agent is None:
            raise KeyError(f"No agent registered for role '{role}' (canonical: '{canonical}')")
        return agent

    @classmethod
    def default(cls) -> AgentRegistry:
        """Construct the registry used outside tests.

        Evidence, candidate, planner and simulation call the real specialist agents. Analysis, critic
        and knowledge are the orchestration layer's own built-in implementations, NOT the agents in
        ``bacteriocin_lab.agents.analysis`` / ``.critic`` / ``.knowledge`` (see TECH_DEBT.md, item 1).
        """
        return cls(
            evidence=LiteratureAgentAdapter(),
            candidate=CandidateAgentAdapter(),
            planner=PlannerAgentAdapter(),
            simulation=SimulationAgentAdapter(),
            analysis=ResultAnalysisAgent(),
            critic=ScientificCriticAgent(),
            knowledge=KnowledgeAgent(),
        )

    @classmethod
    def fixture(
        cls,
        evidence: Any = None,
        candidate: Any = None,
        planner: Any = None,
        simulation: Any = None,
        analysis: Any = None,
        critic: Any = None,
        knowledge: Any = None,
    ) -> AgentRegistry:
        """Construct registry using deterministic fake agents for fast, offline testing."""
        return cls(
            evidence=evidence or FakeEvidenceAgent(),
            candidate=candidate or FakeCandidateAgent(),
            planner=planner or FakePlannerAgent(),
            simulation=simulation or FakeSimulatorAgent(),
            analysis=analysis or FakeAnalysisAgent(),
            critic=critic or FakeCriticAgent(),
            knowledge=knowledge or FakeKnowledgeAgent(),
        )
