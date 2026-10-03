"""Result Analysis Agent request and response types.

Shared types (``ExperimentResult``, ``ExperimentSpec``, ``Evidence``, the
envelopes) are imported from ``..contract`` and are never redefined here. This
module only adds what is specific to interpreting a result.

The agent never produces ``wet-lab-derived`` evidence and never describes a
simulation-derived or model-predicted result as experimentally validated
(contract rules 8 and 9).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ..contract import (
    AgentRequestEnvelope,
    ExperimentResult,
    ExperimentSpec,
    ExtensibleContractModel,
    Uncertainty,
)

#: Vocabulary for how a variable relates to predicted inhibition.
Relationship = Literal["positive", "negative", "none", "non_monotonic", "unresolved"]

#: Per the agent's contract: whether the result supports the hypothesis.
HypothesisStatus = Literal["supported", "weakened", "inconclusive"]

#: How hard the data push on the hypothesis. ``weakened`` with ``strong`` evidence
#: is, in practice, rejection; the status vocabulary itself stays three-valued.
EvidenceStrength = Literal["none", "weak", "moderate", "strong"]


class ExpectedRelationship(ExtensibleContractModel):
    """Structured prediction: how one variable should move predicted inhibition."""

    variable: str
    direction: Literal["positive", "negative", "none"]


class HypothesisUnderTest(ExtensibleContractModel):
    """The hypothesis an experiment was designed to test.

    Extensible on purpose: a ``TestableHypothesis`` produced by the Candidate
    Generation Agent validates here unchanged (``falsified_if``,
    ``key_conditions`` and ``predicted_inhibition_fraction`` carry over).
    Prediction forms, in priority order: ``expected_relationship``, then
    ``predicted_inhibition_fraction`` / ``predicted_direction``, then a keyword
    reading of ``statement`` (lower confidence, always labelled).
    """

    hypothesis_id: str
    statement: str = ""
    candidate_id: str | None = None
    predicted_direction: Literal["inhibition", "no-effect", "conditional"] | None = None
    predicted_inhibition_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    expected_relationship: ExpectedRelationship | None = None
    falsified_if: str | None = None
    key_conditions: dict[str, Any] = Field(default_factory=dict)
    tolerance: float | None = Field(
        default=None, gt=0.0, le=1.0, description="Prediction tolerance on inhibition fraction."
    )


class ResultAnalysisRequest(AgentRequestEnvelope):
    """Common input envelope plus this agent's own fields."""

    result: ExperimentResult
    spec: ExperimentSpec | None = None
    hypothesis: HypothesisUnderTest | None = None
    candidate: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class VariableFinding(ExtensibleContractModel):
    """One condition-response relationship, with the numbers behind it."""

    variable: str
    relationship: Relationship
    effect_size: float | None = Field(
        default=None,
        description=(
            "Change in predicted inhibition fraction per unit of the variable "
            "(per log10 unit for concentration and cell densities). None when not computable."
        ),
    )
    interpretation: str
    delta_inhibition: float | None = None
    z_score: float | None = None
    n_points: int = 0
    controlled: bool = Field(
        default=False,
        description="True when only this variable differed between the compared results.",
    )
    plateau: bool = False
    compared_result_ids: list[str] = Field(default_factory=list)


class UnexpectedResult(ExtensibleContractModel):
    kind: str
    description: str
    severity: Literal["low", "medium", "high"] = "medium"
    refs: list[str] = Field(default_factory=list)


class Driver(ExtensibleContractModel):
    variable: str
    rank: int
    basis: Literal["controlled-comparison", "simulator-important-factors", "both"]
    delta_inhibition: float | None = None


class ResultAnalysis(ExtensibleContractModel):
    """The decision payload. Field names follow the agent's contract example."""

    finding_id: str
    experiment_id: str
    result_id: str
    candidate_id: str
    hypothesis_id: str | None = None
    hypothesis_status: HypothesisStatus = "inconclusive"
    evidence_strength: EvidenceStrength = "none"
    status_basis: str = ""
    prediction_source: str = "none"
    findings: list[VariableFinding] = Field(default_factory=list)
    unexpected_results: list[UnexpectedResult] = Field(default_factory=list)
    drivers: list[Driver] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    uncertainties: list[Uncertainty] = Field(default_factory=list)
    recommended_followup_questions: list[str] = Field(default_factory=list)
    observed: dict[str, Any] = Field(default_factory=dict)
    source_evidence_type: str = "simulation-derived"
    provenance_note: str = ""
    model_version: str | None = None


__all__ = [
    "Driver",
    "EvidenceStrength",
    "ExpectedRelationship",
    "HypothesisStatus",
    "HypothesisUnderTest",
    "Relationship",
    "ResultAnalysis",
    "ResultAnalysisRequest",
    "UnexpectedResult",
    "VariableFinding",
]
