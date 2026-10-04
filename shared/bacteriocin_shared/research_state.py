"""The persistent scientific state of the discovery programme.

Design rules, in order of importance:

1. **History is never overwritten.** Every status lives next to the chronological
   list of statuses it replaced (``status_history``); every relationship next to the
   relationships it superseded. A field that changes keeps its past.
2. **State is a projection.** ``ResearchState`` is a pure function of an append-only
   list of :class:`StateEvent`; replaying the events reproduces it exactly, so any
   past iteration can be reconstructed and any belief traced to the events that
   caused it.
3. **No new truth is invented here.** Results, specs and evidence are carried as
   the JSON the producing agents emitted (``dict``), so this package never needs to
   import an agent's models and never competes with the shared contract. Evidence
   types are preserved verbatim; nothing in this module can mark anything
   experimentally validated.

All models are JSON-serialisable. IDs are whatever the producing agent used
(``cand_...``, ``exp-0001``, ...); the state does not rename them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"

#: ``open``: never decided. ``supported`` / ``weakened``: the latest decisive result.
#: ``rejected``: weakened strongly or repeatedly (see the manager's policy).
#: An *inconclusive* analysis never changes a hypothesis status -- it is recorded as an
#: observation and the hypothesis is reported as untouched.
HypothesisStatus = Literal["open", "supported", "weakened", "rejected"]
CandidateStatus = Literal["proposed", "under_test", "rejected"]
ExperimentStatus = Literal["planned", "completed", "failed"]
QuestionStatus = Literal["open", "closed"]
UncertaintyStatus = Literal["active", "resolved"]
AnalysisStatus = Literal["supported", "weakened", "inconclusive"]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


class StateEvent(BaseModel):
    """One immutable fact appended to the log.

    Event-specific fields sit flat on the event (``extra="allow"``), so an event reads
    like ``{"iteration": 7, "event": "hypothesis_update", "hypothesis_id": "H12",
    "previous_status": "supported", "new_status": "weakened",
    "triggered_by": ["experiment:E17", "finding:F22"]}``.
    ``prev_hash`` / ``event_hash`` chain the log so that rewriting history is detectable.
    """

    model_config = ConfigDict(extra="allow", protected_namespaces=())

    event_id: str
    seq: int = Field(ge=1)
    iteration: int = Field(ge=0)
    timestamp: str
    event: str
    triggered_by: list[str] = Field(default_factory=list)
    prev_hash: str | None = None
    event_hash: str = ""


class StatusChange(_Record):
    """One entry of a status timeline. ``previous_status`` is None for the first."""

    event_id: str
    iteration: int
    timestamp: str
    previous_status: str | None = None
    new_status: str
    triggered_by: list[str] = Field(default_factory=list)
    reason: str = ""
    evidence_strength: str | None = None
    confidence: float | None = None


class ObjectiveRevision(_Record):
    event_id: str
    iteration: int
    objective: dict[str, Any]


class CandidateRecord(_Record):
    candidate_id: str
    name: str | None = None
    origin: str | None = None
    sequence: str | None = None
    bacteriocin_class: str | None = None
    #: Never "experimentally-validated" without wet-lab-derived evidence; see the manager's guard.
    validation_status: str = "unvalidated"
    status: CandidateStatus = "proposed"
    status_history: list[StatusChange] = Field(default_factory=list)
    rank_history: list[dict[str, Any]] = Field(
        default_factory=list
    )  # iteration, rank, score, event_id
    hypothesis_ids: list[str] = Field(default_factory=list)
    experiment_ids: list[str] = Field(default_factory=list)
    expected_failure_modes: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    registered_event_id: str = ""
    registered_iteration: int = 0
    implicit: bool = (
        False  # created from a result/analysis rather than registered by the candidate agent
    )
    rejection_reason: str | None = None


class HypothesisRecord(_Record):
    hypothesis_id: str
    statement: str = ""
    candidate_id: str | None = None
    falsified_if: str | None = None
    predicted_inhibition_fraction: float | None = None
    status: HypothesisStatus = "open"
    status_history: list[StatusChange] = Field(default_factory=list)
    #: Every analysis of this hypothesis, including inconclusive ones that changed nothing.
    observations: list[dict[str, Any]] = Field(default_factory=list)
    n_supporting: int = 0
    n_weakening: int = 0
    n_inconclusive: int = 0
    #: True when decisive results have disagreed, so the current status is not settled.
    contested: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    experiment_ids: list[str] = Field(default_factory=list)
    evidence_basis: dict[str, int] = Field(default_factory=dict)  # evidence_type -> n results
    registered_event_id: str = ""
    registered_iteration: int = 0
    implicit: bool = False
    epistemic_status: str = "inferred hypothesis, not a fact"


class ExperimentRecord(_Record):
    experiment_id: str
    candidate_id: str | None = None
    hypothesis_id: str | None = None
    spec: dict[str, Any] | None = None
    status: ExperimentStatus = "planned"
    result_ids: list[str] = Field(default_factory=list)
    planned_iteration: int = 0
    completed_iteration: int | None = None
    planned_event_id: str = ""
    implicit: bool = False  # no spec was ever recorded; inferred from a result


class ResultRecord(_Record):
    result_id: str
    experiment_id: str
    candidate_id: str | None = None
    evidence_type: str = "simulation-derived"
    model_version: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    finding_ids: list[str] = Field(default_factory=list)
    iteration: int = 0
    event_id: str = ""
    result_supplied: bool = True  # False when only the analysis's observed block was available


class FindingRecord(_Record):
    finding_id: str
    experiment_id: str
    result_id: str
    candidate_id: str | None = None
    hypothesis_id: str | None = None
    analysis_status: AnalysisStatus = "inconclusive"
    evidence_strength: str | None = None
    confidence: float | None = None
    status_basis: str = ""
    findings: list[dict[str, Any]] = Field(default_factory=list)
    unexpected_results: list[dict[str, Any]] = Field(default_factory=list)
    drivers: list[dict[str, Any]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    source_evidence_type: str = "simulation-derived"
    analysis_model_version: str | None = None
    iteration: int = 0
    event_id: str = ""


class RelationshipRecord(_Record):
    """What is currently believed about how one variable moves a candidate's response."""

    candidate_id: str
    variable: str
    relationship: str | None = (
        None  # positive | negative | none | non_monotonic; None until decisive
    )
    effect_size: float | None = None
    n_confirming: int = 0
    n_unresolved: int = 0
    finding_ids: list[str] = Field(default_factory=list)
    history: list[StatusChange] = Field(default_factory=list)


class EvidenceEntry(_Record):
    evidence_id: str
    evidence_type: str
    claim: str = ""
    source: str | None = None
    confidence: float | None = None
    subject_ids: list[str] = Field(default_factory=list)
    derived_from_evidence_type: str | None = None
    first_seen_iteration: int = 0
    event_id: str = ""
    record: dict[str, Any] = Field(default_factory=dict)


class QuestionRecord(_Record):
    question_id: str
    text: str
    kind: str = "followup"
    status: QuestionStatus = "open"
    related_ids: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    opened_iteration: int = 0
    opened_by: list[str] = Field(default_factory=list)
    closed_iteration: int | None = None
    closed_by: list[str] = Field(default_factory=list)
    close_reason: str | None = None
    history: list[StatusChange] = Field(default_factory=list)


class UncertaintyRecord(_Record):
    uncertainty_id: str
    kind: str = "epistemic"
    severity: str = "medium"
    description: str = ""
    affects: list[str] = Field(default_factory=list)
    scope: str = ""  # "<candidate_id>|<hypothesis_id>" of the analysis that reported it
    first_seen_iteration: int = 0
    last_seen_iteration: int = 0
    occurrences: int = 1
    status: UncertaintyStatus = "active"
    history: list[StatusChange] = Field(default_factory=list)


class ModelVersionRecord(_Record):
    name: str
    components: list[str] = Field(default_factory=list)  # e.g. result, analysis, candidate-agent
    first_seen_iteration: int = 0
    last_seen_iteration: int = 0
    occurrences: int = 0


class RankingSnapshot(_Record):
    event_id: str
    iteration: int
    source: str = ""
    ranking: list[dict[str, Any]] = Field(default_factory=list)  # candidate_id, rank, score


class ResearchState(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    schema_version: str = SCHEMA_VERSION
    #: The open loop turn. Starts at 1; advances when an analysis closes a turn.
    iteration: int = 1
    event_count: int = 0
    last_event_hash: str | None = None
    objective: dict[str, Any] = Field(default_factory=dict)
    objective_history: list[ObjectiveRevision] = Field(default_factory=list)
    candidates: dict[str, CandidateRecord] = Field(default_factory=dict)
    hypotheses: dict[str, HypothesisRecord] = Field(default_factory=dict)
    experiments: dict[str, ExperimentRecord] = Field(default_factory=dict)
    results: dict[str, ResultRecord] = Field(default_factory=dict)
    findings: dict[str, FindingRecord] = Field(default_factory=dict)
    relationships: dict[str, RelationshipRecord] = Field(
        default_factory=dict
    )  # key: "candidate_id::variable"
    evidence: dict[str, EvidenceEntry] = Field(default_factory=dict)
    questions: dict[str, QuestionRecord] = Field(default_factory=dict)
    uncertainties: dict[str, UncertaintyRecord] = Field(default_factory=dict)
    model_versions: dict[str, ModelVersionRecord] = Field(default_factory=dict)
    rankings: list[RankingSnapshot] = Field(default_factory=list)

    @property
    def rejected_hypotheses(self) -> list[HypothesisRecord]:
        return [h for h in self.hypotheses.values() if h.status == "rejected"]

    @property
    def rejected_candidates(self) -> list[CandidateRecord]:
        return [c for c in self.candidates.values() if c.status == "rejected"]


class UpdatedResearchState(BaseModel):
    """What an operation returns: the new state plus exactly what changed."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    state: ResearchState
    new_events: list[StateEvent] = Field(default_factory=list)
    hypothesis_transitions: list[dict[str, Any]] = Field(default_factory=list)
    candidate_transitions: list[dict[str, Any]] = Field(default_factory=list)
    relationship_changes: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    previous_event_count: int = 0
    persisted: bool = False


__all__ = [
    "SCHEMA_VERSION",
    "AnalysisStatus",
    "CandidateRecord",
    "CandidateStatus",
    "EvidenceEntry",
    "ExperimentRecord",
    "ExperimentStatus",
    "FindingRecord",
    "HypothesisRecord",
    "HypothesisStatus",
    "ModelVersionRecord",
    "ObjectiveRevision",
    "QuestionRecord",
    "QuestionStatus",
    "RankingSnapshot",
    "RelationshipRecord",
    "ResearchState",
    "ResultRecord",
    "StateEvent",
    "StatusChange",
    "UncertaintyRecord",
    "UncertaintyStatus",
    "UpdatedResearchState",
]
