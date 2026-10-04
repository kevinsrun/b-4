from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceReference(StrictModel):
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    doi_or_url: str | None = None
    year: int | None = Field(default=None, ge=1800, le=2200)
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    source_type: Literal["journal-article", "preprint", "database-record", "other"] = "journal-article"


class SourceDocument(StrictModel):
    source: SourceReference
    text: str = Field(min_length=1)
    locator: str = "abstract"
    retrieved_at: str | None = None


class Quantity(StrictModel):
    value: float | None = None
    unit: str | None = None
    original_value: str = Field(min_length=1)
    original_unit: str | None = None
    normalized_value: float | None = None
    normalized_unit: str | None = None
    normalization_note: str | None = None


class BacteriocinIdentity(StrictModel):
    name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    sequence: str | None = None
    sequence_accession: str | None = None


class TargetIdentity(StrictModel):
    organism: str | None = None
    strain: str | None = None


class ExperimentalConditions(StrictModel):
    bacteriocin_concentration: Quantity | None = None
    target_cell_density: Quantity | None = None
    producer_cell_density: Quantity | None = None
    growth_phase: str | None = None
    ph: Quantity | None = None
    temperature_c: Quantity | None = None
    medium: str | None = None
    ionic_conditions: dict[str, Quantity | str] = Field(default_factory=dict)
    incubation_time: Quantity | None = None
    assay_type: str | None = None
    assay_domain: Literal["in_vitro", "in_vivo", "physiological_model", "unknown"] = "unknown"


class Measurement(StrictModel):
    type: str = Field(min_length=1)
    value: float | str | None = None
    unit: str | None = None
    original_text: str = Field(min_length=1)
    data_role: Literal["measured", "author-interpretation"]


class EvidenceProvenance(StrictModel):
    locator: str
    excerpt: str = Field(min_length=1, max_length=1200)
    extraction_method: Literal["deterministic-rule", "curated", "model-assisted"]


FOCUS_VARIABLES = (
    "bacteriocin_identity",
    "bacteriocin_sequence",
    "target_organism",
    "target_strain",
    "antimicrobial_spectrum",
    "bacteriocin_concentration",
    "target_cell_density",
    "producer_cell_density",
    "growth_phase",
    "ph",
    "temperature_c",
    "medium",
    "ionic_conditions",
    "incubation_time",
    "assay_type",
    "assay_domain",
    "resistance_or_susceptibility",
    "measured_antimicrobial_response",
)


class EvidenceRecord(StrictModel):
    evidence_id: str = Field(pattern=r"^ev_[0-9a-f]{24}$")
    source: SourceReference
    bacteriocin: BacteriocinIdentity
    target: TargetIdentity
    conditions: ExperimentalConditions
    measurement: Measurement
    claim: str = Field(min_length=1)
    evidence_type: Literal["literature-derived"] = "literature-derived"
    confidence: float = Field(ge=0.0, le=1.0)
    missing_variables: list[str]
    provenance: EvidenceProvenance

    @field_validator("missing_variables")
    @classmethod
    def validate_missing_variables(cls, values: list[str]) -> list[str]:
        invalid = sorted(set(values) - set(FOCUS_VARIABLES))
        if invalid:
            raise ValueError(f"unknown focus variables: {', '.join(invalid)}")
        return sorted(set(values))


class Contradiction(StrictModel):
    contradiction_id: str = Field(pattern=r"^cx_[0-9a-f]{24}$")
    evidence_ids: list[str] = Field(min_length=2)
    topic: str
    description: str
    unresolved: bool = True


class RetrievalConfig(StrictModel):
    enabled: bool = False
    sources: list[Literal["europe_pmc"]] = Field(default_factory=lambda: ["europe_pmc"])
    max_results: int = Field(default=10, ge=1, le=50)
    timeout_seconds: float = Field(default=15.0, gt=0, le=60)


class LiteratureQuery(StrictModel):
    query_id: str | None = None
    question: str = Field(min_length=3, max_length=2000)
    bacteriocin: str | None = None
    target_organism: str | None = None
    target_strain: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    source_documents: list[SourceDocument] = Field(default_factory=list, max_length=100)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LiteratureResponse(StrictModel):
    query_id: str
    agent: Literal["literature-evidence-agent"] = "literature-evidence-agent"
    decision: dict[str, Any]
    evidence: list[EvidenceRecord]
    knowledge_gaps: list[str]
    contradictions: list[Contradiction]
    recommended_searches: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainties: list[str]
    artifacts: dict[str, Any]
    warnings: list[str]
    recommended_next_action: dict[str, Any]
