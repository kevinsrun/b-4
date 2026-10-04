from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from .extraction import extract_document
from .models import (
    Contradiction,
    EvidenceRecord,
    LiteratureQuery,
    LiteratureResponse,
    SourceDocument,
)
from .sources import EuropePmcSource, LiteratureSource


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _canonical_query_id(query: LiteratureQuery) -> str:
    if query.query_id:
        return query.query_id
    payload = query.model_dump(mode="json", exclude={"query_id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _stable_id("query", canonical)


def _deduplicate(documents: list[SourceDocument]) -> list[SourceDocument]:
    output: list[SourceDocument] = []
    seen: set[str] = set()
    for document in documents:
        key = document.source.source_id.casefold()
        if key not in seen:
            output.append(document)
            seen.add(key)
    return output


def _contradictions(evidence: list[EvidenceRecord]) -> list[Contradiction]:
    groups: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for record in evidence:
        if record.measurement.type != "antimicrobial_activity":
            continue
        candidate = (record.bacteriocin.name or "unknown").casefold()
        target = (record.target.organism or "unknown").casefold()
        value = str(record.measurement.value).casefold()
        polarity = (
            "positive"
            if value in {"active", "susceptible", "sensitive"}
            else "negative"
            if value in {"inactive", "resistant", "insensitive"}
            else "unknown"
        )
        groups[(candidate, target)][polarity].append(record.evidence_id)

    contradictions: list[Contradiction] = []
    for (candidate, target), polarities in sorted(groups.items()):
        if polarities["positive"] and polarities["negative"]:
            ids = sorted(polarities["positive"] + polarities["negative"])
            contradictions.append(
                Contradiction(
                    contradiction_id=_stable_id("cx", *ids),
                    evidence_ids=ids,
                    topic=f"activity of {candidate} against {target}",
                    description=(
                        "Sources report opposing activity classifications. "
                        "Conditions must be compared before reconciliation."
                    ),
                )
            )
    return contradictions


class LiteratureEvidenceAgent:
    """Stateless, bounded evidence retrieval and deterministic extraction service."""

    def __init__(self, sources: dict[str, LiteratureSource] | None = None) -> None:
        self.sources = sources or {"europe_pmc": EuropePmcSource()}

    def run(self, raw_query: LiteratureQuery | dict) -> LiteratureResponse:
        query = raw_query if isinstance(raw_query, LiteratureQuery) else LiteratureQuery.model_validate(raw_query)
        query_id = _canonical_query_id(query)
        documents = list(query.source_documents)
        warnings: list[str] = []

        if query.retrieval.enabled:
            for source_name in query.retrieval.sources:
                source = self.sources.get(source_name)
                if source is None:
                    warnings.append(f"retrieval source unavailable: {source_name}")
                    continue
                try:
                    documents.extend(
                        source.search(query.question, query.retrieval.max_results, query.retrieval.timeout_seconds)
                    )
                except Exception as exc:  # source failure is explicit, supplied documents remain usable
                    warnings.append(f"{source_name} retrieval failed: {type(exc).__name__}: {exc}")

        documents = _deduplicate(documents)
        evidence: list[EvidenceRecord] = []
        unattributed: list[str] = []
        unparsed: list[str] = []
        for document in documents:
            evidence.extend(
                extract_document(
                    query, document, lambda *parts: _stable_id("ev", *parts), unattributed, unparsed
                )
            )

        contradictions = _contradictions(evidence)
        if documents and not evidence:
            warnings.append(
                "Sources were retrieved but no supported antimicrobial measurement or activity claim was extracted."
            )
        if unattributed:
            warnings.append(
                f"{len(unattributed)} antimicrobial measurement(s) were discarded because no bacteriocin was "
                "named in the sentence reporting them; they may describe a different class of agent."
            )
        if unparsed:
            warnings.append(
                f"{len(unparsed)} source(s) report an MIC that the deterministic rules could not attribute "
                "(typically a range, or several agents in one clause). Review by hand before concluding "
                f"absence of evidence: {', '.join(sorted(unparsed)[:10])}"
            )

        knowledge_gaps = self._knowledge_gaps(evidence)
        confidence = round(sum(item.confidence for item in evidence) / len(evidence), 3) if evidence else 0.0
        if warnings:
            confidence = round(confidence * 0.9, 3)

        recommended_searches = self._recommended_searches(query, knowledge_gaps)
        return LiteratureResponse(
            query_id=query_id,
            decision={
                "status": "evidence-collected" if evidence else "insufficient-evidence",
                "candidate_decision": "not-performed",
                "documents_considered": len(documents),
                "records_extracted": len(evidence),
            },
            evidence=evidence,
            knowledge_gaps=knowledge_gaps,
            contradictions=contradictions,
            recommended_searches=recommended_searches,
            confidence=confidence,
            uncertainties=[
                (
                    "Deterministic extraction is conservative and may miss conditions expressed in tables, figures, "
                    "supplements, or nonstandard prose."
                ),
                "Abstract-only retrieval cannot establish absence of a variable from the full paper.",
            ],
            artifacts={"source_ids": [document.source.source_id for document in documents]},
            warnings=warnings,
            recommended_next_action={
                "action": "review-evidence-and-search-gaps",
                "requires_codex_or_human_adjudication": True,
                "searches": recommended_searches,
            },
        )

    @staticmethod
    def _knowledge_gaps(evidence: list[EvidenceRecord]) -> list[str]:
        if not evidence:
            return ["No extractable evidence records were found for the question."]
        missing_everywhere = set(evidence[0].missing_variables)
        for record in evidence[1:]:
            missing_everywhere.intersection_update(record.missing_variables)
        return [f"No extracted record reports {name.replace('_', ' ')}." for name in sorted(missing_everywhere)]

    @staticmethod
    def _recommended_searches(query: LiteratureQuery, gaps: list[str]) -> list[str]:
        subject = (
            " ".join(part for part in (query.bacteriocin, query.target_organism, query.target_strain) if part)
            or query.question
        )
        terms: list[str] = []
        gap_text = " ".join(gaps)
        if "cell density" in gap_text:
            terms.append(f'"{subject}" (CFU OR OD600 OR inoculum)')
        if "bacteriocin concentration" in gap_text:
            terms.append(f'"{subject}" (MIC OR concentration OR dose-response)')
        if any(term in gap_text for term in ("ph", "temperature", "medium", "ionic")):
            terms.append(f'"{subject}" (pH OR temperature OR medium OR ionic strength)')
        if not terms:
            terms.append(f'"{subject}" bacteriocin antimicrobial assay')
        return terms[:5]
