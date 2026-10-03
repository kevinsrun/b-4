"""The Result Analysis Agent against the REAL simulator's result shape.

``bacteriocin_sim`` returns the contract fields plus extensions, and differs from the shared contract in three
places (quantity objects, object-valued ``important_factors``, a ``failed`` status). These tests use a result
produced by the real simulator (committed as a fixture) and, where ``bacteriocin_sim`` is importable, results
generated live, so a drift in either package fails here rather than in a live Omnigent run.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from bacteriocin_discovery.contract import AgentResponseEnvelope, ExperimentResult
from bacteriocin_discovery.result_analysis_agent import analyze_result
from bacteriocin_discovery.result_analysis_agent.adapters import normalize_payload, normalize_result
from bacteriocin_discovery.result_analysis_agent.comparison import sigma_details

FIXTURE = Path(__file__).parent / "fixtures" / "sim_result_nisin_listeria.json"
SPEC = Path(__file__).parents[2] / "bacteriocin_sim" / "examples" / "spec_nisin_listeria.json"


@pytest.fixture
def sim_result() -> dict:
    return json.loads(FIXTURE.read_text())


def run(payload):
    out = analyze_result(payload)
    AgentResponseEnvelope.model_validate(out)
    return out


def test_real_simulator_result_is_accepted_not_rejected(sim_result):
    out = run(
        {
            "result": sim_result,
            "hypothesis": {"hypothesis_id": "hyp-0001", "predicted_direction": "inhibition"},
        }
    )
    d = out["decision"]
    assert out["warnings"] and not any("did not validate" in w for w in out["warnings"])
    assert d["result_id"] == sim_result["result_id"] and d["candidate_id"] == "cand-nisin-a"
    assert d["source_evidence_type"] == "simulation-derived" and out["confidence"] > 0


def test_quantity_objects_and_factor_objects_are_normalised_without_losing_detail(sim_result):
    norm = normalize_result(sim_result)
    c = norm["conditions"]
    assert c["bacteriocin_concentration"] == 1.0 and c["concentration_unit"] == "uM"
    assert c["target_cell_density"] == 1_000_000.0 and c["target_cell_density_unit"] == "cfu_per_ml"
    assert norm["important_factors"][0] == "bacteriocin_concentration_um"
    assert norm["important_factor_details"][0]["sensitivity"] > 0  # detail kept as extra keys
    ExperimentResult.model_validate(norm)  # now contract-valid
    assert sim_result["conditions"]["bacteriocin_concentration"] == {
        "value": 1.0,
        "unit": "uM",
    }  # input not mutated


def test_contract_shaped_results_pass_through_unchanged():
    contract = {
        "result_id": "r",
        "experiment_id": "e",
        "candidate_id": "c",
        "conditions": {"bacteriocin_concentration": 5.0, "concentration_unit": "ug/mL"},
        "important_factors": ["ph"],
    }
    assert normalize_result(contract) == contract
    assert normalize_result("not a dict") == "not a dict"
    assert normalize_payload({"result": contract, "previous_results": [contract]})[
        "previous_results"
    ] == [contract]


def test_collapsed_uncertainty_at_saturation_is_replaced_by_the_95_interval(sim_result):
    result = ExperimentResult.model_validate(normalize_result(sim_result))
    sigma, defaulted, note = sigma_details(result)
    assert result.measurement.uncertainty < 0.01 and sigma > 0.2 and not defaulted
    assert "understates" in note
    narrower = copy.deepcopy(sim_result)
    narrower["measurement"].update(uncertainty=0.1, ci95_inhibition_fraction=[0.45, 0.55])
    sigma2, _, note2 = sigma_details(ExperimentResult.model_validate(normalize_result(narrower)))
    assert sigma2 == pytest.approx(0.1) and note2 is None  # the wider of the two always wins


def test_saturated_result_is_not_called_decisive_and_says_what_to_use_instead(sim_result):
    d = run(
        {
            "result": sim_result,
            "hypothesis": {"hypothesis_id": "h", "predicted_direction": "inhibition"},
        }
    )["decision"]
    assert (
        d["hypothesis_status"] == "inconclusive"
    )  # point estimate ~1.0, but the model's own interval spans the range
    texts = " ".join(u["description"] for u in d["uncertainties"])
    assert "predicted_log10_reduction_vs_control" in texts and "understates" in texts


def test_imputed_defaults_and_dominant_uncertainty_source_are_surfaced(sim_result):
    d = run({"result": sim_result})["decision"]
    texts = [u["description"] for u in d["uncertainties"]]
    assert any("producer_cell_density_cfu_per_ml" in t and "provisional" in t for t in texts)
    assert any("target_potency_prior" in t for t in texts)


def test_simulator_important_factors_become_drivers(sim_result):
    drivers = run({"result": sim_result})["decision"]["drivers"]
    names = [x["variable"] for x in drivers]
    assert names[:2] == ["bacteriocin_concentration", "incubation_time"] and "ph" in names
    assert all(x["basis"] == "simulator-important-factors" for x in drivers)


def test_a_failed_attempt_is_not_a_negative_finding():
    failed = {
        "result_id": "res-x",
        "experiment_id": "exp-9",
        "candidate_id": "cand-nisin-a",
        "status": "failed",
        "evidence_type": "simulation-derived",
        "error": {"type": "SpecValidationError", "message": "concentration must be >= 0"},
    }
    out = run(
        {
            "result": failed,
            "hypothesis": {"hypothesis_id": "hyp-1", "predicted_direction": "inhibition"},
        }
    )
    d = out["decision"]
    assert (
        out["confidence"] == 0.0
        and d["hypothesis_status"] == "inconclusive"
        and d["findings"] == []
    )
    assert (
        "not a negative finding" in d["status_basis"]
        and "concentration must be >= 0" in d["status_basis"]
    )
    assert out["recommended_next_action"]["payload_hint"]["failed_experiment_id"] == "exp-9"
    assert out["artifacts"]["failed_attempt"] is True


def test_failed_prior_attempts_are_excluded_from_comparisons(sim_result):
    failed = {
        "result_id": "res-bad",
        "experiment_id": "exp-bad",
        "candidate_id": "cand-nisin-a",
        "status": "failed",
        "evidence_type": "simulation-derived",
        "conditions": {},
        "error": {"message": "x"},
    }
    out = run({"result": sim_result, "previous_results": [failed]})
    assert any("failed attempt" in w for w in out["warnings"])


# ---- live generation from the real simulator (skipped when bacteriocin_sim is not importable) ----------


def _live(conc: float, density: float, exp: str, strain: str | None = None) -> dict:
    api = pytest.importorskip("bacteriocin_sim.api")
    spec = json.loads(SPEC.read_text())
    spec["experiment_id"] = exp
    spec["conditions"]["bacteriocin_concentration"]["value"] = conc
    spec["conditions"]["target_cell_density"]["value"] = density
    if strain:
        spec["target"]["strain"] = strain
    return api.run_experiment(spec).model_dump(mode="json")


def test_live_simulator_pair_forms_a_controlled_density_comparison():
    low, high = _live(0.3, 1e6, "exp-lo"), _live(0.3, 1e8, "exp-hi")
    out = run(
        {
            "result": low,
            "previous_results": [high],
            "hypothesis": {
                "hypothesis_id": "hyp-0001",
                "expected_relationship": {
                    "variable": "target_cell_density",
                    "direction": "negative",
                },
            },
        }
    )
    f = next(x for x in out["decision"]["findings"] if x["variable"] == "target_cell_density")
    assert f["controlled"] and f["n_points"] == 2
    assert f["relationship"] in ("negative", "unresolved")  # direction is never reversed
    assert out["decision"]["hypothesis_status"] in ("supported", "inconclusive")


def test_live_simulator_results_for_different_strains_are_not_a_controlled_pair():
    a, b = _live(0.3, 1e6, "exp-a"), _live(0.3, 1e8, "exp-b", strain="10403S")
    out = run(
        {
            "result": a,
            "previous_results": [b],
            "hypothesis": {
                "hypothesis_id": "h",
                "expected_relationship": {
                    "variable": "target_cell_density",
                    "direction": "negative",
                },
            },
        }
    )
    assert out["decision"]["hypothesis_status"] == "inconclusive"
    assert not any(x["controlled"] for x in out["decision"]["findings"])
