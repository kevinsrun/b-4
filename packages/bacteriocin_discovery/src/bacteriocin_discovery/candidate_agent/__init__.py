"""Candidate Generation & Design Agent.

Proposes ranked bacteriocin candidates and falsifiable hypotheses. Proposes
only -- it never claims a candidate is active.

Typical use from Omnigent::

    from bacteriocin_discovery.candidate_agent import generate_candidates

    response = generate_candidates({
        "target": {"organism": "Listeria monocytogenes", "gram": "positive"},
        "desired_behavior": {"high_inhibition": True, "ph_range": [6.0, 7.5]},
        "constraints": {"max_candidates": 5},
    })
"""

from .agent import AGENT_NAME, MODEL_VERSION, CandidateGenerationAgent, generate_candidates
from .knowledge import (
    EmptyKnowledgeSource,
    InMemoryKnowledgeSource,
    JsonFileKnowledgeSource,
    KnowledgeRecord,
    KnowledgeSource,
    default_knowledge_source,
)
from .schema import (
    CandidateConstraints,
    CandidateGenerationResult,
    CandidateProposal,
    CandidateRequest,
    CandidateTarget,
    CompetingHypothesis,
    DesiredBehavior,
    ScoreBreakdown,
    ScoringWeights,
    TestableHypothesis,
)

__all__ = [
    "AGENT_NAME",
    "MODEL_VERSION",
    "CandidateConstraints",
    "CandidateGenerationAgent",
    "CandidateGenerationResult",
    "CandidateProposal",
    "CandidateRequest",
    "CandidateTarget",
    "CompetingHypothesis",
    "DesiredBehavior",
    "EmptyKnowledgeSource",
    "InMemoryKnowledgeSource",
    "JsonFileKnowledgeSource",
    "KnowledgeRecord",
    "KnowledgeSource",
    "ScoreBreakdown",
    "ScoringWeights",
    "TestableHypothesis",
    "default_knowledge_source",
    "generate_candidates",
]
