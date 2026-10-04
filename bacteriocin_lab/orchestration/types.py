"""Shared types and data contracts for the Omnigent orchestration layer.

Reuses existing schemas from bacteriocin_sim, bacteriocin_discovery, and b4_literature
without defining duplicate schema representations.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Re-use existing canonical schemas from the repository
from bacteriocin_lab.agents.simulator.schemas import (
    CandidateSpec,
    Conditions,
    EvidenceRecord,
    EvidenceType,
    ExperimentResult,
    ExperimentSpec,
    Measurement,
    Target,
)
from bacteriocin_lab.shared.contract import (
    Evidence,
    RecommendedNextAction,
    Uncertainty,
)
from bacteriocin_lab.shared.ids import (
    candidate_id as make_candidate_id,
)
from bacteriocin_lab.shared.ids import (
    content_id,
)
from bacteriocin_lab.shared.ids import (
    evidence_id as make_evidence_id,
)
from bacteriocin_lab.shared.ids import (
    hypothesis_id as make_hypothesis_id,
)
from bacteriocin_lab.shared.ids import (
    run_id as make_run_id,
)

__all__ = [
    "Candidate",
    "CandidateSpec",
    "Conditions",
    "DiscoveryResult",
    "Evidence",
    "EvidenceRecord",
    "EvidenceType",
    "ExecutionTraceItem",
    "ExperimentResult",
    "ExperimentSpec",
    "Finding",
    "Hypothesis",
    "Measurement",
    "OrchestrationError",
    "RecommendedNextAction",
    "ResearchObjective",
    "ResearchState",
    "Review",
    "Route",
    "ScientificEvent",
    "Target",
    "content_id",
    "make_candidate_id",
    "make_evidence_id",
    "make_finding_id",
    "make_hypothesis_id",
    "make_review_id",
    "make_run_id",
]

import hashlib


def make_finding_id(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.blake2b(
        f"bacteriocin-discovery/v1|finding|{blob}".encode(), digest_size=16
    ).hexdigest()[:16]
    return f"find_{digest}"


def make_review_id(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.blake2b(
        f"bacteriocin-discovery/v1|review|{blob}".encode(), digest_size=16
    ).hexdigest()[:16]
    return f"rev_{digest}"


_BASE_CONFIG = ConfigDict(
    extra="allow",
    validate_assignment=True,
    populate_by_name=True,
)


class ResearchObjective(BaseModel):
    """Scientific objective guiding the discovery loop."""

    model_config = _BASE_CONFIG

    goal: str = ""
    target: dict[str, Any] = Field(default_factory=dict)
    desired_behavior: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)

    @property
    def species(self) -> str | None:
        return self.target.get("species") or self.target.get("organism")

    @property
    def strain(self) -> str | None:
        return self.target.get("strain")

    @property
    def gram(self) -> str | None:
        return self.target.get("gram")


class Candidate(BaseModel):
    """Bacteriocin candidate proposal."""

    model_config = _BASE_CONFIG

    candidate_id: str
    name: str = ""
    sequence: str | None = None
    source: str | None = None
    score_total: float = Field(default=0.0, ge=0.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    features: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    falsified_if: str | None = None
    # Shared contract rule 9: Proposals only, unvalidated
    validation_status: str = "unvalidated"
    rank: int = 1


class Hypothesis(BaseModel):
    """Testable scientific hypothesis."""

    model_config = _BASE_CONFIG

    hypothesis_id: str
    candidate_id: str | None = None
    statement: str
    prediction: str | None = None
    predicted_direction: Literal["inhibition", "no-effect", "conditional"] | None = None
    predicted_inhibition_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    expected_relationship: dict[str, Any] | None = None
    key_conditions: dict[str, Any] = Field(default_factory=dict)
    tolerance: float | None = Field(default=None, gt=0.0, le=1.0)
    status: Literal["open", "supported", "contradicted", "weakened", "rejected"] = "open"
    prior_plausibility: float = Field(default=0.5, ge=0.0, le=1.0)
    posterior_probability: float = Field(default=0.5, ge=0.0, le=1.0)
    discriminating_feature: str | None = None
    favourable_range: list[float] | None = None
    falsified_if: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    """Scientific finding produced by the Result Analysis Agent."""

    model_config = _BASE_CONFIG

    finding_id: str
    statement: str
    status: Literal["supported", "contradicted", "weakened", "inconclusive"] = "inconclusive"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    candidate_ids: list[str] = Field(default_factory=list)
    hypothesis_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    result_ids: list[str] = Field(default_factory=list)
    factor_sensitivities: dict[str, float] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
    uncertainties: list[str | Uncertainty] = Field(default_factory=list)
    provenance_note: str | None = None
    analysis_payload: dict[str, Any] = Field(default_factory=dict)


class Review(BaseModel):
    """Scientific critique and safety evaluation produced by Critic Agent."""

    model_config = _BASE_CONFIG

    review_id: str
    status: Literal[
        "approved",
        "needs_more_evidence",
        "experiment_inconclusive",
        "analysis_unsupported",
        "rejected",
    ] = "approved"
    critique: str = ""
    recommendation: dict[str, Any] = Field(default_factory=dict)
    reviewer: str = "scientific_critic"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    issues: list[dict[str, Any]] = Field(default_factory=list)
    required_followups: list[dict[str, Any]] = Field(default_factory=list)
    uncertainties: list[str | Uncertainty] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    critic_payload: dict[str, Any] = Field(default_factory=dict)


class ScientificEvent(BaseModel):
    """Immutable, append-only historical event record."""

    model_config = _BASE_CONFIG

    event_id: str
    event_type: str
    iteration: int
    source_agent: str
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: str | None = None


class OrchestrationError(BaseModel):
    """Machine-readable failure classification retained alongside compatibility strings."""

    model_config = _BASE_CONFIG

    error_type: Literal[
        "cycle_detected",
        "visit_limit",
        "route_validation",
        "unknown_agent",
        "invalid_agent_output",
        "state_integrity",
        "invariant_violation",
        "backend_unavailable",
        "agent_execution",
        "failure_limit",
        "unknown",
    ] = "unknown"
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ExecutionTraceItem(BaseModel):
    """One traceable agent invocation record."""

    model_config = _BASE_CONFIG

    trace_id: str
    iteration: int
    agent: str
    input_ids: list[str] = Field(default_factory=list)
    output_ids: list[str] = Field(default_factory=list)
    routing_reason: str = ""
    status: Literal["success", "failure", "skipped"] = "success"
    error: str | None = None
    error_info: OrchestrationError | None = None
    timestamp: str | None = None


class Route(BaseModel):
    """Explicit structured routing instruction."""

    model_config = _BASE_CONFIG

    next_agent: str
    reason: str
    priority: int = 1
    required_inputs: list[str] = Field(default_factory=list)
    terminal: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)


class ResearchState(BaseModel):
    """Comprehensive state of the autonomous discovery campaign."""

    model_config = _BASE_CONFIG

    objective: ResearchObjective = Field(default_factory=ResearchObjective)
    # Provenance-carrying evidence (literature-derived, database-derived, ...). Simulation output lives in
    # ``results`` and keeps its own evidence_type; the two are never merged or relabelled.
    evidence: list[Evidence] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    experiments: list[ExperimentSpec] = Field(default_factory=list)
    results: list[ExperimentResult] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    reviews: list[Review] = Field(default_factory=list)
    knowledge_gaps: list[str] = Field(default_factory=list)
    uncertainties: list[str | Uncertainty] = Field(default_factory=list)
    iteration: int = 0
    scientific_history: list[ScientificEvent] = Field(default_factory=list)
    tested_candidate_ids: list[str] = Field(default_factory=list)
    settled_candidate_ids: list[str] = Field(default_factory=list)
    # The real Knowledge Agent's shared state is the durable scientific projection. The list-based
    # fields remain the workflow view for compatibility while this bridge is incrementally filled.
    knowledge_state: dict[str, Any] | None = None
    resume_agent: str | None = None
    resume_route: dict[str, Any] | None = None

    @property
    def all_results(self) -> list[ExperimentResult]:
        return list(self.results)

    def get_candidate(self, cid: str) -> Candidate | None:
        for c in self.candidates:
            if c.candidate_id == cid:
                return c
        return None

    def get_hypothesis(self, hid: str) -> Hypothesis | None:
        for h in self.hypotheses:
            if h.hypothesis_id == hid:
                return h
        return None

    def clone(self) -> ResearchState:
        """Create a full deep copy for snapshot preservation."""
        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return json.loads(self.model_dump_json(exclude_none=False))


class DiscoveryResult(BaseModel):
    """Structured result returned by run_discovery."""

    model_config = _BASE_CONFIG

    run_id: str
    status: Literal["completed", "stopped", "max_iterations", "failed"]
    objective: dict[str, Any]
    final_state: dict[str, Any]
    execution_trace: list[dict[str, Any]]
    iterations_completed: int
    # ``errors`` stays as human-readable compatibility text; ``error_details`` is authoritative
    # for machine consumers and avoids forcing downstream clients to parse prose.
    errors: list[str] = Field(default_factory=list)
    error_details: list[OrchestrationError] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.model_dump_json(exclude_none=False))
