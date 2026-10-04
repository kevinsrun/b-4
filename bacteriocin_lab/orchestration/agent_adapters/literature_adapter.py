"""Adapter for Literature & Evidence Agent (b4_literature)."""

from __future__ import annotations

from typing import Any

from bacteriocin_lab.agents.evidence.agent import LiteratureEvidenceAgent

from ..state import ResearchStateManager
from ..types import Evidence, ResearchState, content_id

_POSITIVE_ACTIVITY = {"active", "susceptible", "sensitive"}
_NEGATIVE_ACTIVITY = {"inactive", "resistant", "insensitive"}
_LITERATURE_MODES = {"local", "live_ncbi", "hybrid"}
_LITERATURE_SOURCES = {"europe_pmc", "ncbi", "ncbi_pubmed", "ncbi_pmc"}


def _candidate_payload(item: Any, contested_ids: set[str]) -> dict[str, Any] | None:
    """Map an unambiguous activity classification to the candidate agent's input shape."""
    if item.evidence_id in contested_ids or item.measurement.type != "antimicrobial_activity":
        return None

    activity = str(item.measurement.value or "").strip().casefold()
    if activity not in _POSITIVE_ACTIVITY | _NEGATIVE_ACTIVITY:
        return None

    name = item.bacteriocin.name
    sequence = item.bacteriocin.sequence
    target = item.target.organism
    if not (name or sequence) or not target:
        return None

    return {
        "name": name or item.bacteriocin.sequence_accession or "unnamed bacteriocin",
        "sequence": sequence,
        "origin": "literature",
        "known_targets": [target] if activity in _POSITIVE_ACTIVITY else [],
        "known_non_targets": [target] if activity in _NEGATIVE_ACTIVITY else [],
        "accession": item.bacteriocin.sequence_accession,
        "source": item.source.source_id,
        # An extracted sequence or accession has not necessarily been checked against
        # the authoritative protein record.
        "sequence_verified": False,
    }


def _literature_options(constraints: dict[str, Any]) -> dict[str, Any]:
    """Return bounded, explicitly supported LiteratureQuery options from the objective."""
    raw = constraints.get("literature")
    if not isinstance(raw, dict):
        return {}

    options: dict[str, Any] = {}
    mode = raw.get("mode")
    if mode in _LITERATURE_MODES:
        options["mode"] = mode

    bacteriocin = raw.get("bacteriocin")
    if isinstance(bacteriocin, str) and bacteriocin.strip():
        options["bacteriocin"] = bacteriocin.strip()

    documents = raw.get("source_documents")
    if isinstance(documents, list):
        options["source_documents"] = documents[:100]

    retrieval_raw = raw.get("retrieval")
    if isinstance(retrieval_raw, dict):
        retrieval: dict[str, Any] = {"enabled": bool(retrieval_raw.get("enabled", False))}
        sources = retrieval_raw.get("sources")
        if isinstance(sources, list):
            allowed = [source for source in sources if source in _LITERATURE_SOURCES]
            if allowed:
                retrieval["sources"] = allowed
        max_results = retrieval_raw.get("max_results")
        if isinstance(max_results, int) and not isinstance(max_results, bool):
            retrieval["max_results"] = max(1, min(50, max_results))
        timeout = retrieval_raw.get("timeout_seconds")
        if isinstance(timeout, (int, float)) and not isinstance(timeout, bool):
            retrieval["timeout_seconds"] = max(0.1, min(60.0, float(timeout)))
        retrieval_mode = retrieval_raw.get("mode")
        if retrieval_mode in _LITERATURE_MODES:
            retrieval["mode"] = retrieval_mode
        options["retrieval"] = retrieval

    return options


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
        request.update(_literature_options(state.objective.constraints))

        response = self.agent.run(request)
        emitted_ids: list[str] = []

        state_mgr = ResearchStateManager(state)

        contradictions = [item.model_dump(mode="json") for item in response.contradictions]
        contested_ids = {
            evidence_id
            for contradiction in response.contradictions
            for evidence_id in contradiction.evidence_ids
        }

        # Preserve the complete specialist record as an extension. Candidate-facing fields are a
        # deliberately smaller view and are emitted only for explicit, uncontested classifications.
        for item in response.evidence:
            ev_id = item.evidence_id or content_id(
                "evidence",
                {"source": item.source.source_id if item.source else "", "claim": item.claim},
            )
            source_id = item.source.source_id if item.source else "literature"
            linked_contradictions = [
                contradiction
                for contradiction in contradictions
                if ev_id in contradiction["evidence_ids"]
            ]
            extensions: dict[str, Any] = {
                "literature_record": item.model_dump(mode="json"),
                "citation": item.source.model_dump(mode="json"),
                "provenance": item.provenance.model_dump(mode="json"),
                "contradictions": linked_contradictions,
            }
            candidate = _candidate_payload(item, contested_ids)
            if candidate is not None:
                extensions["candidate"] = candidate
            evidence = Evidence(
                evidence_id=ev_id,
                evidence_type=getattr(item, "evidence_type", None) or "literature-derived",
                claim=item.claim,
                source=source_id,
                source_uri=item.source.doi_or_url if item.source else None,
                confidence=getattr(item, "confidence", None),
                **extensions,
            )
            if state_mgr.add_evidence(evidence, source_agent=self.name):
                emitted_ids.append(ev_id)

        for gap in response.knowledge_gaps:
            if gap not in state.knowledge_gaps:
                state.knowledge_gaps.append(gap)

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
