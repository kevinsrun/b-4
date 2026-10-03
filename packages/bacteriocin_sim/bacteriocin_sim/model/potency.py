"""Structure-activity model: effective MIC for a peptide/target/condition triple.

The potency model is additive in log10 MIC, which is the scale on which
susceptibility data is conventionally reported and on which effects such as
receptor loss or outer-membrane exclusion are roughly additive:

    log10 MIC_eff = log10 MIC_base(target)          curated organism prior
                  + class_offset                    structural class
                  - charge_term                     cationicity vs reference
                  - amphipathicity_term             hydrophobic moment
                  + length_mismatch_term
                  + receptor_term                    missing receptor penalty
                  + outer_membrane_term              Gram-negative barrier
                  + resistance_term                  named determinants
                  + electrostatic_term               ionic screening/competition

Each term is bounded (``tanh`` for the continuous descriptors, explicit caps
for the additive penalties) so that extrapolation degrades gracefully instead
of producing unphysical MICs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..schemas import BacteriocinClass, ParameterSource, ResistanceFactor
from . import environment as env
from . import peptide as pep
from .parameters import ParameterStore


@dataclass
class PotencyResult:
    """Effective potency and a full term-by-term breakdown."""

    mic_um: float
    log10_mic_um: float
    hill_coefficient: float
    terms: dict[str, float] = field(default_factory=dict)
    receptor: str = "membrane_only"
    receptor_availability: float = 1.0
    electrostatic_factor: float = 1.0
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def class_parameters(
    bacteriocin_class: str, store: ParameterStore
) -> tuple[dict[str, Any], bool]:
    """Fetch class parameters, falling back to the UNKNOWN profile."""
    entry = store.classes.get(bacteriocin_class)
    if entry is None:
        return dict(store.classes[BacteriocinClass.UNKNOWN.value]), True
    return dict(entry), False


def resistance_shift(
    factors: list[ResistanceFactor],
    bacteriocin_class: str,
    store: ParameterStore,
    warnings: list[str],
) -> tuple[float, list[dict[str, Any]]]:
    """Summed log10 MIC shift from named resistance/sensitisation determinants.

    A determinant whose known mechanism is class-specific (e.g. Man-PTS loss,
    which only affects class IIa) is applied at full magnitude for that class
    and at a quarter magnitude otherwise, rather than being ignored -- most
    determinants have some pleiotropic effect.
    """
    total = 0.0
    applied: list[dict[str, Any]] = []
    for factor in factors:
        key = factor.name.strip().lower().replace(" ", "_").replace("-", "_")
        known = store.resistance.get(key)
        magnitude = factor.magnitude_log10_mic
        source = ParameterSource.PROVIDED
        if magnitude is None:
            if known is not None:
                magnitude = float(known["magnitude_log10_mic"])
                source = ParameterSource.CURATED_PRIOR
            else:
                magnitude = store.g("default_resistance_log10")
                source = ParameterSource.IMPUTED_DEFAULT
                warnings.append(
                    f"resistance factor {factor.name!r} has no magnitude and is not in "
                    f"the curated set; a default {magnitude:+.1f} log10 MIC shift was "
                    "assumed"
                )
        scale = 1.0
        if known is not None and known.get("classes"):
            if bacteriocin_class not in known["classes"]:
                scale = 0.25
        signed = abs(magnitude) * scale
        if factor.effect == "sensitisation":
            signed = -signed
        elif magnitude < 0:
            signed = -abs(magnitude) * scale
        total += signed
        applied.append(
            {
                "name": factor.name,
                "effect": factor.effect,
                "log10_mic_shift": round(signed, 4),
                "magnitude_source": source.value,
                "class_specific_scaling": scale,
                "evidence_type": factor.evidence_type.value
                if hasattr(factor.evidence_type, "value")
                else str(factor.evidence_type),
                "evidence_id": factor.evidence_id,
            }
        )
    cap = store.g("max_resistance_log10")
    if total > cap:
        warnings.append(
            f"summed resistance shift {total:+.2f} log10 capped at {cap:+.2f}; the "
            "model does not extrapolate beyond ~1000-fold determinant stacking"
        )
        total = cap
    return total, applied


def effective_potency(
    descriptors: pep.PeptideDescriptors,
    target_params: dict[str, Any],
    resolved: env.ResolvedConditions,
    resistance_factors: list[ResistanceFactor],
    bacteriocin_class: str,
    store: ParameterStore,
) -> tuple[PotencyResult, list[dict[str, Any]]]:
    """Compute the effective MIC under the resolved conditions.

    Returns the potency result and the list of resistance determinants that
    were actually applied (for the result's provenance block).
    """
    warnings: list[str] = []
    notes: list[str] = []
    cls_params, cls_fallback = class_parameters(bacteriocin_class, store)
    if cls_fallback:
        warnings.append(
            f"structural class {bacteriocin_class!r} is not in the parameter set; the "
            "averaged unknown-class mechanism was used"
        )

    terms: dict[str, float] = {}
    log_mic = float(target_params.get("log10_mic_um_base", 0.7))
    terms["target_baseline"] = log_mic
    terms["class_offset"] = float(cls_params.get("potency_offset_log10", 0.0))

    # --- cationicity: more positive charge binds anionic envelopes better,
    #     with diminishing returns and a penalty for excessive charge that
    #     traps the peptide at the wall rather than the membrane.
    charge_at_ph = descriptors.net_charge
    if descriptors.sequence is not None and abs(descriptors.net_charge_ph - resolved.ph) > 1e-6:
        charge_at_ph = pep.net_charge_at_ph(descriptors.sequence, resolved.ph)
    delta_q = charge_at_ph - pep.REFERENCE_NET_CHARGE
    charge_term = store.g("w_net_charge") * math.tanh(delta_q / store.g("charge_scale"))
    terms["charge"] = -charge_term

    # --- amphipathicity: membrane insertion efficiency
    delta_mu = descriptors.hydrophobic_moment - pep.REFERENCE_HYDROPHOBIC_MOMENT
    moment_term = store.g("w_hydrophobic_moment") * math.tanh(
        delta_mu / store.g("moment_scale")
    )
    terms["amphipathicity"] = -moment_term

    # --- length: strong deviation from the characterised size range costs potency
    terms["length_mismatch"] = store.g("w_length_mismatch") * abs(
        descriptors.length - pep.REFERENCE_LENGTH
    )

    # --- receptor availability
    receptor = str(cls_params.get("receptor", "membrane_only"))
    profile = target_params.get("receptor_profile", {}) or {}
    availability = float(profile.get(receptor, 0.5))
    dependence = float(cls_params.get("receptor_dependence", 0.4))
    receptor_term = store.g("w_receptor") * dependence * (1.0 - availability)
    terms["receptor"] = receptor_term
    if availability < 0.2 and dependence > 0.5:
        notes.append(
            f"target lacks the {receptor} receptor that this class depends on; the "
            "predicted activity is near-baseline membrane activity only"
        )

    # --- Gram-negative outer membrane, relieved by chelators/permeabilisers
    om_barrier = float(target_params.get("om_barrier_log10", 0.0))
    relief = 0.0
    if om_barrier > 0.0:
        if resolved.edta_mm > 0.0:
            half = store.g("edta_permeabilisation_mm")
            relief = om_barrier * (resolved.edta_mm / (half + resolved.edta_mm))
            notes.append(
                f"EDTA at {resolved.edta_mm:g} mM relieves {relief:.2f} log10 of the "
                "outer-membrane barrier"
            )
        if resolved.permeabilizer:
            relief = max(relief, 0.6 * om_barrier)
            notes.append(
                f"permeabiliser {resolved.permeabilizer!r} assumed to relieve 60% of "
                "the outer-membrane barrier; this is a coarse assumption"
            )
        if receptor == "outer_membrane_receptor" and availability > 0.5:
            relief = om_barrier
            notes.append(
                "class uses a dedicated outer-membrane receptor, so the LPS barrier "
                "is bypassed rather than crossed"
            )
    terms["outer_membrane"] = om_barrier - relief

    # --- named resistance determinants
    res_shift, res_applied = resistance_shift(
        resistance_factors, bacteriocin_class, store, warnings
    )
    terms["resistance"] = res_shift

    # --- electrostatics of the surrounding solution
    screen = env.monovalent_screening_factor(resolved.ionic_strength_mm, store)
    compete = env.divalent_competition_factor(resolved.divalent_mm, store)
    electrostatic_factor = screen * compete
    # Only the charge-dependent part of binding is screened. A peptide at the
    # reference charge loses potency with salt; a neutral peptide is unaffected.
    charge_sensitivity = max(0.0, math.tanh(max(charge_at_ph, 0.0) / store.g("charge_scale")))
    terms["electrostatic_screening"] = (
        -math.log10(max(electrostatic_factor, 1e-6)) * charge_sensitivity
    )

    # --- medium peptide availability is handled on the concentration side,
    #     not here, so that free-concentration reporting stays interpretable.

    log_mic = sum(terms.values())
    # Keep the MIC inside a physically meaningful window (0.1 nM .. 10 mM).
    if log_mic < -4.0:
        warnings.append("predicted MIC below 0.1 nM was clamped; treat as 'very potent'")
        log_mic = -4.0
    elif log_mic > 4.0:
        warnings.append("predicted MIC above 10 mM was clamped; treat as 'inactive'")
        log_mic = 4.0

    return PotencyResult(
        mic_um=10.0 ** log_mic,
        log10_mic_um=log_mic,
        hill_coefficient=float(
            cls_params.get("hill_coefficient", store.g("hill_coefficient_default"))
        ),
        terms={k: round(v, 5) for k, v in terms.items()},
        receptor=receptor,
        receptor_availability=availability,
        electrostatic_factor=electrostatic_factor,
        warnings=warnings,
        notes=notes + ([str(cls_params["notes"])] if cls_params.get("notes") else []),
    ), res_applied
