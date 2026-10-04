from __future__ import annotations

from typing import Any

from .client import NcbiClient
from .parsers import parse_pubmed_article_set


def search_pubmed(query: str, limit: int = 10, client: NcbiClient | None = None) -> dict[str, Any]:
    """Search PubMed using NCBI ESearch.

    Returns structured object containing query, pmids, count, and source="ncbi_pubmed".
    """
    c = client or NcbiClient()
    res = c.esearch(db="pubmed", term=query, retmax=limit, retmode="json")
    esearch_result = res.get("esearchresult", {})
    idlist = esearch_result.get("idlist", [])
    count_raw = esearch_result.get("count", 0)
    count = int(count_raw) if str(count_raw).isdigit() else len(idlist)
    return {
        "query": query,
        "pmids": [str(pid) for pid in idlist],
        "count": count,
        "source": "ncbi_pubmed",
    }


def fetch_pubmed_records(pmids: list[str], client: NcbiClient | None = None) -> list[dict[str, Any]]:
    """Retrieve PubMed records by PMIDs using NCBI EFetch.

    Returns structured records extracting PMID, title, abstract, journal,
    year, authors, DOI, PMCID, source URL, and provenance.
    Missing optional fields remain None or empty without fabrication.
    """
    clean_pmids = [str(p).strip() for p in pmids if str(p).strip()]
    if not clean_pmids:
        return []

    c = client or NcbiClient()
    xml_text = c.efetch(db="pubmed", id=clean_pmids, retmode="xml")
    return parse_pubmed_article_set(xml_text)
