"""End-to-end tests for the Result Analysis Agent.

These defend the contract obligations: no false validation claims, honest
inconclusive verdicts, preserved uncertainty, reproducible IDs, graceful failure,
and compatibility with the other agents' output.
"""

from __future__ import annotations

import json

import pytest
from bacteriocin_discovery.candidate_agent import CandidateGenerationAgent
from bacteriocin_discovery.contract import AgentResponseEnvelope, Uncertainty
from bacteriocin_discovery.ids import finding_id
from bacteriocin_discovery.result_analysis_agent import (
    AGENT_NAME,
    MODEL_VERSION,
    AnalysisIntegrityError,
    ResultAnalysisAgent,
    ResultAnalysisRequest,
    analyze_result,
)
from bacteriocin_discovery.result_analysis_agent.agent import claims_experimental_validation
from bacteriocin_discovery.result_analysis_agent.hypothesis import infer_expected_relationship
from result_analysis_helpers import make_result

DENSITY_NEG = {
    "hypothesis_id": "hyp_density",
    "statement": "x",
    "expected_relationship": {"variable": "target_cell_density", "direction": "negative"},
}


def run(payload):
    out = analyze_result(payload)
    AgentResponseEnvelope.model_validate(out)  # contract-valid, always
    return out


def decision(out):
    return out["decision"]


# --------------------------------------------------------------------------
# The example from the agent's brief
# --------------------------------------------------------------------------


def test_brief_example_density_negative_relationship():
    out = run(
        {
            "result": make_result("r2", 0.86, density=1e6, ph=7.0),
            "previous_results": [make_result("r1", 0.43, density=1e8, ph=7.0)],
            "hypothesis": DENSITY_NEG,
        }
    )
    d = decision(out)
    assert set(d) >= {
        "finding_id",
        "experiment_id",
        "hypothesis_id",
        "hypothesis_status",
        "findings",
        "unexpected_results",
        "confidence",
        "uncertainties",
        "recommended_followup_questions",
    }
    f = d["findings"][0]
    assert f["variable"] == "target_cell_density" and f["relationship"] == "negative"
    assert f["effect_size"] == pytest.approx(-0.215) and f["controlled"] is True
    assert (
        "reduced predicted inhibition" in f["interpretation"]
        and "Higher target cell density" in f["interpretation"]
    )


# --------------------------------------------------------------------------
# Hypothesis support / weakening / inconclusive
# --------------------------------------------------------------------------


def test_hypothesis_is_supported_when_controlled_comparison_matches_prediction():
    out = run(
        {
            "result": make_result("r2", 0.86, density=1e6),
            "previous_results": [
                make_result("r1", 0.43, density=1e8),
                make_result("r0", 0.20, density=1e9),
            ],
            "hypothesis": DENSITY_NEG,
        }
    )
    d = decision(out)
    assert d["hypothesis_status"] == "supported" and d["evidence_strength"] in (
        "moderate",
        "strong",
    )
    assert d["prediction_source"] == "expected_relationship"
    assert d["confidence"] > 0.5
    assert out["recommended_next_action"]["agent"] == "experiment_planner"


def test_hypothesis_is_weakened_when_data_show_the_opposite_trend():
    out = run(
        {
            "result": make_result("r2", 0.30, density=1e6),
            "previous_results": [
                make_result("r1", 0.80, density=1e8)
            ],  # MORE inhibition at HIGHER density
            "hypothesis": DENSITY_NEG,
        }
    )
    d = decision(out)
    assert d["hypothesis_status"] == "weakened" and d["evidence_strength"] in ("moderate", "strong")
    assert d["findings"][0]["relationship"] == "positive"
    assert any("alternative" in q.lower() for q in d["recommended_followup_questions"])
    assert "weakened" in out["recommended_next_action"]["reason"]


def test_hypothesis_is_weakened_when_predicted_effect_is_absent():
    out = run(
        {
            "result": make_result("r2", 0.60, density=1e6),
            "previous_results": [make_result("r1", 0.61, density=1e8)],
            "hypothesis": DENSITY_NEG,
        }
    )
    d = decision(out)
    assert d["hypothesis_status"] == "weakened" and d["evidence_strength"] == "weak"


def test_inconclusive_without_a_controlled_comparison_and_says_what_to_run():
    out = run(
        {
            "result": make_result("r2", 0.86, density=1e6),
            "previous_results": [
                make_result("r1", 0.43, density=1e8, ph=5.0)
            ],  # two variables differ: confounded
            "hypothesis": DENSITY_NEG,
        }
    )
    d = decision(out)
    assert d["hypothesis_status"] == "inconclusive"
    unresolved = next(f for f in d["findings"] if f["variable"] == "target_cell_density")
    assert unresolved["relationship"] == "unresolved" and unresolved["controlled"] is False
    assert any("changing only" in q for q in d["recommended_followup_questions"])
    hints = out["artifacts"]["planner_hints"]["suggested_experiments"]
    assert (
        hints
        and hints[0]["vary"] == "target_cell_density"
        and len(hints[0]["suggested_values"]) == 2
    )
    assert any(u["kind"] == "data-gap" and u["severity"] == "high" for u in d["uncertainties"])


def test_inconclusive_when_difference_is_inside_measurement_noise():
    out = run(
        {
            "result": make_result("r2", 0.55, density=1e6, sigma=0.2),
            "previous_results": [make_result("r1", 0.42, density=1e8, sigma=0.2)],
            "hypothesis": DENSITY_NEG,
        }
    )
    assert decision(out)["hypothesis_status"] == "inconclusive"


def test_numeric_prior_supported_and_weakened():
    base = {"hypothesis_id": "h", "predicted_inhibition_fraction": 0.8}
    ok = decision(run({"result": make_result("r", 0.82), "hypothesis": base}))
    bad = decision(run({"result": make_result("r", 0.15), "hypothesis": base}))
    assert (
        ok["hypothesis_status"] == "supported"
        and ok["prediction_source"] == "predicted_inhibition_fraction"
    )
    assert bad["hypothesis_status"] == "weakened"
    assert any(u["kind"] == "prediction_mismatch" for u in bad["unexpected_results"])


def test_directional_predictions_use_thresholds_with_uncertainty():
    inhibit = {"hypothesis_id": "h", "predicted_direction": "inhibition"}
    assert (
        decision(run({"result": make_result("r", 0.9), "hypothesis": inhibit}))["hypothesis_status"]
        == "supported"
    )
    assert (
        decision(run({"result": make_result("r", 0.1), "hypothesis": inhibit}))["hypothesis_status"]
        == "weakened"
    )
    assert (
        decision(run({"result": make_result("r", 0.5), "hypothesis": inhibit}))["hypothesis_status"]
        == "inconclusive"
    )
    none = {"hypothesis_id": "h", "predicted_direction": "no-effect"}
    assert (
        decision(run({"result": make_result("r", 0.02), "hypothesis": none}))["hypothesis_status"]
        == "supported"
    )
    assert (
        decision(run({"result": make_result("r", 0.9), "hypothesis": none}))["hypothesis_status"]
        == "weakened"
    )


def test_result_outside_hypothesis_conditions_is_inconclusive():
    h = {
        "hypothesis_id": "h",
        "predicted_inhibition_fraction": 0.8,
        "key_conditions": {"ph": [6.0, 7.5]},
    }
    d = decision(run({"result": make_result("r", 0.8, ph=5.0), "hypothesis": h}))
    assert (
        d["hypothesis_status"] == "inconclusive" and "outside the conditions" in d["status_basis"]
    )


def test_statement_keyword_reading_is_labelled_and_never_strong():
    assert (
        infer_expected_relationship(
            "Higher target-cell density reduces effective bacteriocin inhibition."
        ).direction
        == "negative"
    )
    assert (
        infer_expected_relationship("Lower pH increases activity.").direction == "negative"
    )  # lower pH x increases = negative in pH
    assert (
        infer_expected_relationship("Higher concentration increases inhibition").direction
        == "positive"
    )
    assert (
        infer_expected_relationship("pH and temperature both reduce activity") is None
    )  # two variables: not guessed
    out = run(
        {
            "result": make_result("r2", 0.9, density=1e6),
            "previous_results": [make_result("r1", 0.1, density=1e9)],
            "hypothesis": {
                "hypothesis_id": "h",
                "statement": "Higher target-cell density reduces inhibition.",
            },
        }
    )
    d = decision(out)
    assert (
        d["prediction_source"] == "statement-keyword-heuristic"
        and d["evidence_strength"] != "strong"
    )
    assert any("keyword rule" in u["description"] for u in d["uncertainties"])


def test_untestable_hypothesis_is_inconclusive_not_supported():
    d = decision(
        run(
            {
                "result": make_result("r", 0.9),
                "hypothesis": {"hypothesis_id": "h", "statement": "Something vague happens."},
            }
        )
    )
    assert d["hypothesis_status"] == "inconclusive" and d["prediction_source"] == "none"


def test_no_hypothesis_still_reports_condition_response():
    out = run(
        {
            "result": make_result("r2", 0.86),
            "previous_results": [make_result("r1", 0.43, density=1e8)],
        }
    )
    d = decision(out)
    assert d["hypothesis_id"] is None and d["hypothesis_status"] == "inconclusive"
    assert d["findings"][0]["relationship"] == "negative"


def test_hypothesis_and_prior_results_can_come_from_research_state():
    state = {
        "hypotheses": {"hyp_density": DENSITY_NEG},
        "results": {"r1": make_result("r1", 0.43, density=1e8)},
    }
    res = make_result("r2", 0.86, density=1e6, hypothesis_id="hyp_density")
    d = decision(run({"result": res, "research_state": state}))
    assert d["hypothesis_status"] == "supported" and d["hypothesis_id"] == "hyp_density"


# --------------------------------------------------------------------------
# Unexpected results, drivers, comparison
# --------------------------------------------------------------------------


def test_reversal_of_an_established_trend_is_flagged_high_severity():
    prior = [make_result("a", 0.85, density=1e5), make_result("b", 0.35, density=1e9)]
    out = run(
        {
            "result": make_result("c", 0.95, density=1e8),
            "previous_results": prior,
            "hypothesis": DENSITY_NEG,
        }
    )
    kinds = {u["kind"]: u for u in decision(out)["unexpected_results"]}
    assert (
        "contradicts_prior_trend" in kinds
        and kinds["contradicts_prior_trend"]["severity"] == "high"
    )
    assert out["artifacts"]["planner_hints"]["reopen_hypothesis_ids"] == ["hyp_density"]
    assert decision(out)["findings"][0]["relationship"] in ("non_monotonic", "positive")


def test_non_monotonic_response_is_reported():
    prior = [make_result("a", 0.3, ph=5.0), make_result("b", 0.35, ph=9.0)]
    d = decision(run({"result": make_result("c", 0.85, ph=7.0), "previous_results": prior}))
    assert any(u["kind"] == "non_monotonic_response" for u in d["unexpected_results"])


def test_inconsistent_inhibition_and_survival_is_flagged():
    d = decision(run({"result": make_result("r", 0.9, survival=0.5)}))
    assert any(
        u["kind"] == "inconsistent_measurement" and u["severity"] == "high"
        for u in d["unexpected_results"]
    )


def test_drivers_merge_controlled_effects_with_producer_factors():
    prior = [make_result("a", 0.43, density=1e8)]
    d = decision(
        run(
            {
                "result": make_result("r", 0.86, factors=["target_cell_density", "ph"]),
                "previous_results": prior,
            }
        )
    )
    drivers = {x["variable"]: x for x in d["drivers"]}
    assert (
        drivers["target_cell_density"]["basis"] == "both"
        and drivers["target_cell_density"]["rank"] == 1
    )
    assert drivers["ph"]["basis"] == "simulator-important-factors"


def test_producer_factor_with_no_controlled_effect_is_a_driver_mismatch():
    prior = [make_result("a", 0.60, density=1e8)]
    d = decision(
        run(
            {
                "result": make_result("r", 0.61, factors=["target_cell_density"]),
                "previous_results": prior,
            }
        )
    )
    assert any(u["kind"] == "driver_mismatch" for u in d["unexpected_results"])


def test_plateau_is_reported_and_prompts_a_followup():
    prior = [make_result("a", 0.10, concentration=1.0), make_result("b", 0.62, concentration=10.0)]
    d = decision(
        run({"result": make_result("c", 0.64, concentration=100.0), "previous_results": prior})
    )
    f = next(f for f in d["findings"] if f["variable"] == "bacteriocin_concentration")
    assert f["plateau"] and "saturation" in f["interpretation"]


# --------------------------------------------------------------------------
# Confidence and uncertainty
# --------------------------------------------------------------------------


def test_simulation_confidence_is_capped_and_wet_lab_cap_is_higher():
    prior = [make_result("a", 0.2, density=1e9), make_result("b", 0.5, density=1e8)]
    sim = decision(
        run(
            {
                "result": make_result("r", 0.9, sigma=0.001),
                "previous_results": prior,
                "hypothesis": DENSITY_NEG,
            }
        )
    )
    wet_prior = [dict(p, evidence_type="wet-lab-derived") for p in prior]
    wet = decision(
        run(
            {
                "result": make_result("r", 0.9, sigma=0.001, evidence_type="wet-lab-derived"),
                "previous_results": wet_prior,
                "hypothesis": DENSITY_NEG,
            }
        )
    )
    assert sim["confidence"] <= 0.85 and wet["confidence"] >= sim["confidence"]


def test_measurement_uncertainty_lowers_confidence():
    prior = [make_result("a", 0.43, density=1e8, sigma=0.03)]
    tight = decision(
        run(
            {
                "result": make_result("r", 0.86, sigma=0.02),
                "previous_results": prior,
                "hypothesis": DENSITY_NEG,
            }
        )
    )
    loose = decision(
        run(
            {
                "result": make_result("r", 0.86, sigma=0.25),
                "previous_results": [make_result("a", 0.43, density=1e8, sigma=0.25)],
                "hypothesis": DENSITY_NEG,
            }
        )
    )
    assert loose["confidence"] < tight["confidence"]


def test_uncertainties_are_preserved_and_structured():
    out = run(
        {
            "result": make_result("r", 0.99, sigma=None),
            "previous_results": [make_result("a", 0.43, density=1e8)],
            "hypothesis": DENSITY_NEG,
        }
    )
    kinds = {(u["kind"], u["severity"]) for u in decision(out)["uncertainties"]}
    assert ("model-limitation", "medium") in kinds  # simulation-derived + ceiling
    assert any(k == "data-gap" for k, _ in kinds)  # sigma assumed
    assert any(
        u["kind"] == "epistemic" for u in decision(out)["uncertainties"]
    )  # two-point relationship
    assert all(isinstance(u, str | dict) for u in out["uncertainties"])
    Uncertainty.model_validate(decision(out)["uncertainties"][0])


# --------------------------------------------------------------------------
# Provenance: never call non-wet-lab evidence experimentally validated
# --------------------------------------------------------------------------


@pytest.mark.parametrize("etype", ["simulation-derived", "model-predicted"])
def test_non_wet_lab_results_are_never_described_as_validated(etype):
    prior = [make_result("a", 0.43, density=1e8, evidence_type=etype)]
    out = run(
        {
            "result": make_result("r", 0.86, evidence_type=etype),
            "previous_results": prior,
            "hypothesis": DENSITY_NEG,
        }
    )
    blob = json.dumps(out)
    for text in _all_strings(out):
        assert not claims_experimental_validation(text), text
    assert decision(out)["source_evidence_type"] == etype
    assert "NOT experimentally validated" in decision(out)["provenance_note"]
    assert (
        "measured" not in " ".join(f["interpretation"] for f in decision(out)["findings"]).lower()
    )
    assert out["artifacts"]["knowledge_update"]["is_experimentally_validated"] is False
    assert "wet-lab-derived" not in {e["evidence_type"] for e in out["evidence"]}
    assert blob  # serialisable


def test_emitted_evidence_is_inferred_hypothesis_and_links_back():
    out = run(
        {
            "result": make_result("r2", 0.86),
            "previous_results": [make_result("r1", 0.43, density=1e8)],
            "hypothesis": DENSITY_NEG,
        }
    )
    assert out["evidence"]
    for e in out["evidence"]:
        assert (
            e["evidence_type"] == "inferred-hypothesis"
            and e["derived_from_evidence_type"] == "simulation-derived"
        )
        assert "r2" in e["subject_ids"] and e["claim"].startswith("[simulation-derived]")
        assert e["evidence_id"].startswith("ev_")


def test_wet_lab_input_is_described_as_measured_but_still_not_minted_as_wet_lab_evidence():
    prior = [make_result("a", 0.43, density=1e8, evidence_type="wet-lab-derived")]
    out = run(
        {
            "result": make_result("r", 0.86, evidence_type="wet-lab-derived"),
            "previous_results": prior,
            "hypothesis": DENSITY_NEG,
        }
    )
    assert "measured inhibition" in decision(out)["findings"][0]["interpretation"]
    assert out["artifacts"]["knowledge_update"]["is_experimentally_validated"] is True
    assert {e["evidence_type"] for e in out["evidence"]} == {"inferred-hypothesis"}
    assert "wet-lab" not in " ".join(
        q for q in decision(out)["recommended_followup_questions"] if "Does this simulated" in q
    )


def test_guard_distinguishes_claims_from_disclaimers():
    assert claims_experimental_validation("The effect was experimentally validated.")
    assert claims_experimental_validation("wet-lab confirmed the trend")
    assert not claims_experimental_validation("It is NOT experimentally validated.")
    assert not claims_experimental_validation("nothing here is experimentally validated.")
    assert not claims_experimental_validation("This has not been experimentally validated yet.")


def test_guard_fails_closed_if_a_draft_claims_validation():
    from bacteriocin_discovery.result_analysis_agent.schema import ResultAnalysis

    bad = ResultAnalysis(
        finding_id="find_x",
        experiment_id="e",
        result_id="r",
        candidate_id="c",
        status_basis="The effect was experimentally validated.",
    )
    with pytest.raises(AnalysisIntegrityError):
        ResultAnalysisAgent._assert_provenance_language(bad, wet=False)
    ResultAnalysisAgent._assert_provenance_language(bad, wet=True)


# --------------------------------------------------------------------------
# Envelope, determinism, IDs, errors
# --------------------------------------------------------------------------


def test_envelope_carries_structured_handoffs_for_planner_and_knowledge_agent():
    out = run(
        {
            "result": make_result("r2", 0.86),
            "previous_results": [make_result("r1", 0.43, density=1e8)],
            "hypothesis": DENSITY_NEG,
        }
    )
    assert out["agent"] == AGENT_NAME and out["model_version"] == MODEL_VERSION
    nxt = out["recommended_next_action"]
    assert (
        nxt["agent"] == "experiment_planner"
        and "knowledge_agent" in nxt["payload_hint"]["also_notify"]
    )
    ku = out["artifacts"]["knowledge_update"]
    assert ku["hypothesis_update"]["status"] == "supported" and ku["claim_evidence_ids"] == [
        e["evidence_id"] for e in out["evidence"]
    ]
    hints = out["artifacts"]["planner_hints"]
    assert "target_cell_density" in hints["resolved_variables"] and "followup_questions" in hints
    assert out["artifacts"]["comparisons"][0]["points"][0]["result_id"] in ("r2", "r1")
    assert set(out["artifacts"]["confidence_breakdown"]) >= {"base", "cap"}


def test_deterministic_and_finding_id_is_content_addressed():
    payload = {
        "result": make_result("r2", 0.86),
        "previous_results": [make_result("r1", 0.43, density=1e8)],
        "hypothesis": DENSITY_NEG,
    }
    a, b = run(payload), run(json.loads(json.dumps(payload)))
    assert a == b
    fid = decision(a)["finding_id"]
    assert fid.startswith("find_") and len(fid) == len("find_") + 16
    assert fid == finding_id(
        experiment_id="exp_r2",
        hypothesis_id="hyp_density",
        result_id="r2",
        model_version=MODEL_VERSION,
    )
    assert fid != finding_id(
        experiment_id="exp_r2", hypothesis_id="hyp_density", result_id="r2", model_version="other/9"
    )
    other = run({**payload, "result": make_result("r3", 0.86)})
    assert decision(other)["finding_id"] != fid


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"result": "nope"},
        {"result": {"result_id": "x"}},
        {"result": make_result("r", 0.5), "previous_results": "bad"},
    ],
)
def test_invalid_requests_return_a_well_formed_zero_confidence_envelope(payload):
    out = run(payload)
    assert (
        out["confidence"] == 0.0
        and out["warnings"]
        and out["uncertainties"][0]["kind"] == "data-gap"
    )
    assert out["decision"]["hypothesis_status"] == "inconclusive"


def test_result_without_measurement_is_handled():
    res = make_result("r", 0.5)
    res["measurement"] = {}
    d = decision(
        run(
            {
                "result": res,
                "hypothesis": {"hypothesis_id": "h", "predicted_inhibition_fraction": 0.5},
            }
        )
    )
    assert d["hypothesis_status"] == "inconclusive"


def test_agent_class_and_request_model_work_directly():
    req = ResultAnalysisRequest.model_validate(
        {
            "result": make_result("r2", 0.86),
            "previous_results": [make_result("r1", 0.43, density=1e8)],
            "hypothesis": DENSITY_NEG,
        }
    )
    outcome = ResultAnalysisAgent().analyze(req)
    assert (
        outcome.analysis.hypothesis_status == "supported"
        and outcome.recommended_next_action.agent == "experiment_planner"
    )


# --------------------------------------------------------------------------
# Compatibility with the existing Candidate Generation Agent
# --------------------------------------------------------------------------


def test_consumes_a_hypothesis_produced_by_the_candidate_agent_unchanged():
    env = CandidateGenerationAgent().run_envelope(
        {
            "target": {"organism": "Listeria monocytogenes", "gram": "positive"},
            "constraints": {"max_candidates": 2},
        }
    )
    cand = env.decision["candidates"][0]
    hyp = cand["hypotheses"][
        0
    ]  # a TestableHypothesis dict, with falsified_if / key_conditions extras
    pred = hyp.get("predicted_inhibition_fraction")
    result = make_result(
        "r1",
        0.2 if pred is None else max(0.0, min(1.0, pred - 0.5)),
        candidate=cand["candidate_id"],
        hypothesis_id=hyp["hypothesis_id"],
    )
    out = run({"result": result, "hypothesis": hyp})
    d = decision(out)
    assert d["hypothesis_id"] == hyp["hypothesis_id"] and d["candidate_id"] == cand["candidate_id"]
    assert d["hypothesis_status"] in ("supported", "weakened", "inconclusive")


def test_previous_results_from_other_candidates_do_not_leak_into_the_analysis():
    prior = [make_result("x", 0.1, density=1e8, candidate="cand_other")]
    d = decision(
        run({"result": make_result("r", 0.9), "previous_results": prior, "hypothesis": DENSITY_NEG})
    )
    assert d["hypothesis_status"] == "inconclusive" and d["observed"]["n_prior_results_used"] == 0


def _all_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _all_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _all_strings(v)
