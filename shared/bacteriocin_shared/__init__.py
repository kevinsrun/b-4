"""Schemas shared by the B-4 bacteriocin-lab agents.

Only the research-state types live here so far. The contract types
(``ExperimentSpec``, ``ExperimentResult``, the envelopes) are intentionally NOT
here: promoting one package's contract module is a joint decision recorded in
``shared/README.md``, not something to smuggle in alongside a new feature.
"""

from .research_state import (
    CandidateRecord,
    EvidenceEntry,
    ExperimentRecord,
    FindingRecord,
    HypothesisRecord,
    ModelVersionRecord,
    ObjectiveRevision,
    QuestionRecord,
    RankingSnapshot,
    RelationshipRecord,
    ResearchState,
    ResultRecord,
    StateEvent,
    StatusChange,
    UncertaintyRecord,
    UpdatedResearchState,
)

__all__ = [
    "CandidateRecord",
    "EvidenceEntry",
    "ExperimentRecord",
    "FindingRecord",
    "HypothesisRecord",
    "ModelVersionRecord",
    "ObjectiveRevision",
    "QuestionRecord",
    "RankingSnapshot",
    "RelationshipRecord",
    "ResearchState",
    "ResultRecord",
    "StateEvent",
    "StatusChange",
    "UncertaintyRecord",
    "UpdatedResearchState",
]
