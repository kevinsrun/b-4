from __future__ import annotations

import logging
from collections.abc import Mapping

from .models import FunctionalEffectHypothesis, RegionType, VariantScoreComponents

logger = logging.getLogger("b4_variant.annotation")

REGION_WEIGHTS: dict[RegionType, float] = {
    "mature_peptide": 1.0,
    "receptor_interaction_region": 0.9,
    "modification_region": 0.8,
    "leader_peptide": 0.5,
    "propeptide": 0.4,
    "signal_peptide": 0.3,
    "unknown": 0.4,
}


def annotate_region(
    position: int,
    annotations: Mapping[str, tuple[int, int]] | None = None,
) -> RegionType:
    """Determine the structural/functional region of a sequence position.

    Args:
        position: 1-indexed ungapped residue coordinate in reference sequence.
        annotations: Mapping of region name -> (start, end) inclusive 1-indexed coordinates.

    Returns:
        RegionType string.
    """
    if not annotations:
        return "unknown"

    for raw_name, (start, end) in annotations.items():
        name = raw_name.lower().replace(" ", "_").replace("-", "_")
        if start <= position <= end:
            if "mature" in name:
                return "mature_peptide"
            if "leader" in name:
                return "leader_peptide"
            if "signal" in name:
                return "signal_peptide"
            if "propeptide" in name or "pro_peptide" in name:
                return "propeptide"
            if "modification" in name or "ring" in name:
                return "modification_region"
            if "receptor" in name or "target" in name:
                return "receptor_interaction_region"
            return "unknown"

    return "unknown"


def compute_conservation_score(
    ref_aa: str,
    homolog_aas: list[str],
) -> float:
    """Compute the conservation score for the reference amino acid across homologs.

    Score is (count of homologs with reference AA) / (total homologs).
    Returns 1.0 if homolog list is empty.
    """
    if not homolog_aas:
        return 1.0

    ref_upper = ref_aa.upper()
    matching = sum(1 for aa in homolog_aas if aa.upper() == ref_upper)
    return round(matching / len(homolog_aas), 4)


def build_functional_effect_hypothesis(
    variant_type: str,
    protein_change: str,
    region: RegionType,
    frequency: float,
    conservation_score: float,
) -> FunctionalEffectHypothesis:
    """Generate a falsifiable, unproven functional effect hypothesis for a variant.

    Enforces conservatism: status is strictly 'hypothesis', confidence is low (<= 0.4),
    and claims are explicitly framed as hypotheses to be tested.
    """
    effects: list[str] = []

    if region == "mature_peptide":
        effects.append("potential_potency_modulation")
        effects.append("potential_spectrum_alteration")
    elif region == "leader_peptide":
        effects.append("potential_processing_or_cleavage_efficiency_impact")
    elif region == "signal_peptide":
        effects.append("potential_secretion_efficiency_impact")
    elif region == "modification_region":
        effects.append("potential_post_translational_modification_impact")
    else:
        effects.append("unspecified_functional_variation")

    if variant_type == "stop_gain":
        effects.append("premature_truncation_likely_inactivating")
    elif variant_type == "insertion":
        effects.append("backbone_length_alteration")
    elif variant_type == "deletion":
        effects.append("deletion_induced_conformation_shift")

    if conservation_score > 0.8:
        effects.append("high_conservation_site_perturbation")

    hyp_text = (
        f"Naturally occurring {variant_type} variant {protein_change} in the {region} "
        f"(observed frequency {frequency:.1%}, reference conservation {conservation_score:.1%}) "
        "is hypothesized to modulate bacteriocin activity or stability; "
        "requires experimental verification."
    )

    return FunctionalEffectHypothesis(
        status="hypothesis",
        possible_effects=effects,
        confidence=0.35 if region == "mature_peptide" else 0.25,
        hypothesis=hyp_text,
    )


def score_variant(
    frequency: float,
    conservation_score: float,
    region: RegionType,
    homolog_count: int,
    source_count: int,
) -> tuple[float, VariantScoreComponents]:
    """Calculate deterministic variant priority score and its components.

    Higher scores prioritize variants that:
    1. Are naturally observed at viable frequencies (natural_frequency).
    2. Fall in functionally relevant regions like mature peptide (region_importance).
    3. Introduce variation at moderately conserved positions (conservation_disruption).
    4. Are supported by diverse distinct sources (diversity_support).

    All outputs are bounded in [0.0, 1.0] and strictly deterministic.
    """
    nat_freq = min(max(frequency, 0.0), 1.0)
    reg_imp = REGION_WEIGHTS.get(region, 0.4)
    # Moderate disruption: positions with some variability are promising for natural diversity
    cons_disrupt = 1.0 - min(max(conservation_score, 0.0), 1.0)
    div_supp = min(source_count / max(homolog_count, 1), 1.0) if homolog_count > 0 else 0.0

    components = VariantScoreComponents(
        natural_frequency=round(nat_freq, 4),
        region_importance=round(reg_imp, 4),
        conservation_disruption=round(cons_disrupt, 4),
        diversity_support=round(div_supp, 4),
    )

    # Weighted composite:
    # 0.35 region + 0.30 frequency + 0.20 disruption + 0.15 diversity
    raw_score = (
        0.35 * reg_imp
        + 0.30 * nat_freq
        + 0.20 * cons_disrupt
        + 0.15 * div_supp
    )
    priority_score = round(min(max(raw_score, 0.0), 1.0), 4)

    return priority_score, components
