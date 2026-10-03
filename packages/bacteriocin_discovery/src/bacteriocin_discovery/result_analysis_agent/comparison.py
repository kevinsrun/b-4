"""Comparison of a result against previous experiments.

The central idea is the *controlled series*: the current result plus every prior
result for the same candidate in which **only one variable differs**. Only a
controlled series can attribute a change in inhibition to a variable; anything
else is confounded and is reported as a data gap rather than as a finding.

All verdicts are uncertainty-aware. A difference counts as a detected effect only
when it is both large enough to matter (``MIN_EFFECT``) and large relative to the
combined measurement uncertainty (``Z_SIGNIFICANT``).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

from ..contract import ExperimentResult

#: Variables treated on a log10 axis (activity is dose-per-cell dependent and spans decades).
LOG_VARIABLES = ("bacteriocin_concentration", "target_cell_density", "producer_cell_density")
#: Variables treated on a linear axis.
LINEAR_VARIABLES = ("ph", "temperature_c", "incubation_time")
NUMERIC_VARIABLES = LOG_VARIABLES + LINEAR_VARIABLES
#: Categorical conditions that must match for a comparison to be controlled.
CATEGORICAL_CONDITIONS = ("medium", "growth_phase", "assay_type", "assay_domain")
#: Unit fields; results in different units are not comparable without conversion.
UNIT_FIELDS = {
    "bacteriocin_concentration": "concentration_unit",
    "target_cell_density": "target_cell_density_unit",
    "incubation_time": "incubation_time_unit",
}

MIN_EFFECT = 0.05  # smallest change in inhibition fraction treated as meaningful
MONOTONIC_TOLERANCE = 0.02  # steps smaller than this are noise for trend direction
Z_SIGNIFICANT = 2.0
DEFAULT_SIGMA = 0.05  # used when a result carries no uncertainty; always flagged
PLATEAU_FRACTION = 0.25  # last step < this fraction of the largest step => plateau

LABELS = {
    "bacteriocin_concentration": "bacteriocin concentration",
    "target_cell_density": "target cell density",
    "producer_cell_density": "producer cell density",
    "ph": "pH",
    "temperature_c": "temperature",
    "incubation_time": "incubation time",
}


@dataclass
class Point:
    result_id: str
    experiment_id: str
    x: float  # position on the (possibly log) axis
    raw: float
    y: float  # predicted inhibition fraction
    sigma: float
    sigma_defaulted: bool


@dataclass
class SeriesVerdict:
    variable: str
    relationship: str
    effect_size: float | None
    delta: float | None
    z: float | None
    n_points: int
    plateau: bool
    points: list[Point] = field(default_factory=list)
    includes_current: bool = True


@dataclass
class ComparisonOutcome:
    verdicts: dict[str, SeriesVerdict]  # variable -> verdict including the current result
    prior_only: dict[str, SeriesVerdict]  # variable -> verdict WITHOUT the current result
    usable_prior: list[ExperimentResult]
    skipped: list[str]  # human-readable reasons prior results were excluded
    unit_mismatches: list[str]
    defaulted_sigma_ids: list[str]


def conditions_of(result: ExperimentResult) -> dict[str, Any]:
    return result.conditions.model_dump()


def inhibition_of(result: ExperimentResult) -> float | None:
    return result.measurement.predicted_inhibition_fraction


def sigma_details(result: ExperimentResult) -> tuple[float, bool, str | None]:
    """(sigma, was_defaulted, note) for the inhibition fraction.

    ``uncertainty`` is a standard deviation of the *fraction*, which collapses
    toward 0 as inhibition saturates near 0 or 1 even when the model is very
    unsure. When the producer also reports a 95% interval (the simulator does),
    the interval's implied sigma is used if it is wider, so significance tests
    are not overconfident at saturation.
    """
    u = result.measurement.uncertainty
    reported = float(u) if u is not None and u > 0 and math.isfinite(u) else None
    from_ci = None
    ci = (result.measurement.model_extra or {}).get("ci95_inhibition_fraction")
    if (
        isinstance(ci, list | tuple)
        and len(ci) == 2
        and all(isinstance(v, int | float) for v in ci)
        and ci[1] > ci[0]
    ):
        from_ci = (ci[1] - ci[0]) / (2 * 1.96)
    if reported is None and from_ci is None:
        return DEFAULT_SIGMA, True, None
    if from_ci is not None and (reported is None or from_ci > reported):
        note = (
            f"reported uncertainty {reported:.4f} understates the spread at this point; "
            f"the 95% interval implies sigma {from_ci:.3f}, which was used instead"
            if reported is not None
            else f"no scalar uncertainty reported; sigma {from_ci:.3f} was derived from the 95% interval"
        )
        return from_ci, False, note
    return float(reported), False, None


def sigma_of(result: ExperimentResult) -> tuple[float, bool]:
    sigma, defaulted, _ = sigma_details(result)
    return sigma, defaulted


def _axis(variable: str, value: float) -> float | None:
    if variable in LOG_VARIABLES:
        return math.log10(value) if value > 0 else None
    return float(value)


def _units_compatible(a: dict[str, Any], b: dict[str, Any], variable: str | None) -> bool:
    """Units must match wherever both results state one, for every dosed quantity."""
    for var, unit_field in UNIT_FIELDS.items():
        ua, ub = a.get(unit_field), b.get(unit_field)
        if ua and ub and ua != ub and (a.get(var) is not None and b.get(var) is not None):
            return False
    return True


def _others_equal(a: dict[str, Any], b: dict[str, Any], variable: str) -> bool:
    """True when every tracked condition except ``variable`` is identical."""
    for var in NUMERIC_VARIABLES:
        if var == variable:
            continue
        va, vb = a.get(var), b.get(var)
        if (va is None) != (vb is None):
            return False
        if va is not None and not math.isclose(va, vb, rel_tol=1e-9, abs_tol=1e-12):
            return False
    for var in CATEGORICAL_CONDITIONS:
        if a.get(var) != b.get(var):
            return False
    # Results that state their target must share it (species and strain) to be a controlled pair.
    ta, tb = a.get("target"), b.get("target")
    states_target = isinstance(ta, dict) and isinstance(tb, dict) and ta.get("species") and tb.get("species")
    if states_target and (ta.get("species"), ta.get("strain")) != (tb.get("species"), tb.get("strain")):
        return False
    return (a.get("ionic_conditions") or {}) == (b.get("ionic_conditions") or {})


def _point(result: ExperimentResult, variable: str) -> Point | None:
    y = inhibition_of(result)
    raw = conditions_of(result).get(variable)
    if y is None or raw is None:
        return None
    x = _axis(variable, raw)
    if x is None:
        return None
    sigma, defaulted = sigma_of(result)
    return Point(result.result_id, result.experiment_id, x, float(raw), float(y), sigma, defaulted)


def classify(variable: str, points: list[Point], *, includes_current: bool = True) -> SeriesVerdict:
    """Classify the response of inhibition to ``variable`` along an ordered series."""
    pts = sorted(points, key=lambda p: p.x)
    n = len(pts)
    if n < 2:
        return SeriesVerdict(
            variable, "unresolved", None, None, None, n, False, pts, includes_current
        )

    lo, hi = pts[0], pts[-1]
    delta = hi.y - lo.y
    sigma = math.hypot(lo.sigma, hi.sigma)
    z = delta / sigma if sigma > 0 else None
    span = hi.x - lo.x
    effect = delta / span if span else None

    steps = [b.y - a.y for a, b in itertools.pairwise(pts)]
    significant = [s for s in steps if abs(s) > MONOTONIC_TOLERANCE]
    signs = {1 if s > 0 else -1 for s in significant}

    if n >= 3 and len(signs) == 2:
        relationship = "non_monotonic"
    elif abs(delta) < MIN_EFFECT:
        relationship = "none" if not significant or n == 2 else "unresolved"
    elif z is not None and abs(z) >= Z_SIGNIFICANT:
        relationship = "positive" if delta > 0 else "negative"
    else:
        relationship = "unresolved"  # large enough to matter, but not distinguishable from noise

    plateau = False
    if relationship in ("positive", "negative") and n >= 3 and significant:
        biggest = max(abs(s) for s in steps)
        plateau = abs(steps[-1]) < PLATEAU_FRACTION * biggest
    return SeriesVerdict(
        variable, relationship, effect, delta, z, n, plateau, pts, includes_current
    )


def _series(variable: str, current: ExperimentResult, prior: list[ExperimentResult]) -> list[Point]:
    """Current result + prior results differing from it in ``variable`` only (or identical)."""
    cc = conditions_of(current)
    cur_point = _point(current, variable)
    if cur_point is None:
        return []
    by_x: dict[float, Point] = {cur_point.x: cur_point}
    for res in prior:
        rc = conditions_of(res)
        if not _others_equal(cc, rc, variable) or not _units_compatible(cc, rc, variable):
            continue
        p = _point(res, variable)
        if p is not None and p.x not in by_x:  # first result at an x wins; later duplicates ignored
            by_x[p.x] = p
    return list(by_x.values())


def usable_prior_results(
    current: ExperimentResult, raw_prior: list[dict[str, Any] | ExperimentResult]
) -> tuple[list[ExperimentResult], list[str]]:
    """Validate prior results; keep same-candidate, same-domain, non-duplicate ones."""
    out: list[ExperimentResult] = []
    skipped: list[str] = []
    seen = {current.result_id}
    for i, entry in enumerate(raw_prior):
        try:
            res = (
                entry
                if isinstance(entry, ExperimentResult)
                else ExperimentResult.model_validate(entry)
            )
        except Exception as exc:
            skipped.append(f"previous_results[{i}] did not validate as ExperimentResult: {exc}")
            continue
        if res.result_id in seen:
            continue
        seen.add(res.result_id)
        if res.candidate_id != current.candidate_id:
            continue  # other candidates are not evidence about this candidate's response
        if res.conditions.assay_domain != current.conditions.assay_domain:
            skipped.append(
                f"{res.result_id}: assay_domain {res.conditions.assay_domain!r} differs from the current result's"
            )
            continue
        if (res.model_extra or {}).get("status") == "failed":
            skipped.append(
                f"{res.result_id}: failed attempt (no measurement); excluded from comparison"
            )
            continue
        if inhibition_of(res) is None:
            skipped.append(f"{res.result_id}: no predicted_inhibition_fraction")
            continue
        out.append(res)
    return out, skipped


def compare(
    current: ExperimentResult, raw_prior: list[dict[str, Any] | ExperimentResult]
) -> ComparisonOutcome:
    prior, skipped = usable_prior_results(current, raw_prior)
    cc = conditions_of(current)

    unit_mismatches = [
        f"{r.result_id}: units differ from the current result (concentration/density/time); excluded from comparison"
        for r in prior
        if not _units_compatible(cc, conditions_of(r), None)
    ]
    comparable = [r for r in prior if _units_compatible(cc, conditions_of(r), None)]

    verdicts: dict[str, SeriesVerdict] = {}
    prior_only: dict[str, SeriesVerdict] = {}
    for var in NUMERIC_VARIABLES:
        pts = _series(var, current, comparable)
        if len(pts) >= 2:
            verdicts[var] = classify(var, pts)
            without = [p for p in pts if p.result_id != current.result_id]
            if len(without) >= 2:
                prior_only[var] = classify(var, without, includes_current=False)

    defaulted = sorted(
        {p.result_id for v in verdicts.values() for p in v.points if p.sigma_defaulted}
    )
    if sigma_of(current)[1] and current.result_id not in defaulted:
        defaulted.append(current.result_id)
    return ComparisonOutcome(verdicts, prior_only, comparable, skipped, unit_mismatches, defaulted)


__all__ = [
    "LABELS",
    "MIN_EFFECT",
    "NUMERIC_VARIABLES",
    "Z_SIGNIFICANT",
    "ComparisonOutcome",
    "Point",
    "SeriesVerdict",
    "classify",
    "compare",
    "conditions_of",
    "inhibition_of",
    "sigma_details",
    "sigma_of",
    "usable_prior_results",
]
