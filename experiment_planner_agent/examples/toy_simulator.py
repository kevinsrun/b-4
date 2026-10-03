"""A TOY simulation backend used only to demonstrate the planning loop.

It is NOT a validated biological model. It implements ``run(spec) -> ExperimentResult`` with the shared
contract shape, so a real simulation_adapter (or a future wet_lab_adapter) can replace it with no planner
changes. Its hidden "ground truth" (pH windows, inoculum slopes) deliberately differs in functional form
from the planner's internal surrogate, so the planner is not simply reading back its own model.
Results are labelled ``simulation-derived`` and are never experimental evidence.
"""

import hashlib
import math

# Hidden ground truth per candidate *name*: (ceiling, ph_lo, ph_hi, inoculum_density_midpoint)
TRUTH = {
    "Nisin A": (0.92, 3.0, 6.8, 5e8),
    "Pediocin PA-1": (0.90, 3.0, 8.0, 3e6),
    "Sakacin P": (0.85, 4.0, 8.0, 2e6),
    "Enterocin A": (0.80, 4.0, 8.0, 5e7),
    "Leucocin A": (0.80, 4.0, 8.0, 5e7),
}
DEFAULT = (0.5, 4.0, 8.0, 1e7)


def _noise(key: str) -> float:
    h = int(hashlib.sha1(key.encode()).hexdigest()[:6], 16) / 0xFFFFFF
    return (h - 0.5) * 0.04


def run(spec, candidate_name):
    c = spec["conditions"]
    ceil, lo, hi, mid = TRUTH.get(candidate_name, DEFAULT)
    ph = c["ph"]
    ph_factor = 1 / (1 + math.exp(-(ph - lo) * 3)) * 1 / (1 + math.exp((ph - hi) * 3))
    inoc = 1 / (1 + (c["target_cell_density"] / mid) ** 0.8)
    dose = c["bacteriocin_concentration"] / (c["bacteriocin_concentration"] + 0.3)
    y = max(0.0, min(1.0, ceil * ph_factor * (0.25 + 0.75 * inoc) * (0.5 + 0.5 * dose) / 0.75 + _noise(spec["experiment_id"])))
    return {"result_id": "res_" + spec["experiment_id"][4:], "experiment_id": spec["experiment_id"],
            "candidate_id": spec["candidate_id"], "hypothesis_id": spec["hypothesis_id"], "conditions": c,
            "measurement": {"predicted_inhibition_fraction": round(y, 4),
                            "predicted_survival_fraction": round(1 - y, 4), "predicted_activity": round(y, 4),
                            "uncertainty": 0.05},
            "important_factors": [], "evidence_type": "simulation-derived", "model_version": "toy_sim-0.1",
            "warnings": ["toy simulator; not a validated model"]}
