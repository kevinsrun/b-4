"""Deterministic fixture agents for fast, reproducible, offline integration testing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..state import ResearchStateManager
from ..types import (
    Candidate,
    Conditions,
    EvidenceType,
    ExperimentResult,
    ExperimentSpec,
    Finding,
    Hypothesis,
    Measurement,
    ResearchState,
    Review,
    Target,
    content_id,
)


class FakeEvidenceAgent:
    """Deterministic evidence agent returning bounded literature claims."""

    name = "evidence"

    def __init__(self, fixed_evidence: list[dict[str, Any]] | None = None) -> None:
        self.call_count = 0
        self.fixed_evidence = fixed_evidence

    def run(self, state: ResearchState) -> dict[str, Any]:
        self.call_count += 1
        species = state.objective.species or "Listeria monocytogenes"
        ev_id = content_id("evidence", {"species": species, "idx": self.call_count})

        # Add literature claim to knowledge gaps / evidence
        claim = f"Nisin and class IIa bacteriocins exhibit nanomolar activity against {species} in broth assays."
        if not state.knowledge_gaps:
            state.knowledge_gaps.append(
                f"Inoculum effect curves across 1e5-1e9 CFU/mL for {species}"
            )

        return {
            "agent": self.name,
            "status": "success",
            "output_ids": [ev_id],
            "claim": claim,
        }


class FakeCandidateAgent:
    """Deterministic candidate generator proposing predictable bacteriocin candidates."""

    name = "candidate"

    def __init__(self, candidates_to_propose: list[Candidate] | None = None) -> None:
        self.call_count = 0
        self.candidates_to_propose = candidates_to_propose

    def run(self, state: ResearchState) -> dict[str, Any]:
        self.call_count += 1
        state_mgr = ResearchStateManager(state)

        if self.candidates_to_propose:
            # Filter out already settled candidates
            to_add = [
                c
                for c in self.candidates_to_propose
                if c.candidate_id not in state.settled_candidate_ids
            ]
        else:
            # Default deterministic progression: B17 first, then alternative B42
            if "cand_b17" in state.settled_candidate_ids:
                to_add = [
                    Candidate(
                        candidate_id="cand_b42",
                        name="B42-pediocin-variant",
                        sequence="KYYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC",
                        score_total=0.91,
                        confidence=0.82,
                        validation_status="unvalidated",
                        rank=1,
                    )
                ]
            else:
                to_add = [
                    Candidate(
                        candidate_id="cand_b17",
                        name="B17",
                        sequence="ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
                        score_total=0.88,
                        confidence=0.75,
                        validation_status="unvalidated",
                        rank=1,
                    )
                ]

        added_cids = state_mgr.add_candidates(to_add, source_agent=self.name)

        # Propose associated hypothesis
        hypotheses = []
        for cand in to_add:
            hid = f"hyp_{cand.candidate_id}_efficacy"
            hypotheses.append(
                Hypothesis(
                    hypothesis_id=hid,
                    candidate_id=cand.candidate_id,
                    statement=f"{cand.name} inhibits target robustly across varying cell densities.",
                    prior_plausibility=0.6,
                    status="open",
                )
            )
        added_hids = state_mgr.add_hypotheses(hypotheses, source_agent=self.name)

        return {
            "agent": self.name,
            "status": "success",
            "candidates_count": len(to_add),
            "output_ids": added_cids + added_hids,
        }


class FakePlannerAgent:
    """Deterministic experiment planner demonstrating adaptive follow-up based on results."""

    name = "planner"

    def __init__(self, override_spec: ExperimentSpec | None = None) -> None:
        self.call_count = 0
        self.override_spec = override_spec

    def run(self, state: ResearchState) -> dict[str, Any]:
        self.call_count += 1
        state_mgr = ResearchStateManager(state)

        if self.override_spec:
            state_mgr.add_experiment_spec(self.override_spec, source_agent=self.name)
            return {
                "agent": self.name,
                "status": "success",
                "output_ids": [self.override_spec.experiment_id],
                "experiment_id": self.override_spec.experiment_id,
            }

        # Select candidate
        active_cands = [
            c for c in state.candidates if c.candidate_id not in state.settled_candidate_ids
        ]
        candidate = (
            active_cands[0] if active_cands else (state.candidates[0] if state.candidates else None)
        )
        cid = candidate.candidate_id if candidate else "cand_b17"

        # Adaptive logic:
        # Check previous results for this candidate
        cand_results = [r for r in state.results if r.candidate_id == cid]

        # Check latest review: did critic or analysis ask for high density?
        latest_review = state.reviews[-1] if state.reviews else None
        density_requested = (
            latest_review
            and latest_review.status == "needs_more_evidence"
            and latest_review.recommendation.get("focus") == "target_cell_density"
        )

        if cand_results and (
            density_requested or cand_results[-1].measurement.predicted_inhibition_fraction >= 0.7
        ):
            # ADAPTATION: Switch from low density (1e6) to high density (1e8)
            density = 1e8
            reason = "Adaptive follow-up: test efficacy at elevated target cell density 1e8 CFU/mL."
        else:
            density = 1e6
            reason = "Initial screening: test efficacy at standard cell density 1e6 CFU/mL."

        exp_id = f"exp_{cid}_d{int(density):g}_{self.call_count}"
        spec = ExperimentSpec(
            experiment_id=exp_id,
            candidate_id=cid,
            target=Target(species=state.objective.species or "Listeria monocytogenes"),
            conditions=Conditions(
                bacteriocin_concentration=10.0,
                target_cell_density=density,
                ph=7.0,
                temperature_c=37.0,
            ),
            notes=reason,
        )

        state_mgr.add_experiment_spec(spec, source_agent=self.name)

        return {
            "agent": self.name,
            "status": "success",
            "output_ids": [exp_id],
            "experiment_id": exp_id,
            "density": density,
        }


class FakeSimulatorAgent:
    """Deterministic simulation runner predicting controlled outcomes."""

    name = "simulation"

    def __init__(
        self,
        outcome_fn: Callable[[ExperimentSpec], tuple[float, float]] | None = None,
        should_fail: bool = False,
        malformed_output: bool = False,
    ) -> None:
        self.call_count = 0
        self.outcome_fn = outcome_fn
        self.should_fail = should_fail
        self.malformed_output = malformed_output

    def run(self, state: ResearchState) -> dict[str, Any]:
        self.call_count += 1
        state_mgr = ResearchStateManager(state)

        if self.should_fail:
            raise RuntimeError("Simulation engine encountered ODE convergence failure.")

        if self.malformed_output:
            # Returns invalid output missing required result_id
            return {"agent": self.name, "malformed": True}

        if not state.experiments:
            return {"agent": self.name, "status": "skipped", "output_ids": []}

        latest_spec = state.experiments[-1]
        cid = latest_spec.candidate_id or "cand_b17"
        density = latest_spec.conditions.target_cell_density if latest_spec.conditions else 1e6

        if self.outcome_fn:
            inhibition, uncertainty = self.outcome_fn(latest_spec)
        else:
            # Default outcome:
            # If B17 at 1e6 -> 0.88 (potent)
            # If B17 at 1e8 -> 0.47 (density sensitive drop!)
            # If B42 at 1e8 -> 0.91 (potent at high density)
            if cid == "cand_b42":
                inhibition = 0.91
                uncertainty = 0.05
            elif density and density >= 1e7:
                inhibition = 0.47
                uncertainty = 0.08
            else:
                inhibition = 0.88
                uncertainty = 0.04

        res_id = f"res_{latest_spec.experiment_id}"
        result = ExperimentResult(
            result_id=res_id,
            experiment_id=latest_spec.experiment_id,
            candidate_id=cid,
            conditions=latest_spec.conditions.model_dump() if latest_spec.conditions else {},
            measurement=Measurement(
                predicted_inhibition_fraction=inhibition,
                predicted_survival_fraction=1.0 - inhibition,
                predicted_activity=inhibition,
                uncertainty=uncertainty,
            ),
            evidence_type=EvidenceType.SIMULATION,
            validated_experimentally=False,
            backend="simulation",
            confidence=0.85,
        )

        state_mgr.add_experiment_result(result, source_agent=self.name)

        return {
            "agent": self.name,
            "status": "success",
            "output_ids": [res_id],
            "result_id": res_id,
            "inhibition": inhibition,
        }


class FakeAnalysisAgent:
    """Deterministic result analysis agent."""

    name = "analysis"

    def __init__(self, override_finding_status: str | None = None) -> None:
        self.call_count = 0
        self.override_finding_status = override_finding_status

    def run(self, state: ResearchState) -> dict[str, Any]:
        self.call_count += 1
        state_mgr = ResearchStateManager(state)

        latest_res = state.results[-1] if state.results else None
        if not latest_res:
            return {"agent": self.name, "status": "skipped", "output_ids": []}

        inhibition = latest_res.measurement.predicted_inhibition_fraction or 0.5
        cid = latest_res.candidate_id or "cand_b17"
        cond = latest_res.conditions if isinstance(latest_res.conditions, dict) else {}
        density = cond.get("target_cell_density", 1e6)

        # Check for density drop
        prev_res = [r for r in state.results[:-1] if r.candidate_id == cid]
        if self.override_finding_status:
            status = self.override_finding_status
            statement = f"Finding for {cid} forced to {status}."
        elif prev_res and density >= 1e7 and inhibition < 0.6:
            status = "weakened"
            statement = f"Candidate {cid} demonstrated marked density sensitivity: inhibition fell to {inhibition:.2f} at {density:g} CFU/mL."
        elif inhibition >= 0.7:
            status = "supported"
            statement = f"Candidate {cid} demonstrated strong inhibition ({inhibition:.2f}) at density {density:g}."
        else:
            status = "contradicted"
            statement = f"Candidate {cid} demonstrated inadequate inhibition ({inhibition:.2f})."

        finding_id = f"find_{latest_res.result_id}_{self.call_count}"
        matched_hids = [h.hypothesis_id for h in state.hypotheses if h.candidate_id == cid]

        finding = Finding(
            finding_id=finding_id,
            statement=statement,
            status=status,  # type: ignore
            confidence=0.85,
            candidate_ids=[cid],
            hypothesis_ids=matched_hids,
            evidence_ids=[latest_res.result_id],
        )
        state_mgr.add_finding(finding, source_agent=self.name)

        return {
            "agent": self.name,
            "status": "success",
            "output_ids": [finding_id],
            "finding_id": finding_id,
            "status_label": status,
        }


class FakeCriticAgent:
    """Deterministic scientific critic and safety agent."""

    name = "critic"

    def __init__(self, forced_status: str | None = None) -> None:
        self.call_count = 0
        self.forced_status = forced_status

    def run(self, state: ResearchState) -> dict[str, Any]:
        self.call_count += 1
        state_mgr = ResearchStateManager(state)

        latest_finding = state.findings[-1] if state.findings else None
        latest_res = state.results[-1] if state.results else None
        cond = (
            latest_res.conditions if latest_res and isinstance(latest_res.conditions, dict) else {}
        )
        density = cond.get("target_cell_density", 1e6)

        if self.forced_status:
            status = self.forced_status
            critique = f"Critic returned forced status: {status}."
        elif (
            latest_finding
            and latest_finding.status == "supported"
            and density < 1e7
            and (state.objective.desired_behavior or {}).get("target_cell_density", 0) >= 1e7
        ):
            # Need more evidence at high density!
            status = "needs_more_evidence"
            critique = "Candidate is potent at low density; verify efficacy at high density."
        elif latest_finding and latest_finding.status == "contradicted":
            status = "rejected"
            critique = "Candidate failed potency requirements; rejected."
        elif latest_finding and latest_finding.status in ("supported", "weakened"):
            status = "approved"
            critique = "Finding supported by simulation evidence."
        else:
            status = "experiment_inconclusive"
            critique = "Inconclusive results."

        review_id = f"rev_{state.iteration}_{self.call_count}"
        review = Review(
            review_id=review_id,
            status=status,  # type: ignore
            critique=critique,
            recommendation={"focus": "target_cell_density"}
            if status == "needs_more_evidence"
            else {},
        )
        state_mgr.add_review(review, source_agent=self.name)

        return {
            "agent": self.name,
            "status": status,
            "output_ids": [review_id],
            "review_id": review_id,
        }


class FakeKnowledgeAgent:
    """Deterministic knowledge agent updating state and advancing iterations."""

    name = "knowledge"

    def run(self, state: ResearchState) -> dict[str, Any]:
        state_mgr = ResearchStateManager(state)
        latest_finding = state.findings[-1] if state.findings else None

        if latest_finding:
            for hid in latest_finding.hypothesis_ids:
                state_mgr.update_hypothesis_status(
                    hid,
                    new_status=latest_finding.status,
                    source_agent=self.name,
                    reason=latest_finding.statement,
                )
            if latest_finding.status in ("contradicted", "weakened"):
                for cid in latest_finding.candidate_ids:
                    if cid not in state.settled_candidate_ids:
                        state.settled_candidate_ids.append(cid)

        state.iteration += 1
        ev_id = state_mgr.record_event(
            event_type="knowledge_updated",
            source_agent=self.name,
            summary=f"Iteration {state.iteration - 1} committed to knowledge state.",
        )

        return {
            "agent": self.name,
            "status": "success",
            "output_ids": [ev_id],
            "iteration": state.iteration,
        }
