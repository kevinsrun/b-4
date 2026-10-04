import copy
import json
import unittest

from bacteriocin_lab.agents.planner import TOOL_SPEC, run_agent  # noqa: E402
from bacteriocin_lab.agents.planner import model as M  # noqa: E402


def cand(cid, mech, win, conf=0.6, charge=3.0):
    return {"candidate_id": cid, "name": cid, "confidence": conf,
            "features": {"mechanism": mech, "net_charge_at_target_ph": charge,
                         "known_targets": ["Listeria monocytogenes"], "stability": {"ph_activity_window": win}}}


HYPS = [{"hypothesis_id": "H_ph", "template": "ph_window", "prior_plausibility": 0.6},
        {"hypothesis_id": "H_inoc", "template": "inoculum_effect", "prior_plausibility": 0.6}]
CANDS = [cand("B17", "receptor_pore", [6.0, 8.0]), cand("B42", "intracellular_target", [3.0, 8.0], conf=0.55)]
BASE = dict(ph=6.75, target_cell_density=1e6, bacteriocin_concentration=1.0)
HIGH = dict(BASE, target_cell_density=1e8)


def req(prev=(), **over):
    r = {"research_objective": {"target": {"species": "Listeria monocytogenes", "strain": "ATCC 19115"},
                                "desired_behavior": {"ph_range": [6.0, 7.5]}},
         "candidates": copy.deepcopy(CANDS), "hypotheses": copy.deepcopy(HYPS),
         "previous_experiments": list(prev), "budget": {"remaining_experiments": 20, "compute_budget": None}}
    r.update(over)
    return r


def res(eid, cid, y, cond, unc=None, etype="simulation-derived"):
    m = {"predicted_inhibition_fraction": y}
    if unc is not None:
        m["uncertainty"] = unc
    return {"experiment_id": eid, "result_id": "r_" + eid, "candidate_id": cid, "conditions": cond,
            "measurement": m, "evidence_type": etype}


def posterior(out):
    return {h["hypothesis_id"]: h["posterior"] for h in out["artifacts"]["hypothesis_posterior"]}


class CriticalAdaptivityTest(unittest.TestCase):
    """Result A -> experiment X next; Result B -> experiment Y next."""

    baseline = res("e0", "B17", 0.80, BASE)

    def test_result_a_vs_b_changes_next_experiment(self):
        # Same experiment just ran (B17 at 1e8 target cells); only the observed outcome differs.
        a = run_agent(req([self.baseline, res("e1", "B17", 0.78, HIGH)]))   # no inoculum effect
        b = run_agent(req([self.baseline, res("e1", "B17", 0.15, HIGH)]))   # strong inoculum effect

        # A: inoculum hypothesis is refuted, pH-window vs null is the open question -> test pH on B17.
        self.assertEqual(a["candidate_id"], "B17")
        self.assertEqual([c["variable"] for c in a["variables_changed"]], ["ph"])
        self.assertLess(posterior(a)["H_inoc"], 0.1)
        self.assertEqual(a["hypothesis_id"], "H_ph")

        # B: inoculum effect is established and pH hypothesis is dead -> no more pH test on B17;
        # planner moves to the untested candidate to widen coverage.
        self.assertGreater(posterior(b)["H_inoc"], 0.85)
        self.assertEqual(b["candidate_id"], "B42")
        self.assertEqual(b["variables_changed"], [])

        self.assertNotEqual(a["experiment_spec"]["candidate_id"], b["experiment_spec"]["candidate_id"])
        self.assertNotEqual(a["experiment_spec"]["conditions"], b["experiment_spec"]["conditions"])

    def test_result_changes_hypothesis_posterior_direction(self):
        a = posterior(run_agent(req([self.baseline, res("e1", "B17", 0.78, HIGH)])))
        b = posterior(run_agent(req([self.baseline, res("e1", "B17", 0.15, HIGH)])))
        self.assertGreater(a["H_ph"], b["H_ph"])
        self.assertGreater(b["H_inoc"], a["H_inoc"])


class PlannerBehaviourTests(unittest.TestCase):
    def test_output_contract(self):
        out = run_agent(req())
        for k in ("experiment_id", "hypothesis_id", "candidate_id", "experiment_spec", "variables_changed",
                  "variables_held_constant", "expected_information_gain", "predicted_possible_outcomes",
                  "why_this_experiment", "confidence", "recommended_next_action", "evidence", "uncertainties",
                  "artifacts", "warnings", "agent", "decision"):
            self.assertIn(k, out)
        spec = out["experiment_spec"]
        self.assertEqual(spec["conditions"]["assay_domain"], "simulated_in_vitro")
        self.assertEqual(spec["target"]["species"], "Listeria monocytogenes")
        self.assertEqual(spec["experiment_id"], out["experiment_id"])
        self.assertEqual(out["experiment_spec_flat"]["ph"], spec["conditions"]["ph"])
        self.assertEqual(out["recommended_next_action"]["agent"], "simulation_runner")
        self.assertEqual(out["decision"]["evidence_type_of_expected_result"], "simulation-derived")
        self.assertGreaterEqual(out["expected_information_gain"], 0.0)
        self.assertTrue(out["predicted_possible_outcomes"])
        json.dumps(out)

    def test_one_variable_at_a_time(self):
        out = run_agent(req([res("e0", "B17", 0.8, BASE), res("e0b", "B42", 0.8, BASE)]))
        self.assertLessEqual(len(out["variables_changed"]), 1)
        spec = out["experiment_spec"]["conditions"]
        for c in out["variables_changed"]:
            self.assertEqual(spec[c["variable"]], c["to"])
        for h in out["variables_held_constant"]:
            self.assertEqual(spec[h["variable"]], h["value"])

    def test_deterministic(self):
        a, b = run_agent(req()), run_agent(copy.deepcopy(req()))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_stable_across_unrelated_input_order(self):
        r1 = req()
        r2 = req(candidates=list(reversed(copy.deepcopy(CANDS))), hypotheses=list(reversed(copy.deepcopy(HYPS))))
        a, b = run_agent(r1), run_agent(r2)
        self.assertEqual(a["candidate_id"], b["candidate_id"])
        self.assertEqual(a["experiment_spec"]["conditions"], b["experiment_spec"]["conditions"])

    def test_no_exact_replicates_by_default(self):
        prev = [res("e0", "B17", 0.8, BASE)]
        for _ in range(1):
            out = run_agent(req(prev))
            same = (out["candidate_id"] == "B17" and not out["variables_changed"])
            self.assertFalse(same, "proposed an exact replicate of a completed experiment")
        out2 = run_agent(req(prev, constraints={"allow_replicates": True}))
        self.assertEqual(out2["decision"]["status"], "propose_experiment")

    def test_hypothesis_specific_prediction_in_explanation(self):
        out = run_agent(req([res("e0", "B17", 0.8, BASE)]))
        self.assertIn(out["hypothesis_id"], out["why_this_experiment"])
        self.assertGreater(out["expected_information_gain"], 0.1)
        self.assertTrue(out["variables_changed"])

    def test_discriminating_experiment_beats_redundant_one(self):
        # Two candidates with identical windows except one; a pH below B17's window is informative for B17 only.
        out = run_agent(req([res("e0", "B17", 0.8, BASE), res("e0b", "B42", 0.8, BASE),
                             res("e1", "B17", 0.78, HIGH), res("e1b", "B42", 0.78, HIGH)]))
        self.assertEqual(out["candidate_id"], "B17")
        self.assertEqual(out["variables_changed"][0]["variable"], "ph")
        self.assertLess(out["variables_changed"][0]["to"], 6.0)

    def test_budget_exhausted(self):
        out = run_agent(req(budget={"remaining_experiments": 0}))
        self.assertEqual(out["decision"]["status"], "stop_budget_exhausted")
        self.assertIsNone(out["experiment_spec"])

    def test_compute_budget_limits_choice(self):
        out = run_agent(req(budget={"remaining_experiments": 5, "compute_budget": 0.5}))
        self.assertEqual(out["decision"]["status"], "stop_budget_exhausted")
        cheap = run_agent(req(budget={"remaining_experiments": 5, "compute_budget": 1.2}))
        self.assertEqual(cheap["decision"]["status"], "propose_experiment")
        self.assertLessEqual(cheap["artifacts"]["budget_after"]["estimated_cost_of_proposal"], 1.2)

    def test_cost_penalises_expensive_assays(self):
        from bacteriocin_lab.agents.planner.planner import estimate_cost
        self.assertGreater(estimate_cost({"assay_domain": "simulated_physiological", "incubation_time": 24}),
                           estimate_cost({"assay_domain": "simulated_in_vitro", "incubation_time": 24}))
        self.assertGreater(estimate_cost({"incubation_time": 96}), estimate_cost({"incubation_time": 24}))
        out = run_agent(req(constraints={"allow_physiological": True}))
        self.assertEqual(out["experiment_spec"]["conditions"]["assay_domain"], "simulated_in_vitro")

    def test_batch_is_diverse(self):
        out = run_agent(req(constraints={"batch_size": 3}))
        self.assertEqual(len(out["batch"]), 3)
        keys = {(b["candidate_id"], json.dumps(b["experiment_spec"]["conditions"], sort_keys=True)) for b in out["batch"]}
        self.assertEqual(len(keys), 3)
        self.assertEqual(out["batch"][0]["experiment_id"], out["experiment_id"])
        self.assertEqual(len({b["experiment_id"] for b in out["batch"]}), 3)
        capped = run_agent(req(constraints={"batch_size": 3}, budget={"remaining_experiments": 2}))
        self.assertEqual(len(capped["batch"]), 2)

    def test_converges_when_nothing_to_learn(self):
        cands = [cand("B17", "x", [6.0, 8.0])]
        hyps = [{"hypothesis_id": "H_null", "template": "null", "prior_plausibility": 0.5}]
        # Densely covered space + only null-equivalent hypotheses -> nothing separable.
        prev = []
        i = 0
        for ph in (3.0, 4.5, 5.5, 6.5, 6.75, 7.5, 8.5, 10.0):
            for d in (1e2, 1e4, 1e6, 1e8, 1e10):
                for conc in (0.01, 0.1, 1.0, 10.0, 100.0):
                    i += 1
                    prev.append(res(f"e{i}", "B17", 0.8, dict(ph=ph, target_cell_density=d, bacteriocin_concentration=conc)))
        out = run_agent(req(prev, candidates=cands, hypotheses=hyps, constraints={"allow_replicates": False}))
        self.assertEqual(out["decision"]["status"], "converged")
        self.assertIsNone(out["experiment_id"])

    def test_wet_lab_evidence_outweighs_simulation(self):
        # Same inhibition value, but wet-lab measurement is trusted more -> posterior moves further.
        sim = run_agent(req([res("e0", "B17", 0.8, BASE), res("e1", "B17", 0.15, HIGH, unc=0.05)]))
        wet = run_agent(req([res("e0", "B17", 0.8, BASE, etype="wet-lab-derived"),
                             res("e1", "B17", 0.15, HIGH, unc=0.05, etype="wet-lab-derived")]))
        self.assertGreaterEqual(posterior(wet)["H_inoc"], posterior(sim)["H_inoc"])

    def test_rejected_hypotheses_excluded_and_unknown_template_warns(self):
        hy = copy.deepcopy(HYPS) + [{"hypothesis_id": "H_x", "template": "mystery", "prior_plausibility": 0.5},
                                    {"hypothesis_id": "H_r", "template": "ph_window", "status": "rejected"}]
        out = run_agent(req(hypotheses=hy))
        ids = [h["hypothesis_id"] for h in out["artifacts"]["hypothesis_posterior"]]
        self.assertNotIn("H_r", ids)
        self.assertTrue(any("H_x" in w for w in out["warnings"]))

    def test_medium_and_temperature_when_controllable(self):
        out = run_agent(req([res("e0", "B17", 0.8, BASE)],
                            constraints={"controllable_variables": ["medium", "temperature_c"], "media": ["BHI", "TSB"]}))
        self.assertEqual(out["decision"]["status"], "propose_experiment")
        for c in out["variables_changed"]:
            self.assertIn(c["variable"], ("medium", "temperature_c"))

    def test_validation_errors_and_warnings(self):
        for bad in (None, [], {}, req(budget={"remaining_experiments": -1}),
                    req(candidates=[{"name": "no id"}]),
                    req(constraints={"batch_size": 0}),
                    req(constraints={"controllable_variables": ["nope"]}),
                    req(hypotheses=[{"template": "ph_window"}]),
                    req(research_objective={"target": {}})):
            out = run_agent(bad)
            self.assertEqual(out["decision"]["status"], "error", bad)
            self.assertTrue(out["warnings"])
        out = run_agent(req([{"candidate_id": "ghost", "measurement": {"predicted_inhibition_fraction": 0.5}},
                             res("bad", "B17", 1.7, BASE)]))
        self.assertEqual(out["decision"]["status"], "propose_experiment")
        self.assertEqual(sum("ignored" in w for w in out["warnings"]), 2)

    def test_no_candidates(self):
        out = run_agent(req(candidates=[]))
        self.assertEqual(out["decision"]["status"], "no_candidates")
        self.assertEqual(out["recommended_next_action"]["agent"], "candidate_generation_design")

    def test_survival_fraction_accepted(self):
        e = {"experiment_id": "e0", "candidate_id": "B17", "conditions": BASE,
             "measurement": {"predicted_survival_fraction": 0.2}}
        out = run_agent(req([e]))
        self.assertEqual(out["artifacts"]["candidate_experiment_counts"]["B17"], 1)

    def test_tool_spec(self):
        self.assertEqual(TOOL_SPEC["name"], "experiment_planner")


class ModelTests(unittest.TestCase):
    def test_mutual_information_bounds(self):
        mi, _ = M.mutual_information([0.5, 0.5], [0.1, 0.9], 0.05)
        self.assertAlmostEqual(mi, 1.0, places=2)
        mi, _ = M.mutual_information([0.5, 0.5], [0.5, 0.5], 0.1)
        self.assertAlmostEqual(mi, 0.0, places=6)
        mi, _ = M.mutual_information([0.99, 0.01], [0.1, 0.9], 0.05)
        self.assertLess(mi, 0.1)

    def test_coverage_shrinks_uncertainty(self):
        base = dict(BASE, producer_cell_density=None, temperature_c=37.0, incubation_time=24.0, medium=None,
                    assay_domain="simulated_in_vitro")
        obs = [{"conditions": base, "uncertainty": None, "evidence_type": "simulation-derived"}]
        near = M.model_uncertainty(dict(base, ph=6.9), obs)
        far = M.model_uncertainty(dict(base, ph=4.0), obs)
        self.assertLess(near, far)
        self.assertLess(far, 1.0 + 1e-9)
        self.assertEqual(M.model_uncertainty(base, []), 1.0)


class NestedMeasurementConditionsTest(unittest.TestCase):
    """``previous_experiments`` may arrive in the shared-contract shape, with conditions
    nested as ``{"value": ..., "unit": ...}`` rather than as bare numbers."""

    def test_nested_conditions_do_not_crash_and_match_flat_equivalent(self):
        nested = {"ph": 6.75,
                  "target_cell_density": {"value": 1e8, "unit": "cfu_per_ml"},
                  "bacteriocin_concentration": {"value": 1000.0, "unit": "nM"}}
        out_nested = run_agent(req([res("e0", "B17", 0.80, BASE), res("e1", "B17", 0.78, nested)]))
        out_flat = run_agent(req([res("e0", "B17", 0.80, BASE), res("e1", "B17", 0.78, HIGH)]))
        self.assertEqual(out_nested["decision"]["status"], "propose_experiment")
        self.assertFalse(any("not convertible" in w for w in out_nested["warnings"]))
        # 1000 nM == 1.0 uM and the density is already CFU/mL, so this is HIGH restated.
        self.assertEqual(out_nested["candidate_id"], out_flat["candidate_id"])
        self.assertEqual(posterior(out_nested), posterior(out_flat))

    def test_log10_density_is_converted(self):
        nested = dict(BASE, target_cell_density={"value": 8.0, "unit": "log10_cfu_per_ml"})
        out = run_agent(req([res("e0", "B17", 0.80, BASE), res("e1", "B17", 0.78, nested)]))
        out_flat = run_agent(req([res("e0", "B17", 0.80, BASE), res("e1", "B17", 0.78, HIGH)]))
        self.assertEqual(posterior(out), posterior(out_flat))

    def test_unconvertible_unit_is_reported_not_silently_mixed(self):
        nested = dict(BASE, bacteriocin_concentration={"value": 40.0, "unit": "IU/mL"})
        out = run_agent(req([res("e1", "B17", 0.78, nested)]))
        self.assertTrue(any("not convertible" in w for w in out["warnings"]))
        # Dropped, so the reference value is assumed in its place.
        self.assertTrue(any("bacteriocin_concentration" in w and "reference" in w for w in out["warnings"]))


class IntegrationWithCandidateAgentTest(unittest.TestCase):
    def test_consumes_candidate_agent_output(self):
        from bacteriocin_lab.agents.candidate import generate_candidates

        gen = generate_candidates({"target": {"organism": "Listeria monocytogenes", "strain": "ATCC 19115"},
                                   "desired_behavior": {"ph_range": [6.0, 7.5], "target_cell_density": 1e8,
                                                        "temperature_c": 37},
                                   "constraints": {"max_candidates": 4}})
        generated = gen["decision"]
        out = run_agent({"research_objective": {"target": {"species": "Listeria monocytogenes", "strain": "ATCC 19115"},
                                                "desired_behavior": {"ph_range": [6.0, 7.5], "target_cell_density": 1e8}},
                        "candidates": generated["candidates"], "hypotheses": [
                            h for c in generated["candidates"] for h in c.get("hypotheses", [])
                        ],
                         "previous_experiments": [], "budget": {"remaining_experiments": 20}})
        self.assertEqual(out["decision"]["status"], "propose_experiment")
        self.assertIn(out["candidate_id"], [c["candidate_id"] for c in generated["candidates"]])
        self.assertIn(out["hypothesis_id"], [h["hypothesis_id"] for c in generated["candidates"] for h in c.get("hypotheses", [])] + [M.NULL_ID])
        self.assertFalse(any("no prediction model" in w for w in out["warnings"]))


if __name__ == "__main__":
    unittest.main()
