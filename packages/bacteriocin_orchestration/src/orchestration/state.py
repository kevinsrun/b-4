"""Research state manager ensuring append-only scientific history, idempotency, and provenance integrity."""

from __future__ import annotations

from typing import Any

from .types import (
    Candidate,
    EvidenceType,
    ExperimentResult,
    ExperimentSpec,
    Finding,
    Hypothesis,
    ResearchState,
    Review,
    ScientificEvent,
    content_id,
)


class ResearchStateManager:
    """Encapsulates mutation of ResearchState adhering to shared system contracts.

    Guarantees:
    1. Append-only scientific history.
    2. Idempotent insertion (no duplicate experiments, results, findings, reviews).
    3. Strict provenance preservation (never converts simulation to wet-lab).
    """

    def __init__(self, state: ResearchState) -> None:
        self.state = state

    def record_event(
        self,
        event_type: str,
        source_agent: str,
        summary: str,
        data: dict[str, Any] | None = None,
    ) -> str:
        """Append an immutable scientific event to the history log."""
        iteration = self.state.iteration
        event_id = content_id(
            "run",
            {
                "event_type": event_type,
                "iteration": iteration,
                "history_len": len(self.state.scientific_history),
                "summary": summary,
            },
        )
        event = ScientificEvent(
            event_id=event_id,
            event_type=event_type,
            iteration=iteration,
            source_agent=source_agent,
            summary=summary,
            data=dict(data or {}),
        )
        self.state.scientific_history.append(event)
        return event_id

    def add_candidates(
        self, candidates: list[Candidate], source_agent: str = "candidate_agent"
    ) -> list[str]:
        """Add candidates idempotently, updating existing ones without duplicating."""
        added_ids: list[str] = []
        for cand in candidates:
            existing = self.state.get_candidate(cand.candidate_id)
            if existing is None:
                self.state.candidates.append(cand)
                added_ids.append(cand.candidate_id)
                self.record_event(
                    event_type="candidate_proposed",
                    source_agent=source_agent,
                    summary=f"Proposed candidate {cand.name or cand.candidate_id} (score: {cand.score_total:.3f})",
                    data=cand.model_dump(),
                )
            else:
                # Update attributes while keeping the ID
                existing.score_total = cand.score_total
                existing.confidence = cand.confidence
                if cand.sequence and not existing.sequence:
                    existing.sequence = cand.sequence
        return added_ids

    def add_hypotheses(
        self, hypotheses: list[Hypothesis], source_agent: str = "candidate_agent"
    ) -> list[str]:
        """Add or update hypotheses, recording status changes in history."""
        added_ids: list[str] = []
        for hyp in hypotheses:
            existing = self.state.get_hypothesis(hyp.hypothesis_id)
            if existing is None:
                self.state.hypotheses.append(hyp)
                added_ids.append(hyp.hypothesis_id)
                self.record_event(
                    event_type="hypothesis_created",
                    source_agent=source_agent,
                    summary=f"Created hypothesis {hyp.hypothesis_id}: {hyp.statement}",
                    data=hyp.model_dump(),
                )
            else:
                if existing.status != hyp.status:
                    old_status = existing.status
                    existing.status = hyp.status
                    existing.posterior_probability = hyp.posterior_probability
                    self.record_event(
                        event_type="hypothesis_status_changed",
                        source_agent=source_agent,
                        summary=f"Hypothesis {hyp.hypothesis_id} changed status from {old_status} to {hyp.status}",
                        data={
                            "hypothesis_id": hyp.hypothesis_id,
                            "old_status": old_status,
                            "new_status": hyp.status,
                        },
                    )
        return added_ids

    def update_hypothesis_status(
        self,
        hypothesis_id: str,
        new_status: str,
        source_agent: str,
        reason: str = "",
    ) -> bool:
        """Update an existing hypothesis status, recording the transition in append-only history."""
        hyp = self.state.get_hypothesis(hypothesis_id)
        if hyp is None:
            return False
        old_status = hyp.status
        hyp.status = new_status  # type: ignore
        self.record_event(
            event_type="hypothesis_status_changed",
            source_agent=source_agent,
            summary=f"Hypothesis {hypothesis_id} updated {old_status} -> {new_status}: {reason}",
            data={
                "hypothesis_id": hypothesis_id,
                "old_status": old_status,
                "new_status": new_status,
                "reason": reason,
            },
        )
        return True

    def add_experiment_spec(
        self, spec: ExperimentSpec, source_agent: str = "planner_agent"
    ) -> bool:
        """Add an experiment spec idempotently (checking by experiment_id and spec_hash)."""
        for existing in self.state.experiments:
            if existing.experiment_id == spec.experiment_id:
                return False
            # Check spec hash to avoid identical scientific experiments under different IDs
            if (
                hasattr(existing, "spec_hash")
                and hasattr(spec, "spec_hash")
                and existing.spec_hash() == spec.spec_hash()
            ):
                return False

        self.state.experiments.append(spec)
        self.record_event(
            event_type="experiment_planned",
            source_agent=source_agent,
            summary=f"Planned experiment {spec.experiment_id} for candidate {spec.candidate_id}",
            data={"experiment_id": spec.experiment_id, "candidate_id": spec.candidate_id},
        )
        return True

    def add_experiment_result(
        self, result: ExperimentResult, source_agent: str = "simulation_agent"
    ) -> bool:
        """Add an experiment result idempotently with provenance enforcement."""
        # Enforce contract rule 9 & 10: never claim wet-lab validation from simulation
        if result.evidence_type == EvidenceType.WET_LAB and result.backend == "simulation":
            raise ValueError("Simulation result cannot be labeled as wet-lab-derived")
        if result.validated_experimentally and result.backend == "simulation":
            raise ValueError("Simulation result cannot claim experimental validation")

        for existing in self.state.results:
            if existing.result_id == result.result_id:
                return False

        self.state.results.append(result)
        if result.candidate_id and result.candidate_id not in self.state.tested_candidate_ids:
            self.state.tested_candidate_ids.append(result.candidate_id)

        inhibition = (
            result.measurement.predicted_inhibition_fraction if result.measurement else None
        )
        self.record_event(
            event_type="experiment_executed",
            source_agent=source_agent,
            summary=(
                f"Executed experiment {result.experiment_id} "
                f"(result {result.result_id}, inhibition={inhibition})"
            ),
            data={
                "result_id": result.result_id,
                "experiment_id": result.experiment_id,
                "candidate_id": result.candidate_id,
                "evidence_type": str(result.evidence_type),
                "inhibition": inhibition,
            },
        )
        return True

    def add_finding(self, finding: Finding, source_agent: str = "analysis_agent") -> bool:
        """Add an analysis finding idempotently."""
        for existing in self.state.findings:
            if existing.finding_id == finding.finding_id:
                return False

        self.state.findings.append(finding)
        self.record_event(
            event_type="finding_generated",
            source_agent=source_agent,
            summary=f"Finding {finding.finding_id}: {finding.statement} ({finding.status})",
            data=finding.model_dump(),
        )
        return True

    def add_review(self, review: Review, source_agent: str = "critic_agent") -> bool:
        """Add a critic review idempotently."""
        for existing in self.state.reviews:
            if existing.review_id == review.review_id:
                return False

        self.state.reviews.append(review)
        self.record_event(
            event_type="review_completed",
            source_agent=source_agent,
            summary=f"Review {review.review_id}: status={review.status}, critique={review.critique[:60]}",
            data=review.model_dump(),
        )
        return True
