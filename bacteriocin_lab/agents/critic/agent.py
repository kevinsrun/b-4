"""The scientific critic / safety agent.

One scientific responsibility: decide whether a claim is carried by the
evidence behind it, before the loop writes it into the research state or acts
on it.

It reviews; it does not research. It runs no experiments, gathers no
literature and forms no hypotheses -- it reads what the other agents produced
and says what is wrong with it, and which agent can fix it.

Design stance
-------------
A critic that approves everything is worse than no critic: it launders
unexamined claims into the research state with a stamp on them. So the
default is *not* approval. A claim is accepted only when no rule objects, and
a single high-severity integrity failure rejects it outright no matter how
much else looks fine.

The verdict is a pure function of the issues found. Nothing here reads the
claim text to form its own scientific opinion -- the rules do that, and the
rules are individually testable.
"""

from __future__ import annotations

import logging
from typing import Any

from bacteriocin_lab.shared.contract import (
    AgentResponseEnvelope,
    Evidence,
    ExperimentResult,
    RecommendedNextAction,
    Uncertainty,
)
from bacteriocin_lab.shared.ids import content_id

from .rules import claims_experimental_validation, review_claim
from .schema import (
    ANALYSIS_AGENT,
    EVIDENCE_AGENT,
    PLANNER_AGENT,
    ClaimUnderReview,
    CriticRequest,
    CriticReview,
    RequiredFollowup,
    ReviewIssue,
    ReviewStatus,
)

logger = logging.getLogger(__name__)

AGENT_NAME = "scientific_critic_agent"
MODEL_VERSION = "critic-rules-v1"

#: Integrity failures. These are not "needs more data" -- they are the claim
#: being wrong about itself, and more experiments would not fix them. They
#: reject rather than defer.
_REJECTING_TYPES: frozenset[str] = frozenset(
    {"misdescribed_provenance", "unsupported_conclusion", "unsupported_extrapolation"}
)

#: Gaps. The claim may well be true; the system has not earned it yet. These
#: route back for more work rather than condemning the claim.
_EVIDENCE_GAP_TYPES: frozenset[str] = frozenset(
    {
        "insufficient_coverage",
        "hypotheses_not_distinguished",
        "confounded_comparison",
        "missing_citation",
        "unclassified_provenance",
    }
)

#: Why each agent would be asked to take the work back.
_FOLLOWUP_REASONS: dict[str, str] = {
    PLANNER_AGENT: "design experiments that close the evidence gap before this claim is accepted",
    EVIDENCE_AGENT: "supply or repair the provenance records this claim cites",
    ANALYSIS_AGENT: "restate the conclusion so it matches what the data and their provenance support",
}


class ScientificCriticAgent:
    """Stateless reviewer. Everything it knows arrives in the envelope."""

    name = AGENT_NAME
    model_version = MODEL_VERSION

    def describe(self) -> dict[str, Any]:
        """Self-description for capability negotiation."""
        return {
            "agent": AGENT_NAME,
            "model_version": MODEL_VERSION,
            "responsibility": (
                "review claims before the loop accepts them: check that the conclusion "
                "follows from the result, that provenance is classified and not "
                "overstated, that coverage and controls are adequate, and that "
                "uncertainty matches the strength of the wording"
            ),
            "does_not": [
                "run experiments",
                "gather literature or database evidence",
                "form hypotheses or design candidates",
                "decide what the system does next (it recommends and routes)",
                "approve by default",
            ],
            "can_route_to": [PLANNER_AGENT, EVIDENCE_AGENT, ANALYSIS_AGENT],
            "statuses": ["approve", "approve_with_caveats", "reject", "needs_more_evidence"],
            "input_schema": CriticRequest.model_json_schema(),
            "output_schema": CriticReview.model_json_schema(),
        }

    # ------------------------------------------------------------------

    def review(self, request: CriticRequest) -> CriticReview:
        """Review every claim in the request and return one verdict."""
        evidence = {e.evidence_id: e for e in request.evidence}
        results = self._parse_results(request.previous_results)

        issues: list[ReviewIssue] = []
        accepted: list[str] = []
        rejected: list[str] = []

        for claim in request.claims:
            found = review_claim(
                claim,
                evidence=evidence,
                results=results,
                competing=request.competing_hypotheses,
                minimum_results=request.minimum_results_per_claim,
            )
            issues.extend(found)
            if any(i.type in _REJECTING_TYPES and i.severity == "high" for i in found):
                rejected.append(claim.claim_id)
            elif not found:
                accepted.append(claim.claim_id)
            # A claim with only gap-type issues is neither accepted nor
            # rejected: it is held pending the followup. Saying so by omission
            # is deliberate -- the orchestrator must not read "not rejected"
            # as "accepted".

        status = self._status(issues, request.claims, accepted, rejected)
        followups = self._followups(issues)
        return CriticReview(
            review_id=self._review_id(request),
            status=status,
            issues=issues,
            accepted_claims=accepted,
            rejected_claims=rejected,
            required_followups=followups,
            confidence=self._confidence(request.claims, issues),
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _parse_results(raw: list[dict[str, Any]]) -> dict[str, ExperimentResult]:
        """Coerce supplied results, skipping any that will not validate.

        A malformed result is dropped rather than raised on: the critic must
        still review the rest, and the claim that cited it will be reported as
        a dangling citation by the rules.
        """
        out: dict[str, ExperimentResult] = {}
        for item in raw:
            if isinstance(item, ExperimentResult):
                out[item.result_id] = item
                continue
            try:
                parsed = ExperimentResult.model_validate(item)
            except Exception as exc:  # noqa: BLE001 - any validation failure is the same here
                logger.warning("%s: skipping unparseable result: %s", AGENT_NAME, exc)
                continue
            out[parsed.result_id] = parsed
        return out

    @staticmethod
    def _status(
        issues: list[ReviewIssue],
        claims: list[ClaimUnderReview],
        accepted: list[str],
        rejected: list[str],
    ) -> ReviewStatus:
        """Map findings onto a verdict.

        Order matters. Integrity failures win over gaps: a claim that
        misdescribes its own provenance is not fixed by running more
        experiments, so it must not be reported as merely needing evidence.
        """
        if not claims:
            return "needs_more_evidence"
        if rejected:
            return "reject"
        if any(i.type in _EVIDENCE_GAP_TYPES for i in issues):
            return "needs_more_evidence"
        if issues:
            return "approve_with_caveats"
        return "approve"

    @staticmethod
    def _followups(issues: list[ReviewIssue]) -> list[RequiredFollowup]:
        """Group issues by the agent that can fix them."""
        by_agent: dict[str, list[ReviewIssue]] = {}
        for issue in issues:
            if issue.route_to:
                by_agent.setdefault(issue.route_to, []).append(issue)
        followups: list[RequiredFollowup] = []
        for agent in sorted(by_agent):
            group = by_agent[agent]
            claim_ids = sorted({i.claim_id for i in group if i.claim_id})
            followups.append(
                RequiredFollowup(
                    agent=agent,
                    reason=_FOLLOWUP_REASONS.get(agent, "address the issues raised"),
                    claim_ids=claim_ids,
                    payload_hint={
                        "issue_types": sorted({i.type for i in group}),
                        "highest_severity": _worst([i.severity for i in group]),
                    },
                )
            )
        return followups

    @staticmethod
    def _confidence(claims: list[ClaimUnderReview], issues: list[ReviewIssue]) -> float:
        """Confidence in the *review*, not in the claims.

        It falls as unresolved problems accumulate, because a claim riddled
        with issues is also one the critic is less sure it has fully
        characterised. With no claims to review there is nothing to be
        confident about.
        """
        if not claims:
            return 0.0
        weight = {"low": 0.05, "medium": 0.15, "high": 0.35}
        penalty = sum(weight[i.severity] for i in issues) / len(claims)
        return round(max(0.0, min(1.0, 1.0 - penalty)), 4)

    @staticmethod
    def _review_id(request: CriticRequest) -> str:
        """Deterministic: the same submission reviewed twice is one review."""
        return content_id(
            "review",
            {
                "claims": [c.model_dump(mode="json") for c in request.claims],
                "evidence": sorted(e.evidence_id for e in request.evidence),
                "results": sorted(
                    str(r.get("result_id")) for r in request.previous_results if isinstance(r, dict)
                ),
                "model_version": MODEL_VERSION,
            },
        )

    # ------------------------------------------------------------------
    # Omnigent-callable interface
    # ------------------------------------------------------------------

    def run_envelope(self, payload: dict[str, Any]) -> AgentResponseEnvelope:
        """Common envelope in, common envelope out."""
        try:
            request = (
                payload if isinstance(payload, CriticRequest) else CriticRequest.model_validate(payload or {})
            )
        except Exception as exc:  # noqa: BLE001 - surfaced structurally, not raised
            logger.warning("Invalid request to %s: %s", AGENT_NAME, exc)
            return AgentResponseEnvelope(
                agent=AGENT_NAME,
                decision={"status": "rejected_input", "reason": "envelope did not validate"},
                confidence=0.0,
                warnings=[f"invalid critic request: {exc}"],
                uncertainties=[
                    Uncertainty(
                        kind="contract-gap",
                        description="the submission could not be parsed, so nothing was reviewed",
                        severity="high",
                    )
                ],
                model_version=MODEL_VERSION,
            )

        review = self.review(request)
        return AgentResponseEnvelope(
            agent=AGENT_NAME,
            decision={
                "status": review.status,
                "review_id": review.review_id,
                "n_claims": len(request.claims),
                "n_accepted": len(review.accepted_claims),
                "n_rejected": len(review.rejected_claims),
                "n_issues": len(review.issues),
            },
            evidence=[],  # a review produces no new scientific evidence
            confidence=review.confidence,
            uncertainties=self._uncertainties(review),
            artifacts={"review": review.model_dump(mode="json")},
            warnings=[
                f"[{i.severity}] {i.type}: {i.description}"
                for i in review.issues
                if i.severity == "high"
            ],
            recommended_next_action=self._next_action(review),
            model_version=MODEL_VERSION,
        )

    @staticmethod
    def _uncertainties(review: CriticReview) -> list[str | Uncertainty]:
        out: list[str | Uncertainty] = []
        if review.status in {"needs_more_evidence", "reject"}:
            out.append(
                Uncertainty(
                    kind="data-gap" if review.status == "needs_more_evidence" else "epistemic",
                    description=(
                        "claims were held or rejected; the research state should not be "
                        "updated with them until the required followups are done"
                    ),
                    affects=sorted(set(review.rejected_claims) | {
                        i.claim_id for i in review.issues if i.claim_id
                    }),
                    severity="high" if review.status == "reject" else "medium",
                )
            )
        out.append(
            Uncertainty(
                kind="model-limitation",
                description=(
                    "the critic applies deterministic rules over provenance, coverage and "
                    "stated conditions; it cannot judge whether the underlying science is "
                    "interesting, only whether the claim is carried by its support"
                ),
                severity="low",
            )
        )
        return out

    @staticmethod
    def _next_action(review: CriticReview) -> RecommendedNextAction | None:
        """Route to the agent with the most to fix.

        The critic recommends; the orchestrator decides. Ties break towards
        the planner, because an evidence gap usually needs an experiment
        before any amount of rewording will help.
        """
        if not review.required_followups:
            return None
        order = {PLANNER_AGENT: 0, EVIDENCE_AGENT: 1, ANALYSIS_AGENT: 2}
        best = max(
            review.required_followups,
            key=lambda f: (len(f.claim_ids), -order.get(f.agent, 9)),
        )
        return RecommendedNextAction(
            agent=best.agent,
            reason=best.reason,
            payload_hint={
                "review_id": review.review_id,
                "status": review.status,
                "claim_ids": best.claim_ids,
                **best.payload_hint,
            },
        )


def _worst(severities: list[str]) -> str:
    for level in ("high", "medium", "low"):
        if level in severities:
            return level
    return "low"


def run_agent(payload: dict[str, Any]) -> AgentResponseEnvelope:
    """Module-level entry point for Omnigent tool calls."""
    return ScientificCriticAgent().run_envelope(payload)


def review_claims(payload: dict[str, Any]) -> dict[str, Any]:
    """Convenience: the review itself, as a plain dict."""
    request = CriticRequest.model_validate(payload or {})
    return ScientificCriticAgent().review(request).model_dump(mode="json")


__all__ = [
    "AGENT_NAME",
    "MODEL_VERSION",
    "ScientificCriticAgent",
    "claims_experimental_validation",
    "review_claims",
    "run_agent",
]
