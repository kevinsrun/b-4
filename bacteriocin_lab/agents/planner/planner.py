"""Experiment Planner / Active Learning Agent.

experiment_score = uncertainty x relevance x (discrimination + 0.15*uncertainty [+ baseline bonus]) / cost

  uncertainty     1 - kernel coverage of the candidate's explored condition space
  relevance       candidate priority x closeness of the conditions to the research objective
  discrimination  mutual information (bits) between "which hypothesis is true" and the
                  outcome, normalised by log2(#hypotheses); hypothesis posteriors are
                  re-computed from previous experiments, so results steer the next choice
  cost            relative simulation cost (domain, incubation time, producer cells, ions)

Proposals are one-variable-at-a-time perturbations of reference conditions, so each
experiment has an interpretable ``variables_changed`` / ``variables_held_constant``.
Stateless and deterministic: everything is reconstructed from the request.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Dict, List, Optional, Tuple

from . import model as M
from .schema import (
    AGENT_NAME,
    DEFAULT_CONTROLLABLE,
    MODEL_VERSION,
    NUMERIC_VARS,
    SCHEMA_VERSION,
    ValidationError,
    build_experiment_spec,
    canonical_json,
    flat_spec,
    normalize_request,
    stable_hash,
)

EXPLORE_WEIGHT = 0.15
BASELINE_BONUS = 0.05
OUTCOME_MERGE = 0.08


def estimate_cost(cond: Dict[str, Any]) -> float:
    c = 3.0 if cond.get("assay_domain") == "simulated_physiological" else 1.0
    c *= math.sqrt(max(cond.get("incubation_time") or 24.0, 1.0) / 24.0)
    if cond.get("producer_cell_density"):
        c += 0.5
    if cond.get("ionic_conditions"):
        c += 0.25
    return round(c, 4)


def _fmt(v: Any) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)


def condition_relevance(cond: Dict[str, Any], desired: Dict[str, Any]) -> float:
    r = 1.0
    ph = desired.get("ph_range")
    if ph:
        dist = max(ph[0] - cond["ph"], cond["ph"] - ph[1], 0.0)
        r *= max(0.35, math.exp(-dist / 3.0))
    d = desired.get("target_cell_density")
    if d:
        r *= max(0.4, math.exp(-abs(math.log10(cond["target_cell_density"]) - math.log10(d)) / 3.0))
    t = desired.get("temperature_c")
    if t is not None and cond.get("temperature_c") is not None:
        r *= max(0.4, math.exp(-abs(cond["temperature_c"] - t) / 10.0))
    return max(0.25, r)


class ExperimentPlanner:
    name = AGENT_NAME

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        req = normalize_request(payload)
        warnings = list(req["warnings"])
        cons, budget, target = req["constraints"], req["budget"], req["target"]
        cands, ref = req["candidates"], req["reference"]
        nf = cons["noise_floor"]

        hyps = M.build_hyps(req["hypotheses"], warnings)
        obs_by_c = M.group_obs(req["experiments"])
        post = M.posterior(hyps, cands, obs_by_c, target, nf)

        remaining = budget["remaining_experiments"]
        comp_left = budget["compute_budget"]
        digest = hashlib.sha256(canonical_json({k: v for k, v in req.items() if k != "warnings"}).encode()).hexdigest()
        base_out = {"agent": AGENT_NAME, "schema_version": SCHEMA_VERSION}

        if not cands:
            return self._stop(base_out, "no_candidates", "No candidates supplied.", post, hyps, req, warnings, digest,
                              agent="candidate_generation_design", why="Request candidates before planning experiments.")
        if remaining is not None and remaining <= 0:
            return self._stop(base_out, "stop_budget_exhausted", "No experiments remain in the budget.", post, hyps,
                              req, warnings, digest)

        points = self._enumerate(req, hyps, post, obs_by_c)
        if comp_left is not None:
            points = [p for p in points if p["cost"] <= comp_left]
        if not points:
            return self._stop(base_out, "stop_budget_exhausted", "No candidate experiment is affordable within the "
                              "compute budget.", post, hyps, req, warnings, digest)

        n_pick = min(cons["batch_size"], remaining if remaining is not None else cons["batch_size"])
        picks: List[Dict[str, Any]] = []
        virtual: Dict[str, List[Dict[str, Any]]] = {}
        spent = 0.0
        first_ranked: List[Dict[str, Any]] = []
        for step in range(n_pick):
            for p in points:
                p["u"] = M.model_uncertainty(p["conditions"], obs_by_c.get(p["candidate_id"], []),
                                             virtual.get(p["candidate_id"], []))
                bonus = BASELINE_BONUS if (p["is_baseline"] and p["n_obs"] == 0) else 0.0
                p["score"] = p["u"] * p["relevance"] * (p["d_norm"] + EXPLORE_WEIGHT * p["u"] + bonus) / p["cost"]
            ranked = sorted(points, key=lambda p: (-p["score"], p["candidate_id"], p["variable"] or "", repr(p["value"])))
            if step == 0:
                first_ranked = ranked
            best = next((p for p in ranked if comp_left is None or spent + p["cost"] <= comp_left), None)
            if best is None or best["score"] <= 0:
                break
            if step == 0 and best["mi"] < cons["min_expected_information_gain"] and best["u"] < 0.35:
                return self._stop(base_out, "converged", "Hypotheses are not separable by any remaining experiment and "
                                  "explored conditions are well covered.", post, hyps, req, warnings, digest)
            picks.append(best)
            spent += best["cost"]
            virtual.setdefault(best["candidate_id"], []).append(best["conditions"])
            points = [p for p in points if p is not best]

        proposals = [self._proposal(p, req, hyps, post, len(req["experiments"]) + i, set(), nf)
                     for i, p in enumerate(picks)]
        used = {e["experiment_id"] for e in req["experiments"] if e.get("experiment_id")}
        for pr in proposals:  # avoid colliding with an existing ID
            while pr["experiment_id"] in used:
                pr["experiment_id"] += "x"
                pr["experiment_spec"]["experiment_id"] = pr["experiment_id"]
            used.add(pr["experiment_id"])
        head = proposals[0]
        head_p = picks[0]

        out = dict(base_out)
        out.update({
            "decision": {"status": "propose_experiment", "n_experiments": len(proposals),
                         "evidence_type_of_expected_result": "simulation-derived"},
            **{k: head[k] for k in ("experiment_id", "hypothesis_id", "candidate_id", "experiment_spec",
                                    "experiment_spec_flat", "variables_changed", "variables_held_constant",
                                    "expected_information_gain", "predicted_possible_outcomes", "why_this_experiment")},
            "confidence": head["confidence"],
            "batch": proposals,
            "evidence": self._evidence(req),
            "uncertainties": self._uncertainties(req, hyps, post),
            "artifacts": self._artifacts(first_ranked, post, hyps, req, picks, remaining, comp_left, digest),
            "warnings": warnings,
            "recommended_next_action": {
                "agent": "simulation_runner",
                "reason": "Run the proposed experiment_spec(s) via run_experiment and return ExperimentResult objects; "
                          "re-invoke the planner with them appended to previous_experiments.",
                "inputs": {"experiment_specs": [p["experiment_spec"] for p in proposals]}},
        })
        return out

    # ---------------------------------------------------------------- points
    def _levels(self, var: str, cand: Dict[str, Any], req: Dict[str, Any]) -> List[Any]:
        ref, desired, cons = req["reference"], req["desired"], req["constraints"]
        lo, hi = cons["bounds"][var]
        lv: List[Any] = []
        if var == "ph":
            lv = [4.5, 5.5, 6.5, 7.5, 8.5] + list(desired.get("ph_range") or [])
            w = (cand.get("features") or {}).get("stability", {}).get("ph_activity_window")
            if w:
                lv += [w[0] - 1.0, w[1] + 1.0]
        elif var == "target_cell_density":
            lv = [1e4, 1e6, 1e8] + ([desired["target_cell_density"]] if desired.get("target_cell_density") else [])
        elif var == "bacteriocin_concentration":
            lv = [ref["bacteriocin_concentration"] * f for f in (0.1, 0.3, 3.0, 10.0)]
        elif var == "temperature_c":
            lv = [25.0, 30.0, 37.0, 42.0]
        elif var == "incubation_time":
            lv = [6.0, 12.0, 24.0, 48.0]
        for h in req["hypotheses"]:
            st = h.get("suggested_test") or {}
            if st.get("vary") == var:
                lv += [x for x in st.get("levels") or [] if isinstance(x, (int, float)) and not isinstance(x, bool)]
        out = sorted({round(float(x), 1) if var == "ph" else float(f"{x:.3g}") for x in lv if lo <= x <= hi})
        return [x for x in out if abs(x - ref[var]) > 1e-9 * max(1.0, abs(x))]

    def _enumerate(self, req: Dict[str, Any], hyps: List[M.Hyp], post: Dict[str, float],
                   obs_by_c: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        cons, ref, target, desired = req["constraints"], req["reference"], req["target"], req["desired"]
        nf = cons["noise_floor"]
        confs = {cid: c.get("confidence") for cid, c in req["candidates"].items()}
        maxc = max([v for v in confs.values() if isinstance(v, (int, float))] or [1.0]) or 1.0

        def cand_rel(cid: str) -> float:
            v = confs[cid]
            return 0.4 + 0.6 * (v / maxc) if isinstance(v, (int, float)) else 0.7

        ordered = sorted(req["candidates"], key=lambda cid: (-cand_rel(cid), cid))[: cons["max_candidates_considered"]]
        weights = [post[h.id] for h in hyps]
        sigma = math.sqrt(nf ** 2 + M.MODEL_ERROR_SD ** 2)
        k_norm = math.log2(max(len(hyps), 2))
        pts: List[Dict[str, Any]] = []
        for cid in ordered:
            cand = req["candidates"][cid]
            obs = obs_by_c.get(cid, [])
            amps = [M.fitted_amplitude(h, cand, obs, target, nf) for h in hyps]
            variants: List[Tuple[Optional[str], Any]] = [(None, None)]
            for var in cons["controllable_variables"]:
                if var == "medium":
                    variants += [("medium", m) for m in cons["media"] if m != ref.get("medium")]
                else:
                    variants += [(var, v) for v in self._levels(var, cand, req)]
            domains = ["simulated_in_vitro"] + (["simulated_physiological"] if cons["allow_physiological"] else [])
            for dom in domains[1:]:
                variants.append(("assay_domain", dom))
            for var, val in variants:
                cond = dict(ref)
                if var:
                    cond[var] = val
                if (not cons["allow_replicates"]
                        and any(M.distance2(cond, o["conditions"]) < 1e-12 for o in obs)):
                    continue
                mus = [M.predict(h, cand, cond, a, target) for h, a in zip(hyps, amps)]
                mi, contribs = M.mutual_information(weights, mus, sigma)
                pts.append({"candidate_id": cid, "variable": var, "value": val, "conditions": cond,
                            "mus": mus, "contribs": contribs, "mi": mi, "d_norm": min(1.0, mi / k_norm),
                            "relevance": cand_rel(cid) * M.clamp(condition_relevance(cond, desired), 0.0, 1.0),
                            "cost": estimate_cost(cond), "is_baseline": var is None, "n_obs": len(obs)})
        return pts

    # ------------------------------------------------------------- proposals
    def _proposal(self, p: Dict[str, Any], req: Dict[str, Any], hyps: List[M.Hyp], post: Dict[str, float],
                  n_prev: int, _unused: set, nf: float) -> Dict[str, Any]:
        ref, target = req["reference"], req["target"]
        cand = req["candidates"][p["candidate_id"]]
        cname = cand.get("name") or p["candidate_id"]
        cond = p["conditions"]
        weights = [post[h.id] for h in hyps]
        real = [i for i, h in enumerate(hyps) if h.id != M.NULL_ID]

        # Primary hypothesis: largest contribution to information gain among non-null hypotheses.
        order = sorted(real, key=lambda i: (-p["contribs"][i], -weights[i], hyps[i].id))
        pi = order[0] if order and p["contribs"][order[0]] > 1e-6 else None
        if pi is None:
            sens = [i for i in real if M.SENSITIVE_VARIABLE.get(hyps[i].template) == p["variable"]]
            pool = sens or real
            pi = max(pool, key=lambda i: (weights[i], hyps[i].id)) if pool else hyps.index(next(h for h in hyps if h.id == M.NULL_ID))
        primary = hyps[pi]
        rivals = sorted((i for i in range(len(hyps)) if i != pi and weights[i] > 0.01),
                        key=lambda i: -abs(p["mus"][i] - p["mus"][pi]) * weights[i])

        eid = "exp_" + stable_hash(p["candidate_id"], canonical_json(cond), n_prev, target["species"], target.get("strain"))
        spec = build_experiment_spec(eid, primary.id, p["candidate_id"], target, cond)
        changed = [] if p["variable"] is None else [{"variable": p["variable"], "from": ref.get(p["variable"]),
                                                      "to": p["value"]}]
        held = [{"variable": k, "value": cond[k]} for k in
                ("bacteriocin_concentration", "target_cell_density", "ph", "temperature_c", "incubation_time", "medium")
                if k != p["variable"] and cond.get(k) is not None]

        # Outcome bands: hypotheses predicting similar inhibition are merged.
        sigma = math.sqrt(nf ** 2 + M.MODEL_ERROR_SD ** 2)
        idx = sorted(range(len(hyps)), key=lambda i: p["mus"][i])
        bands: List[List[int]] = []
        for i in idx:
            if bands and p["mus"][i] - p["mus"][bands[-1][-1]] < OUTCOME_MERGE:
                bands[-1].append(i)
            else:
                bands.append([i])
        outcomes = []
        for b in bands:
            mu = sum(p["mus"][i] for i in b) / len(b)
            after = M.posterior_after(weights, p["mus"], sigma, mu)
            top = sorted(range(len(hyps)), key=lambda i: -after[i])[:3]
            outcomes.append({
                "predicted_inhibition_fraction": round(mu, 3),
                "consistent_hypothesis_ids": [hyps[i].id for i in b],
                "consistent_templates": [hyps[i].template for i in b],
                "posterior_if_observed": {hyps[i].id: round(after[i], 3) for i in top},
                "interpretation": ("Would favour " + ", ".join(hyps[i].template for i in b)
                                   + f" (current combined posterior {sum(weights[i] for i in b):.2f} -> "
                                     f"{sum(after[i] for i in b):.2f}); simulated evidence, not validation.")})

        why = self._why(p, req, hyps, post, primary, rivals, cname, ref)
        d = min(1.0, p["mi"])
        conf = M.clamp(0.3 + 0.4 * d + 0.2 * p["u"] - (0.15 if not primary.has_model else 0.0), 0.05, 0.9)
        return {
            "experiment_id": eid, "hypothesis_id": primary.id, "candidate_id": p["candidate_id"],
            "competing_hypothesis_ids": [hyps[i].id for i in rivals[:3]],
            "experiment_spec": spec, "experiment_spec_flat": flat_spec(cond, target),
            "variables_changed": changed, "variables_held_constant": held,
            "expected_information_gain": round(p["mi"], 4), "expected_information_gain_unit": "bits",
            "predicted_possible_outcomes": outcomes, "why_this_experiment": why, "confidence": round(conf, 3),
            "score": round(p["score"], 5), "estimated_cost": p["cost"],
        }

    def _why(self, p, req, hyps, post, primary, rivals, cname, ref) -> str:
        pi = hyps.index(primary)
        if p["variable"] is None:
            where = f"at the reference conditions"
        else:
            where = f"with {p['variable']} changed from {_fmt(ref.get(p['variable']))} to {_fmt(p['value'])}"
        if p["variable"] is None and p["n_obs"] == 0 and p["mi"] < 0.02:
            return (f"{cname} has no experiments yet. Run it {where} to anchor its activity level before testing "
                    f"hypotheses against it (uncertainty {p['u']:.2f}).")
        if p["mi"] < 0.02:
            return (f"No active hypotheses disagree strongly for {cname} {where}; chosen to cover unexplored "
                    f"condition space (model uncertainty {p['u']:.2f}, relevance {p['relevance']:.2f}, cost {p['cost']}).")
        txt = (f"Hypothesis {primary.id} ({primary.template}, posterior {post[primary.id]:.2f}) predicts inhibition "
               f"~{p['mus'][pi]:.2f} for {cname} {where}")
        if rivals:
            r = rivals[0]
            txt += (f", whereas {hyps[r].id} ({hyps[r].template}, posterior {post[hyps[r].id]:.2f}) predicts "
                    f"~{p['mus'][r]:.2f}")
        held = "all other variables" if p["variable"] else "all variables"
        txt += (f". Holding {held} at reference values separates them: expected information gain "
                f"{p['mi']:.2f} bits; model uncertainty {p['u']:.2f}; {p['n_obs']} prior experiment(s) on this "
                f"candidate; relative cost {p['cost']}.")
        return txt

    # --------------------------------------------------------------- outputs
    @staticmethod
    def _evidence(req: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [{"evidence_id": e.get("result_id") or e.get("experiment_id"), "evidence_type": e["evidence_type"],
                 "candidate_id": e["candidate_id"],
                 "used_for": "hypothesis posterior and coverage estimate"} for e in req["experiments"]]

    @staticmethod
    def _uncertainties(req: Dict[str, Any], hyps: List[M.Hyp], post: Dict[str, float]) -> List[str]:
        u = ["Hypothesis prediction models are simple heuristic priors, not mechanistic simulators; information gain is "
             "relative to those models.",
             "Bacteriocin concentration is in unspecified relative units unless constraints.reference_conditions sets it.",
             "Activity ceilings are fitted per hypothesis from sparse data and shrunk toward the candidate's prior confidence."]
        if not req["experiments"]:
            u.append("No previous experiments: hypothesis posteriors equal their priors.")
        if any(not h.has_model for h in hyps):
            u.append("Some hypotheses have no prediction model and were treated as null-like.")
        if max(post.values()) < 0.6:
            u.append("No hypothesis currently dominates the posterior.")
        return u

    @staticmethod
    def _artifacts(ranked, post, hyps, req, picks, remaining, comp_left, digest) -> Dict[str, Any]:
        spent = sum(p["cost"] for p in picks)
        return {
            "model_version": MODEL_VERSION, "input_digest_sha256": digest,
            "scoring_formula": f"uncertainty x relevance x (discrimination + {EXPLORE_WEIGHT}*uncertainty "
                               f"+ baseline_bonus({BASELINE_BONUS}, untested candidate at reference)) / cost",
            "hypothesis_posterior": [{"hypothesis_id": h.id, "template": h.template, "prior": h.prior,
                                      "posterior": round(post[h.id], 4), "has_model": h.has_model} for h in hyps],
            "top_alternatives": [{"candidate_id": p["candidate_id"], "variable": p["variable"], "value": p["value"],
                                  "score": round(p["score"], 5), "information_gain_bits": round(p["mi"], 4),
                                  "uncertainty": round(p["u"], 3), "relevance": round(p["relevance"], 3),
                                  "cost": p["cost"]} for p in ranked[:8]],
            "candidate_experiment_counts": {cid: sum(1 for e in req["experiments"] if e["candidate_id"] == cid)
                                            for cid in req["candidates"]},
            "reference_conditions": req["reference"],
            "budget_after": {"remaining_experiments": None if remaining is None else remaining - len(picks),
                             "compute_budget": None if comp_left is None else round(comp_left - spent, 4),
                             "estimated_cost_of_proposal": round(spent, 4)},
        }

    def _stop(self, base: Dict[str, Any], status: str, reason: str, post, hyps, req, warnings, digest,
              agent: str = "omnigent", why: Optional[str] = None) -> Dict[str, Any]:
        out = dict(base)
        out.update({
            "decision": {"status": status, "reason": reason}, "experiment_id": None, "hypothesis_id": None,
            "candidate_id": None, "experiment_spec": None, "variables_changed": [], "variables_held_constant": [],
            "expected_information_gain": 0.0, "predicted_possible_outcomes": [], "why_this_experiment": reason,
            "confidence": 0.0, "batch": [], "evidence": self._evidence(req), "uncertainties": self._uncertainties(req, hyps, post),
            "artifacts": {"model_version": MODEL_VERSION, "input_digest_sha256": digest,
                          "hypothesis_posterior": [{"hypothesis_id": h.id, "template": h.template, "prior": h.prior,
                                                    "posterior": round(post[h.id], 4)} for h in hyps]},
            "warnings": warnings,
            "recommended_next_action": {"agent": agent, "reason": why or (
                "Stop or re-plan: " + reason + " Review hypothesis_posterior in artifacts for current conclusions.")},
        })
        return out


def run_agent(payload: Any) -> Dict[str, Any]:
    """Tool entry point; returns an error envelope instead of raising on bad input."""
    try:
        return ExperimentPlanner().run(payload)
    except ValidationError as e:
        return {"agent": AGENT_NAME, "schema_version": SCHEMA_VERSION, "decision": {"status": "error", "reason": "invalid input"},
                "experiment_id": None, "hypothesis_id": None, "candidate_id": None, "experiment_spec": None,
                "variables_changed": [], "variables_held_constant": [], "expected_information_gain": 0.0,
                "predicted_possible_outcomes": [], "why_this_experiment": "", "confidence": 0.0, "evidence": [],
                "uncertainties": [], "artifacts": {"model_version": MODEL_VERSION, "errors": e.errors},
                "warnings": e.errors,
                "recommended_next_action": {"agent": "omnigent", "reason": "Input validation failed; correct and retry."}}


TOOL_SPEC = {
    "name": "experiment_planner",
    "description": ("Choose the next computational bacteriocin experiment by expected information gain, hypothesis "
                    "discrimination, uncertainty, relevance and cost. Returns a ready-to-run ExperimentSpec."),
    "input_schema": {
        "type": "object", "required": ["research_objective", "candidates"],
        "properties": {
            "research_objective": {"type": "object", "properties": {
                "target": {"type": "object", "properties": {"species": {"type": "string"}, "strain": {"type": ["string", "null"]}}},
                "desired_behavior": {"type": "object"}}},
            "candidates": {"type": "array", "items": {"type": "object", "required": ["candidate_id"]}},
            "hypotheses": {"type": "array", "items": {"type": "object", "required": ["hypothesis_id"]}},
            "previous_experiments": {"type": "array"},
            "research_state": {"type": "object"},
            "budget": {"type": "object", "properties": {"remaining_experiments": {"type": ["integer", "null"]},
                                                         "compute_budget": {"type": ["number", "null"]}}},
            "constraints": {"type": "object", "properties": {
                "controllable_variables": {"type": "array", "items": {"enum": list(NUMERIC_VARS) + ["medium"]}},
                "bounds": {"type": "object"}, "media": {"type": "array"}, "allow_physiological": {"type": "boolean"},
                "reference_conditions": {"type": "object"}, "batch_size": {"type": "integer"},
                "min_expected_information_gain": {"type": "number"}, "allow_replicates": {"type": "boolean"},
                "noise_floor": {"type": "number"}}}}},
}
