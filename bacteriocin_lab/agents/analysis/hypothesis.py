"""Decide whether a result supports, weakens, or fails to distinguish a hypothesis.

Prediction forms, in priority order (the first available one decides the status):

1. ``expected_relationship`` -- a structured (variable, direction) claim, tested
   against the controlled series that contains the current result.
2. ``predicted_inhibition_fraction`` -- a numeric prior, tested against the
   observed value with the combined observation + tolerance uncertainty.
3. ``predicted_direction`` of ``inhibition`` / ``no-effect`` -- tested against
   fixed inhibition thresholds, again uncertainty-aware.
4. A keyword reading of ``statement`` -- converted to (1) when it is
   unambiguous, otherwise ignored. Always labelled ``statement-keyword-heuristic``.

A hypothesis is ``inconclusive`` whenever the data cannot separate the outcomes,
including when no controlled comparison exists. It is never pushed to
``supported`` just because nothing contradicted it.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .comparison import Z_SIGNIFICANT, ComparisonOutcome, inhibition_of, sigma_of
from .schema import ExpectedRelationship, HypothesisUnderTest

DEFAULT_TOLERANCE = 0.15  # how far from a numeric prior still counts as consistent
INHIBITS_AT = 0.5  # inhibition fraction at which a candidate counts as inhibiting
NO_EFFECT_AT = 0.2

_VARIABLE_WORDS: dict[str, tuple[str, ...]] = {
    "target_cell_density": (
        "target-cell density",
        "target cell density",
        "cell density",
        "inoculum",
    ),
    "bacteriocin_concentration": ("bacteriocin concentration", "concentration", "dose"),
    "ph": ("ph",),
    "temperature_c": ("temperature",),
    "incubation_time": ("incubation time", "contact time"),
}
_UP = ("higher", "increased", "increasing", "elevated", "greater", "more", "raised")
_DOWN = ("lower", "reduced", "decreased", "decreasing", "less", "smaller")
_EFFECT_NEG = (
    "reduces",
    "reduce",
    "decreases",
    "decrease",
    "lowers",
    "weakens",
    "diminishes",
    "impairs",
    "suppresses",
)
_EFFECT_POS = ("increases", "increase", "enhances", "improves", "raises", "boosts", "strengthens")


@dataclass
class HypothesisVerdict:
    status: str  # supported | weakened | inconclusive
    strength: str  # none | weak | moderate | strong
    basis: str
    source: str  # which prediction form decided it
    z: float | None = None
    variable: str | None = None
    notes: list[str] = field(default_factory=list)
    expected: ExpectedRelationship | None = None
    prediction_mismatch: str | None = None  # set when a numeric prior is badly off


def _strength(z: float | None) -> str:
    if z is None:
        return "none"
    a = abs(z)
    return "strong" if a >= 4 else "moderate" if a >= Z_SIGNIFICANT else "weak"


def infer_expected_relationship(statement: str) -> ExpectedRelationship | None:
    """Read an unambiguous 'higher X reduces/increases ...' statement; else None.

    Deliberately conservative: a statement mentioning two variables, or no
    effect word, is not guessed at.
    """
    text = statement.lower()
    found = [
        var
        for var, words in _VARIABLE_WORDS.items()
        if any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)
    ]
    if len(found) != 1:
        return None
    var = found[0]
    neg = any(re.search(rf"\b{w}\b", text) for w in _EFFECT_NEG)
    pos = any(re.search(rf"\b{w}\b", text) for w in _EFFECT_POS)
    if neg == pos:  # neither or both
        return None
    up = any(re.search(rf"\b{w}\b", text) for w in _UP)
    down = any(re.search(rf"\b{w}\b", text) for w in _DOWN)
    if up and down:
        return None
    var_sign = -1 if down else 1
    effect_sign = -1 if neg else 1
    return ExpectedRelationship(
        variable=var, direction="positive" if var_sign * effect_sign > 0 else "negative"
    )


def _from_relationship(
    exp: ExpectedRelationship, outcome: ComparisonOutcome, source: str
) -> HypothesisVerdict:
    verdict = outcome.verdicts.get(exp.variable)
    if verdict is None or verdict.n_points < 2:
        return HypothesisVerdict(
            "inconclusive",
            "none",
            f"No controlled comparison varies {exp.variable} alone, so its effect on inhibition cannot be separated from other changes.",
            source,
            variable=exp.variable,
            expected=exp,
        )
    rel, z = verdict.relationship, verdict.z
    if exp.direction == "none":
        if rel == "none":
            return HypothesisVerdict(
                "supported",
                "moderate" if verdict.n_points >= 3 else "weak",
                f"{exp.variable} shows no detectable effect across the compared range, as predicted.",
                source,
                z,
                exp.variable,
                expected=exp,
            )
        if rel in ("positive", "negative", "non_monotonic"):
            return HypothesisVerdict(
                "weakened",
                _strength(z),
                f"A no-effect prediction for {exp.variable} conflicts with a {rel} response.",
                source,
                z,
                exp.variable,
                expected=exp,
            )
        return HypothesisVerdict(
            "inconclusive",
            "none",
            f"The {exp.variable} change is too uncertain to confirm or exclude an effect.",
            source,
            z,
            exp.variable,
            expected=exp,
        )
    if rel == exp.direction:
        return HypothesisVerdict(
            "supported",
            _strength(z),
            f"Predicted inhibition moves {rel}ly with {exp.variable}, as the hypothesis states.",
            source,
            z,
            exp.variable,
            expected=exp,
        )
    opposite = {"positive": "negative", "negative": "positive"}[exp.direction]
    if rel == opposite:
        return HypothesisVerdict(
            "weakened",
            _strength(z),
            f"Predicted inhibition moves {rel}ly with {exp.variable}, opposite to the hypothesis.",
            source,
            z,
            exp.variable,
            expected=exp,
        )
    if rel == "none":
        return HypothesisVerdict(
            "weakened",
            "weak",
            f"No detectable {exp.variable} effect was found where a {exp.direction} one was predicted.",
            source,
            z,
            exp.variable,
            expected=exp,
        )
    if rel == "non_monotonic":
        return HypothesisVerdict(
            "inconclusive",
            "weak",
            f"The {exp.variable} response is non-monotonic, which neither confirms nor excludes a simple {exp.direction} trend.",
            source,
            z,
            exp.variable,
            expected=exp,
            notes=["non-monotonic response"],
        )
    return HypothesisVerdict(
        "inconclusive",
        "none",
        f"The {exp.variable} change is not distinguishable from measurement uncertainty.",
        source,
        z,
        exp.variable,
        expected=exp,
    )


def _from_numeric(h: HypothesisUnderTest, y: float, sigma: float) -> HypothesisVerdict:
    tol = h.tolerance or DEFAULT_TOLERANCE
    pred = h.predicted_inhibition_fraction
    assert pred is not None
    total = math.hypot(sigma, tol)
    z = (y - pred) / total
    mismatch = None
    if abs(y - pred) > 2 * math.hypot(sigma, tol):
        mismatch = f"observed inhibition {y:.2f} differs from the hypothesis's predicted {pred:.2f} by more than twice the combined uncertainty"
    if abs(z) <= 1.0:
        return HypothesisVerdict(
            "supported",
            "moderate" if abs(z) <= 0.5 else "weak",
            f"Observed inhibition {y:.2f} is consistent with the predicted {pred:.2f} (|z|={abs(z):.1f}).",
            "predicted_inhibition_fraction",
            z,
            prediction_mismatch=mismatch,
        )
    if abs(z) < Z_SIGNIFICANT:
        return HypothesisVerdict(
            "inconclusive",
            "none",
            f"Observed inhibition {y:.2f} is moderately off the predicted {pred:.2f} (|z|={abs(z):.1f}); not decisive either way.",
            "predicted_inhibition_fraction",
            z,
            prediction_mismatch=mismatch,
        )
    return HypothesisVerdict(
        "weakened",
        _strength(z),
        f"Observed inhibition {y:.2f} is far from the predicted {pred:.2f} (|z|={abs(z):.1f}).",
        "predicted_inhibition_fraction",
        z,
        prediction_mismatch=mismatch,
    )


def _from_direction(h: HypothesisUnderTest, y: float, sigma: float) -> HypothesisVerdict:
    if h.predicted_direction == "no-effect":
        if y + 2 * sigma <= NO_EFFECT_AT + 0.1:
            return HypothesisVerdict(
                "supported",
                "moderate",
                f"Inhibition {y:.2f} is low, consistent with a no-effect prediction.",
                "predicted_direction",
            )
        if y - 2 * sigma > NO_EFFECT_AT + 0.1:
            return HypothesisVerdict(
                "weakened",
                "moderate",
                f"Inhibition {y:.2f} is clearly above the no-effect range.",
                "predicted_direction",
            )
        return HypothesisVerdict(
            "inconclusive",
            "none",
            f"Inhibition {y:.2f} +/- {sigma:.2f} straddles the no-effect boundary.",
            "predicted_direction",
        )
    # "inhibition"
    if y - 2 * sigma >= INHIBITS_AT:
        return HypothesisVerdict(
            "supported",
            "moderate",
            f"Inhibition {y:.2f} is clearly above {INHIBITS_AT}, consistent with an inhibitory prediction.",
            "predicted_direction",
            (y - INHIBITS_AT) / sigma if sigma else None,
        )
    if y + 2 * sigma < INHIBITS_AT:
        return HypothesisVerdict(
            "weakened",
            "moderate",
            f"Inhibition {y:.2f} is clearly below {INHIBITS_AT}, against an inhibitory prediction.",
            "predicted_direction",
            (y - INHIBITS_AT) / sigma if sigma else None,
        )
    return HypothesisVerdict(
        "inconclusive",
        "none",
        f"Inhibition {y:.2f} +/- {sigma:.2f} is not clearly on either side of {INHIBITS_AT}.",
        "predicted_direction",
    )


def _conditions_match(h: HypothesisUnderTest, conditions: dict) -> list[str]:
    """Names of key_conditions the result's conditions do NOT satisfy."""
    off = []
    for key, want in h.key_conditions.items():
        have = conditions.get(key)
        if have is None:
            off.append(f"{key} (not reported)")
        elif (
            isinstance(want, list | tuple)
            and len(want) == 2
            and all(isinstance(w, int | float) for w in want)
        ):
            if not want[0] <= have <= want[1]:
                off.append(f"{key}={have} outside {list(want)}")
        elif isinstance(want, int | float) and isinstance(have, int | float):
            if not math.isclose(have, want, rel_tol=0.05):
                off.append(f"{key}={have} != {want}")
        elif want != have:
            off.append(f"{key}={have!r} != {want!r}")
    return off


def evaluate(
    h: HypothesisUnderTest | None, outcome: ComparisonOutcome, result
) -> HypothesisVerdict:
    if h is None:
        return HypothesisVerdict(
            "inconclusive",
            "none",
            "No hypothesis was supplied, so only condition-response relationships were analysed.",
            "none",
        )
    y = inhibition_of(result)
    sigma, _ = sigma_of(result)
    if y is None:
        return HypothesisVerdict(
            "inconclusive",
            "none",
            "The result carries no predicted_inhibition_fraction to interpret.",
            "none",
        )

    if h.predicted_direction == "conditional" or h.key_conditions:
        off = _conditions_match(h, result.conditions.model_dump())
        if off:
            return HypothesisVerdict(
                "inconclusive",
                "none",
                "The result was obtained outside the conditions the hypothesis is stated for: "
                + "; ".join(off)
                + ".",
                "key_conditions",
                notes=off,
            )

    if h.expected_relationship:
        v = _from_relationship(h.expected_relationship, outcome, "expected_relationship")
        if h.predicted_inhibition_fraction is not None:
            n = _from_numeric(h, y, sigma)
            v.prediction_mismatch = n.prediction_mismatch
        return v
    if h.predicted_inhibition_fraction is not None:
        return _from_numeric(h, y, sigma)
    if h.predicted_direction in ("inhibition", "no-effect"):
        return _from_direction(h, y, sigma)
    inferred = infer_expected_relationship(h.statement) if h.statement else None
    if inferred:
        v = _from_relationship(inferred, outcome, "statement-keyword-heuristic")
        v.notes.append(
            "expected relationship was read from the statement text, not supplied structurally"
        )
        if v.strength == "strong":
            v.strength = "moderate"  # heuristic reading never earns 'strong'
        return v
    return HypothesisVerdict(
        "inconclusive",
        "none",
        "The hypothesis states no testable prediction this agent can evaluate (no expected_relationship, numeric prior, or unambiguous statement).",
        "none",
    )


__all__ = ["HypothesisVerdict", "evaluate", "infer_expected_relationship"]
