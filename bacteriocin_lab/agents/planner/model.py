"""Lightweight surrogate: hypothesis prediction models, posterior, coverage, mutual information.

Everything is deterministic and dependency-free.

Hypothesis models. Each hypothesis (matched by ``template``) predicts an inhibition
fraction for a (candidate, conditions) pair:
  factor models   p = b_c * f(conditions)   (b_c = candidate activity ceiling, fitted per
                                              hypothesis from that candidate's data, shrunk to a prior)
  absolute models p = g(candidate, target)  (no free parameter)
These are intentionally simple, transparent priors, not mechanistic simulators.
A built-in ``null`` hypothesis ("no context effect": p = b_c) is always included so a
single real hypothesis can still be tested against "nothing happens".
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .schema import LOG_VARS, NUMERIC_VARS

NULL_ID = "hyp_null_no_context_effect"
PRIOR_AMPLITUDE_SD = 0.3
# Surrogate hypothesis models are crude: add this model-misspecification SD (in quadrature) to measurement noise
# so posteriors do not collapse to certainty after a few points.
MODEL_ERROR_SD = 0.15


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _feat(cand: Dict[str, Any], key: str, default: Any = None) -> Any:
    return (cand.get("features") or {}).get(key, default)


def prior_amplitude(cand: Dict[str, Any]) -> float:
    conf = cand.get("confidence")
    return clamp(0.4 + 0.5 * conf, 0.05, 0.95) if isinstance(conf, (int, float)) else 0.5


# ------------------------------------------------------------- factor models

def f_null(cand, cond, target) -> float:
    return 1.0


def f_ph_window(cand, cond, target) -> float:
    w = (_feat(cand, "stability") or {}).get("ph_activity_window")
    if not w:
        return 1.0
    dist = max(w[0] - cond["ph"], cond["ph"] - w[1], 0.0)
    return 1.0 - 0.65 * min(1.0, dist / 1.5)


def f_inoculum(cand, cond, target) -> float:
    mech = str(_feat(cand, "mechanism", "") or "")
    slope = 0.3 if "pore" in mech else 0.1
    excess = max(0.0, math.log10(cond["target_cell_density"]) - 6.0)
    return max(0.05, 1.0 - slope * excess)


# ----------------------------------------------------------- absolute models

def a_charge(cand, cond, target) -> Optional[float]:
    q = _feat(cand, "net_charge_at_target_ph")
    if q is None:
        q = _feat(cand, "net_charge_ph7")
    return None if q is None else clamp(0.15 + 0.12 * max(q, 0.0), 0.05, 0.95)


def a_receptor(cand, cond, target) -> float:
    known = [" ".join(t.lower().split()) for t in _feat(cand, "known_targets", []) or []]
    sp = " ".join(target["species"].lower().split())
    if sp in known:
        return 0.85
    if any(k.split(" ")[0] == sp.split(" ")[0] for k in known):
        return 0.6
    return 0.15


FACTOR_MODELS: Dict[str, Callable] = {"null": f_null, "ph_window": f_ph_window, "inoculum_effect": f_inoculum}
ABSOLUTE_MODELS: Dict[str, Callable] = {"cationic_charge": a_charge, "receptor_specificity": a_receptor}

# Variable each template is sensitive to (used for explanation / candidate-point generation).
SENSITIVE_VARIABLE = {"ph_window": "ph", "inoculum_effect": "target_cell_density", "cationic_charge": "candidate",
                      "receptor_specificity": "candidate", "null": None}


class Hyp:
    """A hypothesis with an executable prediction model."""

    def __init__(self, hid: str, template: str, prior: float, statement: str = "", has_model: bool = True):
        self.id, self.template, self.prior, self.statement, self.has_model = hid, template, prior, statement, has_model

    @property
    def kind(self) -> str:
        return "absolute" if self.template in ABSOLUTE_MODELS else "factor"

    def factor(self, cand, cond, target) -> float:
        return FACTOR_MODELS.get(self.template, f_null)(cand, cond, target)

    def absolute(self, cand, cond, target) -> Optional[float]:
        return ABSOLUTE_MODELS[self.template](cand, cond, target)


def build_hyps(raw: List[Dict[str, Any]], warnings: List[str]) -> List[Hyp]:
    hyps = []
    for h in raw:
        t = h.get("template")
        # Candidate generation historically emitted structured conditions without a planner
        # template. Recover the smallest executable model deterministically instead of silently
        # treating those hypotheses as null-like.
        if not t:
            conditions = h.get("key_conditions") or {}
            if conditions.get("ph_range") is not None:
                t = "ph_window"
            elif conditions.get("target_cell_density") is not None:
                t = "inoculum_effect"
            elif conditions.get("mechanism_probe") is not None:
                t = "receptor_specificity"
        known = t in FACTOR_MODELS or t in ABSOLUTE_MODELS
        if not known:
            warnings.append(f"Hypothesis {h['hypothesis_id']} has no prediction model (template={t!r}); "
                            "it is treated as a null-like hypothesis and cannot be discriminated by this planner")
        hyps.append(Hyp(h["hypothesis_id"], t if known else "null", float(h.get("prior_plausibility", 0.5)),
                        h.get("statement", ""), known))
    if not any(h.template == "null" and h.has_model and h.id == NULL_ID for h in hyps):
        hyps.append(Hyp(NULL_ID, "null", 0.3, "No context effect: inhibition independent of pH and density"))
    return hyps


# ----------------------------------------------------------- fitting / posterior

def sigma_of(exp: Dict[str, Any], noise_floor: float) -> float:
    floor = noise_floor * (0.6 if exp.get("evidence_type") == "wet-lab-derived" else 1.0)
    u = exp.get("uncertainty")
    meas = max(floor, float(u)) if isinstance(u, (int, float)) and not isinstance(u, bool) else floor
    return math.sqrt(meas ** 2 + MODEL_ERROR_SD ** 2)


def fitted_amplitude(h: Hyp, cand: Dict[str, Any], obs: List[Dict[str, Any]], target, noise_floor: float) -> float:
    b0 = prior_amplitude(cand)
    if h.kind != "factor" or not obs:
        return b0
    num = b0 / PRIOR_AMPLITUDE_SD ** 2
    den = 1.0 / PRIOR_AMPLITUDE_SD ** 2
    for o in obs:
        s2 = sigma_of(o, noise_floor) ** 2
        f = h.factor(cand, o["conditions"], target)
        num += f * o["y"] / s2
        den += f * f / s2
    return clamp(num / den, 0.02, 1.0)


def predict(h: Hyp, cand: Dict[str, Any], cond: Dict[str, Any], amp: float, target) -> float:
    if h.kind == "absolute":
        v = h.absolute(cand, cond, target)
        return amp if v is None else v
    return clamp(amp * h.factor(cand, cond, target), 0.0, 1.0)


def group_obs(experiments: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for e in experiments:
        out.setdefault(e["candidate_id"], []).append(e)
    return out


def posterior(hyps: List[Hyp], cands: Dict[str, Dict[str, Any]], obs_by_c: Dict[str, List[Dict[str, Any]]],
              target, noise_floor: float) -> Dict[str, float]:
    logp: Dict[str, float] = {}
    for h in hyps:
        lp = math.log(h.prior)
        for cid, obs in obs_by_c.items():
            cand = cands[cid]
            amp = fitted_amplitude(h, cand, obs, target, noise_floor)
            for o in obs:
                s = sigma_of(o, noise_floor)
                r = o["y"] - predict(h, cand, o["conditions"], amp, target)
                lp += -(r * r) / (2 * s * s)
        logp[h.id] = lp
    m = max(logp.values())
    w = {k: math.exp(v - m) for k, v in logp.items()}
    z = sum(w.values())
    return {k: v / z for k, v in w.items()}


# ------------------------------------------------------------ information gain

_GRID = [i / 100.0 for i in range(-30, 131)]
_DY = 0.01


def _pdf(y: float, mu: float, s: float) -> float:
    return math.exp(-0.5 * ((y - mu) / s) ** 2) / (s * math.sqrt(2 * math.pi))


def mutual_information(weights: Sequence[float], mus: Sequence[float], sigma: float
                       ) -> Tuple[float, List[float]]:
    """I(H; y) in bits for y ~ sum_h w_h N(mu_h, sigma^2); also per-hypothesis contributions."""
    mix = [sum(w * _pdf(y, mu, sigma) for w, mu in zip(weights, mus)) for y in _GRID]
    contribs = []
    for w, mu in zip(weights, mus):
        kl = 0.0
        for y, m in zip(_GRID, mix):
            p = _pdf(y, mu, sigma)
            if p > 1e-12 and m > 1e-12:
                kl += p * math.log2(p / m) * _DY
        contribs.append(w * kl)
    return max(0.0, sum(contribs)), [max(0.0, c) for c in contribs]


def posterior_after(weights: Sequence[float], mus: Sequence[float], sigma: float, y: float) -> List[float]:
    lik = [w * _pdf(y, mu, sigma) for w, mu in zip(weights, mus)]
    z = sum(lik) or 1.0
    return [l / z for l in lik]


# ------------------------------------------------------------------- coverage

_SCALE = {"ph": 1.0, "target_cell_density": 1.0, "bacteriocin_concentration": 0.7, "temperature_c": 8.0,
          "incubation_time": 0.7}


def distance2(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    d2 = 0.0
    for v in NUMERIC_VARS:
        x, y = a.get(v), b.get(v)
        if x is None or y is None:
            continue
        if v in LOG_VARS:
            x, y = math.log10(x), math.log10(y)
        d2 += ((x - y) / _SCALE[v]) ** 2
    if a.get("medium") != b.get("medium"):
        d2 += 9.0
    if a.get("assay_domain") != b.get("assay_domain"):
        d2 += 9.0
    return d2


def model_uncertainty(cond: Dict[str, Any], obs: List[Dict[str, Any]], virtual: Sequence[Dict[str, Any]] = ()) -> float:
    """1 - kernel coverage by existing (and virtual, for batching) experiments of this candidate."""
    miss = 1.0
    for o in obs:
        w = 0.9 * (1 - clamp(o["uncertainty"] if isinstance(o.get("uncertainty"), (int, float)) else 0.0, 0, 0.8))
        if o.get("evidence_type") == "wet-lab-derived":
            w = 1.0
        miss *= 1 - w * math.exp(-0.5 * distance2(cond, o["conditions"]))
    for v in virtual:
        miss *= 1 - 0.9 * math.exp(-0.5 * distance2(cond, v))
    return clamp(miss)
