"""Scoring logic and explicit component breakdown for bacteriocin candidates."""

from __future__ import annotations

from .models import DesignScoreComponents


def compute_candidate_score(
    predicted_inhibition: float,
    predicted_log10_reduction: float,
    confidence: float,
    target_organism: str,
    target_gram: str | None,
    candidate_class: str | None,
    known_targets: list[str] | None,
    tier: str,  # "known", "natural_variant", "computational_design"
    has_evidence: bool = True,
    evidence_count: int = 0,
    has_homolog_support: bool = True,
    target_cell_density: float = 1e6,
    has_motif_penalty: bool = False,
    is_conservative: bool = True,
) -> tuple[float, DesignScoreComponents]:
    """Compute explicit scoring components for a candidate under specified conditions."""

    # 1. Predicted activity (max 0.35)
    inhibition_score = 0.25 * max(0.0, min(predicted_inhibition, 1.0))
    log10_score = 0.10 * max(0.0, min(predicted_log10_reduction / 5.0, 1.0))
    activity_comp = inhibition_score + log10_score

    # 2. Target match (max 0.20)
    target_match_comp = 0.0
    norm_target = target_organism.lower().strip()
    is_direct_target = False
    if known_targets:
        is_direct_target = any(
            norm_target in kt.lower() or kt.lower() in norm_target for kt in known_targets
        )

    if is_direct_target:
        target_match_comp = 0.20
    elif (
        target_gram == "positive"
        and candidate_class
        in ("class_i", "class_iia", "class_iib", "class_iic", "class_iid", "class_ii")
    ) or (
        target_gram == "negative" and candidate_class in ("lasso_peptide", "class_v", "microcin")
    ):
        target_match_comp = 0.14
    elif target_gram and candidate_class:
        # Gram mismatch
        target_match_comp = 0.02
    else:
        target_match_comp = 0.10

    # 3. Environmental robustness (max 0.15)
    env_comp = 0.0
    if target_cell_density >= 1e8:
        # High cell density challenge
        if predicted_log10_reduction >= 2.5:
            env_comp = 0.15
        elif predicted_log10_reduction >= 1.5:
            env_comp = 0.10
        else:
            env_comp = 0.05
    else:
        if predicted_inhibition >= 0.95:
            env_comp = 0.15
        elif predicted_inhibition >= 0.80:
            env_comp = 0.10
        else:
            env_comp = 0.05

    # 4. Evidence quality (max 0.15)
    evidence_comp = 0.0
    if tier == "known":
        if evidence_count >= 5 or has_evidence:
            evidence_comp = 0.15
        elif evidence_count > 0:
            evidence_comp = 0.10
        else:
            evidence_comp = 0.06
    elif tier == "natural_variant":
        evidence_comp = 0.08
    else:  # computational_design
        evidence_comp = 0.02

    # 5. Natural support (max 0.10)
    natural_comp = 0.0
    if tier == "known":
        natural_comp = 0.10
    elif tier == "natural_variant":
        natural_comp = 0.08
    else:
        if has_homolog_support:
            natural_comp = 0.05
        elif is_conservative:
            natural_comp = 0.03
        else:
            natural_comp = 0.01

    # 6. Novelty value (max 0.08)
    novelty_comp = 0.0
    if tier == "computational_design":
        novelty_comp = 0.06
    elif tier == "natural_variant":
        novelty_comp = 0.03
    else:
        novelty_comp = 0.00

    # 7. Uncertainty penalty (negative value)
    uncertainty_comp = -0.15 * max(0.0, 1.0 - confidence)

    # 8. Unsupported design penalty (negative value)
    unsupported_comp = 0.0
    if has_motif_penalty:
        unsupported_comp -= 0.15
    if tier == "computational_design" and not is_conservative:
        unsupported_comp -= 0.08

    components = DesignScoreComponents(
        predicted_activity=activity_comp,
        target_match=target_match_comp,
        environmental_robustness=env_comp,
        evidence_quality=evidence_comp,
        natural_support=natural_comp,
        novelty_value=novelty_comp,
        uncertainty_penalty=uncertainty_comp,
        unsupported_design_penalty=unsupported_comp,
    )

    total_score = components.total()
    return total_score, components
