"""Shared builders for result-analysis tests."""

from __future__ import annotations

from typing import Any


def make_result(
    result_id: str,
    inhibition: float,
    *,
    density: float | None = 1e6,
    concentration: float | None = 10.0,
    ph: float | None = 7.0,
    temperature_c: float | None = 37.0,
    sigma: float | None = 0.03,
    candidate: str = "cand_B17",
    experiment_id: str | None = None,
    evidence_type: str = "simulation-derived",
    factors: list[str] | None = None,
    survival: float | None = "auto",  # type: ignore[assignment]
    hypothesis_id: str | None = None,
    **conditions: Any,
) -> dict[str, Any]:
    """A contract-valid ExperimentResult dict."""
    cond = {
        "bacteriocin_concentration": concentration,
        "target_cell_density": density,
        "ph": ph,
        "temperature_c": temperature_c,
        **conditions,
    }
    measurement: dict[str, Any] = {
        "predicted_inhibition_fraction": inhibition,
        "uncertainty": sigma,
    }
    measurement["predicted_survival_fraction"] = (
        round(1 - inhibition, 6) if survival == "auto" else survival
    )
    out = {
        "result_id": result_id,
        "experiment_id": experiment_id or f"exp_{result_id}",
        "candidate_id": candidate,
        "conditions": cond,
        "measurement": measurement,
        "important_factors": factors if factors is not None else [],
        "evidence_type": evidence_type,
        "model_version": "sim/1.0",
    }
    if hypothesis_id:
        out["hypothesis_id"] = hypothesis_id
    return out
