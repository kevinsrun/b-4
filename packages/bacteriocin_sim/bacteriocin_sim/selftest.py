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


def check(name: str):
    def register(fn: Callable[[], tuple[bool, str]]):
        CHECKS[name] = fn
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


@check("uncertainty_grows_when_inputs_are_unknown")
def _uncertainty() -> tuple[bool, str]:
    known = run_experiment(spec())
    unknown = run_experiment(
        {
            "experiment_id": "selftest-unknown",
            "candidate_id": "cand-mystery",
            "target": {"species": "Nocardiopsis mysteriosa"},
            "conditions": {"assay_domain": "simulated_in_vitro"},
        }
    )
    a = known.measurement.sigma_logit_inhibition or 0.0
    b = unknown.measurement.sigma_logit_inhibition or 0.0
    return b > a, (
        f"sigma(logit) fully-specified={a:.3f} vs unknown candidate and organism={b:.3f}"
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
    """Run every invariant check and return a JSON-compatible report."""
    checks: list[dict[str, Any]] = []
    for name, fn in CHECKS.items():
        try:
            passed, detail = fn()
        except Exception as exc:  # a crash is a failure
            passed, detail = False, f"raised {type(exc).__name__}: {exc}"
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
    return {
        "passed": all(c["passed"] for c in checks),
        "n_checks": len(checks),
        "n_failed": sum(1 for c in checks if not c["passed"]),
        "checks": checks,
    }
