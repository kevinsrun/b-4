"""Knowledge / Research-State Agent: updates state, hypothesis status, and audit log."""

from __future__ import annotations

from typing import Any

from ..state import ResearchStateManager
from ..types import ResearchState


class KnowledgeAgent:
    """Consolidates verified findings, updates hypothesis status, and advances campaign iteration."""

    name = "knowledge"

    def run(self, state: ResearchState) -> dict[str, Any]:
        state_mgr = ResearchStateManager(state)

        latest_finding = state.findings[-1] if state.findings else None
        latest_review = state.reviews[-1] if state.reviews else None

        updated_hyps: list[str] = []
        settled_cands: list[str] = []

        if latest_finding:
            # Update matching hypotheses
            for hid in latest_finding.hypothesis_ids:
                new_status = latest_finding.status
                if new_status in ("supported", "contradicted", "weakened") and state_mgr.update_hypothesis_status(
                    hid,
                    new_status=new_status,
                    source_agent=self.name,
                    reason=latest_finding.statement,
                ):
                    updated_hyps.append(hid)

            # If candidate was contradicted or acutely weakened, mark candidate settled
            if latest_finding.status in ("contradicted", "weakened"):
                for cid in latest_finding.candidate_ids:
                    if cid not in state.settled_candidate_ids:
                        state.settled_candidate_ids.append(cid)
                        settled_cands.append(cid)

        # Advance campaign iteration
        state.iteration += 1

        event_id = state_mgr.record_event(
            event_type="knowledge_updated",
            source_agent=self.name,
            summary=(
                f"Completed iteration {state.iteration - 1}. "
                f"Updated hypotheses: {updated_hyps}, settled candidates: {settled_cands}"
            ),
            data={
                "iteration": state.iteration,
                "updated_hypotheses": updated_hyps,
                "settled_candidates": settled_cands,
                "review_status": latest_review.status if latest_review else None,
            },
        )

        return {
            "agent": self.name,
            "status": "success",
            "iteration": state.iteration,
            "updated_hypotheses": updated_hyps,
            "settled_candidates": settled_cands,
            "output_ids": [event_id],
        }
