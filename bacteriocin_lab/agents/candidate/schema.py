"""Candidate schema: the agent's own request/response types.

These extend the shared contract rather than replacing it. ``CandidateProposal``
is the unit this agent produces; it is deliberately richer than the contract's
output example, which is permitted ("specialized agents may extend this schema").

Every proposal carries ``validation_status``, which this agent can only ever set
to ``"unvalidated"`` or ``"computationally-evaluated"``. Nothing in this module
can mark a candidate experimentally validated -- that requires wet-lab evidence
and is not this agent's call to make (contract rule 9).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bacteriocin_lab.shared.contract import (
    AgentRequestEnvelope,
    Evidence,
    ExtensibleContractModel,
    RecommendedNextAction,
    Uncertainty,
)

from .features import PeptideFeatures, SequenceValidationError, normalise_sequence

#: Where a candidate came from.
CandidateOrigin = Literal["literature", "database", "generated", "modified"]

#: How far a candidate has got through the discovery loop. This agent may set
#: only the first two; "experimentally-validated" exists so downstream agents
#: have a value to use, and is never written here.
ValidationStatus = Literal[
    "unvalidated",
    "computationally-evaluated",
    "experimentally-validated",
]

#: Bacteriocin class vocabulary. Kept permissive -- classification schemes for
#: bacteriocins are still contested in the literature, so an unrecognised label
#: is accepted and passed through rather than rejected.
KNOWN_CLASSES = frozenset(
    {
        "class_i",
        "lantibiotic",
        "class_ii",
        "class_iia",
        "class_iib",
        "class_iic",
        "class_iid",
        "class_iii",
        "class_iv",
        "lasso_peptide",
        "sactipeptide",
        "glycocin",
        "circular",
        "microcin",
        "colicin",
        "unknown",
    }
)


class CandidateFeatures(ExtensibleContractModel):
    """Everything known or predicted about a candidate's properties.

    ``computed`` holds this agent's deterministic calculations. The remaining
    fields hold curated knowledge that arrived with the input, so the two
    provenance classes stay distinguishable (contract rule 8).
    """

    computed: PeptideFeatures | None = Field(
        default=None, description="model-predicted, from the primary sequence."
    )
    bacteriocin_class: str | None = Field(default=None, description="literature/database-derived.")
    producing_organism: str | None = None
    known_targets: list[str] = Field(
        default_factory=list, description="Species reported as susceptible in the source."
    )
    known_non_targets: list[str] = Field(
        default_factory=list, description="Species reported as NOT susceptible."
    )
    structural_features: list[str] = Field(default_factory=list)
    known_stability: dict[str, Any] = Field(
        default_factory=dict,
        description="e.g. {'ph_stable_range': [2.0, 8.0], 'thermostable': true}.",
    )
    environmental_sensitivity: list[str] = Field(
        default_factory=list, description="e.g. 'protease-sensitive', 'inactivated above 80C'."
    )
    resistance_concerns: list[str] = Field(
        default_factory=list,
        description="Known or suspected resistance mechanisms in the target.",
    )
    receptor: str | None = Field(
        default=None, description="Known docking/receptor molecule, e.g. 'mannose PTS'."
    )

    @field_validator("bacteriocin_class")
    @classmethod
    def _normalise_class(cls, value: str | None) -> str | None:
        return value.strip().lower().replace("-", "_").replace(" ", "_") if value else value


class ScoreBreakdown(ExtensibleContractModel):
    """Per-objective scores, each in ``[0, 1]``, plus the weighted total.

    Kept explicit so that a ranking can be argued with. A reviewer who disagrees
    with the weighting can recombine these components without re-running
    anything.
    """

    promise: float = Field(ge=0.0, le=1.0, description="Predicted biological usefulness.")
    novelty: float = Field(ge=0.0, le=1.0, description="Dissimilarity to what has been tested.")
    uncertainty: float = Field(ge=0.0, le=1.0, description="Epistemic uncertainty about activity.")
    information_gain: float = Field(
        ge=0.0, le=1.0, description="Expected reduction in uncertainty if tested."
    )
    hypothesis_discrimination: float = Field(
        ge=0.0, le=1.0, description="Power to separate competing hypotheses."
    )
    condition_fit: float = Field(
        ge=0.0, le=1.0, description="Match between known stability and requested conditions."
    )
    total: float = Field(ge=0.0, le=1.0)
    rationale: list[str] = Field(
        default_factory=list, description="Human-readable reasons behind the component scores."
    )


class TestableHypothesis(ExtensibleContractModel):
    """A falsifiable prediction tied to one candidate and one target.

    ``falsified_if`` is the point of this type. A hypothesis that cannot be
    contradicted by a simulation result cannot move the loop forward.
    """

    hypothesis_id: str
    statement: str
    candidate_id: str
    target_species: str
    predicted_direction: Literal["inhibition", "no-effect", "conditional"] = "inhibition"
    predicted_inhibition_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    falsified_if: str = Field(description="The observation that would refute this hypothesis.")
    key_conditions: dict[str, Any] = Field(
        default_factory=dict, description="Conditions the prediction is conditional on."
    )
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_type: Literal["inferred-hypothesis"] = "inferred-hypothesis"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class CandidateProposal(ExtensibleContractModel):
    """One proposed candidate. Never a claim that the candidate works."""

    candidate_id: str
    origin: CandidateOrigin
    name: str | None = None
    sequence: str | None = None
    features: CandidateFeatures = Field(default_factory=CandidateFeatures)
    hypothesis: str = Field(default="", description="One-line summary; detail in hypotheses[].")
    hypotheses: list[TestableHypothesis] = Field(default_factory=list)
    expected_strengths: list[str] = Field(default_factory=list)
    expected_failure_modes: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence that this is worth testing -- NOT that it is active.",
    )
    score: ScoreBreakdown | None = None
    rank: int | None = Field(default=None, ge=1)
    validation_status: ValidationStatus = "unvalidated"
    derived_from_candidate_id: str | None = Field(
        default=None, description="Set when origin == 'modified'."
    )
    parent_candidate_id: str | None = Field(
        default=None, description="Alias of derived_from_candidate_id for modified candidates."
    )
    modifications: list[str] = Field(
        default_factory=list, description="Described changes for 'modified'/'generated' origins."
    )
    sequence_verified: bool = Field(
        default=False,
        description="True only when the sequence was checked against an authoritative database.",
    )

    @field_validator("sequence")
    @classmethod
    def _check_sequence(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return normalise_sequence(value)
        except SequenceValidationError as exc:
            raise ValueError(str(exc)) from exc

    @model_validator(mode="after")
    def _check_identity_and_status(self) -> CandidateProposal:
        if not self.sequence and not self.name:
            raise ValueError("A candidate must have a sequence or a name")
        if self.validation_status == "experimentally-validated":
            raise ValueError(
                "The candidate generation agent must never emit "
                "validation_status='experimentally-validated'; that requires wet-lab evidence"
            )
        if self.origin == "modified":
            if not self.derived_from_candidate_id and not self.parent_candidate_id:
                raise ValueError("origin='modified' requires derived_from_candidate_id")
            if not self.derived_from_candidate_id and self.parent_candidate_id:
                self.derived_from_candidate_id = self.parent_candidate_id
            elif self.derived_from_candidate_id and not self.parent_candidate_id:
                self.parent_candidate_id = self.derived_from_candidate_id
        return self


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class DesiredBehavior(ExtensibleContractModel):
    """What the objective asks for, including the conditions it must hold under."""

    high_inhibition: bool = True
    ph_range: tuple[float, float] | None = None
    temperature_c: float | None = None
    target_cell_density: float | None = Field(
        default=None, ge=0.0, description="CFU/mL. A real variable, not a detail."
    )
    target_cell_density_unit: str | None = "CFU/mL"
    medium: str | None = None
    incubation_time_h: float | None = Field(default=None, ge=0.0)
    assay_domain: str = "simulated_in_vitro"
    avoid_resistance_mechanisms: list[str] = Field(default_factory=list)

    @field_validator("ph_range")
    @classmethod
    def _check_ph_range(cls, value: tuple[float, float] | None) -> tuple[float, float] | None:
        if value is None:
            return None
        low, high = value
        if not (0.0 <= low <= 14.0 and 0.0 <= high <= 14.0):
            raise ValueError(f"ph_range values must be within 0-14, got {value}")
        if low > high:
            raise ValueError(f"ph_range is inverted: {value}")
        return value


class CandidateTarget(ExtensibleContractModel):
    """The organism to act against.

    Named ``organism`` to match the contract's input example for this agent,
    while the shared ``ExperimentTarget`` uses ``species``. The mismatch is
    recorded in docs/proposed-contract-changes.md rather than resolved here.
    """

    organism: str
    strain: str | None = None
    known_resistance_factors: list[str] = Field(default_factory=list)
    gram: Literal["positive", "negative", "unknown"] = "unknown"

    @field_validator("organism")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("target.organism must not be empty")
        return value.strip()


class ScoringWeights(ExtensibleContractModel):
    """Weights for combining score components.

    The defaults deliberately do not put everything on ``promise``: the brief
    asks for a balance between biological usefulness and information gain, so
    roughly half the weight sits on the exploratory terms.
    """

    promise: float = Field(default=0.35, ge=0.0)
    novelty: float = Field(default=0.15, ge=0.0)
    uncertainty: float = Field(default=0.05, ge=0.0)
    information_gain: float = Field(default=0.20, ge=0.0)
    hypothesis_discrimination: float = Field(default=0.10, ge=0.0)
    condition_fit: float = Field(default=0.15, ge=0.0)

    @model_validator(mode="after")
    def _check_nonzero(self) -> ScoringWeights:
        if self.total() <= 0:
            raise ValueError("At least one scoring weight must be positive")
        return self

    def total(self) -> float:
        return (
            self.promise
            + self.novelty
            + self.uncertainty
            + self.information_gain
            + self.hypothesis_discrimination
            + self.condition_fit
        )

    def normalised(self) -> dict[str, float]:
        total = self.total()
        return {name: value / total for name, value in self.model_dump().items()}


class CandidateConstraints(ExtensibleContractModel):
    """Limits on what the agent may return."""

    max_candidates: int = Field(default=10, ge=1, le=500)
    min_total_score: float = Field(default=0.0, ge=0.0, le=1.0)
    allowed_origins: list[CandidateOrigin] | None = None
    min_sequence_length: int | None = Field(default=None, ge=1)
    max_sequence_length: int | None = Field(default=None, ge=1)
    exclude_candidate_ids: list[str] = Field(default_factory=list)
    require_known_sequence: bool = Field(
        default=False, description="Drop candidates with no sequence."
    )
    allow_sequence_modification: bool = Field(
        default=False,
        description="Enable the inverse-design stretch goal (conservative variants).",
    )
    max_modified_candidates: int = Field(default=3, ge=0)
    diversity_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="0 ranks by score alone; higher values trade score for a more diverse set.",
    )
    scoring_weights: ScoringWeights = Field(default_factory=ScoringWeights)

    @model_validator(mode="after")
    def _check_lengths(self) -> CandidateConstraints:
        lo, hi = self.min_sequence_length, self.max_sequence_length
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"min_sequence_length ({lo}) exceeds max_sequence_length ({hi})")
        return self


class CompetingHypothesis(ExtensibleContractModel):
    """A hypothesis already on the table that the next experiment could settle.

    ``discriminating_feature`` names the candidate feature whose value separates
    this hypothesis from its rivals -- for example ``"net_charge"`` for a
    hypothesis that electrostatic association is rate-limiting.
    """

    hypothesis_id: str
    statement: str
    discriminating_feature: str | None = None
    #: Feature values this hypothesis predicts are favourable, as (low, high).
    favourable_range: tuple[float, float] | None = None
    status: Literal["open", "supported", "contradicted"] = "open"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class CandidateRequest(AgentRequestEnvelope):
    """Full input for this agent: the common envelope plus its own fields."""

    target: CandidateTarget
    desired_behavior: DesiredBehavior = Field(default_factory=DesiredBehavior)
    constraints: CandidateConstraints = Field(default_factory=CandidateConstraints)  # type: ignore[assignment]
    competing_hypotheses: list[CompetingHypothesis] = Field(default_factory=list)
    candidate_pool: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Caller-supplied candidate records, merged with the knowledge source.",
    )


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class CandidateGenerationResult(BaseModel):
    """The agent's payload, carried in ``AgentResponseEnvelope.decision``."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    candidates: list[CandidateProposal]
    selection_logic: str
    uncertainties: list[Uncertainty] = Field(default_factory=list)
    recommended_next_action: RecommendedNextAction | None = None
    considered_count: int = Field(
        default=0, ge=0, description="Candidates evaluated before filtering and ranking."
    )
    rejected: list[dict[str, Any]] = Field(
        default_factory=list, description="What was dropped and why, for auditability."
    )
    evidence: list[Evidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model_version: str | None = None


__all__ = [
    "KNOWN_CLASSES",
    "CandidateConstraints",
    "CandidateFeatures",
    "CandidateGenerationResult",
    "CandidateOrigin",
    "CandidateProposal",
    "CandidateRequest",
    "CandidateTarget",
    "CompetingHypothesis",
    "DesiredBehavior",
    "ScoreBreakdown",
    "ScoringWeights",
    "TestableHypothesis",
    "ValidationStatus",
]
