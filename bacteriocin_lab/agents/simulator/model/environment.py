"""Condition resolution: units, defaults, organism/medium lookup, environment terms.

This module turns a loosely-specified :class:`~bacteriocin_lab.agents.simulator.schemas.Conditions`
block into a fully-determined set of numbers, while recording for every value
whether it was *provided* or *imputed*. That record is what lets the backend
report honest uncertainty and tell the planner which unspecified condition
mattered most.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..schemas import (
    AssayType,
    Conditions,
    DensityUnit,
    EvidenceType,
    GrowthPhase,
    ParameterSource,
    Quantity,
)
from . import parameters as P
from .parameters import ParameterStore

AVOGADRO = 6.02214076e23

#: defaults applied when a condition is absent. Chosen to match a standard
#: broth-microdilution susceptibility assay, which is the most common
#: literature context and therefore the least surprising prior.
DEFAULTS: dict[str, Any] = {
    "ph": 7.0,
    "temperature_c": 37.0,
    "medium": P.DEFAULT_MEDIUM,
    "incubation_time_h": 18.0,
    "growth_phase": GrowthPhase.EXPONENTIAL.value,
    "target_cell_density_cfu_per_ml": 5.0e5,  # CLSI-style standard inoculum
    "bacteriocin_concentration_um": 1.0,
    "assay_type": AssayType.MICROTITER_GROWTH_INHIBITION.value,
}


@dataclass
class ResolvedValue:
    """One model input together with how it was obtained."""

    name: str
    value: Any
    source: ParameterSource
    evidence_type: EvidenceType = EvidenceType.DATABASE
    reference: str | None = None


@dataclass
class ResolvedConditions:
    """Fully-determined conditions plus bookkeeping."""

    ph: float
    temperature_c: float
    medium: str
    medium_params: dict[str, Any]
    incubation_time_h: float
    growth_phase: str
    target_density_cfu_per_ml: float
    producer_density_cfu_per_ml: float
    concentration_um: float
    assay_type: str
    assay_domain: str
    ionic_strength_mm: float
    divalent_mm: float
    edta_mm: float
    permeabilizer: str | None
    aeration: str | None
    provenance: list[ResolvedValue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    imputed: list[str] = field(default_factory=list)

    def record(
        self,
        name: str,
        value: Any,
        source: ParameterSource,
        evidence_type: EvidenceType = EvidenceType.DATABASE,
        reference: str | None = None,
    ) -> None:
        self.provenance.append(ResolvedValue(name, value, source, evidence_type, reference))
        if source == ParameterSource.IMPUTED_DEFAULT:
            self.imputed.append(name)


# --------------------------------------------------------------------------
# unit handling
# --------------------------------------------------------------------------


def to_cfu_per_ml(
    raw: float | Quantity | None,
    *,
    od600_to_cfu: float,
    warnings: list[str],
    label: str,
) -> float | None:
    """Convert a density in any supported unit to CFU/mL.

    A bare number is interpreted as CFU/mL with a warning -- cell density is a
    first-class variable in this model and a silent unit assumption that is
    wrong by orders of magnitude would corrupt the inoculum-effect term.
    """
    if raw is None:
        return None
    if isinstance(raw, Quantity):
        unit = (raw.unit or "").strip().lower()
        value = float(raw.value)
        if unit in (DensityUnit.CFU_PER_ML.value, DensityUnit.CELLS_PER_ML.value,
                    "cfu/ml", "cells/ml"):
            return value
        if unit in (DensityUnit.OD600.value, "od", "od_600", "od600nm"):
            return value * od600_to_cfu
        if unit in (DensityUnit.LOG10_CFU_PER_ML.value, "log10cfu/ml", "log_cfu_per_ml"):
            return 10.0 ** value
        warnings.append(
            f"{label}: unrecognised density unit {raw.unit!r}; interpreted as CFU/mL"
        )
        return value
    value = float(raw)
    warnings.append(
        f"{label}: supplied as a bare number without a unit; interpreted as CFU/mL. "
        "Send {'value': ..., 'unit': 'od600'|'cfu_per_ml'|'log10_cfu_per_ml'} to be explicit."
    )
    return value


def to_micromolar(
    raw: float | Quantity | None,
    *,
    molecular_weight_da: float | None,
    warnings: list[str],
) -> float | None:
    """Convert a bacteriocin concentration to micromolar.

    ``ug_per_ml`` requires a molecular weight; without one the conversion is
    refused and the value is treated as already-micromolar, with a warning,
    rather than silently fabricating a mass.
    """
    if raw is None:
        return None
    if isinstance(raw, Quantity):
        unit = (raw.unit or "").strip().lower()
        value = float(raw.value)
        if unit in ("um", "µm", "umol/l", "micromolar"):
            return value
        if unit in ("nm", "nmol/l", "nanomolar"):
            return value / 1000.0
        if unit in ("mm", "mmol/l", "millimolar"):
            return value * 1000.0
        if unit in ("ug_per_ml", "ug/ml", "mg/l", "µg/ml"):
            if molecular_weight_da and molecular_weight_da > 0:
                return value * 1000.0 / molecular_weight_da
            warnings.append(
                "bacteriocin_concentration given in ug/mL but no molecular weight is "
                "available for the candidate; value used as micromolar instead"
            )
            return value
        if unit in ("iu_per_ml", "iu/ml", "au_per_ml", "au/ml"):
            # Activity units are assay-specific and not convertible to molarity.
            warnings.append(
                f"bacteriocin_concentration in {raw.unit!r} is an assay-defined "
                "activity unit and cannot be converted to molarity; the simulation "
                "requires a molar or mass concentration"
            )
            return None
        warnings.append(
            f"unrecognised concentration unit {raw.unit!r}; interpreted as micromolar"
        )
        return value
    warnings.append(
        "bacteriocin_concentration supplied as a bare number without a unit; "
        "interpreted as micromolar"
    )
    return float(raw)


def hours(value: float | None, unit: str) -> float | None:
    if value is None:
        return None
    factor = {"h": 1.0, "min": 1.0 / 60.0, "s": 1.0 / 3600.0}.get(unit, 1.0)
    return value * factor


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------


def resolve_target(
    species: str | None, store: ParameterStore, warnings: list[str]
) -> tuple[dict[str, Any], ParameterSource, str]:
    """Look up target priors by species, then genus, then envelope, then generic."""
    if not species:
        warnings.append(
            "no target species specified; generic unknown-organism prior used and "
            "uncertainty inflated accordingly"
        )
        return dict(P.ENVELOPE_FALLBACKS["unknown"]), ParameterSource.FALLBACK_GENERIC, "unknown"

    key = species.strip().lower()
    if key in store.targets:
        return dict(store.targets[key]), ParameterSource.CURATED_PRIOR, key

    # genus-level: match any curated species sharing the genus
    genus = key.split()[0] if key.split() else key
    for curated_key, entry in store.targets.items():
        if curated_key.split()[0] == genus:
            merged = dict(entry)
            merged["sigma_log10_mic"] = float(entry.get("sigma_log10_mic", 0.8)) + 0.35
            merged["confidence"] = float(entry.get("confidence", 0.3)) * 0.6
            merged["notes"] = (
                f"no entry for {species!r}; priors borrowed from the congener "
                f"{curated_key!r} with widened uncertainty"
            )
            warnings.append(
                f"target {species!r} not in the curated prior set; genus-level priors "
                f"from {curated_key!r} were used"
            )
            return merged, ParameterSource.HEURISTIC_INFERENCE, curated_key

    envelope = P.GENUS_ENVELOPE.get(genus, "unknown")
    warnings.append(
        f"target {species!r} not in the curated prior set and no congener found; "
        f"generic {envelope} prior used"
    )
    return dict(P.ENVELOPE_FALLBACKS[envelope]), ParameterSource.FALLBACK_GENERIC, envelope


def resolve_medium(
    medium: str | None, store: ParameterStore, warnings: list[str]
) -> tuple[str, dict[str, Any], ParameterSource]:
    """Look up medium parameters with normalised naming."""
    if not medium:
        return (
            P.DEFAULT_MEDIUM,
            dict(store.media[P.DEFAULT_MEDIUM]),
            ParameterSource.IMPUTED_DEFAULT,
        )
    key = medium.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "mueller_hinton": "mhb", "mueller_hinton_broth": "mhb",
        "cation_adjusted_mueller_hinton": "camhb", "ca_mhb": "camhb",
        "brain_heart_infusion": "bhi", "tryptic_soy_broth": "tsb",
        "de_man_rogosa_sharpe": "mrs", "luria_bertani": "lb",
        "milk": "skim_milk", "phosphate_buffered_saline": "pbs",
        "minimal_medium": "m9", "sif": "simulated_intestinal_fluid",
    }
    key = aliases.get(key, key)
    if key in store.media:
        return key, dict(store.media[key]), ParameterSource.PROVIDED
    warnings.append(
        f"medium {medium!r} is not in the curated medium set; CAMHB-like reference "
        "properties were assumed (peptide availability and protease activity are "
        "major sensitivities, so this is a notable uncertainty)"
    )
    entry = dict(store.media[P.DEFAULT_MEDIUM])
    entry["confidence"] = 0.15
    entry["notes"] = f"unknown medium {medium!r}; reference properties assumed"
    return key, entry, ParameterSource.FALLBACK_GENERIC


def resolve_growth_phase(phase: Any, warnings: list[str]) -> tuple[str, ParameterSource]:
    if phase is None:
        return DEFAULTS["growth_phase"], ParameterSource.IMPUTED_DEFAULT
    value = phase.value if isinstance(phase, GrowthPhase) else str(phase).strip().lower()
    if value in P.GROWTH_PHASE_SUSCEPTIBILITY:
        return value, ParameterSource.PROVIDED
    warnings.append(
        f"growth_phase {phase!r} not recognised; exponential phase assumed "
        "(growth phase is a strong susceptibility modifier)"
    )
    return DEFAULTS["growth_phase"], ParameterSource.FALLBACK_GENERIC


def resolve_assay_type(assay: Any, warnings: list[str]) -> tuple[str, ParameterSource]:
    if assay is None:
        return DEFAULTS["assay_type"], ParameterSource.IMPUTED_DEFAULT
    value = assay.value if isinstance(assay, AssayType) else str(assay).strip().lower()
    valid = {a.value for a in AssayType}
    if value in valid:
        return value, ParameterSource.PROVIDED
    warnings.append(
        f"assay_type {assay!r} not recognised; microtiter growth inhibition assumed. "
        f"Supported: {sorted(valid)}"
    )
    return DEFAULTS["assay_type"], ParameterSource.FALLBACK_GENERIC


# --------------------------------------------------------------------------
# environment response terms
# --------------------------------------------------------------------------


def cardinal_temperature_factor(t: float, t_min: float, t_opt: float, t_max: float) -> float:
    """Rosso cardinal temperature model (CTMI), clipped to [0, 1].

    Returns the fraction of mu_max supported at temperature ``t``.
    """
    if t <= t_min or t >= t_max:
        return 0.0
    num = (t - t_max) * (t - t_min) ** 2
    den = (t_opt - t_min) * (
        (t_opt - t_min) * (t - t_opt) - (t_opt - t_max) * (t_opt + t_min - 2.0 * t)
    )
    if den == 0:
        return 0.0
    return max(0.0, min(1.0, num / den))


def cardinal_ph_factor(ph: float, ph_min: float, ph_opt: float, ph_max: float) -> float:
    """Rosso cardinal pH model, clipped to [0, 1]."""
    if ph <= ph_min or ph >= ph_max:
        return 0.0
    num = (ph - ph_min) * (ph - ph_max)
    den = (ph - ph_min) * (ph - ph_max) - (ph - ph_opt) ** 2
    if den == 0:
        return 0.0
    return max(0.0, min(1.0, num / den))


def ionic_strength_mm(ionic: Any, medium_params: dict[str, Any]) -> tuple[float, float, float]:
    """Return ``(monovalent_ionic_strength_mM, divalent_mM, edta_mM)``.

    Ionic strength uses I = 1/2 * sum(c_i * z_i^2), so a divalent salt
    contributes three times a monovalent one at equal molarity.
    """
    nacl = float(getattr(ionic, "nacl_mm", None) or 0.0)
    kcl = float(getattr(ionic, "kcl_mm", None) or 0.0)
    mgcl2 = float(getattr(ionic, "mgcl2_mm", None) or 0.0)
    cacl2 = float(getattr(ionic, "cacl2_mm", None) or 0.0)
    edta = float(getattr(ionic, "edta_mm", None) or 0.0)

    explicit_mono = nacl + kcl
    explicit_div = mgcl2 + cacl2
    if explicit_mono <= 0.0:
        explicit_mono = float(medium_params.get("monovalent_baseline_mm", 0.0) or 0.0)
    if explicit_div <= 0.0:
        explicit_div = float(medium_params.get("divalent_baseline_mm", 0.0) or 0.0)

    # EDTA chelates divalent cations roughly 1:1.
    free_div = max(0.0, explicit_div - edta)
    ionic_i = explicit_mono + 3.0 * free_div
    return ionic_i, free_div, edta


def monovalent_screening_factor(ionic_i_mm: float, store: ParameterStore) -> float:
    """Fraction of electrostatic peptide-membrane attraction surviving screening."""
    half = store.g("monovalent_half_mm")
    n = store.g("monovalent_hill")
    if ionic_i_mm <= 0:
        return 1.0
    return 1.0 / (1.0 + (ionic_i_mm / half) ** n)


def divalent_competition_factor(divalent_mm: float, store: ParameterStore) -> float:
    """Competitive displacement of the peptide by Mg2+/Ca2+ at anionic sites."""
    kd = store.g("divalent_kd_mm")
    return 1.0 / (1.0 + max(0.0, divalent_mm) / kd)


def peptide_decay_rate_per_h(
    temperature_c: float,
    ph: float,
    medium_params: dict[str, Any],
    alkaline_lability: float,
    store: ParameterStore,
) -> float:
    """First-order loss of active peptide.

    Combines an Arrhenius temperature term (referenced to 37 C), pH-dependent
    chemical lability (lantibiotics are acid-stable and alkali-labile) and
    medium protease activity.
    """
    k0 = store.g("k_deg_base_per_h")
    ea = store.g("deg_activation_energy_kj") * 1000.0
    r = 8.314
    t_k = temperature_c + 273.15
    t_ref = 310.15
    t_k = max(t_k, 200.0)
    arrhenius = math.exp(-ea / r * (1.0 / t_k - 1.0 / t_ref))

    ph_factor = 1.0
    if ph > 6.5:
        ph_factor *= 10.0 ** (store.g("deg_ph_alkaline_slope") * alkaline_lability * (ph - 6.5))
    elif ph < 4.0:
        ph_factor *= 10.0 ** (store.g("deg_ph_acid_slope") * (4.0 - ph))

    protease = float(medium_params.get("protease_activity", 1.0) or 1.0)
    return k0 * arrhenius * ph_factor * protease


def binding_site_concentration_um(
    cells_per_ml: float, sites_per_cell: float
) -> float:
    """Concentration of peptide-binding membrane sites, in micromolar.

    ``sites_per_cell`` binding sites on ``cells_per_ml`` cells gives
    ``sites_per_cell * cells_per_ml * 1000 / N_A`` mol/L, i.e. the conversion
    below. At 1e5-1e6 sites/cell this is negligible at 1e5 CFU/mL but reaches
    the sub-micromolar range near 1e9 CFU/mL -- which is exactly the regime in
    which the inoculum effect becomes the dominant experimental variable.
    """
    mol_per_litre = sites_per_cell * cells_per_ml * 1000.0 / AVOGADRO
    return mol_per_litre * 1e6


def free_concentration_um(total_um: float, sites_um: float, kd_um: float) -> float:
    """Langmuir mass balance ``total = free + sites*free/(Kd+free)``.

    Solved in closed form (the physical root of the quadratic). This is how
    high cell density titrates peptide out of solution and raises the apparent
    MIC without any ad-hoc fudge factor.
    """
    if total_um <= 0.0:
        return 0.0
    if sites_um <= 0.0:
        return total_um
    kd = max(kd_um, 1e-12)
    b = kd + sites_um - total_um
    c = -kd * total_um
    disc = b * b - 4.0 * c
    disc = max(disc, 0.0)
    free = 0.5 * (-b + math.sqrt(disc))
    return min(total_um, max(0.0, free))


def resolve_conditions(
    conditions: Conditions,
    *,
    target_params: dict[str, Any],
    molecular_weight_da: float | None,
    store: ParameterStore,
) -> ResolvedConditions:
    """Fill in every model input, recording provenance for each."""
    warnings: list[str] = []

    medium_key, medium_params, medium_source = resolve_medium(
        conditions.medium, store, warnings
    )
    ph = conditions.ph
    ph_source = ParameterSource.PROVIDED
    if ph is None:
        ph = DEFAULTS["ph"]
        ph_source = ParameterSource.IMPUTED_DEFAULT

    temp = conditions.temperature_c
    temp_source = ParameterSource.PROVIDED
    if temp is None:
        temp = DEFAULTS["temperature_c"]
        temp_source = ParameterSource.IMPUTED_DEFAULT

    t_h = hours(conditions.incubation_time, conditions.incubation_time_unit)
    time_source = ParameterSource.PROVIDED
    if t_h is None:
        t_h = DEFAULTS["incubation_time_h"]
        time_source = ParameterSource.IMPUTED_DEFAULT

    phase, phase_source = resolve_growth_phase(conditions.growth_phase, warnings)
    assay_type, assay_source = resolve_assay_type(conditions.assay_type, warnings)

    od_factor = float(target_params.get("od600_to_cfu_per_ml", 8.0e8))
    density = to_cfu_per_ml(
        conditions.target_cell_density,
        od600_to_cfu=od_factor,
        warnings=warnings,
        label="target_cell_density",
    )
    density_source = ParameterSource.PROVIDED
    if density is None:
        density = DEFAULTS["target_cell_density_cfu_per_ml"]
        density_source = ParameterSource.IMPUTED_DEFAULT
        warnings.append(
            "target_cell_density was not specified; a standard 5e5 CFU/mL inoculum "
            "was assumed. Cell density changes the apparent potency through peptide "
            "titration, so this assumption is material."
        )

    producer = to_cfu_per_ml(
        conditions.producer_cell_density,
        od600_to_cfu=od_factor,
        warnings=warnings,
        label="producer_cell_density",
    ) or 0.0

    conc = to_micromolar(
        conditions.bacteriocin_concentration,
        molecular_weight_da=molecular_weight_da,
        warnings=warnings,
    )
    conc_source = ParameterSource.PROVIDED
    if conc is None:
        if producer > 0.0:
            conc = 0.0
            conc_source = ParameterSource.IMPUTED_DEFAULT
            warnings.append(
                "no exogenous bacteriocin concentration given; peptide is supplied "
                "only by in-situ production from producer_cell_density"
            )
        else:
            conc = DEFAULTS["bacteriocin_concentration_um"]
            conc_source = ParameterSource.IMPUTED_DEFAULT
            warnings.append(
                "bacteriocin_concentration was not specified; 1 uM was assumed. "
                "This is the strongest single determinant of the predicted outcome."
            )

    ionic = conditions.ionic_conditions
    ionic_i, divalent, edta = ionic_strength_mm(ionic, medium_params)

    resolved = ResolvedConditions(
        ph=float(ph),
        temperature_c=float(temp),
        medium=medium_key,
        medium_params=medium_params,
        incubation_time_h=float(t_h),
        growth_phase=phase,
        target_density_cfu_per_ml=float(density),
        producer_density_cfu_per_ml=float(producer),
        concentration_um=float(conc),
        assay_type=assay_type,
        assay_domain=(
            conditions.assay_domain.value
            if hasattr(conditions.assay_domain, "value")
            else str(conditions.assay_domain)
        ),
        ionic_strength_mm=ionic_i,
        divalent_mm=divalent,
        edta_mm=edta,
        permeabilizer=conditions.permeabilizer,
        aeration=conditions.aeration,
        warnings=warnings,
    )

    resolved.record("ph", ph, ph_source)
    resolved.record("temperature_c", temp, temp_source)
    resolved.record("medium", medium_key, medium_source)
    resolved.record("incubation_time_h", t_h, time_source)
    resolved.record("growth_phase", phase, phase_source)
    resolved.record("assay_type", assay_type, assay_source)
    resolved.record("target_cell_density_cfu_per_ml", density, density_source)
    resolved.record("bacteriocin_concentration_um", conc, conc_source)
    resolved.record(
        "producer_cell_density_cfu_per_ml",
        producer,
        ParameterSource.PROVIDED
        if conditions.producer_cell_density is not None
        else ParameterSource.IMPUTED_DEFAULT,
    )
    # Ionic composition is "provided" when stated explicitly; otherwise it comes
    # from the medium's curated composition, which is a real database-derived
    # value rather than a blind default -- unless the medium itself was imputed.
    medium_was_chosen = medium_source != ParameterSource.IMPUTED_DEFAULT
    mono_explicit = any(
        getattr(ionic, f, None) is not None for f in ("nacl_mm", "kcl_mm")
    )
    div_explicit = any(
        getattr(ionic, f, None) is not None for f in ("mgcl2_mm", "cacl2_mm")
    )
    resolved.record(
        "ionic_strength_mm",
        round(ionic_i, 3),
        ParameterSource.PROVIDED
        if mono_explicit or div_explicit
        else (
            ParameterSource.CURATED_PRIOR
            if medium_was_chosen
            else ParameterSource.IMPUTED_DEFAULT
        ),
        reference=None if (mono_explicit or div_explicit) else f"composition of {medium_key}",
    )
    resolved.record(
        "divalent_cation_mm",
        round(divalent, 3),
        ParameterSource.PROVIDED
        if div_explicit
        else (
            ParameterSource.CURATED_PRIOR
            if medium_was_chosen
            else ParameterSource.IMPUTED_DEFAULT
        ),
        reference=None if div_explicit else f"composition of {medium_key}",
    )
    return resolved


def domain_excursions(
    resolved: ResolvedConditions, store: ParameterStore
) -> list[tuple[str, float, float]]:
    """Report conditions outside the validated domain.

    Each entry is ``(name, value, relative_excursion)`` where the excursion is
    the distance beyond the validated bound, normalised by the bound width (or
    by a decade, for log-scaled quantities).
    """
    out: list[tuple[str, float, float]] = []
    checks = {
        "ph": resolved.ph,
        "temperature_c": resolved.temperature_c,
        "incubation_time_h": resolved.incubation_time_h,
        "bacteriocin_concentration_um": resolved.concentration_um,
        "target_cell_density_cfu_per_ml": resolved.target_density_cfu_per_ml,
        "ionic_strength_mm": resolved.ionic_strength_mm,
    }
    log_scaled = {
        "bacteriocin_concentration_um",
        "target_cell_density_cfu_per_ml",
    }
    for name, value in checks.items():
        bounds = store.domain.get(name)
        if not bounds:
            continue
        low, high = bounds
        if name in log_scaled:
            if value <= 0:
                continue
            if value < low:
                out.append((name, value, abs(math.log10(low / value))))
            elif value > high:
                out.append((name, value, abs(math.log10(value / high))))
        else:
            width = max(high - low, 1e-9)
            if value < low:
                out.append((name, value, (low - value) / width))
            elif value > high:
                out.append((name, value, (value - high) / width))
    return out
