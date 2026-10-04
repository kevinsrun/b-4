"""Contract-shape and validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bacteriocin_lab.agents.simulator.schemas import (
    CandidateSpec,
    Conditions,
    EvidenceType,
    ExperimentResult,
    ExperimentSpec,
    Measurement,
)

#: every field the shared contract names on ExperimentSpec
CONTRACT_SPEC_FIELDS = {"experiment_id", "hypothesis_id", "candidate_id", "target", "conditions"}

#: every field the shared contract names on conditions
CONTRACT_CONDITION_FIELDS = {
    "bacteriocin_concentration",
    "target_cell_density",
    "producer_cell_density",
    "ph",
    "temperature_c",
    "medium",
    "ionic_conditions",
    "incubation_time",
    "growth_phase",
    "assay_domain",
}

#: every field the shared contract names on ExperimentResult
CONTRACT_RESULT_FIELDS = {
    "result_id",
    "experiment_id",
    "candidate_id",
    "conditions",
    "measurement",
    "important_factors",
    "evidence_type",
    "model_version",
    "warnings",
}

CONTRACT_MEASUREMENT_FIELDS = {
    "predicted_inhibition_fraction",
    "predicted_survival_fraction",
    "predicted_activity",
    "uncertainty",
}


def test_spec_has_every_contract_field() -> None:
    assert CONTRACT_SPEC_FIELDS <= set(ExperimentSpec.model_fields)


def test_conditions_have_every_contract_field() -> None:
    assert CONTRACT_CONDITION_FIELDS <= set(Conditions.model_fields)


def test_result_has_every_contract_field() -> None:
    assert CONTRACT_RESULT_FIELDS <= set(ExperimentResult.model_fields)


def test_measurement_has_every_contract_field() -> None:
    assert CONTRACT_MEASUREMENT_FIELDS <= set(Measurement.model_fields)


def test_contract_minimal_spec_validates() -> None:
    """A spec written against the bare contract, with nothing extra, must work."""
    spec = ExperimentSpec.model_validate(
        {
            "experiment_id": "exp-1",
            "hypothesis_id": "hyp-1",
            "candidate_id": "cand-1",
            "target": {"species": "Listeria monocytogenes", "strain": "EGD-e"},
            "conditions": {
                "bacteriocin_concentration": None,
                "target_cell_density": None,
                "producer_cell_density": None,
                "ph": None,
                "temperature_c": None,
                "medium": None,
                "ionic_conditions": {},
                "incubation_time": None,
                "growth_phase": None,
                "assay_domain": "simulated_in_vitro",
            },
        }
    )
    assert spec.experiment_id == "exp-1"
    assert spec.conditions.ph is None


def test_unknown_fields_are_preserved_not_dropped() -> None:
    """Forward compatibility: a newer planner's fields survive a round-trip."""
    spec = ExperimentSpec.model_validate(
        {"experiment_id": "exp-1", "conditions": {"future_field": 42}}
    )
    assert spec.to_json_dict()["conditions"]["future_field"] == 42


def test_spec_hash_ignores_labels_but_not_science() -> None:
    a = ExperimentSpec(experiment_id="exp-a", conditions=Conditions(ph=7.0))
    b = ExperimentSpec(experiment_id="exp-b", conditions=Conditions(ph=7.0))
    c = ExperimentSpec(experiment_id="exp-a", conditions=Conditions(ph=5.0))
    assert a.spec_hash() == b.spec_hash()
    assert a.spec_hash() != c.spec_hash()


@pytest.mark.parametrize(
    "payload",
    [
        {"experiment_id": "", "conditions": {}},
        {"experiment_id": "e", "conditions": {"ph": 15.0}},
        {"experiment_id": "e", "conditions": {"ph": -1.0}},
        {"experiment_id": "e", "conditions": {"temperature_c": 500.0}},
        {"experiment_id": "e", "conditions": {"incubation_time": -5.0}},
        {"experiment_id": "e", "conditions": {"bacteriocin_concentration": -1.0}},
        {"experiment_id": "e", "conditions": {"ionic_conditions": {"nacl_mm": -5.0}}},
    ],
)
def test_invalid_specs_are_rejected(payload: dict) -> None:
    with pytest.raises(ValidationError):
        ExperimentSpec.model_validate(payload)


def test_invalid_sequence_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CandidateSpec.model_validate({"sequence": "ACDE123FG"})


def test_sequence_is_normalised() -> None:
    candidate = CandidateSpec.model_validate({"sequence": "acde fghi-kl*"})
    assert candidate.sequence == "ACDEFGHIKL"


def test_candidate_id_mismatch_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ExperimentSpec.model_validate(
            {
                "experiment_id": "e",
                "candidate_id": "cand-1",
                "candidate": {"candidate_id": "cand-2"},
            }
        )


def test_candidate_id_is_backfilled_from_the_candidate_block() -> None:
    spec = ExperimentSpec.model_validate(
        {"experiment_id": "e", "candidate": {"candidate_id": "cand-7"}}
    )
    assert spec.candidate_id == "cand-7"


def test_result_cannot_claim_wet_lab_provenance() -> None:
    with pytest.raises(ValidationError):
        ExperimentResult(
            result_id="r", experiment_id="e", evidence_type=EvidenceType.WET_LAB
        )


def test_result_cannot_claim_experimental_validation() -> None:
    with pytest.raises(ValidationError):
        ExperimentResult(result_id="r", experiment_id="e", validated_experimentally=True)


def test_fractions_outside_the_unit_interval_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Measurement(predicted_inhibition_fraction=1.5)
