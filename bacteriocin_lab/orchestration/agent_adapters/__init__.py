"""Agent adapters and implementations for the discovery workflow."""

from .analysis_agent import ResultAnalysisAgent
from .candidate_adapter import CandidateAgentAdapter
from .critic_agent import ScientificCriticAgent
from .knowledge_agent import KnowledgeAgent
from .literature_adapter import LiteratureAgentAdapter
from .planner_adapter import PlannerAgentAdapter
from .real_agents import RealAnalysisAdapter, RealCriticAdapter, RealKnowledgeAdapter
from .simulation_adapter import SimulationAgentAdapter

__all__ = [
    "CandidateAgentAdapter",
    "KnowledgeAgent",
    "LiteratureAgentAdapter",
    "PlannerAgentAdapter",
    "RealAnalysisAdapter",
    "RealCriticAdapter",
    "RealKnowledgeAdapter",
    "ResultAnalysisAgent",
    "ScientificCriticAgent",
    "SimulationAgentAdapter",
]
