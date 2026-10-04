"""Closed loop: (candidate_agent, if installed) -> experiment_planner -> toy simulator -> planner -> ...

Run: python -m bacteriocin_lab.evaluation.examples.planner.run_planning_loop [n_steps]
"""
import json
import os
import sys
from . import toy_simulator

import bacteriocin_lab.agents.planner
from bacteriocin_lab.agents.candidate import generate_candidates

HERE = os.path.dirname(os.path.abspath(__file__))

N = int(sys.argv[1]) if len(sys.argv) > 1 else 10

objective = {"target": {"species": "Listeria monocytogenes", "strain": "ATCC 19115"},
             "desired_behavior": {"ph_range": [6.0, 7.5], "target_cell_density": 1e8, "temperature_c": 37}}
try:
    gen = generate_candidates({"target": {"organism": "Listeria monocytogenes", "strain": "ATCC 19115"},
                               "desired_behavior": objective["desired_behavior"],
                               "constraints": {"max_candidates": 3}})
    generated = gen.get("decision", gen)
    candidates = generated.get("candidates", [])
    hypotheses = [h for candidate in candidates for h in candidate.get("hypotheses", [])]
except (KeyError, TypeError, ValueError):
    def _c(cid, name, mech, win, conf):
        return {"candidate_id": cid, "name": name, "confidence": conf,
                "features": {"mechanism": mech, "net_charge_at_target_ph": 3.0,
                             "known_targets": ["Listeria monocytogenes"], "stability": {"ph_activity_window": win}}}
    candidates = [_c("cand_nisin", "Nisin A", "lipid_II_binding_pore_formation", [3.0, 7.0], 0.57),
                  _c("cand_pediocin", "Pediocin PA-1", "mannose_PTS_receptor_pore_formation", [3.0, 8.0], 0.60),
                  _c("cand_sakacin", "Sakacin P", "mannose_PTS_receptor_pore_formation", [4.0, 8.0], 0.60)]
    hypotheses = [{"hypothesis_id": "hyp_ph", "template": "ph_window", "prior_plausibility": 0.7},
                  {"hypothesis_id": "hyp_inoc", "template": "inoculum_effect", "prior_plausibility": 0.55}]
names = {c["candidate_id"]: c["name"] for c in candidates}
print("Candidates:", ", ".join(names.values()))

experiments, remaining = [], N
log = []
while True:
    out = bacteriocin_lab.agents.planner.run_agent({
        "research_objective": objective, "candidates": candidates, "hypotheses": hypotheses,
        "previous_experiments": experiments, "budget": {"remaining_experiments": remaining, "compute_budget": None}})
    status = out["decision"]["status"]
    if status != "propose_experiment":
        print(f"\nPlanner stopped: {status} - {out['decision'].get('reason')}")
        break
    spec = out["experiment_spec"]
    res = toy_simulator.run(spec, names[out["candidate_id"]])
    experiments.append(res)
    remaining -= 1
    ch = out["variables_changed"]
    what = f"{ch[0]['variable']}={ch[0]['to']:g}" if ch else "reference"
    y = res["measurement"]["predicted_inhibition_fraction"]
    post = {h["template"]: h["posterior"] for h in out["artifacts"]["hypothesis_posterior"]}
    print(f"\n[{len(experiments)}] {names[out['candidate_id']]:14s} {what:28s} IG={out['expected_information_gain']:.2f} bits"
          f"  -> inhibition {y:.2f}")
    print("    why:", out["why_this_experiment"][:230])
    print("    posterior:", {k: round(v, 2) for k, v in post.items()})
    log.append({"plan": out, "result": res})

with open(os.path.join(HERE, "planning_loop_log.json"), "w") as f:
    json.dump(log, f, indent=1, sort_keys=True)
