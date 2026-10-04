from __future__ import annotations

from typing import Any

from .blast import (
    AutoBlastBackend,
    BlastBackend,
    LocalBlastBackend,
    RemoteNcbiBlastBackend,
    blastp,
    check_blast_status,
    clear_blast_cache,
    fetch_blast_results,
    normalize_protein_sequence,
    reset_blast_budget,
    submit_blastp,
    summarize_blast_similarity,
)
from .client import NcbiClient
from .config import NCBIConfig
from .errors import (
    BlastBudgetExceededError,
    BlastError,
    BlastParseError,
    BlastRemoteFailure,
    BlastSubmissionError,
    BlastTimeoutError,
    BlastValidationError,
    LocalBlastDatabaseError,
    LocalBlastError,
    LocalBlastExecutionError,
    LocalBlastParseError,
    LocalBlastTimeoutError,
    LocalBlastUnavailableError,
    NCBIError,
    NCBIParseError,
    NCBIRateLimitError,
    NCBIRequestError,
)
from .fasta import fetch_fasta
from .local_blast import (
    build_local_blast_db,
    parse_blast_tsv,
    resolve_local_db,
)
from .pmc import fetch_pmc_article
from .protein import search_protein
from .pubmed import fetch_pubmed_records, search_pubmed
from .source import NcbiSource


def search_ncbi(db: str, query: str, limit: int = 10, client: NcbiClient | None = None) -> dict[str, Any]:
    """Search any NCBI database using ESearch."""
    c = client or NcbiClient()
    return c.esearch(db=db, term=query, retmax=limit, retmode="json")


__all__ = [
    "AutoBlastBackend",
    "BlastBackend",
    "BlastBudgetExceededError",
    "BlastError",
    "BlastParseError",
    "BlastRemoteFailure",
    "BlastSubmissionError",
    "BlastTimeoutError",
    "BlastValidationError",
    "LocalBlastBackend",
    "LocalBlastDatabaseError",
    "LocalBlastError",
    "LocalBlastExecutionError",
    "LocalBlastParseError",
    "LocalBlastTimeoutError",
    "LocalBlastUnavailableError",
    "NCBIConfig",
    "NCBIError",
    "NCBIParseError",
    "NCBIRateLimitError",
    "NCBIRequestError",
    "NcbiClient",
    "NcbiSource",
    "RemoteNcbiBlastBackend",
    "blastp",
    "build_local_blast_db",
    "check_blast_status",
    "clear_blast_cache",
    "fetch_blast_results",
    "fetch_fasta",
    "fetch_pmc_article",
    "fetch_pubmed_records",
    "normalize_protein_sequence",
    "parse_blast_tsv",
    "reset_blast_budget",
    "resolve_local_db",
    "search_ncbi",
    "search_protein",
    "search_pubmed",
    "submit_blastp",
    "summarize_blast_similarity",
]
