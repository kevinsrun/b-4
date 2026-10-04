"""Scientific Critic & Safety Agent: reviews validity, evidence sufficiency, and contract adherence."""

from __future__ import annotations

from typing import Any

from ..state import ResearchStateManager
from ..types import EvidenceType, ResearchState, Review, make_review_id


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


class ScientificCriticAgent:
    """Evaluates findings, enforces scientific rigor, and triggers backtracking when evidence is deficient."""

    name = "critic"

    def run(self, state: ResearchState) -> dict[str, Any]:
        state_mgr = ResearchStateManager(state)

        latest_finding = state.findings[-1] if state.findings else None
        latest_result = state.results[-1] if state.results else None

        # 1. Safety check: Shared contract rule 9 & 10 validation
        for res in state.results:
            if res.evidence_type == EvidenceType.WET_LAB and res.backend == "simulation":
                review_id = make_review_id({"safety": "wet_lab_violation", "iter": state.iteration})
                rev = Review(
                    review_id=review_id,
                    status="rejected",
                    critique="CRITICAL SAFETY VIOLATION: Simulation result claimed wet-lab validation.",
                    recommendation={"action": "halt", "reason": "Contract rule 9 violation"},
                )
                state_mgr.add_review(rev, source_agent=self.name)
                return {
                    "agent": self.name,
                    "status": "safety_violation",
                    "review": rev.model_dump(),
                    "output_ids": [review_id],
                }

        # 2. Check if no results exist
        if not latest_result or not latest_finding:
            review_id = make_review_id({"empty": True, "iter": state.iteration})
            rev = Review(
                review_id=review_id,
                status="needs_more_evidence",
                critique="No experiment results or analysis findings available for critique.",
                recommendation={"agent": "evidence", "reason": "Gather initial evidence"},
            )
            state_mgr.add_review(rev, source_agent=self.name)
            return {
                "agent": self.name,
                "status": "needs_more_evidence",
                "review": rev.model_dump(),
                "output_ids": [review_id],
            }

        # 3. Check for experiment execution failure
        if latest_result.status == "failed":
            review_id = make_review_id(
                {"res_failed": latest_result.result_id, "iter": state.iteration}
            )
            rev = Review(
                review_id=review_id,
                status="experiment_inconclusive",
                critique=f"Underlying simulation experiment {latest_result.experiment_id} failed execution.",
                recommendation={
                    "agent": "planner",
                    "reason": "Repair experiment conditions and re-plan",
                },
            )
            state_mgr.add_review(rev, source_agent=self.name)
            return {
                "agent": self.name,
                "status": "experiment_inconclusive",
                "review": rev.model_dump(),
                "output_ids": [review_id],
            }

        # 4. Check for high sensitivity on imputed default (AGENTS.md habit 1)
        for factor in latest_result.important_factors:
            f_source = getattr(factor, "source", None) or (
                factor.get("source") if isinstance(factor, dict) else None
            )
            f_sens = getattr(factor, "sensitivity", 0.0) or (
                factor.get("sensitivity", 0.0) if isinstance(factor, dict) else 0.0
            )
            if str(f_source) == "imputed_default" and abs(float(f_sens)) > 1.5:
                review_id = make_review_id({"imputed_factor": str(factor), "iter": state.iteration})
                rev = Review(
                    review_id=review_id,
                    status="needs_more_evidence",
                    critique=(
                        f"Prediction is heavily driven by imputed default factor '{getattr(factor, 'factor', '')}' "
                        f"(sensitivity {f_sens}). Spec must be pinned down explicitly before drawing conclusions."
                    ),
                    recommendation={
                        "agent": "planner",
                        "reason": "Pin down imputed condition explicitly in spec",
                    },
                )
                state_mgr.add_review(rev, source_agent=self.name)
                return {
                    "agent": self.name,
                    "status": "needs_more_evidence",
                    "review": rev.model_dump(),
                    "output_ids": [review_id],
                }

        # 5. Check if objective required high-density or specific pH, but tested condition was standard
        desired_density = _extract_numeric(
            (state.objective.desired_behavior or {}).get("target_cell_density")
        )
        cond = latest_result.conditions if isinstance(latest_result.conditions, dict) else {}
        actual_density = _extract_numeric(cond.get("target_cell_density"))

        if (
            desired_density
            and actual_density
            and desired_density >= 1e7
            and actual_density < 1e7
            and latest_finding.status == "supported"
        ):
            # The candidate succeeded at low density, but high-density robustness remains untested
            review_id = make_review_id(
                {"insufficient_density": actual_density, "iter": state.iteration}
            )
            rev = Review(
                review_id=review_id,
                status="needs_more_evidence",
                critique=(
                    f"Candidate performed strongly at low target cell density ({actual_density:g} CFU/mL), "
                    f"but objective specifically targets high density ({desired_density:g} CFU/mL). "
                    "High-density efficacy is not yet established."
                ),
                recommendation={
                    "agent": "planner",
                    "reason": "Sweep high target cell density to verify robustness",
                    "focus": "target_cell_density",
                    "suggested_value": desired_density,
                },
            )
            state_mgr.add_review(rev, source_agent=self.name)
            return {
                "agent": self.name,
                "status": "needs_more_evidence",
                "review": rev.model_dump(),
                "output_ids": [review_id],
            }

        # 6. Check if candidate is conclusively contradicted / density-sensitive
        if latest_finding.status == "contradicted":
            review_id = make_review_id(
                {"contradicted": latest_finding.finding_id, "iter": state.iteration}
            )
            rev = Review(
                review_id=review_id,
                status="rejected",
                critique=f"Candidate failed potency requirements: {latest_finding.statement}",
                recommendation={
                    "agent": "candidate",
                    "reason": "Propose alternative candidate family",
                },
            )
            state_mgr.add_review(rev, source_agent=self.name)
            return {
                "agent": self.name,
                "status": "rejected",
                "review": rev.model_dump(),
                "output_ids": [review_id],
            }

        # 7. Default approval
        review_id = make_review_id({"approved": latest_finding.finding_id, "iter": state.iteration})
        rev = Review(
            review_id=review_id,
            status="approved",
            critique="Finding is consistent with continuous simulation metrics and uncertainty budget.",
            recommendation={
                "agent": "knowledge",
                "reason": "Integrate findings into research state",
            },
        )
        state_mgr.add_review(rev, source_agent=self.name)

        return {
            "agent": self.name,
            "status": "approved",
            "review": rev.model_dump(),
            "output_ids": [review_id],
        }
