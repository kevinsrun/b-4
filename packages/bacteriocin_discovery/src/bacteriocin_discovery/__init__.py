"""Autonomous bacteriocin-discovery system -- shared contract and specialist agents.

This repository currently implements one module of the Omnigent-orchestrated
system: the Candidate Generation & Design Agent. ``contract`` holds the shared
system contract that every agent in the system depends on.
"""

from .contract import (
    AgentRequestEnvelope,
    AgentResponseEnvelope,
    Evidence,
    ExperimentResult,
    ExperimentSpec,
)

__all__ = [
    "AgentRequestEnvelope",
    "AgentResponseEnvelope",
    "Evidence",
    "ExperimentResult",
    "ExperimentSpec",
]

__version__ = "0.1.0"
