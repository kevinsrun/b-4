"""Active learning and adaptive validation loop for target bacteriocin design.

Addresses P1:
- Upper Confidence Bound (UCB) / Bayesian Information Gain acquisition function.
- Balances predicted promise with epistemic uncertainty to pick the most informative experiment.
- Formulates structured validation experiments with explicit information gain rationale.
- Supports closed-loop recalibration and candidate reranking upon ingesting new evidence.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from .calibration import (
    ActivityCalibrator,
    ActivityObservation,
)
from .models import (
    DesignedCandidate,
    RecommendationItem,
    TargetDesignResult,
)
from .ptm import analyze_ptm_profile

logger = logging.getLogger(__name__)

DEFAULT_KAPPA = 0.35  # Exploration bonus parameter


def compute_epistemic_uncertainty(
    confidence: float,
    structural_uncertainty: float = 0.0,
    is_extrapolative: bool = False,
    evidence_count: int = 0,
) -> float:
    """Calculate normalized epistemic uncertainty in [0, 1]."""
    # Base confidence uncertainty
    base_unc = max(0.0, 1.0 - confidence)

    # Scarcity of empirical calibration evidence increases epistemic uncertainty
    evidence_bonus = max(0.0, 0.40 - min(0.40, evidence_count * 0.08))

    # Structural uncertainty from unmodeled RiPP/PTM folding
    ptm_unc = structural_uncertainty * 0.35

    # Out-of-distribution conditions penalty
    ood_unc = 0.25 if is_extrapolative else 0.0

    total_unc = 0.40 * base_unc + evidence_bonus + ptm_unc + ood_unc
    return round(min(1.0, max(0.05, total_unc)), 4)


def compute_acquisition_score(
    calibrated_score: float,
    epistemic_uncertainty: float,
    kappa: float = DEFAULT_KAPPA,
) -> float:
    """Upper Confidence Bound (UCB) acquisition score.

    Acquisition = Mean Promise + kappa * Epistemic Uncertainty.
    Candidates with high predicted activity AND high epistemic uncertainty are prioritized
    because measuring them yields the highest information gain.
    """
    acq = calibrated_score + kappa * epistemic_uncertainty
    return round(acq, 4)


def formulate_validation_experiment(
    candidate: dict[str, Any],
    target_info: dict[str, Any],
    acquisition_score: float,
    epistemic_uncertainty: float,
    calibrated_mic_um: float | None = None,
) -> dict[str, Any]:
    """Formulate an actionable in vitro validation experiment."""
    cand_id = candidate.get("candidate_id", "cand_unknown")
    cand_name = candidate.get("name", cand_id)
    cand_seq = candidate.get("sequence", "")
    cand_tier = candidate.get("tier", "computational_design")
    target_org = target_info.get("organism", "target bacterium")

    anchor_mic = calibrated_mic_um or candidate.get("simulation_metrics", {}).get(
        "predicted_mic_um", 1.0
    )
    # Geometric 2-fold dilution series across 8 concentrations
    dilution_factors = [0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0]
    conc_series = [round(anchor_mic * f, 3) for f in dilution_factors]

    mutations = candidate.get("mutations", [])
    mut_str = f" with mutations ({', '.join(mutations)})" if mutations else ""

    rationale = (
        f"Candidate '{cand_name}'{mut_str} was selected by the active-learning "
        f"acquisition function (score {acquisition_score:.3f} = score + {DEFAULT_KAPPA} * unc "
        f"{epistemic_uncertainty:.3f}). Broth microdilution against {target_org} will "
        f"resolve epistemic uncertainty around binding affinity and insertion."
    )

    return {
        "experiment_id": f"val_exp_{cand_id}",
        "candidate_id": cand_id,
        "candidate_name": cand_name,
        "tier": cand_tier,
        "sequence": cand_seq,
        "target": target_info,
        "recommended_assay": "broth_microdilution_mic",
        "dilution_series_um": conc_series,
        "anchor_mic_um": anchor_mic,
        "information_gain_rationale": rationale,
        "acquisition_score": acquisition_score,
        "epistemic_uncertainty": epistemic_uncertainty,
        "hypothesis_to_test": (
            f"Candidate '{cand_name}' inhibits {target_org} with "
            f"MIC <= {anchor_mic * 2.0:.2f} uM under broth microdilution."
        ),
    }


def recalibrate_and_rerank(
    result: TargetDesignResult,
    new_observation: ActivityObservation,
    calibrator: ActivityCalibrator | None = None,
) -> TargetDesignResult:
    """Ingest a validation result, update calibrator, and rerank candidates.

    Implements closed-loop active learning:
    Observation -> Update Calibration -> Recalibrate Predictions -> Rerank.
    """
    cal = calibrator or ActivityCalibrator()
    # Ingest the new observation
    cal.ingest_observation(new_observation)

    target_org = result.target.get("organism", "")

    # Deep copy the result to modify
    updated = copy.deepcopy(result)

    # 1. Recalibrate known candidates
    for k in updated.known_candidates:
        sim = k.get("simulation_metrics", {})
        cal_pred = cal.calibrate(
            raw_score=k["score"],
            raw_inhibition=sim.get("predicted_inhibition", 0.5),
            raw_mic_um=sim.get("predicted_mic_um"),
            target_organism=target_org,
            bacteriocin_class=k.get("bacteriocin_class"),
        )
        ptm = analyze_ptm_profile(k.get("sequence", ""), k.get("bacteriocin_class"), k.get("name"))
        unc = compute_epistemic_uncertainty(
            confidence=cal_pred.confidence,
            structural_uncertainty=ptm.structural_uncertainty_score,
            is_extrapolative=cal_pred.is_extrapolative,
            evidence_count=cal_pred.calibration_evidence_count,
        )
        acq = compute_acquisition_score(cal_pred.calibrated_score, unc)

        k["calibrated_prediction"] = cal_pred.model_dump()
        k["epistemic_uncertainty"] = unc
        k["acquisition_score"] = acq
        k["score"] = cal_pred.calibrated_score

    # 2. Recalibrate natural variants
    for n in updated.natural_variant_candidates:
        sim = n.get("simulation_metrics", {})
        cal_pred = cal.calibrate(
            raw_score=n["score"],
            raw_inhibition=sim.get("predicted_inhibition", 0.5),
            raw_mic_um=sim.get("predicted_mic_um"),
            target_organism=target_org,
            bacteriocin_class=n.get("bacteriocin_class"),
        )
        ptm = analyze_ptm_profile(n.get("sequence", ""), n.get("bacteriocin_class"), n.get("name"))
        unc = compute_epistemic_uncertainty(
            confidence=cal_pred.confidence,
            structural_uncertainty=ptm.structural_uncertainty_score,
            is_extrapolative=cal_pred.is_extrapolative,
            evidence_count=cal_pred.calibration_evidence_count,
        )
        acq = compute_acquisition_score(cal_pred.calibrated_score, unc)

        n["calibrated_prediction"] = cal_pred.model_dump()
        n["epistemic_uncertainty"] = unc
        n["acquisition_score"] = acq
        n["score"] = cal_pred.calibrated_score

    # 3. Recalibrate computational designs
    new_designed: list[DesignedCandidate] = []
    for d in updated.designed_candidates:
        sim = d.simulation_metrics
        cal_pred = cal.calibrate(
            raw_score=d.score,
            raw_inhibition=sim.get("predicted_inhibition", 0.5),
            raw_mic_um=sim.get("predicted_mic_um"),
            target_organism=target_org,
        )
        ptm = analyze_ptm_profile(d.sequence, d.design_class, d.candidate_id)
        unc = compute_epistemic_uncertainty(
            confidence=cal_pred.confidence,
            structural_uncertainty=ptm.structural_uncertainty_score,
            is_extrapolative=cal_pred.is_extrapolative,
            evidence_count=cal_pred.calibration_evidence_count,
        )
        acq = compute_acquisition_score(cal_pred.calibrated_score, unc)

        d_dict = d.model_dump()
        d_dict["score"] = cal_pred.calibrated_score
        d_dict["calibrated_prediction"] = cal_pred.model_dump()
        d_dict["uncertainty"]["epistemic_uncertainty"] = unc
        d_dict["uncertainty"]["acquisition_score"] = acq
        new_designed.append(DesignedCandidate(**d_dict))
    updated.designed_candidates = new_designed

    # 4. Sort all by acquisition score for exploration/validation, and update best candidate
    all_cands: list[dict[str, Any]] = []
    for k in updated.known_candidates:
        all_cands.append(k)
    for n in updated.natural_variant_candidates:
        all_cands.append(n)
    for d in updated.designed_candidates:
        all_cands.append(
            {
                "candidate_id": d.candidate_id,
                "name": f"Design {d.candidate_id}",
                "sequence": d.sequence,
                "tier": "computational_design",
                "score": d.score,
                "acquisition_score": d.uncertainty.get("acquisition_score", d.score),
                "epistemic_uncertainty": d.uncertainty.get("epistemic_uncertainty", 0.3),
                "calibrated_prediction": d.model_dump().get("calibrated_prediction"),
                "provenance": d.provenance,
                "simulation_metrics": d.simulation_metrics,
                "mutations": [f"{m.reference}{m.position}{m.alternate}" for m in d.mutations],
            }
        )

    # Sort candidates by acquisition score (for next validation target) and score (for current best)
    all_cands.sort(key=lambda c: c.get("acquisition_score", 0.0), reverse=True)
    validation_target = all_cands[0] if all_cands else None

    # Best confirmed/predicted performer by calibrated score
    by_score = sorted(all_cands, key=lambda c: c.get("score", 0.0), reverse=True)
    updated.best_current_candidate = by_score[0] if by_score else None

    # Formulate updated recommended next experiment
    if validation_target:
        cal_mic = None
        cal_pred_dict = validation_target.get("calibrated_prediction")
        if cal_pred_dict:
            cal_mic = cal_pred_dict.get("calibrated_mic_um")

        updated.recommended_next_experiment = formulate_validation_experiment(
            candidate=validation_target,
            target_info=updated.target,
            acquisition_score=validation_target.get("acquisition_score", 0.8),
            epistemic_uncertainty=validation_target.get("epistemic_uncertainty", 0.3),
            calibrated_mic_um=cal_mic,
        )

    # Rebuild recommendations
    new_recs: list[RecommendationItem] = []
    for c in by_score[:3]:
        new_recs.append(
            RecommendationItem(
                tier=c.get("tier", "computational_design"),
                name=c.get("name", c.get("candidate_id")),
                score=c.get("score", 0.0),
                predicted_inhibition=c.get("simulation_metrics", {}).get(
                    "predicted_inhibition", 0.5
                ),
                confidence="high"
                if c.get("simulation_metrics", {}).get("confidence", 0.5) >= 0.7
                else "moderate",
                evidence_count=c.get("evidence_count"),
                candidate_id=c.get("candidate_id"),
                mutations=c.get("mutations", []),
            )
        )
    updated.recommendations = new_recs

    # Add calibration summary
    updated.evidence_summary["calibration_observations_count"] = len(cal.observations)
    updated.evidence_summary["last_ingested_observation"] = {
        "bacteriocin": new_observation.bacteriocin_name,
        "target": new_observation.target_organism,
        "measured_mic_um": new_observation.measured_mic_um,
        "source": new_observation.source_citation,
    }

    return updated
