"""Request and review schemas for the scientific critic.

The critic reviews *claims*, not experiments. A claim is whatever the loop is
about to write into its research state or act on; the critic's job is to say
whether the evidence behind it actually carries it.

Every type extends the shared contract rather than inventing a parallel
vocabulary, so a claim's ``evidence_ids`` resolve against the same
``Evidence`` records every other agent emits.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from bacteriocin_lab.shared.contract import AgentRequestEnvelope, ExtensibleContractModel

#: Agents the critic can send work back to. These are the real agent names
#: used elsewhere in the system, not labels invented here, so a routing
#: decision is directly actionable by the orchestrator.
PLANNER_AGENT = "experiment_planner"
EVIDENCE_AGENT = "literature-evidence-agent"
ANALYSIS_AGENT = "result_analysis_agent"

ReviewStatus = Literal["approve", "approve_with_caveats", "reject", "needs_more_evidence"]
Severity = Literal["low", "medium", "high"]

#: The failure modes the critic knows how to name. Keeping these a closed
#: vocabulary means the orchestrator can route on ``type`` without parsing
#: prose, and makes it obvious when a new check needs a new category.
IssueType = Literal[
    "unsupported_conclusion",
    "misdescribed_provenance",
    "unclassified_provenance",
    "insufficient_coverage",
    "confounded_comparison",
    "unsupported_extrapolation",
    "overstated_certainty",
    "hypotheses_not_distinguished",
    "missing_citation",
]


class ClaimUnderReview(ExtensibleContractModel):
    """One assertion the loop wants to accept.

    ``evidence_ids`` and ``result_ids`` are how a claim is tied to what
    supports it. A claim that names neither is not reviewable on its merits --
    the critic reports that as a missing citation rather than guessing.
    """

    claim_id: str
    statement: str
    evidence_ids: list[str] = Field(default_factory=list)
    result_ids: list[str] = Field(default_factory=list)
    hypothesis_id: str | None = None
    candidate_id: str | None = None
    asserted_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    conditions_claimed: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Conditions the claim asserts it holds under. Compared against the "
            "conditions actually tested to catch extrapolation."
        ),
    )


class CompetingHypothesis(ExtensibleContractModel):
    """A rival explanation the experiment was supposed to rule out."""

    hypothesis_id: str
    statement: str
    discriminating_variable: str | None = Field(
        default=None,
        description="The condition that would separate this from the favoured hypothesis.",
    )


class CriticRequest(AgentRequestEnvelope):
    """Common envelope plus the critic's specialised input.

    ``previous_results`` and ``evidence`` come from the common envelope and
    are the critic's primary material -- it reads what the rest of the system
    already produced rather than requiring a bespoke payload.
    """

    claims: list[ClaimUnderReview] = Field(default_factory=list)
    competing_hypotheses: list[CompetingHypothesis] = Field(default_factory=list)
    minimum_results_per_claim: int = Field(
        default=2,
        ge=1,
        description=(
            "Coverage floor. A conclusion resting on a single run has no "
            "replication and no dose-response; one point cannot show a trend."
        ),
    )


class ReviewIssue(ExtensibleContractModel):
    """One problem found with one claim."""

    severity: Severity
    type: IssueType
    description: str
    claim_id: str | None = None
    route_to: str | None = Field(
        default=None,
        description="Which agent can actually fix this, when one can.",
    )


class RequiredFollowup(ExtensibleContractModel):
    """Work that must happen before the claim can be accepted."""

    agent: str
    reason: str
    claim_ids: list[str] = Field(default_factory=list)
    payload_hint: dict[str, Any] = Field(default_factory=dict)


class CriticReview(ExtensibleContractModel):
    """The critic's verdict.

    ``accepted_claims`` and ``rejected_claims`` hold claim IDs, not restated
    text: the orchestrator resolves them against the claims it submitted, so
    the verdict cannot drift from the wording it was passed.
    """

    review_id: str
    status: ReviewStatus
    issues: list[ReviewIssue] = Field(default_factory=list)
    accepted_claims: list[str] = Field(default_factory=list)
    rejected_claims: list[str] = Field(default_factory=list)
    required_followups: list[RequiredFollowup] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


__all__ = [
    "ANALYSIS_AGENT",
    "EVIDENCE_AGENT",
    "PLANNER_AGENT",
    "ClaimUnderReview",
    "CompetingHypothesis",
    "CriticRequest",
    "CriticReview",
    "IssueType",
    "RequiredFollowup",
    "ReviewIssue",
    "ReviewStatus",
    "Severity",
]
