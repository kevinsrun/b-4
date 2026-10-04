"""Scientific critic / safety agent for the bacteriocin-discovery loop.

Reviews claims before the system accepts them into its research state or uses
them to justify a consequential next step. It challenges rather than rubber
stamps: approval is what is left when no rule objects, not the default.

    from bacteriocin_lab.agents.critic import run_agent

    envelope = run_agent({
        "claims": [{
            "claim_id": "claim-1",
            "statement": "Nisin inhibits L. monocytogenes at 1 uM.",
            "result_ids": ["res-1", "res-2"],
        }],
        "previous_results": [result_one, result_two],
    })

    envelope.decision["status"]   # approve | approve_with_caveats
                                  # | reject | needs_more_evidence
"""

from __future__ import annotations

__version__ = "0.1.0"

from .agent import (
    AGENT_NAME,
    MODEL_VERSION,
    ScientificCriticAgent,
    claims_experimental_validation,
    review_claims,
    run_agent,
)
from .rules import review_claim
from .schema import (
    ANALYSIS_AGENT,
    EVIDENCE_AGENT,
    PLANNER_AGENT,
    ClaimUnderReview,
    CompetingHypothesis,
    CriticRequest,
    CriticReview,
    RequiredFollowup,
    ReviewIssue,
)

__all__ = [
    "AGENT_NAME",
    "ANALYSIS_AGENT",
    "EVIDENCE_AGENT",
    "MODEL_VERSION",
    "PLANNER_AGENT",
    "ClaimUnderReview",
    "CompetingHypothesis",
    "CriticRequest",
    "CriticReview",
    "RequiredFollowup",
    "ReviewIssue",
    "ScientificCriticAgent",
    "__version__",
    "claims_experimental_validation",
    "review_claim",
    "review_claims",
    "run_agent",
]
