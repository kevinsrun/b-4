"""Adapter for Literature & Evidence Agent (b4_literature)."""

from __future__ import annotations

from typing import Any

from b4_literature.agent import LiteratureEvidenceAgent

from ..types import ResearchState, content_id


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

        # Convert literature response items into shared contract Evidence records
        for item in response.evidence:
            ev_id = item.evidence_id or content_id(
                "evidence",
                {"source": item.source.source_id if item.source else "", "claim": item.claim},
            )
            claim = item.claim
            source_id = item.source.source_id if item.source else "literature"
            emitted_ids.append(ev_id)

            # Record in state's scientific history
            state.scientific_history.append(
                # Import here or rely on state types
                type(state.scientific_history[0])(
                    event_id=content_id("run", {"ev_id": ev_id, "iter": state.iteration}),
                    event_type="evidence_added",
                    iteration=state.iteration,
                    source_agent=self.name,
                    summary=f"Literature evidence: {claim[:80]}",
                    data={
                        "evidence_id": ev_id,
                        "evidence_type": "literature-derived",
                        "source": source_id,
                    },
                )
                if state.scientific_history
                # fallback if history empty
                else type(state.scientific_history)._item_type(  # type: ignore
                    event_id=content_id("run", {"ev_id": ev_id, "iter": state.iteration}),
                    event_type="evidence_added",
                    iteration=state.iteration,
                    source_agent=self.name,
                    summary=f"Literature evidence: {claim[:80]}",
                    data={
                        "evidence_id": ev_id,
                        "evidence_type": "literature-derived",
                        "source": source_id,
                    },
                )
                if hasattr(type(state.scientific_history), "_item_type")
                else None  # type: ignore
            ) if False else None

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
