"""Adapter for Simulation / Computational Experiment Agent (bacteriocin_sim)."""

from __future__ import annotations

from typing import Any

from bacteriocin_lab.agents.simulator.api import run_experiments
from bacteriocin_lab.agents.simulator.schemas import CandidateSpec, EvidenceType, ExperimentResult

from ..state import ResearchStateManager
from ..types import ResearchState


class SimulationAgentAdapter:
    """Executes planned ExperimentSpecs against bacteriocin_sim computational backend."""

    name = "simulation"

    def __init__(self, parameter_overrides: dict[str, Any] | None = None) -> None:
        self.parameter_overrides = parameter_overrides

    def run(self, state: ResearchState) -> dict[str, Any]:
        state_mgr = ResearchStateManager(state)

        # Identify specs not yet executed
        executed_exp_ids = {r.experiment_id for r in state.results}
        specs_to_run = [s for s in state.experiments if s.experiment_id not in executed_exp_ids]

        if not specs_to_run and state.experiments:
            # Re-run latest if all were executed
            specs_to_run = [state.experiments[-1]]

        if not specs_to_run:
            return {
                "agent": self.name,
                "status": "skipped",
                "reason": "No experiment specs to execute",
                "output_ids": [],
            }

        # Build candidate registry with sequences
        candidate_registry: dict[str, CandidateSpec] = {}
        for c in state.candidates:
            if c.sequence:
                candidate_registry[c.candidate_id] = CandidateSpec(
                    candidate_id=c.candidate_id,
                    name=c.name,
                    sequence=c.sequence,
                )

        # Extract parameter_overrides if specified on adapter or state
        overrides = (
            self.parameter_overrides
            or getattr(state, "parameter_overrides", None)
            or state.objective.constraints.get("parameter_overrides")
            or state.objective.target.get("parameter_overrides")
        )

        results = run_experiments(
            specs_to_run,
            candidate_registry=candidate_registry,
            parameter_overrides=overrides,
        )

        emitted_ids: list[str] = []
        for res in results:
            # Enforce contract rule 9 & 10: simulation results are never wet-lab
            if not isinstance(res, ExperimentResult):
                res = ExperimentResult.model_validate(res)

            object.__setattr__(res, "evidence_type", EvidenceType.SIMULATION)
            object.__setattr__(res, "validated_experimentally", False)

            if state_mgr.add_experiment_result(res, source_agent=self.name):
                emitted_ids.append(res.result_id)

        return {
            "agent": self.name,
            "status": "success",
            "executed": len(specs_to_run),
            "output_ids": emitted_ids,
            "results": [r.to_json_dict() for r in results],
        }
