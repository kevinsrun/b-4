from __future__ import annotations

from typing import Any

from .client import NcbiClient
from .parsers import parse_pmc_article


def fetch_pmc_article(pmcid: str, client: NcbiClient | None = None) -> dict[str, Any]:
    """Retrieve PMC full-text article by PMCID using NCBI EFetch.

    Returns structured output preserving PMCID, PMID, DOI, title, section text,
    full text, raw XML, and provenance.
    """
    clean_id = pmcid.strip()
    # EFetch accepts numeric ID or PMC-prefixed ID
    id_for_fetch = clean_id[3:] if clean_id.upper().startswith("PMC") else clean_id

    c = client or NcbiClient()
    xml_text = c.efetch(db="pmc", id=id_for_fetch, retmode="xml")
    result = parse_pmc_article(xml_text)

    # Ensure PMCID is normalized to include PMC prefix
    if not result.get("pmcid"):
        result["pmcid"] = clean_id if clean_id.upper().startswith("PMC") else f"PMC{clean_id}"

    return result
