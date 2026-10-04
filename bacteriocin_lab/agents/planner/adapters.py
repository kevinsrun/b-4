"""Input adapters: accept what the neighbouring agents actually emit.

The planner's native input is flat. The agents around it emit richer shapes:

* the simulator reports quantities as ``{"value": ..., "unit": ...}``;
* the candidate agent keeps its physicochemical features under ``computed`` and its stability
  priors under ``known_stability``.

Everything here is additive: native flat shapes work unchanged and original fields are never
overwritten, only supplemented.
"""

from __future__ import annotations

import math
from typing import Any

_LOG10_UNITS = {"log10_cfu_per_ml", "log10_cfu/ml", "log10cfu/ml"}


def plain_number(value: Any) -> tuple[Any, str | None]:
    """Reduce a simulator ``Quantity`` to a float. Returns (value, note-or-None)."""
    if isinstance(value, dict) and "value" in value:
        v, unit = value["value"], str(value.get("unit") or "").lower()
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            if unit in _LOG10_UNITS:
                return 10.0**v, None
            if unit in ("od600", "od"):
                return v, f"unit {unit!r} cannot be converted to CFU/mL; value used as-is"
            return float(v), None
    return value, None


def plain_conditions(cond: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Flatten every ``Quantity`` in a conditions dict; returns (conditions, notes)."""
    out: dict[str, Any] = {}
    notes: list[str] = []
    for k, v in (cond or {}).items():
        if isinstance(v, dict) and "value" in v:
            v, note = plain_number(v)
            if note:
                notes.append(f"{k}: {note}")
        out[k] = v
    return out, notes


def normalize_candidate(c: dict[str, Any]) -> dict[str, Any]:
    """Copy of ``c`` whose ``features`` also carry the keys the planner's models read."""
    c = dict(c)
    f = dict(c.get("features") or {})
    comp = f.get("computed") if isinstance(f.get("computed"), dict) else {}
    if "net_charge_at_target_ph" not in f and comp.get("net_charge") is not None:
        f["net_charge_at_target_ph"] = comp["net_charge"]
        f.setdefault("net_charge_ph7", comp["net_charge"])
    stab = f.get("stability") if isinstance(f.get("stability"), dict) else {}
    ks = f.get("known_stability") if isinstance(f.get("known_stability"), dict) else {}
    if not stab.get("ph_activity_window") and ks.get("ph_stable_range"):
        # The stability range is the closest available proxy for an activity window.
        stab = dict(
            stab, ph_activity_window=ks["ph_stable_range"], basis="known_stability.ph_stable_range"
        )
    if stab:
        f["stability"] = stab
    if not f.get("mechanism"):
        mech = f.get("receptor") or f.get("bacteriocin_class")
        if mech:
            f["mechanism"] = str(mech)
    if "sequence_length" not in f and comp.get("sequence_length") is not None:
        f["sequence_length"] = comp["sequence_length"]
    c["features"] = f
    return c
