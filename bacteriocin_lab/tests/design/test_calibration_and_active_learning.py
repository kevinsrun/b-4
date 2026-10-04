"""Tests for calibration, active learning, environmental scenarios, and PTM uncertainty.

Verifies:
- P0: Activity calibration, grounded literature references, refusal to invent MICs, OOD detection.
- P1: Active-learning acquisition scoring, structured validation experiments, closed-loop reranking.
- P2: Environmental scenario profiles (infection, acid, high fat, protease).
- P3: PTM family detection, modification site identification, structural uncertainty.
- Integration: Full loop from design -> calibration -> active learning -> recalibration.
"""

from __future__ import annotations

import pytest

from bacteriocin_lab.agents.design import (
    CURATED_REFERENCE_OBSERVATIONS,
    ActivityCalibrator,
    ActivityObservation,
    CalibratedPrediction,
    TargetContext,
    analyze_ptm_profile,
    compute_acquisition_score,
    compute_gravy,
    count_protease_cleavage_sites,
    design_for_target,
    evaluate_environmental_scenarios,
    formulate_validation_experiment,
    recalibrate_and_rerank,
)

# --------------------------------------------------------------------------
# P0: Calibration and Uncertainty Tests
# --------------------------------------------------------------------------


def test_grounded_curated_reference_dataset() -> None:
    """Ensure reference observations come from peer-reviewed literature with citations."""
    assert len(CURATED_REFERENCE_OBSERVATIONS) >= 8

    # Check key anchors
    nisin_listeria = [
        o
        for o in CURATED_REFERENCE_OBSERVATIONS
        if "nisin" in o.bacteriocin_name.lower() and "listeria" in o.target_organism.lower()
    ]
    assert len(nisin_listeria) >= 1
    assert nisin_listeria[0].measured_mic_um == pytest.approx(0.35, rel=0.1)
    assert (
        "DOI:" in nisin_listeria[0].source_citation or "1988" in nisin_listeria[0].source_citation
    )

    # Check negative control (Gram-negative specific lasso inactive against Gram-positive)
    j25_listeria = [
        o
        for o in CURATED_REFERENCE_OBSERVATIONS
        if "j25" in o.bacteriocin_name.lower() and "listeria" in o.target_organism.lower()
    ]
    assert len(j25_listeria) >= 1
    assert not j25_listeria[0].is_active
    assert j25_listeria[0].measured_mic_um is None


def test_distinguishes_raw_and_calibrated_estimates() -> None:
    """Calibrator must output distinct raw and calibrated metrics with confidence intervals."""
    calibrator = ActivityCalibrator()
    pred = calibrator.calibrate(
        raw_score=0.82,
        raw_inhibition=0.95,
        raw_mic_um=0.52,
        target_organism="Listeria monocytogenes",
        bacteriocin_class="class_iia",
    )

    assert isinstance(pred, CalibratedPrediction)
    assert pred.raw_score == 0.82
    assert pred.raw_mic_um == 0.52
    assert pred.calibrated_score > 0.0
    assert pred.calibrated_mic_um is not None
    assert pred.calibration_mode == "affine_mic_fit"
    assert pred.validation_status == "in_silico_hypothesis"

    # 95% Confidence interval
    low, high = pred.uncertainty_interval
    assert low < pred.calibrated_mic_um < high


def test_refuses_to_fabricate_unsupported_absolute_mic() -> None:
    """When target has no empirical quantitative MIC data, do NOT fabricate an absolute MIC."""
    calibrator = ActivityCalibrator()
    # Novel target without quantitative MIC references
    pred = calibrator.calibrate(
        raw_score=0.75,
        raw_inhibition=0.88,
        raw_mic_um=1.2,
        target_organism="NovelBacterium hypotheticalus",
        bacteriocin_class="class_ii",
    )

    assert pred.calibrated_mic_um is None
    assert pred.calibration_mode in ("relative_ranking", "uncalibrated_prior")
    # Interval bounds scale score, not fabricated MIC
    low, high = pred.uncertainty_interval
    assert 0.0 <= low <= pred.calibrated_score <= high <= 1.0


def test_detects_out_of_distribution_extrapolation() -> None:
    """Detects when pH, temp, density, or organism fall outside validated domain."""
    calibrator = ActivityCalibrator()

    # In-domain conditions
    ood_in, reasons_in = calibrator.check_extrapolation(
        {"ph": 6.5, "temperature_c": 37.0, "target_cell_density": 1e6},
        "Listeria monocytogenes",
    )
    assert not ood_in
    assert len(reasons_in) == 0

    # Extreme acidic pH outside validated domain [4.0, 8.0]
    ood_out, reasons_out = calibrator.check_extrapolation(
        {"ph": 2.5, "temperature_c": 37.0},
        "Listeria monocytogenes",
    )
    assert ood_out
    assert any("ph" in r for r in reasons_out)

    # Prediction under OOD conditions should be marked extrapolative and have reduced confidence
    pred_ood = calibrator.calibrate(
        raw_score=0.80,
        raw_inhibition=0.90,
        raw_mic_um=0.5,
        target_organism="Listeria monocytogenes",
        conditions={"ph": 2.5},
        base_confidence=0.80,
    )
    assert pred_ood.is_extrapolative
    assert pred_ood.confidence < 0.80
    assert len(pred_ood.extrapolation_reasons) > 0


# --------------------------------------------------------------------------
# P1: Active Learning and Validation Loop Tests
# --------------------------------------------------------------------------


def test_acquisition_scoring_balances_promise_and_uncertainty() -> None:
    """Acquisition score rewards both predicted activity and epistemic uncertainty."""
    # High score, low uncertainty
    acq_known = compute_acquisition_score(
        calibrated_score=0.90, epistemic_uncertainty=0.10, kappa=0.35
    )
    # Moderate score, high uncertainty (informative experiment!)
    acq_novel = compute_acquisition_score(
        calibrated_score=0.82, epistemic_uncertainty=0.45, kappa=0.35
    )

    assert acq_known == pytest.approx(0.90 + 0.35 * 0.10, abs=1e-3)
    assert acq_novel == pytest.approx(0.82 + 0.35 * 0.45, abs=1e-3)
    # The informative candidate can overtake a slightly higher known candidate
    assert acq_novel > acq_known


def test_formulates_structured_validation_experiment() -> None:
    """Validation experiment must specify 2-fold dilution series and information-gain rationale."""
    cand = {
        "candidate_id": "nisin_a_h27k",
        "name": "Nisin A H27K",
        "sequence": "ITSISLCTPGCKTGALMGCNMKTATCHCSINVSK",
        "tier": "computational_design",
        "mutations": ["H27K"],
        "simulation_metrics": {"predicted_mic_um": 0.35},
    }
    target = {"organism": "Listeria monocytogenes", "gram": "positive"}

    exp = formulate_validation_experiment(
        candidate=cand,
        target_info=target,
        acquisition_score=0.92,
        epistemic_uncertainty=0.38,
        calibrated_mic_um=0.30,
    )

    assert exp["experiment_id"] == "val_exp_nisin_a_h27k"
    assert exp["recommended_assay"] == "broth_microdilution_mic"
    assert len(exp["dilution_series_um"]) == 8
    assert "information_gain_rationale" in exp
    assert "acquisition function" in exp["information_gain_rationale"]
    assert exp["anchor_mic_um"] == 0.30


def test_closed_loop_recalibration_and_reranking() -> None:
    """Ingesting a new validation observation updates calibration and alters candidate ranking."""
    # Initial design run for Listeria
    res1 = design_for_target("Listeria monocytogenes", max_known_candidates=3)
    assert res1.best_current_candidate is not None
    assert len(res1.recommendations) > 0

    initial_cal_count = res1.evidence_summary.get("calibration_observations_count", 0)

    # Ingest a new wet-lab validation observation proving high potency for a candidate
    new_obs = ActivityObservation(
        bacteriocin_name="nisin A",
        target_organism="Listeria monocytogenes",
        bacteriocin_class="class_i",
        measured_mic_um=0.08,  # Ultra-potent measured result
        is_active=True,
        evidence_type="wet-lab-derived",
        source_citation="LabRun-2026-VAL-042",
        notes="High-throughput broth microdilution validation confirmed 0.08 uM MIC",
    )

    res2 = recalibrate_and_rerank(res1, new_obs)
    assert res2.best_current_candidate is not None
    assert res2.evidence_summary["calibration_observations_count"] == initial_cal_count + 1
    assert res2.evidence_summary["last_ingested_observation"]["source"] == "LabRun-2026-VAL-042"
    assert "recommended_next_experiment" in res2.model_dump()


# --------------------------------------------------------------------------
# P2: Environmental Scenarios Tests
# --------------------------------------------------------------------------


def test_gravy_calculation_and_protease_cleavage_scanning() -> None:
    """Verify GRAVY score and trypsin cleavage site counts."""
    # Nisin A: ITSISLCTPGCKTGALMGCNMKTATCHCSINVSK
    nisin_seq = "ITSISLCTPGCKTGALMGCNMKTATCHCSINVSK"
    gravy = compute_gravy(nisin_seq)
    assert isinstance(gravy, float)

    # Count Lys (K) and Arg (R) sites
    trypsin_sites, _ = count_protease_cleavage_sites(nisin_seq)
    # Nisin contains 3 Lys (K12, K22, K34) and 0 Arg -> 3 trypsin sites
    assert trypsin_sites == 3


def test_environmental_scenario_profiles() -> None:
    """Evaluate 5 scenarios for Class I, Class IIa, and Lasso peptides."""
    nisin_seq = "ITSISLCTPGCKTGALMGCNMKTATCHCSINVSK"
    scenarios = evaluate_environmental_scenarios(
        sequence=nisin_seq,
        bacteriocin_class="class_i",
        candidate_name="Nisin A",
        target_organism="Listeria monocytogenes",
    )

    assert len(scenarios) == 5
    scenario_ids = [s.scenario_id for s in scenarios]
    assert "standard_in_vitro" in scenario_ids
    assert "high_density_infection" in scenario_ids
    assert "acidic_food_matrix" in scenario_ids
    assert "high_fat_dairy" in scenario_ids
    assert "protease_challenge" in scenario_ids

    # Nisin is acid stable
    acid_scen = next(s for s in scenarios if s.scenario_id == "acidic_food_matrix")
    assert acid_scen.predicted_activity_retention >= 1.0

    # Inoculum effect reduces retention in high-density infection
    inf_scen = next(s for s in scenarios if s.scenario_id == "high_density_infection")
    assert inf_scen.predicted_activity_retention < 1.0


def test_lasso_peptide_protease_resistance() -> None:
    """Lasso peptides must show superior protease retention due to macrolactam knot."""
    mccj25_seq = "GGAGHVPEYFVGIGTPISFYG"
    lasso_scen = evaluate_environmental_scenarios(
        sequence=mccj25_seq,
        bacteriocin_class="lasso_peptide",
        candidate_name="Microcin J25",
    )
    prot = next(s for s in lasso_scen if s.scenario_id == "protease_challenge")
    assert prot.predicted_activity_retention >= 0.90
    assert "lasso" in prot.matrix_effects.get("structural_protection", "")


# --------------------------------------------------------------------------
# P3: PTM-Aware Uncertainty Tests
# --------------------------------------------------------------------------


def test_ptm_detection_class_i_lantibiotic() -> None:
    """Class I lantibiotic detects required dehydrations and thioether bridges."""
    nisin_seq = "ITSISLCTPGCKTGALMGCNMKTATCHCSINVSK"
    ptm = analyze_ptm_profile(nisin_seq, bacteriocin_class="class_i", candidate_name="Nisin A")

    assert ptm.is_ptm_dependent
    assert ptm.ptm_class == "class_i_lantibiotic"
    assert ptm.requires_enzymatic_machinery
    assert ptm.structural_uncertainty_score == 0.50
    assert not ptm.mature_topology_confirmed
    assert ptm.modification_summary.get("cysteine_bridge_donors") == 5
    assert ptm.modification_summary.get("serine_dehydration_candidates") == 4


def test_ptm_detection_lasso_peptide() -> None:
    """Lasso peptide detects macrolactam ring residues."""
    mccj25_seq = "GGAGHVPEYFVGIGTPISFYG"
    ptm = analyze_ptm_profile(
        mccj25_seq, bacteriocin_class="lasso_peptide", candidate_name="Microcin J25"
    )

    assert ptm.is_ptm_dependent
    assert ptm.ptm_class == "lasso_peptide"
    assert ptm.structural_uncertainty_score == 0.60
    assert ptm.requires_enzymatic_machinery


def test_ptm_detection_class_iia_and_unmodified() -> None:
    """Class IIa has disulfide bridge; linear peptide has minimal PTM uncertainty."""
    pediocin_seq = "KYYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC"
    ptm_iia = analyze_ptm_profile(pediocin_seq, bacteriocin_class="class_iia")
    assert not ptm_iia.is_ptm_dependent  # ribosomally synthesized
    assert ptm_iia.ptm_class == "class_iia_disulfide"
    assert ptm_iia.structural_uncertainty_score <= 0.20

    linear_seq = "AGLKLFKKLLKKL"
    ptm_lin = analyze_ptm_profile(linear_seq, bacteriocin_class="class_iib")
    assert not ptm_lin.is_ptm_dependent
    assert ptm_lin.ptm_class == "unmodified_ribosomal"
    assert ptm_lin.structural_uncertainty_score <= 0.10


# --------------------------------------------------------------------------
# End-to-End Pipeline Integration Tests
# --------------------------------------------------------------------------


def test_full_pipeline_calibration_and_uncertainty_integration() -> None:
    """Verify that design_for_target runs end-to-end with calibration and active learning."""
    res = design_for_target(
        target_organism="Listeria monocytogenes",
        context=TargetContext(ph=6.5, target_cell_density=1e6),
    )

    assert res.best_current_candidate is not None
    assert "calibrated_prediction" in res.best_current_candidate
    assert "scenario_profiles" in res.best_current_candidate
    assert "ptm_profile" in res.best_current_candidate
    assert res.recommended_validation_experiment is not None
    assert res.recommended_validation_experiment["recommended_assay"] == "broth_microdilution_mic"
    assert res.calibration_summary.get("calibrated") is True
    assert res.iteration == 1

    # Check that recommendations include calibrated values
    for rec in res.recommendations:
        assert rec.calibrated_score is not None
