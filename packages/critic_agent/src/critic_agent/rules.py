"""The critic's validation rules.

One function per check, each taking the claim plus the material behind it and
returning the issues it found. They are pure and independent so a rule can be
tested, tuned or disabled without touching the others, and so a reviewer can
see exactly which rule produced a given issue.

Every rule is written to be *quiet when it has nothing to say*. A critic that
emits something for every claim trains the orchestrator to ignore it.
"""

from __future__ import annotations

import re
from typing import Any

from bacteriocin_discovery.contract import (
    EXPERIMENTALLY_VALIDATED_EVIDENCE,
    Evidence,
    ExperimentResult,
)
from .schema import (
    ANALYSIS_AGENT,
    EVIDENCE_AGENT,
    PLANNER_AGENT,
    ClaimUnderReview,
    CompetingHypothesis,
    ReviewIssue,
)

#: Phrases that assert a finding was experimentally validated.
#:
#: Deliberately owned here rather than imported from ``result_analysis_agent``:
#: depending on a sibling *agent's* internals would couple the critic to the
#: thing it reviews, and a reviewer that breaks when the reviewed module is
#: refactored is not much of a reviewer. The duplication is guarded by a test
#: asserting both implementations agree; the real fix is to promote this into
#: the shared contract, which is a cross-team decision.
_VALIDATION_CLAIM = re.compile(
    r"\b(?:experimentally|empirically)\s+(?:validated|confirmed|verified|proven|demonstrated)\b"
    r"|\bwet-?lab[- ](?:validated|confirmed|verified)\b",
    re.IGNORECASE,
)
#: A negation shortly before the phrase makes it a disclaimer, not a claim.
_NEGATION_BEFORE = re.compile(
    r"\b(?:not|never|no|nothing|none|without|cannot|nor|isn't|aren't|neither)\b[^.;:]{0,30}$",
    re.IGNORECASE,
)


def claims_experimental_validation(text: str) -> bool:
    """True when ``text`` asserts (rather than disclaims) experimental validation."""
    for m in _VALIDATION_CLAIM.finditer(text):
        if not _NEGATION_BEFORE.search(text[max(0, m.start() - 40) : m.start()]):
            return True
    return False


#: Language asserting a result holds generally or certainly. Matched against
#: the claim text and weighed against the uncertainty actually reported.
_STRONG_LANGUAGE = re.compile(
    r"\b(?:always|never|all |every |any |guarantee[sd]?|certain(?:ly)?|proves?|proven|"
    r"definitive(?:ly)?|conclusive(?:ly)?|establishes?|confirms?|demonstrates?)\b",
    re.IGNORECASE,
)

#: Hedges that make a claim appropriately tentative. Their presence does not
#: excuse strong language elsewhere, but a wholly hedged claim is not overstated.
_HEDGE = re.compile(
    r"\b(?:may|might|could|suggests?|indicates?|consistent with|appears?|likely|"
    r"preliminar(?:y|ily)|tentative(?:ly)?|hypothes\w+)\b",
    re.IGNORECASE,
)

#: Numeric conditions worth comparing between what was claimed and what was
#: tested. Each maps to the attribute on ``ExperimentConditions``.
_NUMERIC_CONDITIONS: dict[str, str] = {
    "ph": "ph",
    "temperature_c": "temperature_c",
    "bacteriocin_concentration": "bacteriocin_concentration",
    "target_cell_density": "target_cell_density",
    "incubation_time": "incubation_time",
}

#: Categorical conditions where a difference is a difference, not a distance.
_CATEGORICAL_CONDITIONS: tuple[str, ...] = ("medium", "growth_phase", "assay_type", "assay_domain")

#: Inhibition at or below this is not a positive finding, whatever the claim says.
_INACTIVE_INHIBITION = 0.2

#: Uncertainty wider than this makes a point estimate unusable as support for
#: a strong claim: the interval spans most of the possible range.
_WIDE_UNCERTAINTY = 0.25


def _claim_results(claim: ClaimUnderReview, results: dict[str, ExperimentResult]) -> list[ExperimentResult]:
    return [results[r] for r in claim.result_ids if r in results]


def _claim_evidence(claim: ClaimUnderReview, evidence: dict[str, Evidence]) -> list[Evidence]:
    return [evidence[e] for e in claim.evidence_ids if e in evidence]


# ---------------------------------------------------------------------------
# 9. citations / evidence IDs
# ---------------------------------------------------------------------------


def check_citations(
    claim: ClaimUnderReview,
    evidence: dict[str, Evidence],
    results: dict[str, ExperimentResult],
) -> list[ReviewIssue]:
    """Every claim must name what supports it, and the names must resolve."""
    issues: list[ReviewIssue] = []
    if not claim.evidence_ids and not claim.result_ids:
        issues.append(
            ReviewIssue(
                severity="high",
                type="missing_citation",
                description=(
                    "the claim cites neither evidence nor an experiment result, so there "
                    "is nothing to review it against"
                ),
                claim_id=claim.claim_id,
                route_to=EVIDENCE_AGENT,
            )
        )
        return issues

    dangling_e = [e for e in claim.evidence_ids if e not in evidence]
    dangling_r = [r for r in claim.result_ids if r not in results]
    for kind, missing, route in (
        ("evidence_id", dangling_e, EVIDENCE_AGENT),
        ("result_id", dangling_r, ANALYSIS_AGENT),
    ):
        if missing:
            issues.append(
                ReviewIssue(
                    severity="high",
                    type="missing_citation",
                    description=(
                        f"{kind}(s) {', '.join(sorted(missing))} are cited but were not "
                        "supplied, so the support for this claim cannot be checked"
                    ),
                    claim_id=claim.claim_id,
                    route_to=route,
                )
            )
    return issues


# ---------------------------------------------------------------------------
# 2. provenance is classified
# ---------------------------------------------------------------------------


def check_provenance_classified(
    claim: ClaimUnderReview, evidence: dict[str, Evidence]
) -> list[ReviewIssue]:
    """Evidence without a usable provenance class cannot be weighed."""
    unclassified = [
        e.evidence_id
        for e in _claim_evidence(claim, evidence)
        if not getattr(e, "evidence_type", None)
    ]
    if not unclassified:
        return []
    return [
        ReviewIssue(
            severity="medium",
            type="unclassified_provenance",
            description=(
                f"evidence {', '.join(sorted(unclassified))} carries no evidence_type; "
                "a claim cannot be weighed without knowing whether its support was "
                "measured, computed, or inferred"
            ),
            claim_id=claim.claim_id,
            route_to=EVIDENCE_AGENT,
        )
    ]


# ---------------------------------------------------------------------------
# 3. simulated evidence described as experimentally validated
# ---------------------------------------------------------------------------


def check_validation_misdescribed(
    claim: ClaimUnderReview,
    evidence: dict[str, Evidence],
    results: dict[str, ExperimentResult],
) -> list[ReviewIssue]:
    """Contract rule 9. The single thing the critic must never let through.

    A claim may say "experimentally validated" only when something behind it
    actually is. Everything this system produces today is simulation- or
    model-derived, so in practice this fires whenever the wording outruns the
    provenance.
    """
    if not claims_experimental_validation(claim.statement):
        return []

    backing = _claim_evidence(claim, evidence)
    backing_results = _claim_results(claim, results)
    validated = any(
        e.evidence_type in EXPERIMENTALLY_VALIDATED_EVIDENCE for e in backing
    ) or any(r.evidence_type in EXPERIMENTALLY_VALIDATED_EVIDENCE for r in backing_results)
    if validated:
        return []

    kinds = sorted(
        {e.evidence_type for e in backing} | {r.evidence_type for r in backing_results}
    )
    seen = ", ".join(kinds) if kinds else "no resolvable support"
    return [
        ReviewIssue(
            severity="high",
            type="misdescribed_provenance",
            description=(
                "the claim describes the finding as experimentally validated, but its "
                f"support is {seen}. Simulated and model-derived results are hypotheses "
                "to be tested, never observations"
            ),
            claim_id=claim.claim_id,
            route_to=ANALYSIS_AGENT,
        )
    ]


# ---------------------------------------------------------------------------
# 1. the conclusion follows from the result
# ---------------------------------------------------------------------------


def check_conclusion_supported(
    claim: ClaimUnderReview, results: dict[str, ExperimentResult]
) -> list[ReviewIssue]:
    """Catch the claim that contradicts its own data.

    Deliberately narrow: it only fires where the direction of the claim and
    the direction of the measurement disagree. A critic that second-guesses
    every interpretation would be noise.
    """
    backing = _claim_results(claim, results)
    if not backing:
        return []

    measured = [
        r.measurement.predicted_inhibition_fraction
        for r in backing
        if r.measurement.predicted_inhibition_fraction is not None
    ]
    if not measured:
        return []

    asserts_activity = re.search(
        r"\b(?:inhibit\w*|active|effective|kill\w*|potent|suscept\w*|works?)\b",
        claim.statement,
        re.IGNORECASE,
    ) and not re.search(
        r"\b(?:not|no|fails?|ineffective|inactive|without)\b", claim.statement, re.IGNORECASE
    )
    best = max(measured)
    if asserts_activity and best <= _INACTIVE_INHIBITION:
        return [
            ReviewIssue(
                severity="high",
                type="unsupported_conclusion",
                description=(
                    f"the claim asserts activity but the best supporting result shows "
                    f"inhibition of only {best:.3f}; the data do not carry the conclusion"
                ),
                claim_id=claim.claim_id,
                route_to=ANALYSIS_AGENT,
            )
        ]
    return []


# ---------------------------------------------------------------------------
# 4. coverage
# ---------------------------------------------------------------------------


def check_coverage(
    claim: ClaimUnderReview, results: dict[str, ExperimentResult], minimum: int
) -> list[ReviewIssue]:
    """A conclusion resting on one run has no replication and no trend."""
    backing = _claim_results(claim, results)
    if not backing or len(backing) >= minimum:
        return []
    return [
        ReviewIssue(
            severity="medium" if len(backing) == minimum - 1 else "high",
            type="insufficient_coverage",
            description=(
                f"the claim rests on {len(backing)} experiment(s); at least {minimum} are "
                "needed before a single point is read as a trend"
            ),
            claim_id=claim.claim_id,
            route_to=PLANNER_AGENT,
        )
    ]


# ---------------------------------------------------------------------------
# 5. confounders
# ---------------------------------------------------------------------------


def check_confounders(
    claim: ClaimUnderReview, results: dict[str, ExperimentResult]
) -> list[ReviewIssue]:
    """Two arms that differ in several variables cannot attribute a difference.

    Only fires when the supporting results genuinely disagree in outcome: if
    every arm gave the same answer, the varying conditions did not drive a
    conclusion and there is nothing to confound.
    """
    backing = _claim_results(claim, results)
    if len(backing) < 2:
        return []

    outcomes = [
        r.measurement.predicted_inhibition_fraction
        for r in backing
        if r.measurement.predicted_inhibition_fraction is not None
    ]
    if len(outcomes) < 2 or (max(outcomes) - min(outcomes)) < 0.2:
        return []

    varying: list[str] = []
    for label, attr in _NUMERIC_CONDITIONS.items():
        values = {getattr(r.conditions, attr, None) for r in backing}
        values.discard(None)
        if len(values) > 1:
            varying.append(label)
    for attr in _CATEGORICAL_CONDITIONS:
        values = {getattr(r.conditions, attr, None) for r in backing}
        values.discard(None)
        if len(values) > 1:
            varying.append(attr)

    if len(varying) < 2:
        return []
    return [
        ReviewIssue(
            severity="medium",
            type="confounded_comparison",
            description=(
                f"the compared experiments differ in {len(varying)} conditions "
                f"({', '.join(sorted(varying))}) while their outcomes differ by "
                f"{max(outcomes) - min(outcomes):.2f}; the effect cannot be attributed "
                "to any one of them"
            ),
            claim_id=claim.claim_id,
            route_to=PLANNER_AGENT,
        )
    ]


# ---------------------------------------------------------------------------
# 6. extrapolation
# ---------------------------------------------------------------------------


def check_extrapolation(
    claim: ClaimUnderReview, results: dict[str, ExperimentResult]
) -> list[ReviewIssue]:
    """A claim may not assert conditions that were never tested."""
    backing = _claim_results(claim, results)
    if not backing or not claim.conditions_claimed:
        return []

    issues: list[ReviewIssue] = []
    for label, attr in _NUMERIC_CONDITIONS.items():
        claimed = claim.conditions_claimed.get(label)
        if not isinstance(claimed, (int, float)):
            continue
        tested = [
            getattr(r.conditions, attr, None)
            for r in backing
            if getattr(r.conditions, attr, None) is not None
        ]
        if not tested:
            continue
        low, high = min(tested), max(tested)
        if claimed < low or claimed > high:
            issues.append(
                ReviewIssue(
                    severity="high",
                    type="unsupported_extrapolation",
                    description=(
                        f"the claim asserts {label}={claimed:g}, outside the tested range "
                        f"{low:g}-{high:g}; activity was not measured there"
                    ),
                    claim_id=claim.claim_id,
                    route_to=PLANNER_AGENT,
                )
            )

    for attr in _CATEGORICAL_CONDITIONS:
        claimed = claim.conditions_claimed.get(attr)
        if claimed is None:
            continue
        tested = {getattr(r.conditions, attr, None) for r in backing}
        tested.discard(None)
        if tested and claimed not in tested:
            issues.append(
                ReviewIssue(
                    severity="high",
                    type="unsupported_extrapolation",
                    description=(
                        f"the claim asserts {attr}={claimed!r}, which was never tested "
                        f"(tested: {', '.join(sorted(str(t) for t in tested))})"
                    ),
                    claim_id=claim.claim_id,
                    route_to=PLANNER_AGENT,
                )
            )
    return issues


# ---------------------------------------------------------------------------
# 7. uncertainty vs strength of claim
# ---------------------------------------------------------------------------


def check_uncertainty(
    claim: ClaimUnderReview,
    evidence: dict[str, Evidence],
    results: dict[str, ExperimentResult],
) -> list[ReviewIssue]:
    """Strong wording must be earned by narrow uncertainty."""
    strong = bool(_STRONG_LANGUAGE.search(claim.statement))
    hedged = bool(_HEDGE.search(claim.statement))

    backing = _claim_results(claim, results)
    spreads = [
        r.measurement.uncertainty for r in backing if r.measurement.uncertainty is not None
    ]
    widest = max(spreads) if spreads else None

    confidences = [
        e.confidence for e in _claim_evidence(claim, evidence) if e.confidence is not None
    ]
    if claim.asserted_confidence is not None:
        confidences.append(claim.asserted_confidence)
    weakest = min(confidences) if confidences else None

    issues: list[ReviewIssue] = []
    if strong and not hedged and widest is not None and widest > _WIDE_UNCERTAINTY:
        issues.append(
            ReviewIssue(
                severity="medium",
                type="overstated_certainty",
                description=(
                    f"the claim is stated without qualification but the supporting "
                    f"measurement carries uncertainty of {widest:.3f}; the interval is too "
                    "wide for the wording"
                ),
                claim_id=claim.claim_id,
                route_to=ANALYSIS_AGENT,
            )
        )
    if strong and not hedged and weakest is not None and weakest < 0.4:
        issues.append(
            ReviewIssue(
                severity="medium",
                type="overstated_certainty",
                description=(
                    f"the claim is stated without qualification but rests on support with "
                    f"confidence {weakest:.2f}"
                ),
                claim_id=claim.claim_id,
                route_to=ANALYSIS_AGENT,
            )
        )
    return issues


# ---------------------------------------------------------------------------
# 8. did the experiment distinguish the competing hypotheses?
# ---------------------------------------------------------------------------


def check_hypotheses_distinguished(
    claim: ClaimUnderReview,
    results: dict[str, ExperimentResult],
    competing: list[CompetingHypothesis],
) -> list[ReviewIssue]:
    """A result consistent with every rival explanation has settled nothing."""
    if not competing or claim.hypothesis_id is None:
        return []
    rivals = [h for h in competing if h.hypothesis_id != claim.hypothesis_id]
    if not rivals:
        return []

    backing = _claim_results(claim, results)
    if not backing:
        return []

    undiscriminated: list[str] = []
    for rival in rivals:
        variable = rival.discriminating_variable
        if variable is None:
            undiscriminated.append(rival.hypothesis_id)
            continue
        attr = _NUMERIC_CONDITIONS.get(variable, variable)
        values = {getattr(r.conditions, attr, None) for r in backing}
        values.discard(None)
        if len(values) < 2:
            undiscriminated.append(rival.hypothesis_id)

    if not undiscriminated:
        return []
    return [
        ReviewIssue(
            severity="medium",
            type="hypotheses_not_distinguished",
            description=(
                f"the supporting experiments do not separate this claim from competing "
                f"hypothes(es) {', '.join(sorted(undiscriminated))}: the discriminating "
                "variable was not varied, so the result is consistent with both"
            ),
            claim_id=claim.claim_id,
            route_to=PLANNER_AGENT,
        )
    ]


def review_claim(
    claim: ClaimUnderReview,
    *,
    evidence: dict[str, Evidence],
    results: dict[str, ExperimentResult],
    competing: list[CompetingHypothesis],
    minimum_results: int,
) -> list[ReviewIssue]:
    """Run every rule against one claim."""
    issues = check_citations(claim, evidence, results)
    issues += check_provenance_classified(claim, evidence)
    issues += check_validation_misdescribed(claim, evidence, results)
    issues += check_conclusion_supported(claim, results)
    issues += check_coverage(claim, results, minimum_results)
    issues += check_confounders(claim, results)
    issues += check_extrapolation(claim, results)
    issues += check_uncertainty(claim, evidence, results)
    issues += check_hypotheses_distinguished(claim, results, competing)
    return issues


__all__ = [
    "check_citations",
    "check_conclusion_supported",
    "check_confounders",
    "check_coverage",
    "check_extrapolation",
    "check_hypotheses_distinguished",
    "check_provenance_classified",
    "check_uncertainty",
    "check_validation_misdescribed",
    "review_claim",
]
