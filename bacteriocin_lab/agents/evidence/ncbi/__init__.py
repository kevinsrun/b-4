from __future__ import annotations

from typing import Any

from .client import NcbiClient
from .config import NCBIConfig
from .errors import NCBIError, NCBIParseError, NCBIRateLimitError, NCBIRequestError
from .fasta import fetch_fasta
from .pmc import fetch_pmc_article
from .protein import search_protein
from .pubmed import fetch_pubmed_records, search_pubmed
from .source import NcbiSource


def search_ncbi(db: str, query: str, limit: int = 10, client: NcbiClient | None = None) -> dict[str, Any]:
    """Search any NCBI database using ESearch."""
    c = client or NcbiClient()
    return c.esearch(db=db, term=query, retmax=limit, retmode="json")


__all__ = [
    "NCBIConfig",
    "NCBIError",
    "NCBIParseError",
    "NCBIRateLimitError",
    "NCBIRequestError",
    "NcbiClient",
    "NcbiSource",
    "fetch_fasta",
    "fetch_pmc_article",
    "fetch_pubmed_records",
    "search_ncbi",
    "search_protein",
    "search_pubmed",
]
