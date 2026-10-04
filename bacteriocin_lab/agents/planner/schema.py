"""Request validation/normalisation and experiment-spec construction."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, List, Optional

from . import adapters

AGENT_NAME = "experiment_planner"
SCHEMA_VERSION = "experiment_planner.v1"
MODEL_VERSION = "experiment_planner-0.1.0+scoring-v1"

CONDITION_KEYS = ("bacteriocin_concentration", "target_cell_density", "producer_cell_density", "ph",
                  "temperature_c", "medium", "ionic_conditions", "incubation_time", "growth_phase", "assay_domain")
# Variables the planner is able to vary one-at-a-time.
NUMERIC_VARS = ("ph", "target_cell_density", "bacteriocin_concentration", "temperature_c", "incubation_time")
DEFAULT_CONTROLLABLE = ["ph", "target_cell_density", "bacteriocin_concentration"]
LOG_VARS = ("target_cell_density", "bacteriocin_concentration", "incubation_time")

DEFAULT_BOUNDS = {"ph": [3.0, 10.0], "target_cell_density": [1e2, 1e10], "bacteriocin_concentration": [1e-3, 1e3],
                  "temperature_c": [4.0, 45.0], "incubation_time": [1.0, 72.0]}

DEFAULT_CONSTRAINTS = {
    "controllable_variables": DEFAULT_CONTROLLABLE,
    "bounds": {},
    "media": [],
    "allow_physiological": False,
    "reference_conditions": {},
    "batch_size": 1,
    "min_expected_information_gain": 0.02,
    "allow_replicates": False,
    "max_candidates_considered": 20,
    "noise_floor": 0.12,
}


class ValidationError(ValueError):
    def __init__(self, errors: List[str]):
        super().__init__("; ".join(errors))
        self.errors = list(errors)


def stable_hash(*parts: Any, n: int = 12) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:n]


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def reference_conditions(desired: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    ph = desired.get("ph_range")
    ref = {
        "bacteriocin_concentration": 1.0,  # relative units; override via constraints.reference_conditions
        "target_cell_density": desired.get("target_cell_density") or 1e6,
        "producer_cell_density": desired.get("producer_cell_density"),
        "ph": round(sum(ph) / 2, 2) if ph else 7.0,
        "temperature_c": desired.get("temperature_c") if desired.get("temperature_c") is not None else 37.0,
        "medium": None, "ionic_conditions": {}, "incubation_time": 24.0, "growth_phase": None,
        "assay_domain": "simulated_in_vitro",
    }
    ref.update({k: v for k, v in overrides.items() if k in CONDITION_KEYS})
    return ref


def normalize_request(payload: Any) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    if not isinstance(payload, dict):
        raise ValidationError(["request must be a JSON object"])

    obj = payload.get("research_objective") or {}
    if not isinstance(obj, dict):
        errors.append("research_objective must be an object")
        obj = {}
    target = obj.get("target") or payload.get("target") or {}
    desired = obj.get("desired_behavior") or payload.get("desired_behavior") or {}
    if not isinstance(target, dict) or not isinstance(desired, dict):
        errors.append("target and desired_behavior must be objects")
        target, desired = {}, {}
    species = target.get("species") or target.get("organism")
    if not isinstance(species, str) or not species.strip():
        errors.append("research_objective.target.species (or organism) is required")
        species = ""
    ph = desired.get("ph_range")
    if ph is not None and (not isinstance(ph, (list, tuple)) or len(ph) != 2 or not all(_num(v) for v in ph)
                           or not 0 <= ph[0] <= ph[1] <= 14):
        errors.append("desired_behavior.ph_range must be [low, high] within 0-14")

    cons = dict(DEFAULT_CONSTRAINTS)
    c_raw = payload.get("constraints") or obj.get("constraints") or {}
    if not isinstance(c_raw, dict):
        errors.append("constraints must be an object")
        c_raw = {}
    unknown = sorted(set(c_raw) - set(DEFAULT_CONSTRAINTS))
    if unknown:
        warnings.append(f"Ignored unknown constraint keys: {unknown}")
    cons.update({k: v for k, v in c_raw.items() if k in DEFAULT_CONSTRAINTS})
    bad_vars = [v for v in cons["controllable_variables"] if v not in NUMERIC_VARS + ("medium",)]
    if not isinstance(cons["controllable_variables"], list) or bad_vars:
        errors.append(f"constraints.controllable_variables must be a list drawn from {list(NUMERIC_VARS) + ['medium']}")
    if not isinstance(cons["batch_size"], int) or not 1 <= cons["batch_size"] <= 20:
        errors.append("constraints.batch_size must be an integer in [1, 20]")
    if not _num(cons["noise_floor"]) or not 0.01 <= cons["noise_floor"] <= 0.5:
        errors.append("constraints.noise_floor must be in [0.01, 0.5]")
    bounds = {k: list(v) for k, v in DEFAULT_BOUNDS.items()}
    for k, v in (cons["bounds"] or {}).items():
        if k not in DEFAULT_BOUNDS or not (isinstance(v, (list, tuple)) and len(v) == 2 and all(_num(i) for i in v) and v[0] < v[1]):
            errors.append(f"constraints.bounds.{k} must be [min, max] for a known variable")
        else:
            bounds[k] = list(v)
    cons["bounds"] = bounds

    budget = payload.get("budget") or {}
    if not isinstance(budget, dict):
        errors.append("budget must be an object")
        budget = {}
    rem = budget.get("remaining_experiments")
    if rem is not None and (not isinstance(rem, int) or isinstance(rem, bool) or rem < 0):
        errors.append("budget.remaining_experiments must be a non-negative integer or null")
    cb = budget.get("compute_budget")
    if cb is not None and (not _num(cb) or cb < 0):
        errors.append("budget.compute_budget must be a non-negative number or null")

    cands: Dict[str, Dict[str, Any]] = {}
    raw_c = payload.get("candidates") or []
    if not isinstance(raw_c, list):
        errors.append("candidates must be a list")
        raw_c = []
    for i, c in enumerate(raw_c):
        if not isinstance(c, dict) or not c.get("candidate_id"):
            errors.append(f"candidates[{i}] needs a candidate_id")
            continue
        cands[c["candidate_id"]] = adapters.normalize_candidate(c)

    hyps: List[Dict[str, Any]] = []
    raw_h = payload.get("hypotheses") or []
    if not isinstance(raw_h, list):
        errors.append("hypotheses must be a list")
        raw_h = []
    for i, h in enumerate(raw_h):
        if not isinstance(h, dict) or not h.get("hypothesis_id"):
            errors.append(f"hypotheses[{i}] needs a hypothesis_id")
            continue
        if h.get("status") == "rejected":
            warnings.append(f"Hypothesis {h['hypothesis_id']} has status 'rejected'; excluded from planning")
            continue
        p = h.get("prior_plausibility", 0.5)
        if not _num(p) or not 0 < p <= 1:
            errors.append(f"hypotheses[{i}].prior_plausibility must be in (0, 1]")
            continue
        hyps.append(h)

    ref = reference_conditions(desired, cons["reference_conditions"] or {})
    exps: List[Dict[str, Any]] = []
    raw_e = payload.get("previous_experiments") or payload.get("previous_results") or []
    if not isinstance(raw_e, list):
        errors.append("previous_experiments must be a list")
        raw_e = []
    for i, e in enumerate(raw_e):
        if not isinstance(e, dict) or e.get("candidate_id") not in cands:
            warnings.append(f"previous_experiments[{i}] ignored: unknown or missing candidate_id")
            continue
        m = e.get("measurement") or {}
        e_conditions, unit_notes = adapters.plain_conditions(e.get("conditions") or {})
        warnings.extend(f"previous_experiments[{i}] {n}" for n in unit_notes)
        y = m.get("predicted_inhibition_fraction")
        if y is None and _num(m.get("predicted_survival_fraction")):
            y = 1 - m["predicted_survival_fraction"]
        if y is None:
            y = m.get("predicted_activity")
        if not _num(y) or not 0 <= y <= 1:
            warnings.append(f"previous_experiments[{i}] ignored: no inhibition value in [0, 1]")
            continue
        cond = dict(ref)
        incomplete = [k for k in ("ph", "target_cell_density", "bacteriocin_concentration") if e_conditions.get(k) is None]
        if incomplete:
            warnings.append(f"previous_experiments[{i}] lacks {incomplete}; reference values assumed")
        cond.update({k: v for k, v in e_conditions.items() if k in CONDITION_KEYS and v is not None})
        exps.append({"experiment_id": e.get("experiment_id"), "result_id": e.get("result_id"),
                     "candidate_id": e["candidate_id"], "hypothesis_id": e.get("hypothesis_id"),
                     "conditions": cond, "y": float(y), "uncertainty": m.get("uncertainty"),
                     "evidence_type": e.get("evidence_type", "simulation-derived")})

    if errors:
        raise ValidationError(errors)
    if not cands:
        warnings.append("No candidates supplied")
    return {"target": {"species": species.strip(), "strain": target.get("strain")}, "desired": desired,
            "constraints": cons, "budget": {"remaining_experiments": rem, "compute_budget": cb},
            "candidates": cands, "hypotheses": hyps, "experiments": exps, "reference": ref,
            "research_state": payload.get("research_state") or {}, "warnings": warnings}


def build_experiment_spec(experiment_id: str, hypothesis_id: str, candidate_id: str, target: Dict[str, Any],
                          conditions: Dict[str, Any]) -> Dict[str, Any]:
    """ExperimentSpec in the shared-contract shape (conditions nested)."""
    return {"experiment_id": experiment_id, "hypothesis_id": hypothesis_id, "candidate_id": candidate_id,
            "target": {"species": target["species"], "strain": target.get("strain")},
            "conditions": {k: conditions.get(k) for k in CONDITION_KEYS}}


def flat_spec(conditions: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    """The flat experiment_spec shape named in the planner task statement."""
    return {"target": {"species": target["species"], "strain": target.get("strain")},
            "bacteriocin_concentration": conditions.get("bacteriocin_concentration"),
            "target_cell_density": conditions.get("target_cell_density"),
            "producer_cell_density": conditions.get("producer_cell_density"),
            "ph": conditions.get("ph"), "temperature_c": conditions.get("temperature_c"),
            "medium": conditions.get("medium"), "incubation_time": conditions.get("incubation_time"),
            "assay_domain": conditions.get("assay_domain", "simulated_in_vitro")}
