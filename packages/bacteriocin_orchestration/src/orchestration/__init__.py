"""Omnigent orchestration and workflow layer for the autonomous bacteriocin-discovery lab."""

from .omnigent_adapter import OmnigentAdapter
from .registry import AgentRegistry
from .router import Router
from .state import ResearchStateManager
from .trace import TraceRecorder
from .types import (
    Candidate,
    Conditions,
    DiscoveryResult,
    Evidence,
    EvidenceRecord,
    EvidenceType,
    ExecutionTraceItem,
    ExperimentResult,
    ExperimentSpec,
    Finding,
    Hypothesis,
    Measurement,
    ResearchObjective,
    ResearchState,
    Review,
    Route,
    ScientificEvent,
    Target,
)
from .workflow import DiscoveryWorkflowEngine, run_discovery

__all__ = [
    "AgentRegistry",
    "Candidate",
    "Conditions",
    "DiscoveryResult",
    "DiscoveryWorkflowEngine",
    "Evidence",
    "EvidenceRecord",
    "EvidenceType",
    "ExecutionTraceItem",
    "ExperimentResult",
    "ExperimentSpec",
    "Finding",
    "Hypothesis",
    "Measurement",
    "OmnigentAdapter",
    "ResearchObjective",
    "ResearchState",
    "ResearchStateManager",
    "Review",
    "Route",
    "Router",
    "ScientificEvent",
    "Target",
    "TraceRecorder",
    "run_discovery",
]

__version__ = "0.1.0"
