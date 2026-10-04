"""Adapter for Experiment Planner / Active Learning Agent (experiment_planner)."""

from __future__ import annotations

from typing import Any

from bacteriocin_lab.agents.planner.planner import ExperimentPlanner

from ..state import ResearchStateManager
from ..types import ExperimentSpec, ResearchState


class PlannerAgentAdapter:
    """Wraps ExperimentPlanner to turn hypotheses and candidates into concrete ExperimentSpecs."""

    name = "planner"

    def __init__(self, planner: ExperimentPlanner | None = None) -> None:
        self.planner = planner or ExperimentPlanner()

    def run(self, state: ResearchState) -> dict[str, Any]:
        state_mgr = ResearchStateManager(state)
        species = state.objective.species or "Listeria monocytogenes"

        # Active candidates only
        active_cands = [
            c for c in state.candidates if c.candidate_id not in state.settled_candidate_ids
        ]
        if not active_cands:
            active_cands = list(state.candidates)

        cands_payload = [
            {
                "candidate_id": c.candidate_id,
                "name": c.name,
                "confidence": c.confidence,
                "features": c.features,
            }
            for c in active_cands
        ]

        hyps_payload = [
            {
                "hypothesis_id": h.hypothesis_id,
                "statement": h.statement,
                "prior_plausibility": h.prior_plausibility,
                "status": h.status,
            }
            for h in state.hypotheses
            if h.status != "rejected"
        ]

        # Ensure at least one hypothesis exists for planner's internal models
        if not hyps_payload and active_cands:
            default_hid = f"hyp_baseline_{active_cands[0].candidate_id}"
            hyps_payload.append(
                {
                    "hypothesis_id": default_hid,
                    "statement": f"{active_cands[0].name} inhibits {species} under standard conditions.",
                    "prior_plausibility": 0.5,
                    "status": "open",
                }
            )

        req = {
            "research_objective": {
                "target": {"species": species, "strain": state.objective.strain},
                "desired_behavior": dict(state.objective.desired_behavior or {}),
            },
            "candidates": cands_payload,
            "hypotheses": hyps_payload,
            "previous_experiments": [r.model_dump() for r in state.results],
            "budget": {
                "remaining_experiments": max(1, 10 - state.iteration),
            },
            "constraints": dict(state.objective.constraints or {}),
        }

        response = self.planner.run(req)
        decision = response.get("decision") or {}

        emitted_ids: list[str] = []
        spec_dict = response.get("experiment_spec")
        if spec_dict:
            spec = ExperimentSpec.model_validate(spec_dict)
            state_mgr.add_experiment_spec(spec, source_agent=self.name)
            emitted_ids.append(spec.experiment_id)

        # Also support batch specs if returned
        batch = response.get("batch") or []
        for b_item in batch:
            if isinstance(b_item, dict) and b_item.get("experiment_id"):
                b_spec = ExperimentSpec.model_validate(b_item)
                if state_mgr.add_experiment_spec(b_spec, source_agent=self.name):
                    emitted_ids.append(b_spec.experiment_id)

        return {
            "agent": self.name,
            "status": "success" if emitted_ids else "no_specs",
            "decision": decision,
            "output_ids": emitted_ids,
            "experiment_spec": spec_dict,
            "recommended_next_action": response.get("recommended_next_action"),
        }
