"""Uncertainty accounting and local sensitivity analysis.

Philosophy
----------
A simulation backend that returns a point estimate without saying how much it
knows is worse than useless in an autonomous loop: the next-experiment chooser
cannot distinguish "confidently inactive" from "no idea". So variance is
accumulated explicitly from named, auditable sources and reported both as a
total and as a breakdown.

Variance is accumulated on the **logit scale of the inhibition fraction**,
because that is the scale on which the model's own error is roughly
homoscedastic: a prediction of 0.5 can be wrong in either direction, while a
prediction of 0.999 cannot be very wrong upward. Independent sources are
summed in quadrature. The reported ``uncertainty`` is then the delta-method
standard deviation of the inhibition fraction itself, so downstream agents can
use it directly without knowing about the logit transform.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..schemas import ImportantFactor, ParameterSource, UncertaintyComponent
from .parameters import ParameterStore

#: inhibition fractions are clamped away from 0/1 before the logit transform.
#: Tight, because a saturated prediction must still produce a usable gradient:
#: logit is the scale on which both the sensitivity analysis and the variance
#: budget stay informative when the inhibition fraction is pinned at ~1.
_EPS = 1e-12


def logit(p: float) -> float:
    p = min(1.0 - _EPS, max(_EPS, p))
    return math.log(p / (1.0 - p))


def expit(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


@dataclass
class UncertaintyBudget:
    """Accumulated variance with an auditable breakdown."""

    components: list[UncertaintyComponent] = field(default_factory=list)

    def add(self, source: str, sigma_logit: float, rationale: str | None = None) -> None:
        if sigma_logit <= 0:
            return
        self.components.append(
            UncertaintyComponent(
                source=source, sigma_logit=round(sigma_logit, 4), rationale=rationale
            )
        )

    @property
    def total_sigma_logit(self) -> float:
        return math.sqrt(sum(c.sigma_logit ** 2 for c in self.components))

    def interval(self, p: float, z: float = 1.96) -> tuple[float, float]:
        """Credible-style interval on the inhibition fraction."""
        s = self.total_sigma_logit
        centre = logit(p)
        return expit(centre - z * s), expit(centre + z * s)

    def sigma_fraction(self, p: float) -> float:
        """Delta-method standard deviation of the fraction itself.

        ``dp/dlogit = p(1-p)``, so ``sigma_p ~ p(1-p) * sigma_logit``, capped at
        the largest standard deviation a [0, 1] variable can have (0.5).
        """
        pc = min(1.0 - _EPS, max(_EPS, p))
        return min(0.5, pc * (1.0 - pc) * self.total_sigma_logit)

    def confidence(self, p: float) -> float:
        """A single 0-1 confidence for the common output envelope.

        Defined as ``1 / (1 + sigma_logit)``, i.e. 1.0 for a perfectly known
        prediction, 0.5 at one logit unit of spread, decaying smoothly. This is
        a monotone summary of the budget, not a calibrated probability, and is
        documented as such.
        """
        return round(1.0 / (1.0 + self.total_sigma_logit), 4)


def build_budget(
    *,
    store: ParameterStore,
    target_sigma_log10_mic: float,
    target_confidence: float,
    target_is_fallback: bool,
    peptide_is_generic: bool,
    class_is_unknown: bool,
    class_inference_confidence: float,
    n_imputed_conditions: int,
    domain_excursions: list[tuple[str, float, float]],
    potency_sigma_logit: float,
    potency_rationale: str,
    medium_confidence: float,
    extra: list[tuple[str, float, str]] | None = None,
) -> UncertaintyBudget:
    """Assemble the variance budget for one prediction.

    ``potency_sigma_logit`` is supplied by the caller, which propagates the
    organism's MIC-prior uncertainty by re-running the forward model with the
    dose shifted by plus and minus one sigma *decade* and halving the span
    (a log10 error in the predicted MIC is equivalent to the same log10 error
    in the applied dose, with the opposite sign). A secant over the real
    uncertainty range is used rather than a local derivative because the
    priors are wide -- often more than a decade -- and a response that is
    locally flat can still be far from flat one sigma away. A local derivative
    would report near-zero uncertainty for a saturated prediction that a
    plausible MIC error would move off its plateau entirely.
    """
    budget = UncertaintyBudget()

    # --- model-form floor: the forward model is a coarse mechanistic sketch
    budget.add(
        "model_form",
        store.g("sigma_model_form_logit"),
        "irreducible error of a coarse mechanistic model with uncalibrated priors",
    )

    # --- potency uncertainty, propagated through the model itself
    budget.add(
        "target_potency_prior",
        potency_sigma_logit,
        f"curated MIC prior for this organism has sigma={target_sigma_log10_mic:.2f} "
        f"log10 units (confidence {target_confidence:.2f}); {potency_rationale}",
    )

    if target_is_fallback:
        budget.add(
            "unknown_target_organism",
            store.g("sigma_unknown_target_logit"),
            "no curated prior for this organism; a generic envelope-level prior was used",
        )

    if peptide_is_generic:
        budget.add(
            "no_candidate_sequence",
            store.g("sigma_generic_peptide_logit"),
            "no sequence or descriptors were available for the candidate; a generic "
            "small-bacteriocin prior was used, so this prediction is not specific to "
            "the named candidate",
        )
    elif class_is_unknown or class_inference_confidence < 0.4:
        budget.add(
            "uncertain_structural_class",
            store.g("sigma_unknown_class_logit")
            * (1.0 - min(class_inference_confidence, 1.0)),
            f"structural class inferred from sequence motifs only "
            f"(confidence {class_inference_confidence:.2f}); receptor dependence and "
            "Hill cooperativity are therefore uncertain",
        )

    if n_imputed_conditions:
        budget.add(
            "imputed_conditions",
            store.g("sigma_per_imputed_condition_logit") * math.sqrt(n_imputed_conditions),
            f"{n_imputed_conditions} condition(s) were not specified and were filled "
            "with assay defaults",
        )

    for name, value, excursion in domain_excursions:
        budget.add(
            f"extrapolation:{name}",
            min(1.5, 0.45 * excursion),
            f"{name}={value:.4g} lies outside the validated domain "
            f"{store.domain.get(name)}; excursion {excursion:.2f}",
        )

    if medium_confidence < 0.3:
        budget.add(
            "medium_properties",
            0.45,
            "peptide availability and protease activity of this medium are poorly "
            "constrained",
        )

    for name, sigma, rationale in extra or []:
        budget.add(name, sigma, rationale)

    return budget


#: How each condition is perturbed, and the unit its sensitivity is reported in.
#:
#: Ratio-scale quantities (dose, cell density, time, salt) are perturbed and
#: reported per **decade**, which is the scale on which they are designed and
#: varied. Interval-scale quantities (pH, temperature) have an arbitrary zero,
#: so a relative step would be meaningless; they are perturbed and reported per
#: a fixed absolute step. Reporting the unit alongside the number is what makes
#: sensitivities comparable across factors instead of merely sortable.
SENSITIVITY_STEPS: dict[str, tuple[str, float, str]] = {
    "bacteriocin_concentration_um": ("log10", 0.10, "per decade of concentration"),
    "target_cell_density_cfu_per_ml": ("log10", 0.10, "per decade of cell density"),
    "producer_cell_density_cfu_per_ml": ("log10", 0.10, "per decade of producer density"),
    "incubation_time_h": ("log10", 0.10, "per decade of incubation time"),
    "ionic_strength_mm": ("log10", 0.10, "per decade of ionic strength"),
    "divalent_cation_mm": ("log10", 0.10, "per decade of divalent cation"),
    "ph": ("linear", 0.25, "per pH unit"),
    "temperature_c": ("linear", 1.0, "per 5 C"),
}

#: reporting scale for linear factors: sensitivity is quoted per this many
#: native units, chosen so the number reflects an experimentally meaningful step
_LINEAR_REPORT_SCALE: dict[str, float] = {"ph": 1.0, "temperature_c": 5.0}

#: smallest value treated as non-zero for a log-scale perturbation
_LOG_FLOOR = 1e-6


def local_sensitivity(
    evaluate,
    base_value: float,
    factors: dict[str, float],
    sources: dict[str, ParameterSource],
    *,
    steps: dict[str, tuple[str, float, str]] | None = None,
) -> tuple[list[ImportantFactor], dict[str, float]]:
    """Rank conditions by local sensitivity of the response.

    Returns ``(ranked_factors, raw_derivatives)``, where the raw derivatives
    are keyed by factor name and are per-decade for log-scale factors (the
    form the variance budget needs for dose).

    ``evaluate(name, value) -> float`` must re-run the forward model with one
    condition changed and return the response on the **logit-of-inhibition**
    scale. Logit rather than the raw fraction is what keeps this analysis
    informative for a saturated prediction: at 0.99999 inhibition every
    derivative of the fraction is ~0, while the logit derivative still ranks
    the factors correctly. One logit unit is ~0.43 log10 of survival.

    All derivatives are central differences. A factor sitting at zero on a
    ratio scale (no salt, no producer cells) cannot be perturbed
    multiplicatively, so it is probed one-sided from a small positive value and
    flagged in its rationale.
    """
    steps = steps or SENSITIVITY_STEPS
    out: list[ImportantFactor] = []
    derivatives: dict[str, float] = {}

    for name, value in factors.items():
        if value is None:
            continue
        kind, step, unit = steps.get(name, ("log10", 0.10, "per decade"))
        one_sided = False
        try:
            if kind == "log10":
                if value <= _LOG_FLOOR:
                    # one-sided probe: ask what one decade of *adding* the factor does
                    probe = max(value, 0.0) + 10.0 ** -step
                    deriv = (evaluate(name, probe) - base_value) / step
                    one_sided = True
                else:
                    up = evaluate(name, value * 10.0 ** step)
                    down = evaluate(name, value * 10.0 ** -step)
                    deriv = (up - down) / (2.0 * step)
            else:
                up = evaluate(name, value + step)
                down = evaluate(name, value - step)
                deriv = (up - down) / (2.0 * step)
                deriv *= _LINEAR_REPORT_SCALE.get(name, 1.0)
        except Exception as exc:  # a perturbation may leave the valid domain
            out.append(
                ImportantFactor(
                    factor=name,
                    sensitivity=0.0,
                    direction="negligible",
                    value=value,
                    unit=unit,
                    source=sources.get(name, ParameterSource.PROVIDED),
                    rationale=f"sensitivity could not be evaluated: {exc}",
                )
            )
            continue

        derivatives[name] = deriv

        if abs(deriv) < 1e-3:
            direction = "negligible"
        elif deriv > 0:
            direction = "increases_activity"
        else:
            direction = "decreases_activity"

        source = sources.get(name, ParameterSource.PROVIDED)
        rationale = (
            f"d logit(inhibition) = {deriv:+.3f} {unit} at the evaluated point"
            f" (~{deriv / 2.303:+.2f} log10 of survival)"
        )
        if one_sided:
            rationale += "; one-sided probe because the factor is at zero"
        if source == ParameterSource.IMPUTED_DEFAULT and abs(deriv) > 0.5:
            rationale += (
                "; this factor was NOT specified in the spec yet strongly affects the "
                "outcome -- specify or sweep it"
            )
        out.append(
            ImportantFactor(
                factor=name,
                sensitivity=round(deriv, 5),
                direction=direction,
                value=value,
                unit=unit,
                source=source,
                rationale=rationale,
            )
        )

    out.sort(key=lambda f: abs(f.sensitivity), reverse=True)
    return out, derivatives
