"""Research state manager ensuring append-only scientific history, idempotency, and provenance integrity."""

from __future__ import annotations

from typing import Any

from .types import (
    Candidate,
    Evidence,
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
        # A failed run is a failure to record, not scientific evidence: it has no measurement and
        # downstream agents would analyse nothing.
        if getattr(result, "status", "ok") != "ok":
            raise ValueError(
                f"Result {result.result_id} has status {result.status!r}; failed runs are recorded "
                "with record_experiment_failure, never stored as results"
            )
        # Enforce contract rule 9 & 10: never claim wet-lab validation from simulation. Judge by the
        # assay domain as well as the backend label so a mislabelled backend cannot launder it.
        simulated = result.backend == "simulation" or str(
            getattr(result.assay_domain, "value", result.assay_domain)
        ).startswith("simulated")
        if result.evidence_type == EvidenceType.WET_LAB and simulated:
            raise ValueError("Simulation result cannot be labeled as wet-lab-derived")
        if result.validated_experimentally and simulated:
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
                "evidence_type": getattr(result.evidence_type, "value", str(result.evidence_type)),
                "inhibition": inhibition,
            },
        )
        return True

    def add_evidence(self, evidence: Evidence, source_agent: str = "evidence_agent") -> bool:
        """Add a provenance-carrying evidence record idempotently, preserving its evidence_type.

        ``wet-lab-derived`` evidence is refused here: the only legitimate source is a real wet-lab
        adapter, which does not exist yet. Simulation output is not evidence of this kind; it is
        stored as an ExperimentResult with its own provenance.
        """
        if evidence.evidence_type == "wet-lab-derived":
            raise ValueError("wet-lab-derived evidence cannot enter state without a wet-lab adapter")
        for existing in self.state.evidence:
            if existing.evidence_id == evidence.evidence_id:
                return False
        self.state.evidence.append(evidence)
        self.record_event(
            event_type="evidence_added",
            source_agent=source_agent,
            summary=f"Evidence {evidence.evidence_id} ({evidence.evidence_type}): {evidence.claim[:80]}",
            data={
                "evidence_id": evidence.evidence_id,
                "evidence_type": evidence.evidence_type,
                "source": evidence.source,
            },
        )
        return True

    def record_experiment_failure(
        self, experiment_id: str, error: str, source_agent: str = "simulation_agent"
    ) -> None:
        """Log that an experiment could not produce a result. Never creates a result."""
        self.record_event(
            event_type="experiment_failed",
            source_agent=source_agent,
            summary=f"Experiment {experiment_id} produced no result: {error[:100]}",
            data={"experiment_id": experiment_id, "error": error},
        )

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


class StateIntegrityError(ValueError):
    """The research state is internally inconsistent; the dispatch that produced it is rejected."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def check_state_integrity(state: ResearchState) -> list[str]:
    """Return every integrity problem in ``state`` (empty list == consistent).

    Agents mutate state directly, so nothing stops one from appending an object that bypassed
    validation or that points at records which do not exist. This is the one check that does not
    trust the agent: records are re-validated from their serialised form and references are resolved.
    """
    problems: list[str] = []
    try:
        ResearchState.model_validate(state.model_dump(mode="json"))
    except Exception as exc:  # every validation failure is reported as a problem, not raised
        first = str(exc).strip().splitlines()
        problems.append(f"state failed schema re-validation: {first[0] if first else exc}")
        return problems  # references are meaningless if the records themselves are invalid

    def dupes(label: str, ids: list[str]) -> None:
        seen: set[str] = set()
        for i in ids:
            if i in seen:
                problems.append(f"duplicate {label} id {i!r}")
            seen.add(i)

    dupes("candidate", [c.candidate_id for c in state.candidates])
    dupes("hypothesis", [h.hypothesis_id for h in state.hypotheses])
    dupes("experiment", [e.experiment_id for e in state.experiments])
    dupes("result", [r.result_id for r in state.results])
    dupes("finding", [f.finding_id for f in state.findings])
    dupes("review", [r.review_id for r in state.reviews])
    dupes("evidence", [e.evidence_id for e in state.evidence])

    for label, ids in (
        ("candidate", [c.candidate_id for c in state.candidates]),
        ("hypothesis", [h.hypothesis_id for h in state.hypotheses]),
        ("experiment", [e.experiment_id for e in state.experiments]),
        ("result", [r.result_id for r in state.results]),
        ("finding", [f.finding_id for f in state.findings]),
        ("review", [r.review_id for r in state.reviews]),
    ):
        if any(not i for i in ids):
            problems.append(f"empty {label} id")

    cand_ids = {c.candidate_id for c in state.candidates}
    hyp_ids = {h.hypothesis_id for h in state.hypotheses}
    exp_ids = {e.experiment_id for e in state.experiments}
    result_ids = {r.result_id for r in state.results}
    evidence_ids = {e.evidence_id for e in state.evidence}

    for h in state.hypotheses:
        if h.candidate_id and h.candidate_id not in cand_ids:
            problems.append(f"hypothesis {h.hypothesis_id} cites unknown candidate {h.candidate_id}")
    for e in state.experiments:
        if e.candidate_id and e.candidate_id not in cand_ids:
            problems.append(f"experiment {e.experiment_id} cites unknown candidate {e.candidate_id}")
    for r in state.results:
        if r.experiment_id not in exp_ids:
            problems.append(f"result {r.result_id} cites unknown experiment {r.experiment_id}")
        if r.candidate_id and r.candidate_id not in cand_ids:
            problems.append(f"result {r.result_id} cites unknown candidate {r.candidate_id}")
    for f in state.findings:
        for cid in f.candidate_ids:
            if cid not in cand_ids:
                problems.append(f"finding {f.finding_id} cites unknown candidate {cid}")
        for hid in f.hypothesis_ids:
            if hid not in hyp_ids:
                problems.append(f"finding {f.finding_id} cites unknown hypothesis {hid}")
        for eid in f.evidence_ids:
            if eid not in result_ids and eid not in evidence_ids:
                problems.append(f"finding {f.finding_id} cites unknown evidence/result {eid}")
    for cid in state.tested_candidate_ids + state.settled_candidate_ids:
        if cid not in cand_ids:
            problems.append(f"candidate list references unknown candidate {cid}")
    return problems
