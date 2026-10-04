"""Curated prior parameters for the forward model, with provenance and hashing.

IMPORTANT SCIENTIFIC CAVEAT
---------------------------
Every number in this file is a **coarse, order-of-magnitude prior** assembled
from the general bacteriocin literature. None of it is a fitted calibration
against a specific dataset, and none of it should be reported as a measured
value. The structure matters more than the numbers: the parameter store is
hashed into every result (``parameter_set_hash``) and can be overridden
wholesale, so when the loop eventually produces real observations -- from
simulation-informed refits or from a wet-lab adapter -- the knowledge-update
step replaces these priors without touching the model code or the interface.

Each entry carries ``confidence`` and ``sigma_log10_mic``, which propagate
into the reported uncertainty. Low-confidence entries widen the interval
rather than silently pretending to precision.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from ..schemas import BacteriocinClass

PARAMETER_SET_VERSION = "priors-2026-10-03"

# --------------------------------------------------------------------------
# global model coefficients
# --------------------------------------------------------------------------

GLOBAL: dict[str, float] = {
    # --- potency (log10 MIC) structure-activity coefficients ---
    "w_net_charge": 0.55,          # log10 MIC units per charge-scale unit (saturating)
    "charge_scale": 3.0,           # charge difference giving ~tanh(1)
    "w_hydrophobic_moment": 0.45,  # log10 MIC units per moment-scale unit
    "moment_scale": 0.30,
    "w_length_mismatch": 0.004,    # log10 MIC per residue of |len - reference|
    "w_receptor": 1.60,            # max log10 MIC penalty for a missing receptor
    "default_resistance_log10": 0.9,  # assumed shift when magnitude is unknown
    "max_resistance_log10": 3.0,      # cap on summed resistance shift

    # --- Hill / binding ---
    "hill_coefficient_default": 1.8,
    "kd_over_mic": 1.0,            # membrane-site Kd expressed in MIC units
    "binding_sites_per_cell": 1.0e6,

    # --- killing kinetics ---
    "k_max_per_h": 2.2,            # max specific kill rate at full occupancy
    "resistant_subpopulation_fraction": 2.0e-6,
    "resistant_residual_susceptibility": 0.05,

    # --- peptide stability ---
    "k_deg_base_per_h": 0.015,     # clean buffer, 37 C, pH 6.0
    "deg_activation_energy_kj": 60.0,
    "deg_ph_alkaline_slope": 0.45, # log10 rate increase per pH above 6.5
    "deg_ph_acid_slope": 0.10,     # per pH below 4.0

    # --- ionic screening ---
    "monovalent_half_mm": 220.0,   # ionic strength giving 50% loss of binding
    "monovalent_hill": 1.4,
    "divalent_kd_mm": 6.0,         # competitive divalent cation Kd
    "edta_permeabilisation_mm": 1.5,  # EDTA giving ~50% OM-barrier relief

    # --- in-situ production by a producer strain ---
    "production_rate_um_per_h_per_1e9cells": 0.35,

    # --- growth ---
    "carrying_capacity_cfu_per_ml": 2.0e9,

    # --- assay coupling ---
    "zone_diffusion_mm_per_log10": 3.2,
    "zone_base_mm": 6.0,           # well diameter

    # --- uncertainty floors ---
    "sigma_model_form_logit": 0.55,
    "sigma_per_imputed_condition_logit": 0.18,
    "sigma_generic_peptide_logit": 1.40,
    "sigma_unknown_class_logit": 0.45,
    "sigma_unknown_target_logit": 1.10,
    # --- ignorance expressed in MIC decades, not logit units ---
    #
    # Not knowing which peptide you have, or which organism, is an uncertainty
    # about the *MIC*, not about the response. Expressing it here lets it be
    # propagated by re-running the forward model -- the same treatment the
    # organism's own MIC prior gets -- instead of being bolted onto the total
    # afterwards. See ``SimulationAdapter._build_budget``.
    #
    # Both are coarse, like every prior in this file. Bacteriocin MICs span
    # four to five decades across the family, so not knowing the peptide is a
    # large but not total ignorance; the organism term sits on top of the
    # envelope fallback's own width, which already encodes some of it.
    "sigma_generic_peptide_log10_mic": 1.20,
    "sigma_unknown_target_log10_mic": 0.80,
}

# --------------------------------------------------------------------------
# validated condition domain (outside this, extrapolation uncertainty grows)
# --------------------------------------------------------------------------

VALIDATED_DOMAIN: dict[str, tuple[float, float]] = {
    "ph": (4.0, 8.0),
    "temperature_c": (4.0, 45.0),
    "incubation_time_h": (0.0, 48.0),
    "bacteriocin_concentration_um": (1e-4, 200.0),
    "target_cell_density_cfu_per_ml": (1e3, 1e9),
    "ionic_strength_mm": (0.0, 500.0),
}

# --------------------------------------------------------------------------
# structural-class parameters
# --------------------------------------------------------------------------
# receptor_dependence: how strongly potency depends on the target expressing
#   the class's receptor (0 = membrane-only mechanism, 1 = strictly
#   receptor-mediated).
# receptor: the key looked up in a target's receptor_profile.

CLASS_PARAMETERS: dict[str, dict[str, Any]] = {
    BacteriocinClass.CLASS_I_LANTIBIOTIC.value: {
        "receptor": "lipid_ii",
        "receptor_dependence": 0.75,
        "hill_coefficient": 2.2,
        "potency_offset_log10": -0.35,
        "alkaline_lability": 1.3,
        "confidence": 0.6,
        "notes": "lipid II binder with pore formation; acid-stable, alkali-labile",
    },
    BacteriocinClass.CLASS_IIA_PEDIOCIN_LIKE.value: {
        "receptor": "man_pts",
        "receptor_dependence": 0.95,
        "hill_coefficient": 1.6,
        "potency_offset_log10": -0.20,
        "alkaline_lability": 0.8,
        "confidence": 0.6,
        "notes": "mannose-PTS receptor-mediated; narrow spectrum, Listeria-active",
    },
    BacteriocinClass.CLASS_IIB_TWO_PEPTIDE.value: {
        "receptor": "apc_transporter",
        "receptor_dependence": 0.85,
        "hill_coefficient": 1.8,
        "potency_offset_log10": 0.0,
        "alkaline_lability": 0.8,
        "confidence": 0.45,
        "notes": "requires both complementary peptides; single-peptide specs are approximate",
    },
    BacteriocinClass.CLASS_IIC_CIRCULAR.value: {
        "receptor": "membrane_only",
        "receptor_dependence": 0.15,
        "hill_coefficient": 1.5,
        "potency_offset_log10": 0.10,
        "alkaline_lability": 0.4,
        "confidence": 0.4,
        "notes": "head-to-tail circular; broad, largely receptor-independent",
    },
    BacteriocinClass.CLASS_IID_UNMODIFIED.value: {
        "receptor": "membrane_only",
        "receptor_dependence": 0.30,
        "hill_coefficient": 1.6,
        "potency_offset_log10": 0.25,
        "alkaline_lability": 0.7,
        "confidence": 0.35,
        "notes": "heterogeneous unmodified peptides",
    },
    BacteriocinClass.CLASS_III_BACTERIOLYSIN.value: {
        "receptor": "cell_wall",
        "receptor_dependence": 0.55,
        "hill_coefficient": 1.2,
        "potency_offset_log10": 0.45,
        "alkaline_lability": 1.0,
        "confidence": 0.3,
        "notes": "large, often murein-hydrolase; heat-labile",
    },
    BacteriocinClass.COLICIN_LIKE.value: {
        "receptor": "outer_membrane_receptor",
        "receptor_dependence": 0.98,
        "hill_coefficient": 1.3,
        "potency_offset_log10": -0.30,
        "alkaline_lability": 0.8,
        "confidence": 0.35,
        "notes": "Gram-negative targeted via specific OM receptors",
    },
    BacteriocinClass.UNKNOWN.value: {
        "receptor": "membrane_only",
        "receptor_dependence": 0.45,
        "hill_coefficient": 1.8,
        "potency_offset_log10": 0.30,
        "alkaline_lability": 0.9,
        "confidence": 0.1,
        "notes": "class could not be inferred; averaged mechanism with wide uncertainty",
    },
}

# --------------------------------------------------------------------------
# target organism priors
# --------------------------------------------------------------------------
# aerotolerance: "facultative" unless stated. An obligate anaerobe assayed
#   aerobically is an incoherent experiment, and the backend must say so rather
#   than returning a number.
# log10_mic_um_base: log10 of the MIC (uM) of the *reference* peptide
#   (nisin-A-like descriptors) against exponential-phase cells in a reference
#   medium at pH 6.5 / 37 C. Coarse prior, +/- sigma_log10_mic.
# om_barrier_log10: additional log10 MIC penalty from a Gram-negative outer
#   membrane, relievable by a chelator/permeabiliser.
# cardinal temperature/pH values drive the growth and susceptibility models.

TARGETS: dict[str, dict[str, Any]] = {
    "listeria monocytogenes": {
        "envelope": "gram_positive", "log10_mic_um_base": 0.00, "sigma_log10_mic": 0.55,
        "om_barrier_log10": 0.0,
        "receptor_profile": {"lipid_ii": 1.0, "man_pts": 1.0, "apc_transporter": 0.7,
                             "cell_wall": 1.0, "membrane_only": 1.0,
                             "outer_membrane_receptor": 0.0},
        "t_min_c": -0.4, "t_opt_c": 37.0, "t_max_c": 45.0,
        "ph_min": 4.4, "ph_opt": 7.1, "ph_max": 9.4,
        "mu_max_per_h": 0.75, "od600_to_cfu_per_ml": 1.0e9,
        "confidence": 0.65,
        "notes": "canonical bacteriocin indicator organism; Man-PTS positive",
    },
    "listeria innocua": {
        "envelope": "gram_positive", "log10_mic_um_base": -0.15, "sigma_log10_mic": 0.60,
        "om_barrier_log10": 0.0,
        "receptor_profile": {"lipid_ii": 1.0, "man_pts": 1.0, "apc_transporter": 0.7,
                             "cell_wall": 1.0, "membrane_only": 1.0,
                             "outer_membrane_receptor": 0.0},
        "t_min_c": -0.4, "t_opt_c": 37.0, "t_max_c": 45.0,
        "ph_min": 4.4, "ph_opt": 7.1, "ph_max": 9.4,
        "mu_max_per_h": 0.80, "od600_to_cfu_per_ml": 1.0e9,
        "confidence": 0.55, "notes": "non-pathogenic Listeria surrogate",
    },
    "staphylococcus aureus": {
        "envelope": "gram_positive", "log10_mic_um_base": 1.05, "sigma_log10_mic": 0.65,
        "om_barrier_log10": 0.0,
        "receptor_profile": {"lipid_ii": 1.0, "man_pts": 0.05, "apc_transporter": 0.2,
                             "cell_wall": 0.8, "membrane_only": 0.85,
                             "outer_membrane_receptor": 0.0},
        "t_min_c": 7.0, "t_opt_c": 37.0, "t_max_c": 48.0,
        "ph_min": 4.0, "ph_opt": 7.0, "ph_max": 10.0,
        "mu_max_per_h": 1.10, "od600_to_cfu_per_ml": 8.0e8,
        "confidence": 0.60,
        "notes": "Man-PTS poor: class IIa peptides are typically weak here; thick "
                 "cell wall and D-alanylated teichoic acids reduce cationic binding",
    },
    "enterococcus faecalis": {
        "envelope": "gram_positive", "log10_mic_um_base": 0.60, "sigma_log10_mic": 0.70,
        "om_barrier_log10": 0.0,
        "receptor_profile": {"lipid_ii": 1.0, "man_pts": 0.8, "apc_transporter": 0.6,
                             "cell_wall": 0.9, "membrane_only": 0.9,
                             "outer_membrane_receptor": 0.0},
        "t_min_c": 5.0, "t_opt_c": 37.0, "t_max_c": 47.0,
        "ph_min": 4.4, "ph_opt": 7.0, "ph_max": 9.6,
        "mu_max_per_h": 0.90, "od600_to_cfu_per_ml": 9.0e8,
        "confidence": 0.50, "notes": "highly strain-variable susceptibility",
    },
    "lactiplantibacillus plantarum": {
        "envelope": "gram_positive", "log10_mic_um_base": 0.45, "sigma_log10_mic": 0.70,
        "om_barrier_log10": 0.0,
        "receptor_profile": {"lipid_ii": 1.0, "man_pts": 0.7, "apc_transporter": 0.8,
                             "cell_wall": 0.9, "membrane_only": 0.9,
                             "outer_membrane_receptor": 0.0},
        "t_min_c": 8.0, "t_opt_c": 32.0, "t_max_c": 42.0,
        "ph_min": 3.4, "ph_opt": 6.0, "ph_max": 8.0,
        "mu_max_per_h": 0.65, "od600_to_cfu_per_ml": 7.0e8,
        "confidence": 0.45, "notes": "acid-tolerant LAB; frequent competitor organism",
    },
    "lactococcus lactis": {
        "envelope": "gram_positive", "log10_mic_um_base": 0.30, "sigma_log10_mic": 0.75,
        "om_barrier_log10": 0.0,
        "receptor_profile": {"lipid_ii": 1.0, "man_pts": 0.8, "apc_transporter": 0.9,
                             "cell_wall": 0.9, "membrane_only": 0.9,
                             "outer_membrane_receptor": 0.0},
        "t_min_c": 4.0, "t_opt_c": 30.0, "t_max_c": 40.0,
        "ph_min": 4.0, "ph_opt": 6.5, "ph_max": 8.5,
        "mu_max_per_h": 0.85, "od600_to_cfu_per_ml": 7.0e8,
        "confidence": 0.45,
        "notes": "common nisin producer: immunity/NSR-type determinants are frequent "
                 "and must be supplied as resistance_factors when known",
    },
    "bacillus subtilis": {
        "envelope": "gram_positive", "log10_mic_um_base": 0.50, "sigma_log10_mic": 0.70,
        "om_barrier_log10": 0.0,
        "receptor_profile": {"lipid_ii": 1.0, "man_pts": 0.3, "apc_transporter": 0.4,
                             "cell_wall": 1.0, "membrane_only": 0.95,
                             "outer_membrane_receptor": 0.0},
        "t_min_c": 8.0, "t_opt_c": 37.0, "t_max_c": 52.0,
        "ph_min": 4.5, "ph_opt": 7.0, "ph_max": 9.5,
        "mu_max_per_h": 1.20, "od600_to_cfu_per_ml": 6.0e8,
        "confidence": 0.50, "notes": "sporulation can produce apparent tolerance",
    },
    "clostridium perfringens": {
        "envelope": "gram_positive", "log10_mic_um_base": 0.35, "sigma_log10_mic": 0.80,
        "om_barrier_log10": 0.0,
        "receptor_profile": {"lipid_ii": 1.0, "man_pts": 0.5, "apc_transporter": 0.4,
                             "cell_wall": 1.0, "membrane_only": 0.9,
                             "outer_membrane_receptor": 0.0},
        "t_min_c": 12.0, "t_opt_c": 43.0, "t_max_c": 50.0,
        "ph_min": 5.0, "ph_opt": 7.0, "ph_max": 8.5,
        "mu_max_per_h": 1.80, "od600_to_cfu_per_ml": 8.0e8,
        "aerotolerance": "obligate_anaerobe",
        "confidence": 0.40, "notes": "strict anaerobe; aerobic specs are not meaningful",
    },
    "streptococcus agalactiae": {
        "envelope": "gram_positive", "log10_mic_um_base": 0.40, "sigma_log10_mic": 0.80,
        "om_barrier_log10": 0.0,
        "receptor_profile": {"lipid_ii": 1.0, "man_pts": 0.5, "apc_transporter": 0.5,
                             "cell_wall": 0.9, "membrane_only": 0.9,
                             "outer_membrane_receptor": 0.0},
        "t_min_c": 15.0, "t_opt_c": 37.0, "t_max_c": 42.0,
        "ph_min": 5.0, "ph_opt": 7.2, "ph_max": 9.0,
        "mu_max_per_h": 0.95, "od600_to_cfu_per_ml": 8.0e8,
        "confidence": 0.35, "notes": "capsule may shield the membrane",
    },
    "micrococcus luteus": {
        "envelope": "gram_positive", "log10_mic_um_base": -0.70, "sigma_log10_mic": 0.70,
        "om_barrier_log10": 0.0,
        "receptor_profile": {"lipid_ii": 1.0, "man_pts": 0.1, "apc_transporter": 0.3,
                             "cell_wall": 1.0, "membrane_only": 1.0,
                             "outer_membrane_receptor": 0.0},
        "t_min_c": 10.0, "t_opt_c": 30.0, "t_max_c": 40.0,
        "ph_min": 5.0, "ph_opt": 7.0, "ph_max": 9.0,
        "mu_max_per_h": 0.45, "od600_to_cfu_per_ml": 5.0e8,
        "confidence": 0.45, "notes": "hypersensitive screening indicator",
    },
    "escherichia coli": {
        "envelope": "gram_negative", "log10_mic_um_base": 0.70, "sigma_log10_mic": 0.70,
        "om_barrier_log10": 1.70,
        "receptor_profile": {"lipid_ii": 1.0, "man_pts": 0.6, "apc_transporter": 0.2,
                             "cell_wall": 0.4, "membrane_only": 0.8,
                             "outer_membrane_receptor": 1.0},
        "t_min_c": 7.0, "t_opt_c": 37.0, "t_max_c": 46.0,
        "ph_min": 4.4, "ph_opt": 7.0, "ph_max": 9.0,
        "mu_max_per_h": 1.60, "od600_to_cfu_per_ml": 8.0e8,
        "confidence": 0.55,
        "notes": "LPS outer membrane excludes most Gram-positive-targeted "
                 "bacteriocins unless a chelator is present; colicins bypass via "
                 "dedicated OM receptors",
    },
    "salmonella enterica": {
        "envelope": "gram_negative", "log10_mic_um_base": 0.80, "sigma_log10_mic": 0.75,
        "om_barrier_log10": 1.80,
        "receptor_profile": {"lipid_ii": 1.0, "man_pts": 0.5, "apc_transporter": 0.2,
                             "cell_wall": 0.4, "membrane_only": 0.8,
                             "outer_membrane_receptor": 0.8},
        "t_min_c": 7.0, "t_opt_c": 37.0, "t_max_c": 45.0,
        "ph_min": 4.0, "ph_opt": 7.0, "ph_max": 9.0,
        "mu_max_per_h": 1.50, "od600_to_cfu_per_ml": 8.0e8,
        "confidence": 0.50, "notes": "as E. coli, with PhoPQ-modified LPS",
    },
    "pseudomonas aeruginosa": {
        "envelope": "gram_negative", "log10_mic_um_base": 1.10, "sigma_log10_mic": 0.80,
        "om_barrier_log10": 2.10,
        "receptor_profile": {"lipid_ii": 1.0, "man_pts": 0.0, "apc_transporter": 0.1,
                             "cell_wall": 0.3, "membrane_only": 0.7,
                             "outer_membrane_receptor": 0.5},
        "t_min_c": 10.0, "t_opt_c": 37.0, "t_max_c": 44.0,
        "ph_min": 4.5, "ph_opt": 7.0, "ph_max": 9.0,
        "mu_max_per_h": 1.30, "od600_to_cfu_per_ml": 1.0e9,
        "confidence": 0.45,
        "notes": "very low permeability plus efflux; Man-PTS absent",
    },
}

#: fallbacks used when a species is absent from TARGETS
ENVELOPE_FALLBACKS: dict[str, dict[str, Any]] = {
    "gram_positive": {
        "envelope": "gram_positive", "log10_mic_um_base": 0.60, "sigma_log10_mic": 1.00,
        "om_barrier_log10": 0.0,
        "receptor_profile": {"lipid_ii": 1.0, "man_pts": 0.5, "apc_transporter": 0.5,
                             "cell_wall": 0.9, "membrane_only": 0.9,
                             "outer_membrane_receptor": 0.0},
        "t_min_c": 5.0, "t_opt_c": 37.0, "t_max_c": 45.0,
        "ph_min": 4.5, "ph_opt": 7.0, "ph_max": 9.0,
        "mu_max_per_h": 0.90, "od600_to_cfu_per_ml": 8.0e8,
        "confidence": 0.20, "notes": "generic Gram-positive fallback prior",
    },
    "gram_negative": {
        "envelope": "gram_negative", "log10_mic_um_base": 0.85, "sigma_log10_mic": 1.10,
        "om_barrier_log10": 1.80,
        "receptor_profile": {"lipid_ii": 1.0, "man_pts": 0.4, "apc_transporter": 0.2,
                             "cell_wall": 0.4, "membrane_only": 0.8,
                             "outer_membrane_receptor": 0.6},
        "t_min_c": 7.0, "t_opt_c": 37.0, "t_max_c": 45.0,
        "ph_min": 4.5, "ph_opt": 7.0, "ph_max": 9.0,
        "mu_max_per_h": 1.40, "od600_to_cfu_per_ml": 8.0e8,
        "confidence": 0.18, "notes": "generic Gram-negative fallback prior",
    },
    "unknown": {
        "envelope": "unknown", "log10_mic_um_base": 0.70, "sigma_log10_mic": 1.30,
        "om_barrier_log10": 0.9,
        "receptor_profile": {"lipid_ii": 0.9, "man_pts": 0.45, "apc_transporter": 0.35,
                             "cell_wall": 0.7, "membrane_only": 0.85,
                             "outer_membrane_receptor": 0.3},
        "t_min_c": 5.0, "t_opt_c": 37.0, "t_max_c": 45.0,
        "ph_min": 4.5, "ph_opt": 7.0, "ph_max": 9.0,
        "mu_max_per_h": 1.00, "od600_to_cfu_per_ml": 8.0e8,
        "confidence": 0.10, "notes": "no taxonomic match; envelope type unknown",
    },
}

#: genus-level envelope assignment for species not in TARGETS
GENUS_ENVELOPE: dict[str, str] = {
    "listeria": "gram_positive", "staphylococcus": "gram_positive",
    "enterococcus": "gram_positive", "lactobacillus": "gram_positive",
    "lactiplantibacillus": "gram_positive", "lacticaseibacillus": "gram_positive",
    "lactococcus": "gram_positive", "streptococcus": "gram_positive",
    "bacillus": "gram_positive", "clostridium": "gram_positive",
    "clostridioides": "gram_positive", "micrococcus": "gram_positive",
    "pediococcus": "gram_positive", "leuconostoc": "gram_positive",
    "carnobacterium": "gram_positive", "weissella": "gram_positive",
    "cutibacterium": "gram_positive", "propionibacterium": "gram_positive",
    "mycobacterium": "gram_positive", "corynebacterium": "gram_positive",
    "escherichia": "gram_negative", "salmonella": "gram_negative",
    "pseudomonas": "gram_negative", "klebsiella": "gram_negative",
    "acinetobacter": "gram_negative", "campylobacter": "gram_negative",
    "helicobacter": "gram_negative", "vibrio": "gram_negative",
    "shigella": "gram_negative", "enterobacter": "gram_negative",
    "yersinia": "gram_negative", "neisseria": "gram_negative",
    "haemophilus": "gram_negative", "cronobacter": "gram_negative",
    "serratia": "gram_negative", "proteus": "gram_negative",
}

# --------------------------------------------------------------------------
# media
# --------------------------------------------------------------------------
# availability: fraction of peptide that stays free (protein/lipid binding and
#   plastic adsorption). Milk and other fatty matrices sequester strongly.
# protease_activity: multiplier on the peptide degradation rate.
# richness: multiplier on mu_max.

MEDIA: dict[str, dict[str, Any]] = {
    "mrs": {"availability": 0.65, "protease_activity": 1.0, "richness": 1.00,
            "divalent_baseline_mm": 1.0, "monovalent_baseline_mm": 60.0, "confidence": 0.5,
            "notes": "LAB-selective; Tween 80 can sequester hydrophobic peptides"},
    "m17": {"availability": 0.70, "protease_activity": 1.0, "richness": 0.95,
            "divalent_baseline_mm": 1.5, "monovalent_baseline_mm": 90.0, "confidence": 0.45},
    "bhi": {"availability": 0.60, "protease_activity": 1.1, "richness": 1.00,
            "divalent_baseline_mm": 1.2, "monovalent_baseline_mm": 90.0, "confidence": 0.5},
    "tsb": {"availability": 0.62, "protease_activity": 1.1, "richness": 0.95,
            "divalent_baseline_mm": 1.2, "monovalent_baseline_mm": 85.0, "confidence": 0.45},
    "camhb": {"availability": 0.72, "protease_activity": 0.9, "richness": 0.90,
              "divalent_baseline_mm": 2.1, "monovalent_baseline_mm": 80.0, "confidence": 0.55,
              "notes": "cation-adjusted Mueller-Hinton: the standard MIC medium; its "
                       "20-25 mg/L Ca2+ and 10-12.5 mg/L Mg2+ measurably antagonise "
                       "cationic peptides"},
    "mhb": {"availability": 0.72, "protease_activity": 0.9, "richness": 0.90,
            "divalent_baseline_mm": 1.0, "monovalent_baseline_mm": 80.0, "confidence": 0.45},
    "lb": {"availability": 0.68, "protease_activity": 1.0, "richness": 0.95,
           "divalent_baseline_mm": 0.8, "monovalent_baseline_mm": 170.0, "confidence": 0.45},
    "m9": {"availability": 0.90, "protease_activity": 0.8, "richness": 0.45,
           "divalent_baseline_mm": 1.1, "monovalent_baseline_mm": 100.0, "confidence": 0.40,
           "notes": "minimal medium: slow growth, little peptide sequestration"},
    "pbs": {"availability": 0.92, "protease_activity": 0.7, "richness": 0.02,
            "divalent_baseline_mm": 0.0, "monovalent_baseline_mm": 150.0, "confidence": 0.50,
            "notes": "non-growth buffer: time-kill only, no replication"},
    "saline": {"availability": 0.95, "protease_activity": 0.6, "richness": 0.02,
               "divalent_baseline_mm": 0.0, "monovalent_baseline_mm": 150.0, "confidence": 0.50},
    "water": {"availability": 0.98, "protease_activity": 0.5, "richness": 0.0,
              "divalent_baseline_mm": 0.0, "monovalent_baseline_mm": 0.0, "confidence": 0.45},
    "skim_milk": {"availability": 0.18, "protease_activity": 1.3, "richness": 0.80,
                  "divalent_baseline_mm": 8.0, "monovalent_baseline_mm": 40.0,
                  "confidence": 0.40,
                  "notes": "casein and fat bind peptide; high Ca2+ antagonises binding"},
    "whole_milk": {"availability": 0.10, "protease_activity": 1.3, "richness": 0.80,
                   "divalent_baseline_mm": 8.0, "monovalent_baseline_mm": 40.0,
                   "confidence": 0.35},
    "meat_slurry": {"availability": 0.22, "protease_activity": 1.6, "richness": 0.70,
                    "divalent_baseline_mm": 5.0, "monovalent_baseline_mm": 120.0,
                    "confidence": 0.30},
    "simulated_intestinal_fluid": {"availability": 0.20, "protease_activity": 3.0,
                                   "richness": 0.60, "divalent_baseline_mm": 3.0,
                                   "monovalent_baseline_mm": 140.0, "confidence": 0.25,
                                   "notes": "pancreatin degrades most unprotected peptides"},
}

DEFAULT_MEDIUM = "camhb"

#: multiplier on susceptibility by growth phase. Actively dividing cells are
#: most susceptible (membrane potential, active lipid II cycling); stationary
#: and especially biofilm populations are markedly more tolerant.
GROWTH_PHASE_SUSCEPTIBILITY: dict[str, float] = {
    "lag": 0.55,
    "early_exponential": 0.95,
    "exponential": 1.00,
    "late_exponential": 0.80,
    "stationary": 0.35,
    "biofilm": 0.10,
}

#: fraction of mu_max realised in each phase
GROWTH_PHASE_RATE: dict[str, float] = {
    "lag": 0.10,
    "early_exponential": 0.90,
    "exponential": 1.00,
    "late_exponential": 0.50,
    "stationary": 0.05,
    "biofilm": 0.05,
}

#: named resistance determinants with literature-suggested magnitudes
#: (log10 MIC shift). Used when a caller names a factor without a magnitude.
KNOWN_RESISTANCE_FACTORS: dict[str, dict[str, Any]] = {
    "nisin_immunity_nisi": {"magnitude_log10_mic": 1.3, "classes": ["class_I_lantibiotic"]},
    "nsr": {"magnitude_log10_mic": 1.5, "classes": ["class_I_lantibiotic"]},
    "nisfeg": {"magnitude_log10_mic": 1.0, "classes": ["class_I_lantibiotic"]},
    "man_pts_loss": {"magnitude_log10_mic": 2.2, "classes": ["class_IIa_pediocin_like"]},
    "mptc_deletion": {"magnitude_log10_mic": 2.2, "classes": ["class_IIa_pediocin_like"]},
    "dlt_dalanylation": {"magnitude_log10_mic": 0.7, "classes": []},
    "mprf": {"magnitude_log10_mic": 0.6, "classes": []},
    "liafsr_activation": {"magnitude_log10_mic": 0.8, "classes": []},
    "capsule": {"magnitude_log10_mic": 0.5, "classes": []},
    "biofilm": {"magnitude_log10_mic": 0.9, "classes": []},
    "efflux_overexpression": {"magnitude_log10_mic": 0.5, "classes": []},
    "lps_modification": {"magnitude_log10_mic": 0.8, "classes": []},
    "cognate_immunity_protein": {"magnitude_log10_mic": 1.8, "classes": []},
    "permeabilised_outer_membrane": {"magnitude_log10_mic": -1.2, "classes": []},
}


@dataclass
class ParameterStore:
    """Immutable-by-convention bundle of all model parameters, with a hash.

    ``overrides`` is a nested dict merged over the defaults. This is the seam
    the knowledge-update step of the loop uses: a refitted
    ``targets["listeria monocytogenes"]["log10_mic_um_base"]`` changes the
    predictions *and* the ``parameter_set_hash`` in every result, so no result
    is ever ambiguous about which parameter set produced it.
    """

    version: str = PARAMETER_SET_VERSION
    global_: dict[str, float] = field(default_factory=lambda: copy.deepcopy(GLOBAL))
    targets: dict[str, dict[str, Any]] = field(default_factory=lambda: copy.deepcopy(TARGETS))
    media: dict[str, dict[str, Any]] = field(default_factory=lambda: copy.deepcopy(MEDIA))
    classes: dict[str, dict[str, Any]] = field(
        default_factory=lambda: copy.deepcopy(CLASS_PARAMETERS)
    )
    resistance: dict[str, dict[str, Any]] = field(
        default_factory=lambda: copy.deepcopy(KNOWN_RESISTANCE_FACTORS)
    )
    domain: dict[str, tuple[float, float]] = field(
        default_factory=lambda: copy.deepcopy(VALIDATED_DOMAIN)
    )

    @classmethod
    def from_overrides(cls, overrides: dict[str, Any] | None) -> "ParameterStore":
        """Build a store with a deep-merged override layer applied."""
        store = cls()
        if not overrides:
            return store
        mapping = {
            "global": store.global_, "global_": store.global_,
            "targets": store.targets, "media": store.media,
            "classes": store.classes, "resistance": store.resistance,
        }
        for key, patch in overrides.items():
            if key == "version":
                store.version = str(patch)
                continue
            if key == "domain" and isinstance(patch, dict):
                for dk, dv in patch.items():
                    if isinstance(dv, (list, tuple)) and len(dv) == 2:
                        store.domain[dk] = (float(dv[0]), float(dv[1]))
                continue
            target = mapping.get(key)
            if target is None or not isinstance(patch, dict):
                continue
            _deep_merge(target, patch)
        store.version = f"{store.version}+override"
        return store

    def hash(self) -> str:
        """Content hash of the whole parameter set."""
        blob = json.dumps(
            {
                "version": self.version,
                "global": self.global_,
                "targets": self.targets,
                "media": self.media,
                "classes": self.classes,
                "resistance": self.resistance,
                "domain": {k: list(v) for k, v in self.domain.items()},
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]

    def g(self, key: str) -> float:
        """Look up a global coefficient."""
        try:
            return float(self.global_[key])
        except KeyError as exc:  # pragma: no cover - guards override typos
            raise KeyError(f"unknown global model parameter {key!r}") from exc


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
