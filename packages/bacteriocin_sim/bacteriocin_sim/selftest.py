"""Qualitative invariants the forward model must satisfy.

These are not precision checks -- the priors are too coarse for that. They are
*directional* checks: statements that are true of bacteriocin biology and must
therefore be true of any usable model of it. If one fails, the model is giving
scientifically wrong answers regardless of how confident it looks.

Available both as ``python -m bacteriocin_sim selftest`` and as the backbone of
the pytest suite, so the invariants are checked in CI and in the field.
"""

from __future__ import annotations

from typing import Any, Callable

from .api import run_experiment

NISIN_A = "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK"
PEDIOCIN_PA1 = "KYYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC"


def spec(**overrides: Any) -> dict[str, Any]:
    """A reference spec: nisin-like peptide vs Listeria under standard conditions."""
    conditions = {
        "bacteriocin_concentration": {"value": 1.0, "unit": "uM"},
        "target_cell_density": {"value": 1.0e6, "unit": "cfu_per_ml"},
        "ph": 6.5,
        "temperature_c": 30.0,
        "medium": "bhi",
        "incubation_time": 6.0,
        "growth_phase": "exponential",
        "assay_domain": "simulated_in_vitro",
        "assay_type": "microtiter_growth_inhibition",
    }
    conditions.update(overrides.pop("conditions", {}))
    base: dict[str, Any] = {
        "experiment_id": overrides.pop("experiment_id", "selftest"),
        "candidate_id": "cand-nisin-a",
        "candidate": {
            "sequence": NISIN_A,
            "bacteriocin_class": "class_I_lantibiotic",
        },
        "target": {"species": "Listeria monocytogenes"},
        "conditions": conditions,
    }
    base.update(overrides)
    return base


def inhibition(**overrides: Any) -> float:
    result = run_experiment(spec(**overrides))
    return float(result.measurement.predicted_inhibition_fraction or 0.0)


def mic(**overrides: Any) -> float:
    result = run_experiment(spec(**overrides))
    return float(result.measurement.predicted_mic_um or 0.0)


def _conditions(**kwargs: Any) -> dict[str, Any]:
    return {"conditions": kwargs}


#: each check returns ``(passed, detail)``
CHECKS: dict[str, Callable[[], tuple[bool, str]]] = {}

#: Invariants that are *correct as written* but that the model currently
#: violates -- open defects, not wrong tests.
#:
#: They are registered rather than weakened because an invariant that passes
#: while the model is wrong is worse than no invariant at all: it certifies
#: the defect. Keeping the real statement here means the check flips to
#: ``unexpectedly_fixed`` the moment someone repairs the model, so nobody has
#: to remember to come back and tighten it.
#:
#: A known failure does not fail the run. It is reported, loudly, as an open
#: defect so it cannot block unrelated work while the fix is being decided.
KNOWN_FAILURES: dict[str, str] = {}


def check(name: str, *, known_failure: str | None = None):
    def register(fn: Callable[[], tuple[bool, str]]):
        CHECKS[name] = fn
        if known_failure:
            KNOWN_FAILURES[name] = known_failure
        return fn

    return register


@check("dose_response_is_monotone")
def _dose_monotone() -> tuple[bool, str]:
    doses = [0.0, 0.05, 0.2, 0.5, 1.0, 2.0, 5.0, 20.0]
    values = [
        inhibition(**_conditions(bacteriocin_concentration={"value": d, "unit": "uM"}))
        for d in doses
    ]
    ok = all(b >= a - 1e-9 for a, b in zip(values, values[1:]))
    return ok, f"inhibition vs dose {list(zip(doses, [round(v, 5) for v in values]))}"


@check("zero_dose_gives_no_inhibition")
def _zero_dose() -> tuple[bool, str]:
    value = inhibition(
        **_conditions(bacteriocin_concentration={"value": 0.0, "unit": "uM"})
    )
    return value < 1e-6, f"inhibition at zero dose = {value}"


@check("inoculum_effect_raises_apparent_resistance")
def _inoculum() -> tuple[bool, str]:
    densities = [1e4, 1e6, 1e8, 1e9]
    values = [
        inhibition(
            **_conditions(
                target_cell_density={"value": d, "unit": "cfu_per_ml"},
                bacteriocin_concentration={"value": 0.6, "unit": "uM"},
            )
        )
        for d in densities
    ]
    ok = all(b <= a + 1e-9 for a, b in zip(values, values[1:]))
    return ok, f"inhibition vs density {list(zip(densities, [round(v, 5) for v in values]))}"


@check("gram_negative_is_less_susceptible")
def _gram_negative() -> tuple[bool, str]:
    gp = mic(target={"species": "Listeria monocytogenes"})
    gn = mic(target={"species": "Escherichia coli"})
    return gn > gp, f"MIC Listeria={gp:.4g} uM vs E. coli={gn:.4g} uM"


@check("edta_relieves_the_outer_membrane_barrier")
def _edta() -> tuple[bool, str]:
    without = mic(target={"species": "Escherichia coli"})
    with_edta = mic(
        target={"species": "Escherichia coli"},
        **_conditions(ionic_conditions={"edta_mm": 5.0}),
    )
    return with_edta < without, f"MIC without EDTA={without:.4g}, with EDTA={with_edta:.4g}"


@check("class_IIa_needs_the_mannose_pts_receptor")
def _receptor() -> tuple[bool, str]:
    candidate = {"sequence": PEDIOCIN_PA1, "bacteriocin_class": "class_IIa_pediocin_like"}
    listeria = mic(candidate=candidate, target={"species": "Listeria monocytogenes"})
    aureus = mic(candidate=candidate, target={"species": "Staphylococcus aureus"})
    return aureus > listeria * 3.0, (
        f"class IIa MIC: Listeria (Man-PTS+)={listeria:.4g} uM, "
        f"S. aureus (Man-PTS-)={aureus:.4g} uM"
    )


@check("resistance_determinants_reduce_activity")
def _resistance() -> tuple[bool, str]:
    plain = mic()
    resistant = mic(
        target={
            "species": "Listeria monocytogenes",
            "resistance_factors": [{"name": "nsr", "effect": "resistance"}],
        }
    )
    return resistant > plain, f"MIC without NSR={plain:.4g}, with NSR={resistant:.4g}"


@check("divalent_cations_antagonise_a_cationic_peptide")
def _divalent() -> tuple[bool, str]:
    low = mic(**_conditions(ionic_conditions={"mgcl2_mm": 0.0, "cacl2_mm": 0.0}))
    high = mic(**_conditions(ionic_conditions={"mgcl2_mm": 10.0, "cacl2_mm": 10.0}))
    return high > low, f"MIC at low divalent={low:.4g}, at 20 mM divalent={high:.4g}"


@check("stationary_cells_are_more_tolerant_than_exponential")
def _growth_phase() -> tuple[bool, str]:
    exponential = inhibition(
        **_conditions(
            growth_phase="exponential", bacteriocin_concentration={"value": 0.6, "unit": "uM"}
        )
    )
    stationary = inhibition(
        **_conditions(
            growth_phase="stationary", bacteriocin_concentration={"value": 0.6, "unit": "uM"}
        )
    )
    return stationary < exponential, (
        f"inhibition exponential={exponential:.5f} vs stationary={stationary:.5f}"
    )


@check("binding_media_reduce_activity")
def _medium() -> tuple[bool, str]:
    broth = inhibition(
        **_conditions(medium="camhb", bacteriocin_concentration={"value": 0.6, "unit": "uM"})
    )
    milk = inhibition(
        **_conditions(
            medium="whole_milk", bacteriocin_concentration={"value": 0.6, "unit": "uM"}
        )
    )
    return milk < broth, f"inhibition in CAMHB={broth:.5f} vs whole milk={milk:.5f}"


@check("incubation_time_changes_the_readout")
def _time() -> tuple[bool, str]:
    early = inhibition(
        **_conditions(
            incubation_time=2.0, bacteriocin_concentration={"value": 0.6, "unit": "uM"}
        )
    )
    late = inhibition(
        **_conditions(
            incubation_time=24.0, bacteriocin_concentration={"value": 0.6, "unit": "uM"}
        )
    )
    return abs(late - early) > 1e-4, (
        f"inhibition at 2 h={early:.5f} vs 24 h={late:.5f} (must differ: time is a "
        "genuine experimental variable, not a formality)"
    )


@check("determinism")
def _determinism() -> tuple[bool, str]:
    a = run_experiment(spec()).to_json_dict()
    b = run_experiment(spec()).to_json_dict()
    a.pop("created_at", None)
    b.pop("created_at", None)
    return a == b, "two identical runs produced identical results (excluding timestamp)"


#: Doses spanning the response curve: well below the MIC, across the
#: transition, and saturating above it.
_UNCERTAINTY_DOSES_UM = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 50.0)

#: Readout times spanning kill, plateau and regrowth. Both axes are required:
#: the violation occupies a *region* of the dose-time plane (roughly 0.25-1 uM
#: at 8-24 h), so a sweep over dose alone at the reference 6 h readout passes
#: cleanly while the model is wrong.
_UNCERTAINTY_HOURS = (6.0, 12.0, 24.0)


def _blind_spec(dose_um: float) -> dict[str, Any]:
    """The reference experiment with the candidate and organism withheld.

    Every *condition* is still specified and identical to :func:`spec`, so the
    only difference is what the model knows about the peptide and the target.
    That isolation matters: leaving conditions unspecified too would add
    ``imputed_conditions`` variance and let the invariant pass for a reason
    that has nothing to do with the ignorance being tested.
    """
    s = spec(
        experiment_id="selftest-blind",
        conditions={"bacteriocin_concentration": {"value": dose_um, "unit": "uM"}},
    )
    s.pop("candidate", None)
    s["candidate_id"] = "cand-mystery"
    s["target"] = {"species": "Nocardiopsis mysteriosa"}
    return s


@check(
    "uncertainty_grows_when_inputs_are_unknown",
    known_failure=(
        "the sigma budget is dominated by target_potency_prior, a secant of the "
        "response curve at +/-1 sigma of the MIC prior. With the candidate and "
        "organism unknown the model falls back to a weak-peptide prior, which "
        "places the prediction far below the MIC on the flat floor of the "
        "sigmoid; the secant there collapses faster than the ignorance terms "
        "(no_candidate_sequence, unknown_target_organism) grow, so total sigma "
        "FALLS. Fixing it is a modelling decision -- floor the budget by the "
        "ignorance terms, or widen the secant until it leaves the plateau -- "
        "and it changes published numbers, so it is not applied here."
    ),
)
def _uncertainty() -> tuple[bool, str]:
    """Knowing less must never make the model more certain.

    Swept over dose *and* readout time rather than tested at one point. The
    violation occupies a bounded region of that plane -- around the MIC, once
    enough time has passed for kill and regrowth to compete -- so a check at a
    single hard-coded point reports whatever that point happens to sit on. The
    original version of this invariant tested one dose at the 6 h reference
    readout, which lies just outside the region, and so certified the model as
    sound while it was not.
    """
    violations: list[str] = []
    n_points = 0
    for hours in _UNCERTAINTY_HOURS:
        for dose in _UNCERTAINTY_DOSES_UM:
            n_points += 1
            informed = run_experiment(
                spec(
                    conditions={
                        "bacteriocin_concentration": {"value": dose, "unit": "uM"},
                        "incubation_time": hours,
                    }
                )
            )
            blind_spec = _blind_spec(dose)
            blind_spec["conditions"]["incubation_time"] = hours
            blind = run_experiment(blind_spec)
            a = informed.measurement.sigma_logit_inhibition or 0.0
            b = blind.measurement.sigma_logit_inhibition or 0.0
            if b < a:
                violations.append(f"{dose:g}uM/{hours:g}h: informed={a:.3f} > blind={b:.3f}")

    if violations:
        shown = "; ".join(violations[:4])
        more = f" (+{len(violations) - 4} more)" if len(violations) > 4 else ""
        return False, (
            f"withholding the candidate sequence and the organism LOWERED "
            f"sigma(logit) at {len(violations)}/{n_points} dose-time points "
            f"[{shown}{more}] -- the model reports more certainty when it knows less"
        )
    return True, (
        f"sigma(logit) never fell when inputs were withheld, across {n_points} "
        f"dose-time points spanning the response curve and the regrowth window"
    )


@check("never_claims_experimental_validation")
def _provenance() -> tuple[bool, str]:
    result = run_experiment(spec())
    ok = (
        result.evidence_type.value == "simulation-derived"
        and result.validated_experimentally is False
        and any("SIMULATION-DERIVED" in w for w in result.warnings)
    )
    return ok, f"evidence_type={result.evidence_type.value}, warnings carry the caveat"


def run_selftest() -> dict[str, Any]:
    """Run every invariant check and return a JSON-compatible report.

    Each check gets a ``status``:

    ``pass``
        The invariant holds.
    ``fail``
        The invariant is violated and that is news. The run fails.
    ``known_failure``
        A violation already recorded in :data:`KNOWN_FAILURES`, with the
        reason. Reported but does not fail the run, so an open modelling
        defect does not block unrelated work.
    ``unexpectedly_fixed``
        A known failure that now passes. Does not fail the run, but says so
        plainly: somebody repaired the model and this entry should be retired
        from :data:`KNOWN_FAILURES`.
    """
    checks: list[dict[str, Any]] = []
    for name, fn in CHECKS.items():
        try:
            passed, detail = fn()
        except Exception as exc:  # a crash is a failure
            passed, detail = False, f"raised {type(exc).__name__}: {exc}"
        known = KNOWN_FAILURES.get(name)
        if known is None:
            status = "pass" if passed else "fail"
        else:
            status = "unexpectedly_fixed" if passed else "known_failure"
        entry: dict[str, Any] = {
            "check": name,
            "passed": bool(passed),
            "status": status,
            "detail": detail,
        }
        if known is not None:
            entry["known_failure_reason"] = known
        checks.append(entry)

    n_known = sum(1 for c in checks if c["status"] == "known_failure")
    n_fixed = sum(1 for c in checks if c["status"] == "unexpectedly_fixed")
    n_failed = sum(1 for c in checks if c["status"] == "fail")
    report: dict[str, Any] = {
        "passed": n_failed == 0,
        "n_checks": len(checks),
        "n_failed": n_failed,
        "n_known_failures": n_known,
        "checks": checks,
    }
    if n_known:
        report["note"] = (
            f"{n_known} invariant(s) are known to be violated: open defects in the "
            f"model, not wrong tests. See each check's known_failure_reason."
        )
    if n_fixed:
        report["n_unexpectedly_fixed"] = n_fixed
        report["note_fixed"] = (
            f"{n_fixed} known failure(s) now pass -- retire them from KNOWN_FAILURES."
        )
    return report
