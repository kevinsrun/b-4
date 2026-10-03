from __future__ import annotations

import re

from .models import Quantity

MICRO = "µ"


def _number(raw: str) -> float | None:
    cleaned = raw.strip().replace(",", "")
    scientific = re.fullmatch(r"(?:([0-9]+(?:\.[0-9]+)?)\s*[x×]\s*)?10\s*\^\s*([+-]?\d+)", cleaned, re.I)
    if scientific:
        coefficient = float(scientific.group(1) or 1)
        return coefficient * (10 ** int(scientific.group(2)))
    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_concentration(value: str, unit: str) -> Quantity:
    numeric = _number(value)
    canonical = unit.strip().replace("μ", MICRO).replace("ug", f"{MICRO}g")
    factors = {
        f"{MICRO}g/ml": 1.0,
        "mg/l": 1.0,
        "ng/ml": 0.001,
        f"{MICRO}g/l": 0.001,
        "g/l": 1000.0,
        "mg/ml": 1000.0,
    }
    factor = factors.get(canonical.lower())
    if numeric is not None and factor is not None:
        return Quantity(
            value=numeric,
            unit=canonical,
            original_value=value,
            original_unit=unit,
            normalized_value=numeric * factor,
            normalized_unit=f"{MICRO}g/mL",
            normalization_note="Exact mass/volume conversion; no molecular-weight assumption used.",
        )
    return Quantity(
        value=numeric,
        unit=canonical,
        original_value=value,
        original_unit=unit,
        normalization_note="Original unit preserved; normalization requires additional molecular or assay information.",
    )


def normalize_time(value: str, unit: str) -> Quantity:
    numeric = _number(value)
    normalized: float | None = None
    lower = unit.lower()
    if numeric is not None:
        if lower.startswith(("h", "hr")):
            normalized = numeric
        elif lower.startswith("min"):
            normalized = numeric / 60
        elif lower.startswith(("d", "day")):
            normalized = numeric * 24
    return Quantity(
        value=numeric,
        unit=unit,
        original_value=value,
        original_unit=unit,
        normalized_value=normalized,
        normalized_unit="h" if normalized is not None else None,
        normalization_note="Converted to hours." if normalized is not None else "Original unit preserved.",
    )


def observed_quantity(value: str, unit: str | None = None) -> Quantity:
    return Quantity(value=_number(value), unit=unit, original_value=value, original_unit=unit)
