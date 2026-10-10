"""Scientific and transport contracts for independently trained AMP classifiers."""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SequenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    sequence: str = Field(min_length=1, max_length=10000)

    @field_validator("sequence")
    @classmethod
    def canonical_sequence(cls, value: str) -> str:
        # Do not silently remove modifications, gaps, stop codons or ambiguous residues.
        if not value.isascii() or any(c not in "ACDEFGHIKLMNPQRSTVWY" for c in value):
            raise ValueError("use uppercase canonical amino acids without gaps or stop codons")
        return value

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sequence.encode("ascii")).hexdigest()


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequences: list[SequenceInput] = Field(min_length=1, max_length=128)
    models: list[str] = Field(
        default_factory=lambda: ["ampir", "ampeppy"], min_length=1, max_length=6
    )
    ampir_model: Literal["mature", "precursor"] = "mature"
    amplify_model: Literal["balanced"] = "balanced"
    ampir_threshold: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    timeout_seconds: float = Field(default=60, ge=0.1, le=120, allow_inf_nan=False)

    @model_validator(mode="after")
    def limits_and_identifiers(self) -> PredictRequest:
        ids = [s.sequence_id for s in self.sequences]
        if len(set(ids)) != len(ids):
            raise ValueError("sequence identifiers must be unique")
        if len(set(self.models)) != len(self.models):
            raise ValueError("model identifiers must be unique")
        if sum(len(s.sequence) for s in self.sequences) > 128000:
            raise ValueError("batch exceeds 128000 total residues")
        return self


class Prediction(BaseModel):
    sequence_id: str
    sequence_checksum: str
    model_id: str
    model_version: str
    model_variant: str | None = None
    class_definition: str = "upstream AMP-vs-nonAMP training label; not bacteriocin identity"
    benchmark_validation: dict[str, Any] = Field(
        default_factory=lambda: {
            "status": "BLOCKED",
            "applicability": "independent biological performance not established",
        }
    )
    native_scores: dict[str, float] = Field(default_factory=dict)
    raw_score: float | None = Field(default=None, allow_inf_nan=False)
    score_interpretation: str
    binary_prediction: bool | None = None
    threshold: float | None = None
    threshold_interpretation: str | None = None
    status: Literal["succeeded", "failed", "timeout", "unavailable", "ineligible"]
    timestamp: str
    duration_seconds: float = 0
    cached: bool = False
    warnings: list[str] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    reproducibility: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_outcome(self) -> Prediction:
        if self.status == "succeeded" and self.raw_score is None:
            raise ValueError("successful classification requires a raw score")
        if self.status != "succeeded" and (
            self.raw_score is not None or self.binary_prediction is not None
        ):
            raise ValueError("unsuccessful execution cannot carry a score or class")
        return self


class SequenceEvidence(BaseModel):
    sequence_id: str
    sequence_checksum: str
    predictions: list[Prediction]
    agreement: dict[str, Any]
    dramp_matches: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PredictionReport(BaseModel):
    schema_version: str = "amp-inference/1"
    status: Literal["succeeded", "partial_success", "failed"]
    evidence_type: Literal["computational-prediction"] = "computational-prediction"
    timestamp: str
    sequences: list[SequenceEvidence]
    execution: dict[str, Any]
    warnings: list[str] = Field(
        default_factory=lambda: [
            "AMP classification does not establish bacteriocin identity or experimental activity.",
            "Scores have independent training contexts; no cross-model calibration is established.",
            "DRAMP matches are reference annotations, not independent experimental validation.",
            "Primary-sequence matches do not establish identical modifications "
            "or chemical structure.",
        ]
    )


class JobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "partial_success", "failed", "interrupted"]
    created_at: str
    updated_at: str
    report: PredictionReport | None = None
    error: dict[str, Any] | None = None
