from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RegionType = Literal[
    "signal_peptide",
    "leader_peptide",
    "propeptide",
    "mature_peptide",
    "modification_region",
    "receptor_interaction_region",
    "unknown",
]

VariantType = Literal[
    "missense",
    "synonymous",
    "insertion",
    "deletion",
    "truncation",
    "stop_gain",
    "unknown",
]


class FunctionalEffectHypothesis(BaseModel):
    """Hypothetical functional impact of a sequence variant.

    Never represents experimentally validated claims without wet-lab verification.
    """

    model_config = ConfigDict(extra="ignore")

    status: str = "hypothesis"
    possible_effects: list[str] = Field(default_factory=list)
    confidence: float = 0.3
    hypothesis: str = ""


class VariantScoreComponents(BaseModel):
    """Score breakdown for variant prioritization."""

    model_config = ConfigDict(extra="ignore")

    natural_frequency: float = 0.0
    region_importance: float = 0.0
    conservation_disruption: float = 0.0
    diversity_support: float = 0.0


class VariantRecord(BaseModel):
    """Structured record for an observed sequence variant in a bacteriocin homolog."""

    model_config = ConfigDict(extra="ignore")

    variant_id: str
    parent_candidate_id: str

    protein_position: int = Field(ge=1, description="1-indexed ungapped reference coordinate.")
    reference_aa: str
    alternate_aa: str
    protein_change: str

    nucleotide_change: str | None = None
    codon_position: int | None = None

    variant_type: VariantType = "missense"

    observed_count: int = Field(ge=0)
    homolog_count: int = Field(ge=0)
    frequency: float = Field(ge=0.0, le=1.0)
    conservation_score: float = Field(ge=0.0, le=1.0)

    region: RegionType = "unknown"

    source_accessions: list[str] = Field(default_factory=list)
    provenance: str = "database-derived"

    variant_priority_score: float = Field(default=0.0, ge=0.0, le=1.0)
    score_components: VariantScoreComponents = Field(default_factory=VariantScoreComponents)
    functional_effect: FunctionalEffectHypothesis = Field(
        default_factory=FunctionalEffectHypothesis
    )


class VariantDiscoveryResult(BaseModel):
    """Envelope returned by the variant discovery flow."""

    model_config = ConfigDict(extra="ignore")

    candidate_id: str
    reference_sequence: str
    homolog_count: int
    aligned_homolog_count: int
    variants: list[VariantRecord] = Field(default_factory=list)
    provenance: str = "database-derived"
    sources: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
