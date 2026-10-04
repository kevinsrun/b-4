"""Adapter for Candidate Generation & Design Agent (bacteriocin_discovery)."""

from __future__ import annotations

from typing import Any

from bacteriocin_lab.agents.candidate import CandidateGenerationAgent, generate_candidates

from ..state import ResearchStateManager
from ..types import Candidate, Hypothesis, ResearchState


class CandidateAgentAdapter:
    """Wraps CandidateGenerationAgent to propose ranked bacteriocin candidates and hypotheses."""

    name = "candidate"

    def __init__(self, agent: CandidateGenerationAgent | None = None) -> None:
        self.agent = agent

    def run(self, state: ResearchState) -> dict[str, Any]:
        state_mgr = ResearchStateManager(state)
        species = state.objective.species or "Listeria monocytogenes"
        gram = state.objective.gram or "positive"

        request = {
            "target": {
                "organism": species,
                "strain": state.objective.strain or "standard",
                "gram": gram,
            },
            "desired_behavior": dict(state.objective.desired_behavior or {"high_inhibition": True}),
            "constraints": {
                "max_candidates": state.objective.constraints.get("max_candidates", 3),
                "exclude_candidate_ids": list(state.settled_candidate_ids),
                "diversity_weight": 0.3,
            },
            "previous_results": [r.model_dump() for r in state.results],
            "evidence": [item.model_dump(mode="json") for item in state.evidence],
            "competing_hypotheses": [
                {
                    "hypothesis_id": h.hypothesis_id,
                    "statement": h.statement,
                    "discriminating_feature": h.discriminating_feature,
                    "favourable_range": h.favourable_range,
                    "status": h.status,
                }
                for h in state.hypotheses
                if h.discriminating_feature
            ],
        }

        if self.agent:
            response_dict = self.agent.run_envelope(request).model_dump(mode="json")
        else:
            response_dict = generate_candidates(request)

        raw_candidates = (
            response_dict.get("candidates")
            or response_dict.get("decision", {}).get("candidates")
            or []
        )
        candidates_to_add: list[Candidate] = []
        hypotheses_to_add: list[Hypothesis] = []

        for i, c in enumerate(raw_candidates):
            cid = (
                c.get("candidate_id")
                or f"cand_{c.get('name', 'bacteriocin').lower().replace(' ', '_')}"
            )

            score_val = c.get("score_total")
            if score_val is None and isinstance(c.get("score"), dict):
                score_val = c["score"].get("total", 0.5)
            elif score_val is None and isinstance(c.get("score"), (int, float)):
                score_val = c.get("score")

            cand = Candidate(
                candidate_id=cid,
                name=c.get("name", "Unknown"),
                sequence=c.get("sequence"),
                source=c.get("source", "candidate_generation"),
                score_total=float(score_val if score_val is not None else 0.5),
                confidence=float(c.get("confidence", 0.5)),
                features=dict(c.get("features") or {}),
                evidence_ids=list(c.get("evidence_ids") or []),
                falsified_if=c.get("falsified_if"),
                validation_status="unvalidated",
                rank=c.get("rank", i + 1),
            )
            candidates_to_add.append(cand)

            # Ingest hypotheses attached to candidate
            cand_hyps = c.get("hypotheses") or []
            for h in cand_hyps:
                hid = (
                    h.get("hypothesis_id")
                    or f"hyp_{len(state.hypotheses) + len(hypotheses_to_add) + 1}"
                )
                hyp = Hypothesis(
                    hypothesis_id=hid,
                    candidate_id=cid,
                    statement=h.get("statement", ""),
                    prediction=h.get("predicted_direction") or h.get("prediction"),
                    predicted_direction=h.get("predicted_direction"),
                    predicted_inhibition_fraction=h.get("predicted_inhibition_fraction"),
                    expected_relationship=h.get("expected_relationship"),
                    key_conditions=dict(h.get("key_conditions") or {}),
                    tolerance=h.get("tolerance"),
                    status="open",
                    prior_plausibility=float(
                        h.get("prior_plausibility") or h.get("confidence") or 0.5
                    ),
                    posterior_probability=float(h.get("posterior_probability") or 0.5),
                    discriminating_feature=h.get("discriminating_feature"),
                    favourable_range=h.get("favourable_range"),
                    falsified_if=h.get("falsified_if"),
                    evidence_ids=list(h.get("evidence_ids") or []),
                )
                hypotheses_to_add.append(hyp)

        added_cids = state_mgr.add_candidates(candidates_to_add, source_agent=self.name)

        # Ingest top-level hypotheses if present
        raw_hypotheses = response_dict.get("hypotheses") or []
        for h in raw_hypotheses:
            hid = (
                h.get("hypothesis_id")
                or f"hyp_{len(state.hypotheses) + len(hypotheses_to_add) + 1}"
            )
            hyp = Hypothesis(
                hypothesis_id=hid,
                candidate_id=h.get("candidate_id"),
                statement=h.get("statement", ""),
                prediction=h.get("prediction"),
                predicted_direction=h.get("predicted_direction"),
                predicted_inhibition_fraction=h.get("predicted_inhibition_fraction"),
                expected_relationship=h.get("expected_relationship"),
                key_conditions=dict(h.get("key_conditions") or {}),
                tolerance=h.get("tolerance"),
                status="open",
                prior_plausibility=float(h.get("prior_plausibility", 0.5)),
                posterior_probability=float(h.get("posterior_probability", 0.5)),
                discriminating_feature=h.get("discriminating_feature"),
                favourable_range=h.get("favourable_range"),
                falsified_if=h.get("falsified_if"),
                evidence_ids=list(h.get("evidence_ids") or []),
            )
            hypotheses_to_add.append(hyp)

        added_hids = state_mgr.add_hypotheses(hypotheses_to_add, source_agent=self.name)

        return {
            "agent": self.name,
            "status": "success",
            "candidates_count": len(candidates_to_add),
            "output_ids": added_cids + added_hids,
            "recommended_next_action": response_dict.get("recommended_next_action"),
        }
