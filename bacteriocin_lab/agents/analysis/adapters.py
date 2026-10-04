"""Boundary adapter for the simulator's richer ``ExperimentResult`` shape.

``bacteriocin_sim`` returns the contract fields plus additive extensions, and in
three places the shape differs from the shared contract's flat types:

* quantities in ``conditions`` are ``{"value": 1.0, "unit": "uM"}`` objects, where
  the contract has a float plus a ``*_unit`` field;
* ``important_factors`` are objects (``factor``, ``sensitivity``, ``direction``,
  ``source``) where the contract has strings;
* ``status`` may be ``"failed"`` (an error, not a measurement).

This module normalises the first two into the contract shape *without losing
information* (the richer detail is kept as extra keys, which the contract's
extensible models allow) and exposes the third so the agent can treat a failed
attempt as a failed attempt rather than a negative finding. Anything that is not
recognisably the simulator's shape passes through untouched, so contract-shaped
results (and wet-lab adapters) are unaffected.
"""

from __future__ import annotations

import copy
from typing import Any

#: condition name -> the contract field that carries its unit.
_UNIT_FIELDS = {
    "bacteriocin_concentration": "concentration_unit",
    "target_cell_density": "target_cell_density_unit",
    "producer_cell_density": "producer_cell_density_unit",
    "incubation_time": "incubation_time_unit",
}


def is_failed_attempt(raw: Any) -> bool:
    return isinstance(raw, dict) and raw.get("status") == "failed"


def normalize_result(raw: Any) -> Any:
    """Return ``raw`` in contract shape; non-dict input is returned unchanged."""
    if not isinstance(raw, dict):
        return raw
    out = copy.deepcopy(raw)

    cond = out.get("conditions")
    if isinstance(cond, dict):
        for name, unit_field in _UNIT_FIELDS.items():
            value = cond.get(name)
            if isinstance(value, dict) and "value" in value:
                cond[name] = value["value"]
                if value.get("unit") and not cond.get(unit_field):
                    cond[unit_field] = value["unit"]

    factors = out.get("important_factors")
    if isinstance(factors, list) and any(isinstance(f, dict) for f in factors):
        out["important_factor_details"] = [f for f in factors if isinstance(f, dict)]
        out["important_factors"] = [
            f["factor"] if isinstance(f, dict) and "factor" in f else str(f) for f in factors
        ]
    return out


def normalize_payload(payload: Any) -> Any:
    """Normalise every result-shaped object in a request payload."""
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    if "result" in out:
        out["result"] = normalize_result(out["result"])
    if isinstance(out.get("previous_results"), list):
        out["previous_results"] = [normalize_result(r) for r in out["previous_results"]]
    state = out.get("research_state")
    if isinstance(state, dict) and state.get("results"):
        stored = state["results"]
        norm = (
            {k: normalize_result(v) for k, v in stored.items()}
            if isinstance(stored, dict)
            else [normalize_result(v) for v in stored]
        )
        out["research_state"] = {**state, "results": norm}
    return out


__all__ = ["is_failed_attempt", "normalize_payload", "normalize_result"]
