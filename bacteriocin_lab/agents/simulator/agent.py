"""The Omnigent-callable agent wrapper around the experiment backend.

Responsibility boundary
-----------------------
This agent executes experiments that were *already planned* and reports what
it predicted. It does not plan, hypothesise, or select candidates. Its
``recommended_next_action`` is a recommendation derived from its own
sensitivity and uncertainty output -- the planning agent and Omnigent remain
free to ignore it.

It never raises for a bad batch: a malformed spec becomes a failed result, and
the envelope always comes back well-formed, because an autonomous loop that
crashes on one bad field loses an entire iteration.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .api import run_experiments
from .registry import describe_backends
from .schemas import (
    AGENT_NAME,
    AgentInput,
    AgentOutput,
    EvidenceRecord,
    EvidenceType,
    ExperimentResult,
)

#: how many sensitivity entries to surface per result in the recommendation
_TOP_FACTORS = 3

#: |d logit(inhibition)| above which an unspecified factor is worth chasing.
#: One logit unit is ~0.43 log10 of survival, so this is roughly "a factor of
#: two in survivors" -- small enough to matter scientifically, large enough not
#: to flag numerical noise.
_MATERIAL_SENSITIVITY = 1.0


class SimulationBackendAgent:
    """Stateless agent facade. All state is in the input envelope."""

    name = AGENT_NAME

    def __init__(self) -> None:
        # Deliberately no instance state: agent rule 6 requires that Omnigent
        # be able to reconstruct everything the agent knows from the envelope.
        pass

    @classmethod
    def selftest(
        cls, parameter_overrides: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run directional biology invariants, optionally testing candidate parameter overrides."""
        from .selftest import run_selftest

        return run_selftest(parameter_overrides=parameter_overrides)

    # ------------------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        """Self-description for capability negotiation / tool registration."""
        return {
            "agent": self.name,
            "responsibility": (
                "execute planned bacteriocin activity experiments against a "
                "computational simulation backend and return continuous, "
                "uncertainty-quantified predictions"
            ),
            "does_not": [
                "gather literature or database evidence",
                "generate hypotheses",
                "design or select candidates",
                "choose the next experiment (it only recommends)",
                "maintain hidden state between calls",
            ],
            "input_schema": AgentInput.model_json_schema(),
            "output_schema": AgentOutput.model_json_schema(),
            "backends": describe_backends(),
        }

    # ------------------------------------------------------------------

    def run(self, payload: AgentInput | dict[str, Any]) -> AgentOutput:
        """Execute every spec in the envelope and summarise the outcome."""
        try:
            request = (
                payload
                if isinstance(payload, AgentInput)
                else AgentInput.model_validate(payload or {})
            )
        except Exception as exc:
            return AgentOutput(
                agent=self.name,
                decision={"action": "rejected_input", "reason": "envelope did not validate"},
                confidence=0.0,
                warnings=[f"invalid agent input: {exc}"],
                recommended_next_action={
                    "action": "repair_agent_input",
                    "detail": "see warnings; expected keys include experiment_specs",
                },
            )

        if not request.experiment_specs:
            return AgentOutput(
                agent=self.name,
                decision={
                    "action": "no_experiments_executed",
                    "reason": "the envelope contained no experiment_specs",
                    "n_executed": 0,
                },
                confidence=0.0,
                warnings=[
                    "no experiment_specs were supplied; this agent executes planned "
                    "experiments and does not design them"
                ],
                artifacts={"backends": describe_backends()},
                recommended_next_action={
                    "action": "request_experiment_plan",
                    "detail": (
                        "ask the experiment-planning agent for one or more "
                        "ExperimentSpec objects, then call this agent again"
                    ),
                },
            )

        max_experiments = request.constraints.get("max_experiments")
        specs = list(request.experiment_specs)
        warnings: list[str] = []
        if isinstance(max_experiments, int) and max_experiments > 0 and len(specs) > max_experiments:
            warnings.append(
                f"constraints.max_experiments={max_experiments} is below the "
                f"{len(specs)} specs supplied; only the first {max_experiments} were run"
            )
            specs = specs[:max_experiments]

        results = run_experiments(
            specs,
            backend=request.backend,
            candidate_registry=request.candidate_registry or None,
            parameter_overrides=request.parameter_overrides or None,
        )

        return self._build_output(results, warnings, request)

    # ------------------------------------------------------------------

    def _build_output(
        self,
        results: list[ExperimentResult],
        warnings: list[str],
        request: AgentInput,
    ) -> AgentOutput:
        ok = [r for r in results if r.status == "ok"]
        failed = [r for r in results if r.status != "ok"]

        evidence = [self._to_evidence(r) for r in ok]
        uncertainties = self._summarise_uncertainties(ok)
        for r in results:
            warnings.extend(r.warnings)
        warnings = list(dict.fromkeys(warnings))

        confidence = (
            round(sum(r.confidence or 0.0 for r in ok) / len(ok), 4) if ok else 0.0
        )

        decision = {
            "action": "experiments_executed",
            "n_requested": len(results),
            "n_executed": len(ok),
            "n_failed": len(failed),
            "backends_used": sorted({r.backend for r in results}),
            "evidence_type": EvidenceType.SIMULATION.value,
            "validated_experimentally": False,
            "summary": self._summarise_results(ok),
        }
        if failed:
            decision["failures"] = [
                {
                    "experiment_id": r.experiment_id,
                    "error": (r.error or {}).get("error_code", "unknown"),
                    "message": (r.error or {}).get("message"),
                }
                for r in failed
            ]

        return AgentOutput(
            agent=self.name,
            decision=decision,
            evidence=evidence,
            confidence=confidence,
            uncertainties=uncertainties,
            artifacts={
                "results": [r.to_json_dict() for r in results],
                "model_versions": sorted({r.model_version for r in results}),
                "parameter_set_hashes": sorted(
                    {
                        r.reproducibility.parameter_set_hash
                        for r in results
                        if r.reproducibility.parameter_set_hash
                    }
                ),
            },
            warnings=warnings,
            recommended_next_action=self._recommend(ok, failed),
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _to_evidence(result: ExperimentResult) -> EvidenceRecord:
        """Turn one result into a provenance-preserving evidence record.

        ``evidence_id`` is derived from the result ID, so re-running a
        deterministic experiment produces the same evidence ID instead of
        duplicating the research state.
        """
        m = result.measurement
        inhibition = m.predicted_inhibition_fraction
        digest = hashlib.sha256(result.result_id.encode("utf-8")).hexdigest()[:12]
        species = (result.conditions.get("target") or {}).get("species") or "the target"

        if inhibition is None:
            statement = f"no measurement was produced for {result.experiment_id}"
        else:
            ci = m.ci95_inhibition_fraction or [None, None]
            statement = (
                f"Simulation predicts {inhibition:.3f} inhibition of {species} "
                f"(95% interval {ci[0]:.3f}-{ci[1]:.3f}) at "
                f"{result.conditions.get('bacteriocin_concentration', {}).get('value')} uM "
                f"and {result.conditions.get('target_cell_density', {}).get('value'):.3g} "
                f"CFU/mL, pH {result.conditions.get('ph')}, "
                f"{result.conditions.get('temperature_c')} C, "
                f"{result.conditions.get('incubation_time')} h in "
                f"{result.conditions.get('medium')}. "
                f"Predicted effective MIC {m.predicted_mic_um} uM. "
                "This is a model prediction, not an experimental observation."
            )

        return EvidenceRecord(
            evidence_id=f"ev-sim-{digest}",
            evidence_type=EvidenceType.SIMULATION,
            statement=statement,
            candidate_id=result.candidate_id,
            hypothesis_id=result.hypothesis_id,
            experiment_id=result.experiment_id,
            result_id=result.result_id,
            confidence=result.confidence or 0.0,
            model_version=result.model_version,
            validated_experimentally=False,
            supporting_values={
                "predicted_inhibition_fraction": m.predicted_inhibition_fraction,
                "predicted_survival_fraction": m.predicted_survival_fraction,
                "predicted_activity": m.predicted_activity,
                "uncertainty": m.uncertainty,
                "ci95_inhibition_fraction": m.ci95_inhibition_fraction,
                "predicted_mic_um": m.predicted_mic_um,
                "predicted_log10_reduction_vs_control": (
                    m.predicted_log10_reduction_vs_control
                ),
                "primary_metric": m.primary_metric,
            },
            derived_from=[result.result_id],
        )

    @staticmethod
    def _summarise_results(results: list[ExperimentResult]) -> dict[str, Any]:
        if not results:
            return {}
        inhibitions = [
            r.measurement.predicted_inhibition_fraction
            for r in results
            if r.measurement.predicted_inhibition_fraction is not None
        ]
        if not inhibitions:
            return {}
        best = max(
            results,
            key=lambda r: r.measurement.predicted_inhibition_fraction or -1.0,
        )
        return {
            "mean_predicted_inhibition_fraction": round(
                sum(inhibitions) / len(inhibitions), 5
            ),
            "max_predicted_inhibition_fraction": round(max(inhibitions), 5),
            "min_predicted_inhibition_fraction": round(min(inhibitions), 5),
            "most_active_condition": {
                "experiment_id": best.experiment_id,
                "candidate_id": best.candidate_id,
                "predicted_inhibition_fraction": (
                    best.measurement.predicted_inhibition_fraction
                ),
                "predicted_mic_um": best.measurement.predicted_mic_um,
                "confidence": best.confidence,
            },
        }

    @staticmethod
    def _summarise_uncertainties(results: list[ExperimentResult]) -> list[str]:
        """Aggregate the dominant uncertainty source across the batch."""
        if not results:
            return []
        totals: dict[str, float] = {}
        rationales: dict[str, str] = {}
        for r in results:
            for c in r.uncertainty_components:
                totals[c.source] = totals.get(c.source, 0.0) + c.sigma_logit ** 2
                if c.rationale and c.source not in rationales:
                    rationales[c.source] = c.rationale
        ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
        out = [
            f"{source}: {rationales.get(source, 'contributes to prediction variance')}"
            for source, _ in ranked[:5]
        ]
        out.append(
            "All results are simulation-derived predictions from uncalibrated priors; "
            "no claim of experimental validation is made."
        )
        return out

    @staticmethod
    def _recommend(
        ok: list[ExperimentResult], failed: list[ExperimentResult]
    ) -> dict[str, Any]:
        """Suggest what would most reduce uncertainty next.

        Priority order:
        1. repair failed specs -- a failed experiment teaches nothing;
        2. pin down an *imputed* condition that the sensitivity analysis shows
           is driving the outcome;
        3. supply a missing candidate sequence, which dominates everything;
        4. sweep the most sensitive specified condition to locate the
           transition region, which is where the next experiment is most
           informative.
        """
        if failed and not ok:
            return {
                "action": "repair_experiment_specs",
                "rationale": "every experiment failed validation or execution",
                "failed_experiment_ids": [r.experiment_id for r in failed],
            }

        if not ok:
            return {"action": "none", "rationale": "no results to act on"}

        # 3: a missing sequence is the single largest uncertainty source
        missing_sequence = [
            r
            for r in ok
            if any(c.source == "no_candidate_sequence" for c in r.uncertainty_components)
        ]
        if missing_sequence:
            return {
                "action": "resolve_candidate_sequences",
                "rationale": (
                    "predictions were made from a generic peptide prior because the "
                    "candidate sequence was unavailable; these results are not "
                    "specific to the named candidates"
                ),
                "experiment_ids": [r.experiment_id for r in missing_sequence],
                "candidate_ids": sorted(
                    {r.candidate_id for r in missing_sequence if r.candidate_id}
                ),
                "detail": (
                    "supply spec.candidate.sequence, or pass a candidate_registry "
                    "mapping candidate_id to CandidateSpec"
                ),
            }

        # 2: an unspecified but influential condition
        imputed_drivers: list[dict[str, Any]] = []
        for r in ok:
            for f in r.important_factors[:_TOP_FACTORS]:
                if (
                    f.source.value == "imputed_default"
                    and abs(f.sensitivity) > _MATERIAL_SENSITIVITY
                ):
                    imputed_drivers.append(
                        {
                            "experiment_id": r.experiment_id,
                            "factor": f.factor,
                            "assumed_value": f.value,
                            "sensitivity": f.sensitivity,
                        }
                    )
        if imputed_drivers:
            return {
                "action": "specify_influential_conditions",
                "rationale": (
                    "conditions that were not specified in the spec are driving the "
                    "predicted outcome; the predictions describe the assumed defaults "
                    "rather than a defined experiment"
                ),
                "factors": imputed_drivers[:10],
            }

        # 4: sweep the most informative specified variable
        widest = max(ok, key=lambda r: (r.measurement.uncertainty or 0.0))
        top = widest.important_factors[0] if widest.important_factors else None
        suggestion: dict[str, Any] = {
            "action": "refine_with_condition_sweep",
            "rationale": (
                "the next most informative experiment varies the factor the model is "
                "most sensitive to, around the predicted transition region"
            ),
            "anchor_experiment_id": widest.experiment_id,
            "candidate_id": widest.candidate_id,
            "widest_uncertainty": widest.measurement.uncertainty,
        }
        if top is not None:
            suggestion["suggested_factor"] = top.factor
            suggestion["sensitivity"] = top.sensitivity
            base = top.value if isinstance(top.value, (int, float)) else None
            if base and base > 0:
                suggestion["suggested_values"] = [
                    round(base * m, 6) for m in (0.1, 0.3, 1.0, 3.0, 10.0)
                ]
        mic = widest.measurement.predicted_mic_um
        if mic:
            suggestion["predicted_transition_region_um"] = [
                round(mic * 0.25, 6),
                round(mic * 4.0, 6),
            ]
        return suggestion


def run_agent(payload: AgentInput | dict[str, Any]) -> AgentOutput:
    """Module-level convenience entry point for Omnigent tool calls."""
    return SimulationBackendAgent().run(payload)


SimulationAgent = SimulationBackendAgent

