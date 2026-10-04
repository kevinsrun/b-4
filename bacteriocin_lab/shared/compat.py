"""Boundary normalisers between the simulator's result shape and the shared contract's.

The simulator reports quantities as ``{"value": ..., "unit": ...}`` and ``important_factors`` as
structured objects. The shared contract's ``ExperimentResult`` holds plain floats and strings. Both
are legitimate for their producer, so the difference is bridged here, at the consumer's boundary,
without changing either schema.
"""

from __future__ import annotations

import math
from typing import Any

_LOG10_UNITS = {"log10_cfu_per_ml", "log10_cfu/ml", "log10cfu/ml"}


def _plain(value: Any) -> Any:
    """Reduce a ``{"value", "unit"}`` quantity to a float (log10 CFU/mL is un-logged)."""
    if isinstance(value, dict) and "value" in value:
        v = value["value"]
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            unit = str(value.get("unit") or "").lower()
            return 10.0**v if unit in _LOG10_UNITS else float(v)
    return value


def _factor_text(item: Any) -> str:
    """One readable string for a structured important-factor record."""
    if not isinstance(item, dict):
        return str(item)
    name = item.get("factor") or item.get("name") or item.get("variable") or "factor"
    detail = item.get("effect") or item.get("description") or item.get("detail")
    return f"{name}: {detail}" if detail else str(name)


def contract_result_dict(raw: Any) -> Any:
    """A copy of a simulator-shaped result that validates against the shared contract.

    Anything that is not a dict, or is already contract-shaped, is returned unchanged. Only the
    representation changes; no value is added, dropped or relabelled (provenance fields such as
    ``evidence_type`` pass through untouched).
    """
    if not isinstance(raw, dict):
        return raw
    out = dict(raw)
    conditions = out.get("conditions")
    if isinstance(conditions, dict):
        out["conditions"] = {k: _plain(v) for k, v in conditions.items()}
    factors = out.get("important_factors")
    if isinstance(factors, list):
        out["important_factors"] = [_factor_text(f) for f in factors]
    return out
