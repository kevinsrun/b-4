from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any, Literal

from .extraction import extract_document
from .models import (
    Contradiction,
    EvidenceRecord,
    LiteratureQuery,
    LiteratureResponse,
    SourceDocument,
    SourceReference,
)
from .ncbi.client import NcbiClient
from .ncbi.source import NcbiSource
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


def _extract_identifiers(doc: SourceDocument) -> dict[str, Any]:
    sid = doc.source.source_id.strip()
    url = (doc.source.doi_or_url or "").strip()
    title = doc.source.title.strip()

    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None

    if sid.lower().startswith("pmid:"):
        pmid = sid.split(":", 1)[1].strip()
    elif sid.lower().startswith("pmc:"):
        pmcid = sid.split(":", 1)[1].strip().upper()
    elif sid.lower().startswith("doi:"):
        doi = sid.split(":", 1)[1].strip().lower()

    if not pmid:
        m_pmid = re.search(r"(?:pubmed\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov/pubmed)/(\d+)", url, re.I)
        if m_pmid:
            pmid = m_pmid.group(1)
    if not pmcid:
        m_pmc = re.search(r"ncbi\.nlm\.nih\.gov/pmc/articles/(PMC\d+)", url, re.I)
        if m_pmc:
            pmcid = m_pmc.group(1).upper()
    if not doi:
        m_doi = re.search(r"doi\.org/(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)", url, re.I)
        if m_doi:
            doi = m_doi.group(1).strip().lower()

    norm_title = re.sub(r"[^a-z0-9]", "", title.lower()) if len(title) >= 15 else None

    return {
        "pmid": pmid,
        "pmcid": pmcid,
        "doi": doi,
        "norm_title": norm_title,
        "raw_id": sid.casefold(),
    }


def _matches_existing(id_a: dict[str, Any], id_b: dict[str, Any]) -> bool:
    if id_a["raw_id"] == id_b["raw_id"]:
        return True
    if id_a["pmid"] and id_b["pmid"] and id_a["pmid"] == id_b["pmid"]:
        return True
    if id_a["pmcid"] and id_b["pmcid"] and id_a["pmcid"] == id_b["pmcid"]:
        return True
    if id_a["doi"] and id_b["doi"] and id_a["doi"] == id_b["doi"]:
        return True
    return bool(id_a["norm_title"] and id_b["norm_title"] and id_a["norm_title"] == id_b["norm_title"])


def _merge_source_documents(primary: SourceDocument, secondary: SourceDocument) -> SourceDocument:
    p_src = primary.source
    s_src = secondary.source

    # Merge authors preserving order and uniqueness
    authors = list(p_src.authors)
    for a in s_src.authors:
        if a not in authors:
            authors.append(a)

    # Preserve both source IDs if different
    if p_src.source_id.casefold() == s_src.source_id.casefold() or s_src.source_id in p_src.source_id:
        source_id = p_src.source_id
    elif p_src.source_id in s_src.source_id:
        source_id = s_src.source_id
    else:
        source_id = f"{p_src.source_id}|{s_src.source_id}"

    doi_or_url = p_src.doi_or_url or s_src.doi_or_url
    year = p_src.year or s_src.year
    journal = p_src.journal or s_src.journal

    merged_ref = SourceReference(
        source_id=source_id,
        title=p_src.title,
        doi_or_url=doi_or_url,
        year=year,
        authors=authors,
        journal=journal,
        source_type=p_src.source_type if p_src.source_type != "other" else s_src.source_type,
    )

    return SourceDocument(
        source=merged_ref,
        text=primary.text,
        locator=primary.locator,
        retrieved_at=primary.retrieved_at or secondary.retrieved_at,
    )


def _deduplicate(documents: list[SourceDocument]) -> list[SourceDocument]:
    output: list[SourceDocument] = []
    identifiers: list[dict[str, Any]] = []

    for doc in documents:
        doc_id = _extract_identifiers(doc)
        matched_idx = -1
        for idx, existing_id in enumerate(identifiers):
            if _matches_existing(existing_id, doc_id):
                matched_idx = idx
                break

        if matched_idx >= 0:
            # Merge into existing record
            merged = _merge_source_documents(output[matched_idx], doc)
            output[matched_idx] = merged
            identifiers[matched_idx] = _extract_identifiers(merged)
        else:
            output.append(doc)
            identifiers.append(doc_id)

    return output


def build_ncbi_query(query: LiteratureQuery) -> str:
    """Construct an NCBI PubMed query string from a LiteratureQuery."""
    q = query.question.strip()
    if any(op in q for op in (" AND ", " OR ", "[Title/Abstract]", "[Mesh]", "[All Fields]")):
        return q

    terms: list[str] = []
    if query.bacteriocin:
        terms.append(query.bacteriocin.strip())
    if query.target_organism:
        terms.append(query.target_organism.strip())
    if query.target_strain:
        terms.append(query.target_strain.strip())

    lower_q = q.lower()
    keywords: list[str] = []
    if any(k in lower_q for k in ("density", "cfu", "od600", "inoculum")):
        keywords.append("(cell density OR CFU OR OD600 OR inoculum)")
    if any(k in lower_q for k in ("concentration", "mic", "dose")):
        keywords.append("(concentration OR MIC OR inhibition)")
    if "ph" in lower_q:
        keywords.append("pH")
    if "temperature" in lower_q:
        keywords.append("temperature")

    if terms:
        base = " AND ".join(terms)
        if keywords:
            return f"{base} AND {' AND '.join(keywords)}"
        remaining_words = [
            w
            for w in re.findall(r"\w+", q)
            if w.lower() not in {t.lower() for t in terms}
            and w.lower() not in {"what", "is", "the", "under", "which", "does", "against", "in", "and", "or", "of"}
        ]
        if remaining_words:
            return f"{base} AND ({' '.join(remaining_words)})"
        return base

    return q


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

    def __init__(
        self,
        sources: dict[str, LiteratureSource] | None = None,
        mode: Literal["local", "live_ncbi", "hybrid"] = "local",
        ncbi_client: NcbiClient | None = None,
    ) -> None:
        self.mode = mode
        self.ncbi_client = ncbi_client or NcbiClient()
        ncbi_source = NcbiSource(client=self.ncbi_client)
        default_sources: dict[str, LiteratureSource] = {
            "europe_pmc": EuropePmcSource(),
            "ncbi": ncbi_source,
            "ncbi_pubmed": ncbi_source,
        }
        if sources is not None:
            default_sources.update(sources)
        self.sources = default_sources

    def run(self, raw_query: LiteratureQuery | dict) -> LiteratureResponse:
        query = raw_query if isinstance(raw_query, LiteratureQuery) else LiteratureQuery.model_validate(raw_query)
        query_id = _canonical_query_id(query)
        warnings: list[str] = []

        # Resolve mode: query.mode > query.retrieval.mode > inference from retrieval.enabled > self.mode
        explicit_mode = query.mode or query.retrieval.mode
        if explicit_mode:
            effective_mode = explicit_mode
        elif query.retrieval.enabled:
            has_ncbi = any(s in query.retrieval.sources for s in ("ncbi", "ncbi_pubmed", "ncbi_pmc"))
            if query.source_documents:
                effective_mode = "hybrid" if has_ncbi else "legacy_retrieval"
            else:
                effective_mode = "live_ncbi" if has_ncbi else "legacy_retrieval"
        else:
            effective_mode = self.mode

        documents: list[SourceDocument] = []

        if effective_mode == "local":
            documents = _deduplicate(list(query.source_documents))

        elif effective_mode == "live_ncbi":
            ncbi_src = self.sources.get("ncbi") or self.sources.get("ncbi_pubmed")
            if ncbi_src is None:
                warnings.append("retrieval source unavailable: ncbi")
            else:
                search_query = build_ncbi_query(query)
                try:
                    documents.extend(
                        ncbi_src.search(search_query, query.retrieval.max_results, query.retrieval.timeout_seconds)
                    )
                except Exception as exc:
                    warnings.append(f"ncbi retrieval failed: {type(exc).__name__}: {exc}")
            documents = _deduplicate(documents)

        elif effective_mode == "hybrid":
            local_docs = list(query.source_documents)
            remote_docs: list[SourceDocument] = []

            sources_to_query = list(query.retrieval.sources)
            if explicit_mode == "hybrid" and not any("ncbi" in s for s in sources_to_query):
                sources_to_query.append("ncbi")

            for source_name in sources_to_query:
                source = self.sources.get(source_name)
                if source is None:
                    warnings.append(f"retrieval source unavailable: {source_name}")
                    continue
                search_query = build_ncbi_query(query) if "ncbi" in source_name else query.question
                try:
                    remote_docs.extend(
                        source.search(search_query, query.retrieval.max_results, query.retrieval.timeout_seconds)
                    )
                except Exception as exc:
                    warnings.append(f"{source_name} retrieval failed: {type(exc).__name__}: {exc}")

            documents = _deduplicate(local_docs + remote_docs)

        else:  # legacy_retrieval
            documents = list(query.source_documents)
            for source_name in query.retrieval.sources:
                source = self.sources.get(source_name)
                if source is None:
                    warnings.append(f"retrieval source unavailable: {source_name}")
                    continue
                try:
                    documents.extend(
                        source.search(query.question, query.retrieval.max_results, query.retrieval.timeout_seconds)
                    )
                except Exception as exc:
                    warnings.append(f"{source_name} retrieval failed: {type(exc).__name__}: {exc}")
            documents = _deduplicate(documents)
        evidence: list[EvidenceRecord] = []
        for document in documents:
            evidence.extend(extract_document(query, document, lambda *parts: _stable_id("ev", *parts)))

        contradictions = _contradictions(evidence)
        if documents and not evidence:
            warnings.append(
                "Sources were retrieved but no supported antimicrobial measurement or activity claim was extracted."
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
