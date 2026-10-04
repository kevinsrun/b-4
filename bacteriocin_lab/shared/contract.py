"""Shared system contract types.

This module is a faithful implementation of the SHARED SYSTEM CONTRACT owned by
the Omnigent orchestration layer. It is deliberately dependency-free apart from
Pydantic so that every specialist agent can import it without pulling in another
agent's implementation.

Nothing in here is specific to candidate generation. If a field needs to change,
do NOT edit it unilaterally -- record the request in
``docs/proposed-contract-changes.md`` and raise it with the orchestration owner.
See that file for the changes this module's author believes are needed.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Provenance vocabulary
# ---------------------------------------------------------------------------

#: How a piece of information came to exist. Contract rule 8 requires every
#: agent to keep these distinct, and rule 9 forbids presenting any of the
#: non-wet-lab values as experimentally validated.
EvidenceType = Literal[
    "literature-derived",
    "database-derived",
    "model-predicted",
    "simulation-derived",
    "inferred-hypothesis",
    "wet-lab-derived",
]

#: Evidence types that represent a real measurement on real cells. Only these
#: may ever be described as experimentally validated.
EXPERIMENTALLY_VALIDATED_EVIDENCE: frozenset[str] = frozenset({"wet-lab-derived"})

#: The experimental context a measurement belongs to. ``simulated_in_vitro`` is
#: the default backend for the current system.
AssayDomain = Literal[
    "simulated_in_vitro",
    "simulated_in_vivo_like",
    "in_vitro",
    "in_vivo",
]

GrowthPhase = Literal["lag", "early_exponential", "exponential", "late_exponential", "stationary"]


class ContractModel(BaseModel):
    """Base for contract types: strict about unknown fields, JSON-friendly."""

    model_config = ConfigDict(
        extra="forbid", validate_assignment=True, protected_namespaces=()
    )


class ExtensibleContractModel(BaseModel):
    """Base for contract types that specialist agents are allowed to extend.

    The contract says "specialized agents may extend this schema", so these
    models accept extra keys rather than rejecting them.

    ``protected_namespaces`` is cleared because the contract specifies a
    ``model_version`` field, which would otherwise collide with Pydantic's
    reserved ``model_`` prefix. The field name comes from the shared contract
    and is not ours to rename.
    """

    model_config = ConfigDict(
        extra="allow", validate_assignment=True, protected_namespaces=()
    )


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class Evidence(ExtensibleContractModel):
    """A single provenance-carrying claim.

    ``evidence_id`` is persistent: downstream agents reference it rather than
    copying the claim text, so a claim can be re-examined or retracted later.
    """

    evidence_id: str
    evidence_type: EvidenceType
    claim: str = Field(description="What this evidence asserts, in one sentence.")
    source: str | None = Field(
        default=None,
        description="Citation, database accession, or producing agent + model_version.",
    )
    source_uri: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    subject_ids: list[str] = Field(
        default_factory=list,
        description="Persistent IDs this evidence is about (candidate_id, hypothesis_id, ...).",
    )
    retrieved_at: str | None = None
    notes: str | None = None

    @property
    def is_experimentally_validated(self) -> bool:
        return self.evidence_type in EXPERIMENTALLY_VALIDATED_EVIDENCE


# ---------------------------------------------------------------------------
# Common envelope (input)
# ---------------------------------------------------------------------------


class AgentRequestEnvelope(ExtensibleContractModel):
    """The common input shape every agent accepts.

    Agents may require additional specialised fields; they arrive as extra keys
    and each agent is responsible for validating its own additions.
    """

    research_objective: dict[str, Any] = Field(default_factory=dict)
    research_state: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    previous_results: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Common envelope (output)
# ---------------------------------------------------------------------------


class RecommendedNextAction(ExtensibleContractModel):
    """Advice for Omnigent. Advisory only -- the orchestrator decides."""

    agent: str
    reason: str = ""
    payload_hint: dict[str, Any] = Field(default_factory=dict)


class Uncertainty(ExtensibleContractModel):
    """An explicit statement of what this agent does not know.

    Contract rule 4 requires explicit uncertainty. Free-form strings are also
    accepted on output for readability; see ``AgentResponseEnvelope``.
    """

    kind: Literal["aleatoric", "epistemic", "data-gap", "model-limitation", "contract-gap"]
    description: str
    affects: list[str] = Field(default_factory=list, description="Persistent IDs affected.")
    severity: Literal["low", "medium", "high"] = "medium"


class AgentResponseEnvelope(ExtensibleContractModel):
    """The common output shape every agent returns."""

    agent: str
    decision: dict[str, Any] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    uncertainties: list[str | Uncertainty] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    recommended_next_action: RecommendedNextAction | None = None
    model_version: str | None = None


# ---------------------------------------------------------------------------
# Experiment interface
# ---------------------------------------------------------------------------


class ExperimentTarget(ExtensibleContractModel):
    species: str
    strain: str | None = None
    #: Resistance/susceptibility factors already known for this target.
    known_resistance_factors: list[str] = Field(default_factory=list)


class ExperimentConditions(ExtensibleContractModel):
    """Biological context for one experiment.

    ``target_cell_density`` is a first-class variable, not an afterthought:
    bacteriocin activity is dose-per-cell dependent, so the same concentration
    can inhibit a dilute culture and fail against a dense one.
    """

    bacteriocin_concentration: float | None = Field(
        default=None, ge=0.0, description="Concentration; unit carried in concentration_unit."
    )
    concentration_unit: str | None = Field(
        default=None, description="e.g. 'nM', 'ug/mL', 'IU/mL', 'AU/mL'."
    )
    target_cell_density: float | None = Field(
        default=None, ge=0.0, description="CFU/mL unless target_cell_density_unit says otherwise."
    )
    target_cell_density_unit: str | None = Field(default=None, description="e.g. 'CFU/mL', 'OD600'.")
    producer_cell_density: float | None = Field(default=None, ge=0.0)
    ph: float | None = Field(default=None, ge=0.0, le=14.0)
    temperature_c: float | None = None
    medium: str | None = None
    ionic_conditions: dict[str, Any] = Field(default_factory=dict)
    incubation_time: float | None = Field(default=None, ge=0.0)
    incubation_time_unit: str | None = Field(default=None, description="e.g. 'h', 'min'.")
    growth_phase: GrowthPhase | None = None
    assay_type: str | None = None
    assay_domain: AssayDomain = "simulated_in_vitro"


class ExperimentSpec(ExtensibleContractModel):
    """``run_experiment(ExperimentSpec) -> ExperimentResult``."""

    experiment_id: str
    candidate_id: str
    target: ExperimentTarget
    conditions: ExperimentConditions = Field(default_factory=ExperimentConditions)
    hypothesis_id: str | None = None
    replicates: int = Field(default=1, ge=1)
    notes: str | None = None


class ExperimentMeasurement(ExtensibleContractModel):
    """Continuous readouts preferred over active/inactive labels."""

    predicted_inhibition_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    predicted_survival_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    predicted_activity: float | None = None
    uncertainty: float | None = Field(default=None, ge=0.0)


class ExperimentResult(ExtensibleContractModel):
    """The single shape both the simulation and any future wet-lab adapter return."""

    result_id: str
    experiment_id: str
    candidate_id: str
    conditions: ExperimentConditions = Field(default_factory=ExperimentConditions)
    measurement: ExperimentMeasurement = Field(default_factory=ExperimentMeasurement)
    important_factors: list[str] = Field(default_factory=list)
    evidence_type: EvidenceType = "simulation-derived"
    model_version: str | None = None
    warnings: list[str] = Field(default_factory=list)
    hypothesis_id: str | None = None

    @property
    def is_experimentally_validated(self) -> bool:
        return self.evidence_type in EXPERIMENTALLY_VALIDATED_EVIDENCE


__all__ = [
    "EXPERIMENTALLY_VALIDATED_EVIDENCE",
    "AgentRequestEnvelope",
    "AgentResponseEnvelope",
    "AssayDomain",
    "ContractModel",
    "Evidence",
    "EvidenceType",
    "ExperimentConditions",
    "ExperimentMeasurement",
    "ExperimentResult",
    "ExperimentSpec",
    "ExperimentTarget",
    "ExtensibleContractModel",
    "GrowthPhase",
    "RecommendedNextAction",
    "Uncertainty",
]
