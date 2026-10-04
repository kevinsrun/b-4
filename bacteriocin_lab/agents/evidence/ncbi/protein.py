from __future__ import annotations

import re
from typing import Any

from .client import NcbiClient

ORGANISM_RE = re.compile(r"\[([^\]]+)\]$")


def search_protein(query: str, limit: int = 10, client: NcbiClient | None = None) -> list[dict[str, Any]]:
    """Search NCBI Protein database using ESearch + ESummary.

    Returns:
    - protein IDs/accessions where available
    - title/description
    - organism
    - database source ("ncbi_protein")
    """
    c = client or NcbiClient()
    esearch_res = c.esearch(db="protein", term=query, retmax=limit, retmode="json")
    idlist = esearch_res.get("esearchresult", {}).get("idlist", [])
    if not idlist:
        return []

    # Retrieve summaries for returned UIDs
    summaries: dict[str, Any] = {}
    try:
        sum_res = c.esummary(db="protein", id=idlist, retmode="json")
        summaries = sum_res.get("result", {})
    except Exception:
        summaries = {}

    results: list[dict[str, Any]] = []
    for uid in idlist:
        item = summaries.get(str(uid), {})
        title = item.get("title", "")
        accession = item.get("caption") or str(uid)

        organism: str | None = None
        if title:
            m = ORGANISM_RE.search(title.strip())
            if m:
                organism = m.group(1).strip()
        if not organism:
            organism = item.get("organism") or item.get("source")

        results.append(
            {
                "id": str(uid),
                "accession": accession,
                "title": title,
                "organism": organism,
                "source": "ncbi_protein",
            }
        )

    return results
