"""Backend interface, routing, batching and error-handling tests."""

from __future__ import annotations

import pytest

from bacteriocin_sim import (
    AssayDomain,
    BackendUnavailableError,
    CandidateSpec,
    SimulationAdapter,
    SpecValidationError,
    ExperimentAdapter,
    UnknownBackendError,
    WetLabAdapter,
    available_backends,
    backend_for_domain,
    coerce_spec,
    describe_backends,
    get_adapter,
    run_experiment,
    run_experiments,
)
from bacteriocin_sim.selftest import NISIN_A, spec

# --------------------------------------------------------------------------
# routing and capabilities
# --------------------------------------------------------------------------


def test_both_backends_are_registered() -> None:
    assert set(available_backends()) >= {"simulation", "wet_lab"}


def test_simulated_domains_route_to_the_simulator() -> None:
    assert backend_for_domain(AssayDomain.SIMULATED_IN_VITRO) == "simulation"
    assert backend_for_domain("simulated_in_vivo_like") == "simulation"


def test_wet_lab_domains_route_to_the_wet_lab_backend() -> None:
    assert backend_for_domain("wet_lab_in_vitro") == "wet_lab"


def test_unknown_domain_is_reported_clearly() -> None:
    with pytest.raises(UnknownBackendError):
        backend_for_domain("telepathy")


def test_unknown_backend_name_is_reported_clearly() -> None:
    with pytest.raises(UnknownBackendError):
        get_adapter("nonexistent")


def test_capability_report_marks_wet_lab_unavailable() -> None:
    report = describe_backends()
    assert report["simulation"]["available"] is True
    assert report["wet_lab"]["available"] is False
    assert report["simulation"]["deterministic"] is True


def test_wet_lab_backend_refuses_with_an_actionable_message() -> None:
    lab_spec = coerce_spec(spec(conditions={"assay_domain": "wet_lab_in_vitro"}))
    with pytest.raises(BackendUnavailableError) as exc:
        WetLabAdapter().run(lab_spec)
    assert "simulated_in_vitro" in exc.value.message
    assert exc.value.details["available_backends"] == ["simulation"]


def test_wet_lab_adapter_implements_the_same_interface() -> None:
    """The seam must already be real, not a future refactor."""
    assert isinstance(WetLabAdapter(), ExperimentAdapter)
    assert isinstance(SimulationAdapter(), ExperimentAdapter)
    capabilities = WetLabAdapter().capabilities()
    assert capabilities.evidence_type == "wet-lab-derived"
    assert capabilities.deterministic is False


def test_wet_lab_domain_is_rejected_by_the_simulator() -> None:
    with pytest.raises(SpecValidationError):
        run_experiment(
            spec(conditions={"assay_domain": "wet_lab_in_vitro"}), backend="simulation"
        )


# --------------------------------------------------------------------------
# result shape
# --------------------------------------------------------------------------


def test_result_carries_provenance_and_reproducibility() -> None:
    result = run_experiment(spec())
    assert result.status == "ok"
    assert result.evidence_type.value == "simulation-derived"
    assert result.validated_experimentally is False
    assert result.reproducibility.deterministic is True
    assert result.reproducibility.spec_hash
    assert result.reproducibility.parameter_set_hash
    assert result.model_version.startswith("bacteriocin-sim/")
    assert result.parameter_provenance
    assert result.uncertainty_components


def test_result_echoes_the_conditions_actually_used() -> None:
    """An omitted condition must come back as the value the model assumed."""
    result = run_experiment(
        {"experiment_id": "e", "target": {"species": "Listeria monocytogenes"}}
    )
    conditions = result.conditions
    assert conditions["ph"] is not None
    assert conditions["temperature_c"] is not None
    assert conditions["medium"]
    assert "ph" in conditions["imputed_fields"]
    assert conditions["target_cell_density"]["unit"] == "cfu_per_ml"


def test_measurements_are_continuous_not_labels() -> None:
    result = run_experiment(
        spec(conditions={"bacteriocin_concentration": {"value": 0.25, "unit": "uM"}})
    )
    m = result.measurement
    assert 0.0 < m.predicted_inhibition_fraction < 1.0
    assert m.predicted_survival_fraction == pytest.approx(
        1.0 - m.predicted_inhibition_fraction, abs=1e-5
    )
    assert m.predicted_mic_um > 0
    assert m.uncertainty is not None
    assert m.ci95_inhibition_fraction[0] <= m.ci95_inhibition_fraction[1]


def test_important_factors_are_ranked_and_carry_units() -> None:
    result = run_experiment(spec())
    factors = result.important_factors
    assert factors
    magnitudes = [abs(f.sensitivity) for f in factors]
    assert magnitudes == sorted(magnitudes, reverse=True)
    assert all(f.unit for f in factors)
    assert {"bacteriocin_concentration_um", "target_cell_density_cfu_per_ml"} <= {
        f.factor for f in factors
    }


def test_result_id_is_stable_across_identical_runs() -> None:
    a = run_experiment(spec())
    b = run_experiment(spec())
    assert a.result_id == b.result_id


def test_result_id_changes_when_the_science_changes() -> None:
    a = run_experiment(spec())
    b = run_experiment(spec(conditions={"ph": 5.0}))
    assert a.result_id != b.result_id


# --------------------------------------------------------------------------
# candidate resolution
# --------------------------------------------------------------------------


def test_candidate_registry_resolves_a_bare_candidate_id() -> None:
    registry = {"cand-x": CandidateSpec(candidate_id="cand-x", sequence=NISIN_A)}
    with_registry = run_experiment(
        {
            "experiment_id": "e",
            "candidate_id": "cand-x",
            "target": {"species": "Listeria monocytogenes"},
            "conditions": {"bacteriocin_concentration": {"value": 1.0, "unit": "uM"}},
        },
        candidate_registry=registry,
    )
    assert not any("generic" in w for w in with_registry.warnings)


def test_missing_sequence_is_flagged_loudly() -> None:
    result = run_experiment(
        {
            "experiment_id": "e",
            "candidate_id": "cand-unknown",
            "target": {"species": "Listeria monocytogenes"},
            "conditions": {"bacteriocin_concentration": {"value": 1.0, "unit": "uM"}},
        }
    )
    assert any("generic" in w for w in result.warnings)
    assert any(
        c.source == "no_candidate_sequence" for c in result.uncertainty_components
    )


def test_unknown_organism_falls_back_and_warns() -> None:
    result = run_experiment(spec(target={"species": "Quasibacterium imaginarium"}))
    assert any("not in the curated prior set" in w for w in result.warnings)


def test_congener_priors_are_borrowed_for_an_unlisted_species() -> None:
    result = run_experiment(spec(target={"species": "Listeria ivanovii"}))
    assert any("genus-level priors" in w for w in result.warnings)


# --------------------------------------------------------------------------
# batching and failure isolation
# --------------------------------------------------------------------------


def test_one_bad_spec_does_not_sink_the_batch() -> None:
    results = run_experiments(
        [
            spec(experiment_id="good-1"),
            {"experiment_id": "bad-1", "conditions": {"ph": 99.0}},
            spec(experiment_id="good-2", conditions={"ph": 5.5}),
        ]
    )
    assert [r.status for r in results] == ["ok", "failed", "ok"]
    assert results[1].error["error_code"] == "spec_validation_error"
    assert results[1].experiment_id == "bad-1"


def test_batch_preserves_input_order() -> None:
    specs = [spec(experiment_id=f"e-{i}", conditions={"ph": 5.0 + i * 0.5}) for i in range(5)]
    results = run_experiments(specs)
    assert [r.experiment_id for r in results] == [s["experiment_id"] for s in specs]


def test_mixed_domains_are_routed_per_spec() -> None:
    results = run_experiments(
        [
            spec(experiment_id="sim-1"),
            spec(experiment_id="lab-1", conditions={"assay_domain": "wet_lab_in_vitro"}),
        ]
    )
    assert results[0].status == "ok"
    assert results[1].status == "failed"
    assert results[1].error["error_code"] == "backend_unavailable"


def test_non_dict_spec_is_rejected_not_crashed() -> None:
    results = run_experiments(["not a spec"])
    assert results[0].status == "failed"


# --------------------------------------------------------------------------
# parameter overrides (the knowledge-update seam)
# --------------------------------------------------------------------------


def test_parameter_overrides_change_predictions_and_the_hash() -> None:
    base = run_experiment(spec())
    refit = run_experiment(
        spec(),
        parameter_overrides={
            "targets": {"listeria monocytogenes": {"log10_mic_um_base": 1.5}}
        },
    )
    assert refit.measurement.predicted_mic_um > base.measurement.predicted_mic_um
    assert (
        refit.reproducibility.parameter_set_hash
        != base.reproducibility.parameter_set_hash
    )
    assert refit.model_version != base.model_version


def test_overrides_do_not_leak_between_adapters() -> None:
    SimulationAdapter(
        parameter_overrides={"targets": {"listeria monocytogenes": {"log10_mic_um_base": 3.0}}}
    )
    clean = SimulationAdapter()
    assert clean.store.targets["listeria monocytogenes"]["log10_mic_um_base"] == 0.0


def test_obligate_anaerobe_assayed_aerobically_is_flagged() -> None:
    result = run_experiment(
        spec(
            target={"species": "Clostridium perfringens"},
            conditions={"aeration": "aerobic"},
        )
    )
    assert any("obligate anaerobe" in w for w in result.warnings)


def test_non_growth_buffer_with_a_growth_readout_is_flagged() -> None:
    result = run_experiment(
        spec(conditions={"medium": "pbs", "assay_type": "microtiter_growth_inhibition"})
    )
    assert any("does not support growth" in w for w in result.warnings)


def test_temperature_outside_the_growth_range_is_flagged() -> None:
    result = run_experiment(spec(conditions={"temperature_c": 50.0}))
    assert any("outside the growth range" in w for w in result.warnings)


def test_time_kill_assay_reports_log_reduction_as_its_primary_metric() -> None:
    result = run_experiment(spec(conditions={"assay_type": "time_kill"}))
    assert result.measurement.primary_metric == "predicted_log10_reduction_vs_control"
    assert result.measurement.predicted_log10_reduction_vs_control is not None


def test_diffusion_assay_reports_a_zone_diameter_and_its_caveat() -> None:
    result = run_experiment(spec(conditions={"assay_type": "agar_well_diffusion"}))
    assert result.measurement.predicted_zone_diameter_mm > 0
    assert any("well-mixed model" in w for w in result.warnings)


def test_producer_cells_alone_can_drive_activity() -> None:
    """In-situ production is a supported peptide source, not just a label."""
    result = run_experiment(
        spec(
            conditions={
                "bacteriocin_concentration": None,
                "producer_cell_density": {"value": 5.0e8, "unit": "cfu_per_ml"},
                "incubation_time": 24.0,
            }
        )
    )
    assert result.measurement.predicted_inhibition_fraction > 0.0
    assert any(
        c.source == "in_situ_production_rate" for c in result.uncertainty_components
    )


def test_unrecognised_assay_type_falls_back_with_a_warning() -> None:
    result = run_experiment(spec(conditions={"assay_type": "crystal_ball"}))
    assert result.status == "ok"
    assert any("not recognised" in w for w in result.warnings)
