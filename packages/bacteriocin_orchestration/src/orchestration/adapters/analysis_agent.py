"""Result Analysis Agent: interprets simulation results against motivating hypotheses."""

from __future__ import annotations

from typing import Any

from ..state import ResearchStateManager
from ..types import Finding, ResearchState, make_finding_id


def _extract_numeric(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    if isinstance(val, dict):
        v = val.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    if (
        hasattr(val, "value")
        and isinstance(val.value, (int, float))
        and not isinstance(val.value, bool)
    ):
        return float(val.value)
    return None


class ResultAnalysisAgent:
    """Interprets experiment results against motivating hypotheses and identifies critical sensitivities."""

    name = "analysis"

    def run(self, state: ResearchState) -> dict[str, Any]:
        state_mgr = ResearchStateManager(state)

        if not state.results:
            return {
                "agent": self.name,
                "status": "skipped",
                "reason": "No experiment results to analyze",
                "output_ids": [],
            }

        latest_result = state.results[-1]
        cid = latest_result.candidate_id or "unknown"
        cand = state.get_candidate(cid)
        cand_name = cand.name if cand else cid

        # Check for failed experiment status
        if latest_result.status == "failed":
            finding_id = make_finding_id({"res": latest_result.result_id, "fail": True})
            finding = Finding(
                finding_id=finding_id,
                statement=f"Experiment {latest_result.experiment_id} for {cand_name} failed execution.",
                status="inconclusive",
                confidence=0.0,
                candidate_ids=[cid] if cid != "unknown" else [],
                recommendations=["Fix experiment spec conditions and re-run."],
            )
            state_mgr.add_finding(finding, source_agent=self.name)
            return {
                "agent": self.name,
                "status": "success",
                "output_ids": [finding_id],
                "finding": finding.model_dump(),
            }

        # Analyze inhibition observable
        measurement = latest_result.measurement
        inhibition = measurement.predicted_inhibition_fraction if measurement else None
        if inhibition is None:
            inhibition = 0.5

        # Check conditions
        cond = latest_result.conditions if isinstance(latest_result.conditions, dict) else {}
        density = _extract_numeric(cond.get("target_cell_density"))
        ph = _extract_numeric(cond.get("ph"))

        factor_sensitivities: dict[str, float] = {}
        for factor in latest_result.important_factors:
            if hasattr(factor, "factor") and hasattr(factor, "sensitivity"):
                factor_sensitivities[factor.factor] = float(factor.sensitivity)
            elif isinstance(factor, dict):
                factor_sensitivities[factor.get("factor", "")] = float(
                    factor.get("sensitivity", 0.0)
                )

        # Check for multi-condition comparison on same candidate (e.g. density sensitivity)
        prev_cand_results = [
            r for r in state.results[:-1] if r.candidate_id == cid and r.status == "ok"
        ]
        density_sensitive = False
        if prev_cand_results and density is not None:
            prev_res = prev_cand_results[-1]
            prev_cond = prev_res.conditions if isinstance(prev_res.conditions, dict) else {}
            prev_density = _extract_numeric(prev_cond.get("target_cell_density"))
            prev_inhib = (
                prev_res.measurement.predicted_inhibition_fraction if prev_res.measurement else 0.5
            )
            # If low density had high inhibition and high density had low inhibition
            if (
                prev_density is not None
                and density > prev_density
                and prev_inhib is not None
                and prev_inhib >= 0.7
                and inhibition < 0.6
            ):
                density_sensitive = True

        # Formulate statement and status
        if density_sensitive:
            statement = (
                f"Candidate {cand_name} demonstrates acute target cell density sensitivity: "
                f"inhibition dropped from {prev_inhib:.2f} at {prev_density:g} CFU/mL "
                f"to {inhibition:.2f} at {density:g} CFU/mL."
            )
            finding_status = "weakened"
            confidence = 0.88
            recommendations = [
                f"Candidate {cand_name} is density-sensitive. Consider higher dose sweep or testing alternative candidate."
            ]
        elif inhibition >= 0.70:
            statement = (
                f"Candidate {cand_name} demonstrated strong predicted inhibition ({inhibition:.2f}) "
                f"at target cell density {density if density is not None else 'standard'} CFU/mL."
            )
            finding_status = "supported"
            confidence = float(latest_result.confidence or 0.85)
            # If high density was already tested and succeeded
            if density is not None and density >= 1e7:
                recommendations = [
                    f"Robust efficacy demonstrated against high density for {cand_name}."
                ]
            else:
                recommendations = [
                    f"Test robustness of {cand_name} at elevated target cell density (e.g. 1e8 CFU/mL)."
                ]
        elif inhibition <= 0.40:
            statement = (
                f"Candidate {cand_name} showed low predicted inhibition ({inhibition:.2f}) "
                f"under conditions (density={density}, pH={ph})."
            )
            finding_status = "contradicted"
            confidence = float(latest_result.confidence or 0.75)
            recommendations = [
                f"Candidate {cand_name} appears ineffective under tested conditions. Screen alternative candidates."
            ]
        else:
            statement = f"Candidate {cand_name} showed borderline / intermediate inhibition ({inhibition:.2f})."
            finding_status = "inconclusive"
            confidence = 0.50
            recommendations = [
                f"Sweep concentration around transition region for {cand_name} to resolve MIC."
            ]

        finding_id = make_finding_id(
            {
                "res_id": latest_result.result_id,
                "cand": cid,
                "status": finding_status,
                "iter": state.iteration,
            }
        )

        # Match to relevant hypotheses
        matched_hids = [
            h.hypothesis_id for h in state.hypotheses if h.candidate_id == cid or not h.candidate_id
        ]

        finding = Finding(
            finding_id=finding_id,
            statement=statement,
            status=finding_status,
            confidence=confidence,
            candidate_ids=[cid] if cid != "unknown" else [],
            hypothesis_ids=matched_hids,
            evidence_ids=[latest_result.result_id],
            factor_sensitivities=factor_sensitivities,
            recommendations=recommendations,
        )
        state_mgr.add_finding(finding, source_agent=self.name)

        return {
            "agent": self.name,
            "status": "success",
            "output_ids": [finding_id],
            "finding": finding.model_dump(),
        }
