from __future__ import annotations

from typing import Any

from .client import NcbiClient
from .errors import NCBIError
from .parsers import parse_fasta_text

SUPPORTED_FASTA_DBS = {"protein", "nuccore"}


def fetch_fasta(db: str, ids: list[str] | str, client: NcbiClient | None = None) -> dict[str, Any]:
    """Retrieve FASTA text and structured sequences from NCBI (protein or nuccore).

    Supported db values include 'protein' and 'nuccore'.
    Returns structured sequences preserving accession/ID, sequence, and source database,
    as well as the raw FASTA text payload.
    """
    db_clean = db.strip().lower()
    if db_clean not in SUPPORTED_FASTA_DBS:
        raise NCBIError(f"Unsupported database '{db}' for FASTA retrieval; must be one of {SUPPORTED_FASTA_DBS}")

    id_list = [ids] if isinstance(ids, str) else list(ids)
    clean_ids = [str(i).strip() for i in id_list if str(i).strip()]
    if not clean_ids:
        return {
            "db": db_clean,
            "ids": [],
            "records": [],
            "raw_fasta": "",
        }

    c = client or NcbiClient()
    raw_fasta = c.efetch(db=db_clean, id=clean_ids, rettype="fasta", retmode="text")
    records = parse_fasta_text(raw_fasta, db=db_clean)

    return {
        "db": db_clean,
        "ids": clean_ids,
        "records": records,
        "raw_fasta": raw_fasta,
    }
