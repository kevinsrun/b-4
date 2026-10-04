"""Builders for knowledge-agent tests: candidate-agent and result-analysis-shaped payloads."""

from __future__ import annotations

from typing import Any

FIXED_TIME = "2026-10-03T12:00:00.000+00:00"


def clock() -> str:
    return FIXED_TIME


def candidate_envelope(*ids: str, run_id: str = "run_1") -> dict[str, Any]:
    """A candidate-agent envelope: each candidate has one hypothesis ``hyp_<id>``."""
    cands = []
    for rank, cid in enumerate(ids or ("cand_a", "cand_b"), start=1):
        cands.append(
            {
                "candidate_id": cid,
                "name": f"name {cid}",
                "origin": "literature",
                "sequence": "KYYGNGV",
                "rank": rank,
                "validation_status": "unvalidated",
                "score": {"total": 1.0 - rank / 10},
                "features": {"bacteriocin_class": "class_iia"},
                "expected_failure_modes": ["narrow spectrum"],
                "hypotheses": [
                    {
                        "hypothesis_id": f"hyp_{cid}",
                        "statement": f"{cid} inhibits the target",
                        "candidate_id": cid,
                        "falsified_if": "inhibition < 0.2",
                        "predicted_inhibition_fraction": 0.8,
                    }
                ],
            }
        )
    return {
        "decision": {"candidates": cands},
        "artifacts": {"run_id": run_id},
        "model_version": "candidate-generation/0.1.0",
    }


def spec(
    experiment_id: str,
    candidate_id: str = "cand_a",
    hypothesis_id: str | None = "auto",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "candidate_id": candidate_id,
        "hypothesis_id": f"hyp_{candidate_id}" if hypothesis_id == "auto" else hypothesis_id,
        "target": {"species": "Listeria monocytogenes"},
        "conditions": {"bacteriocin_concentration": 10.0, "target_cell_density": 1e6, "ph": 7.0},
        **extra,
    }


def result(
    result_id: str,
    experiment_id: str,
    candidate_id: str = "cand_a",
    inhibition: float = 0.8,
    *,
    model_version: str = "sim/1.0",
    evidence_type: str = "simulation-derived",
) -> dict[str, Any]:
    return {
        "result_id": result_id,
        "experiment_id": experiment_id,
        "candidate_id": candidate_id,
        "conditions": {"bacteriocin_concentration": 10.0, "target_cell_density": 1e6, "ph": 7.0},
        "measurement": {
            "predicted_inhibition_fraction": inhibition,
            "predicted_survival_fraction": round(1 - inhibition, 4),
            "uncertainty": 0.03,
        },
        "evidence_type": evidence_type,
        "model_version": model_version,
    }


def analysis(
    experiment_id: str,
    status: str,
    *,
    result_id: str | None = None,
    candidate_id: str = "cand_a",
    hypothesis_id: str | None = "auto",
    strength: str = "moderate",
    finding_id: str | None = None,
    findings: list[dict[str, Any]] | None = None,
    unexpected: list[dict[str, Any]] | None = None,
    uncertainties: list[dict[str, Any]] | None = None,
    followups: list[str] | None = None,
    suggested: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    model_version: str = "result-analysis/0.1.0",
    failed: bool = False,
) -> dict[str, Any]:
    """A Result Analysis Agent envelope (decision + artifacts + evidence)."""
    rid = result_id or f"res_{experiment_id}"
    hid = f"hyp_{candidate_id}" if hypothesis_id == "auto" else hypothesis_id
    decision = {
        "finding_id": finding_id or f"find_{experiment_id}",
        "experiment_id": experiment_id,
        "result_id": rid,
        "candidate_id": candidate_id,
        "hypothesis_id": hid,
        "hypothesis_status": status,
        "evidence_strength": strength,
        "status_basis": f"basis for {experiment_id}",
        "findings": findings or [],
        "unexpected_results": unexpected or [],
        "drivers": [],
        "confidence": 0.7,
        "uncertainties": uncertainties or [],
        "recommended_followup_questions": followups or [],
        "observed": {"predicted_inhibition_fraction": 0.5},
        "source_evidence_type": "simulation-derived",
        "model_version": model_version,
    }
    artifacts: dict[str, Any] = {"planner_hints": {"suggested_experiments": suggested or []}}
    if failed:
        artifacts["failed_attempt"] = True
    return {
        "agent": "result_analysis_agent",
        "decision": decision,
        "evidence": evidence or [],
        "confidence": 0.7,
        "artifacts": artifacts,
        "model_version": model_version,
    }


def finding(
    variable: str, relationship: str, *, controlled: bool = True, effect: float | None = -0.2
) -> dict[str, Any]:
    return {
        "variable": variable,
        "relationship": relationship,
        "effect_size": effect,
        "controlled": controlled,
        "interpretation": f"{variable} is {relationship}",
    }


def uncertainty(
    description: str, kind: str = "epistemic", severity: str = "medium"
) -> dict[str, Any]:
    return {"kind": kind, "severity": severity, "description": description, "affects": []}
