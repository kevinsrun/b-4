"""Adapter for Literature & Evidence Agent (b4_literature)."""

from __future__ import annotations

from typing import Any

from bacteriocin_lab.agents.evidence.agent import LiteratureEvidenceAgent

from ..state import ResearchStateManager
from ..types import Evidence, ResearchState, content_id


class LiteratureAgentAdapter:
    """Invokes b4_literature to gather literature evidence for the current research objective."""

    name = "evidence"

    def __init__(self, agent: LiteratureEvidenceAgent | None = None) -> None:
        self.agent = agent or LiteratureEvidenceAgent()

    def run(self, state: ResearchState) -> dict[str, Any]:
        species = state.objective.species or "Listeria monocytogenes"
        query_id = content_id("evidence", {"species": species, "iteration": state.iteration})

        request = {
            "query_id": query_id,
            "question": f"Known bacteriocin activity and conditions against {species}",
            "target_organism": species,
            "bacteriocin": "bacteriocin",
            "retrieval": {"enabled": False},
        }

        response = self.agent.run(request)
        emitted_ids: list[str] = []

        state_mgr = ResearchStateManager(state)

        # Record each literature item as a provenance-carrying contract Evidence. The type is taken
        # from the agent's own record and defaults to literature-derived; it is never upgraded.
        for item in response.evidence:
            ev_id = item.evidence_id or content_id(
                "evidence",
                {"source": item.source.source_id if item.source else "", "claim": item.claim},
            )
            source_id = item.source.source_id if item.source else "literature"
            evidence = Evidence(
                evidence_id=ev_id,
                evidence_type=getattr(item, "evidence_type", None) or "literature-derived",
                claim=item.claim,
                source=source_id,
                confidence=getattr(item, "confidence", None),
            )
            if state_mgr.add_evidence(evidence, source_agent=self.name):
                emitted_ids.append(ev_id)

        # Add generic knowledge gap if none found
        if not response.evidence:
            gap = f"Sparse published quantitative MIC curves for {species} under specified cell densities."
            if gap not in state.knowledge_gaps:
                state.knowledge_gaps.append(gap)

        return {
            "agent": self.name,
            "status": "success",
            "query_id": query_id,
            "evidence_count": len(response.evidence),
            "output_ids": emitted_ids,
        }
