"""Pydantic schemas for project-centered research, samples, annotated sequences, and CRISPR research."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class BiologicalSample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_id: str
    project_id: str
    sample_name: str
    organism: str
    strain: str | None = None
    gram_stain: Literal["positive", "negative", "variable", "unknown"] = "unknown"
    isolation_source: str | None = None
    collection_date: str | None = None
    sequencing_run_ids: list[str] = Field(default_factory=list)
    dataset_ids: list[str] = Field(default_factory=list)
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SequenceAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    annotation_id: str
    feature_type: Literal[
        "cds",
        "core_peptide",
        "leader_peptide",
        "cleavage_site",
        "modification_enzyme",
        "immunity_protein",
        "transporter",
        "regulator",
        "crispr_repeat",
        "crispr_spacer",
        "promoter",
        "terminator",
    ]
    name: str
    start: int
    end: int
    strand: Literal["+", "-"] = "+"
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)


class AnnotatedSequence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence_id: str
    project_id: str
    sample_id: str | None = None
    source_dataset_id: str | None = None
    name: str
    molecule_type: Literal["dna", "protein", "rna"]
    sequence: str
    length: int
    description: str | None = None
    genomic_coordinates: str | None = None
    reference_version: str | None = None
    orientation: Literal["5to3", "3to5"] = "5to3"
    annotations: list[SequenceAnnotation] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class SequenceVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant_id: str
    reference_sequence_id: str
    position: int
    reference_allele: str
    alternate_allele: str
    variant_type: Literal["snv", "insertion", "deletion", "substitution"]
    coordinate_system: Literal["1_based", "0_based"] = "1_based"
    predicted_effect: str | None = None
    evidence_citations: list[str] = Field(default_factory=list)
    uncertainty_level: Literal["low", "medium", "high", "unconfirmed"] = "unconfirmed"
    confidence_score: float | None = None


class CrisprTargetRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: str
    study_id: str
    target_name: str
    locus_tag: str | None = None
    sequence_id: str
    start_pos: int
    end_pos: int
    strand: Literal["+", "-"] = "+"
    target_sequence: str
    pam_motif: str | None = None
    orientation: str = "5to3"
    annotations: list[str] = Field(default_factory=list)
    published_evidence: list[dict[str, Any]] = Field(default_factory=list)
    validation_status: Literal["computational_only", "in_vitro_tested", "literature_confirmed", "unvalidated"] = "computational_only"


class CrisprObjective(BaseModel):
    model_config = ConfigDict(extra="forbid")
    study_id: str
    project_id: str
    sample_id: str | None = None
    title: str
    investigation_purpose: str
    target_gene: str
    target_sequence_id: str
    reference_version: str
    target_regions: list[CrisprTargetRegion] = Field(default_factory=list)
    variants: list[SequenceVariant] = Field(default_factory=list)
    specificity_considerations: str | None = None
    experimental_findings_summary: str | None = None
    review_status: Literal["draft", "in_review", "approved", "archived"] = "draft"
    created_at: str
    updated_at: str


class ResearchProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    name: str
    description: str
    lead_investigator: str | None = None
    target_organism: str
    status: Literal["active", "completed", "archived"] = "active"
    sample_ids: list[str] = Field(default_factory=list)
    sequencing_run_ids: list[str] = Field(default_factory=list)
    dataset_ids: list[str] = Field(default_factory=list)
    sequence_ids: list[str] = Field(default_factory=list)
    amp_job_ids: list[str] = Field(default_factory=list)
    crispr_study_ids: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    lead_investigator: str | None = None
    target_organism: str = Field(min_length=1, max_length=120)


class SampleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_name: str = Field(min_length=1, max_length=120)
    organism: str = Field(min_length=1, max_length=120)
    strain: str | None = None
    gram_stain: Literal["positive", "negative", "variable", "unknown"] = "unknown"
    isolation_source: str | None = None


class CrisprObjectiveCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=150)
    investigation_purpose: str = Field(min_length=1, max_length=2000)
    target_gene: str = Field(min_length=1, max_length=100)
    target_sequence_id: str
    reference_version: str = "v1.0"
    sample_id: str | None = None
    specificity_considerations: str | None = None


class SequenceComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_sequence_id: str
    query_sequence: str
    query_name: str | None = "Query Sequence"


class SequenceComparisonResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_id: str
    reference_name: str
    query_name: str
    length_reference: int
    length_query: int
    identity_percentage: float
    mismatches_count: int
    gaps_count: int
    variants: list[SequenceVariant]
    alignment_chunks: list[dict[str, Any]]
