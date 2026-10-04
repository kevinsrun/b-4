"""Pydantic schemas and data models for target-driven bacteriocin design."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DesignMutation(BaseModel):
    """A discrete amino-acid substitution in a prospective bacteriocin design."""

    model_config = ConfigDict(frozen=True)

    position: int = Field(..., description="1-indexed position in the mature peptide sequence")
    reference: str = Field(
        ..., min_length=1, max_length=1, description="Wild-type reference amino acid"
    )
    alternate: str = Field(
        ..., min_length=1, max_length=1, description="Proposed replacement amino acid"
    )
    origin: Literal["natural_homolog", "conservative_substitution", "model_ranked_substitution"] = (
        Field(..., description="Design source for this mutation")
    )
    supporting_accessions: list[str] = Field(
        default_factory=list, description="Accession numbers of homologs observing this residue"
    )
    rationale: str | None = Field(default=None, description="Hypothesis for this specific mutation")


class DesignRationale(BaseModel):
    """Scientific rationale supporting a computational sequence hypothesis."""

    model_config = ConfigDict(extra="ignore")

    status: str = Field(
        default="hypothesis", description="Always hypothesis for computational designs"
    )
    evidence_ids: list[str] = Field(default_factory=list)
    natural_variant_support: list[str] = Field(default_factory=list)
    expected_properties: list[str] = Field(default_factory=list)


class DesignScoreComponents(BaseModel):
    """Explicit components contributing to candidate ranking score."""

    model_config = ConfigDict(extra="ignore")

    predicted_activity: float = 0.0
    target_match: float = 0.0
    environmental_robustness: float = 0.0
    evidence_quality: float = 0.0
    natural_support: float = 0.0
    novelty_value: float = 0.0
    uncertainty_penalty: float = 0.0
    unsupported_design_penalty: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "predicted_activity": round(self.predicted_activity, 4),
            "target_match": round(self.target_match, 4),
            "environmental_robustness": round(self.environmental_robustness, 4),
            "evidence_quality": round(self.evidence_quality, 4),
            "natural_support": round(self.natural_support, 4),
            "novelty_value": round(self.novelty_value, 4),
            "uncertainty_penalty": round(self.uncertainty_penalty, 4),
            "unsupported_design_penalty": round(self.unsupported_design_penalty, 4),
        }

    def total(self) -> float:
        tot = (
            self.predicted_activity
            + self.target_match
            + self.environmental_robustness
            + self.evidence_quality
            + self.natural_support
            + self.novelty_value
            + self.uncertainty_penalty
            + self.unsupported_design_penalty
        )
        return round(tot, 4)


class DesignedCandidate(BaseModel):
    """A bounded, prospective computational peptide candidate."""

    model_config = ConfigDict(extra="ignore")

    candidate_id: str
    parent_candidate_id: str
    sequence: str
    mutations: list[DesignMutation] = Field(default_factory=list)
    design_class: str = "conservative_variant"
    rationale: DesignRationale = Field(default_factory=DesignRationale)
    provenance: Literal["model-predicted"] = "model-predicted"
    experimentally_validated: Literal[False] = False
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0
    components: dict[str, float] = Field(default_factory=dict)
    generation: int = 1
    critic_verdict: str = "pending"
    critic_notes: list[str] = Field(default_factory=list)
    simulation_metrics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _enforce_computational_provenance(self) -> DesignedCandidate:
        if self.experimentally_validated:
            raise ValueError("Computational designs cannot claim experimental validation")
        if self.provenance != "model-predicted":
            raise ValueError("Designed candidate provenance must be model-predicted")
        return self


class RecommendationItem(BaseModel):
    """Structured candidate recommendation for frontend display."""

    model_config = ConfigDict(extra="ignore")

    tier: Literal["known", "natural_variant", "computational_design"]
    name: str
    score: float
    predicted_inhibition: float
    confidence: str
    evidence_count: int | None = None
    experimentally_validated: bool = False
    candidate_id: str | None = None
    mutations: list[str] = Field(default_factory=list)


class TargetContext(BaseModel):
    """Target environment and assay conditions."""

    model_config = ConfigDict(extra="ignore")

    environment: str = "simulated_in_vitro"
    target_cell_density: float = 1e6
    ph: float = 6.5
    temperature_c: float = 37.0
    incubation_hours: float = 24.0
    bacteriocin_concentration: float = 5.0


class DesiredProperties(BaseModel):
    """Specific desired traits for bacteriocin candidates."""

    model_config = ConfigDict(extra="ignore")

    high_density_activity: bool = False
    broad_activity: bool = False
    prefer_known_bacteriocins: bool = True


class FutureProductionConcept(BaseModel):
    """Non-operational concept for potential future evaluation.

    CRITICAL: Contains NO executable wet-lab or genetic engineering instructions.
    """

    model_config = ConfigDict(extra="ignore")

    status: str = "requires_specialist_review"
    candidate_peptide: str = ""
    producer_compatibility: str = "unknown"
    notes: list[str] = Field(
        default_factory=lambda: [
            "Organism engineering and recombinant expression are out of scope.",
            "Candidate peptide requires specialist biosafety and wet-lab experimental "
            "review before expression testing.",
            "This is a non-operational future-validation concept only.",
        ]
    )


class TargetDesignResult(BaseModel):
    """Top-level structured output of the target-to-bacteriocin design system."""

    model_config = ConfigDict(extra="ignore")

    target: dict[str, Any]
    known_candidates: list[dict[str, Any]] = Field(default_factory=list)
    natural_variant_candidates: list[dict[str, Any]] = Field(default_factory=list)
    designed_candidates: list[DesignedCandidate] = Field(default_factory=list)
    best_current_candidate: dict[str, Any] | None = None
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    uncertainties: list[str] = Field(default_factory=list)
    recommended_next_experiment: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    recommendations: list[RecommendationItem] = Field(default_factory=list)
    future_production_concept: FutureProductionConcept = Field(
        default_factory=FutureProductionConcept
    )
