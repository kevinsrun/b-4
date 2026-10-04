from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import NCBIConfig
from .errors import (
    LocalBlastDatabaseError,
    LocalBlastParseError,
    LocalBlastUnavailableError,
)

logger = logging.getLogger("b4_literature.local_blast")

# Expected columns for outfmt 6
# "6 qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore stitle sacc slen"
OUTFMT_6_SPEC = (
    "6 qseqid sseqid pident length mismatch gapopen qstart qend sstart send evalue bitscore stitle sacc slen"
)


def is_executable_available(exe: str) -> bool:
    """Check if an executable is found on PATH or exists as an executable file."""
    if not exe or not isinstance(exe, str):
        return False
    try:
        p = Path(exe)
        if p.is_file() and os.access(str(p), os.X_OK):
            return True
    except (ValueError, OSError):
        return False
    return shutil.which(exe) is not None


def local_db_exists(prefix: Path | str) -> bool:
    """Check whether a BLAST+ database exists for the given file path or prefix."""
    try:
        p = Path(prefix)
    except (ValueError, OSError):
        return False

    prefix_str = str(p)
    # Check common BLAST+ protein database file extensions
    for ext in ("", ".pin", ".psq", ".phr", ".pdb", ".pal", ".pjs", ".pot", ".ptf", ".pto"):
        candidate = Path(prefix_str + ext)
        try:
            if candidate.is_file():
                return True
        except (ValueError, OSError):
            continue

    try:
        if p.is_dir():
            for child in p.iterdir():
                if child.suffix in (".pin", ".psq", ".phr", ".pdb", ".pal"):
                    return True
    except (ValueError, OSError):
        return False

    return False


def get_local_db_identifier(db_path: Path | str) -> str:
    """Return a compact, reproducible identifier for a local database."""
    try:
        p = Path(db_path)
    except (ValueError, OSError):
        return str(db_path)

    mtime = 0.0
    prefix_str = str(p)
    for ext in (".pin", ".phr", ".psq", ".pdb", ""):
        candidate = Path(prefix_str + ext)
        try:
            if candidate.is_file():
                mtime = candidate.stat().st_mtime
                break
        except (ValueError, OSError):
            continue

    return f"{p.name}:{int(mtime)}"


def resolve_local_db(database: str, config: NCBIConfig | None = None) -> str | None:
    """Resolve a database name or path into a local BLAST database file prefix.

    Rules:
    - "swissprot" / "uniprot" -> config.blast_local_swissprot_db, or <db_dir>/swissprot
    - "refseq_protein" / "refseq" -> config.blast_local_refseq_db, or <db_dir>/refseq_protein
    - "bacteriocin" / "bacteriocins" -> config.blast_local_bacteriocin_db, or <db_dir>/bacteriocins
    - "nr" -> ONLY if explicitly configured via config.blast_local_nr_db or <db_dir>/nr exists
    - Direct path or prefix -> checked directly
    - Name inside config.blast_local_db_dir -> checked
    - "default" -> config.blast_local_default_db
    """
    if not database or not isinstance(database, str):
        return None

    # Reject null bytes or suspicious control characters in database path
    if "\x00" in database or "\n" in database or "\r" in database:
        return None

    cfg = config or NCBIConfig()
    db_lower = database.strip().lower()

    # 1. Logical database aliases
    if db_lower in ("swissprot", "uniprot", "sp"):
        if cfg.blast_local_swissprot_db and local_db_exists(cfg.blast_local_swissprot_db):
            return str(cfg.blast_local_swissprot_db)
        if cfg.blast_local_db_dir:
            cand = Path(cfg.blast_local_db_dir) / "swissprot"
            if local_db_exists(cand):
                return str(cand)
        return None

    if db_lower in ("refseq", "refseq_protein"):
        if cfg.blast_local_refseq_db and local_db_exists(cfg.blast_local_refseq_db):
            return str(cfg.blast_local_refseq_db)
        if cfg.blast_local_db_dir:
            cand = Path(cfg.blast_local_db_dir) / "refseq_protein"
            if local_db_exists(cand):
                return str(cand)
        return None

    if db_lower in ("bacteriocin", "bacteriocins"):
        if cfg.blast_local_bacteriocin_db and local_db_exists(cfg.blast_local_bacteriocin_db):
            return str(cfg.blast_local_bacteriocin_db)
        if cfg.blast_local_db_dir:
            for name in ("bacteriocins", "bacteriocin"):
                cand = Path(cfg.blast_local_db_dir) / name
                if local_db_exists(cand):
                    return str(cand)
        return None

    if db_lower == "nr":
        # Hard rule: DO NOT auto-download nr; only use if explicitly configured locally
        if cfg.blast_local_nr_db and local_db_exists(cfg.blast_local_nr_db):
            return str(cfg.blast_local_nr_db)
        if cfg.blast_local_db_dir:
            cand = Path(cfg.blast_local_db_dir) / "nr"
            if local_db_exists(cand):
                return str(cand)
        return None

    if db_lower == "default":
        if cfg.blast_local_default_db and local_db_exists(cfg.blast_local_default_db):
            return str(cfg.blast_local_default_db)
        return None

    # 2. Check direct path / prefix
    try:
        p = Path(database)
        if local_db_exists(p):
            return str(p)
    except (ValueError, OSError):
        pass

    # 3. Check inside blast_local_db_dir
    if cfg.blast_local_db_dir:
        try:
            cand = Path(cfg.blast_local_db_dir) / database
            if local_db_exists(cand):
                return str(cand)
        except (ValueError, OSError):
            pass

    return None


def parse_blast_tsv(
    output_text: str,
    candidate_id: str | None = None,
    query_id: str = "query",
    query_length: int = 0,
    database: str = "",
) -> list[dict[str, Any]]:
    """Parse local blastp tabular output (outfmt 6) into normalized hit records.

    Expected column order:
    0: qseqid
    1: sseqid
    2: pident
    3: length
    4: mismatch
    5: gapopen
    6: qstart
    7: qend
    8: sstart
    9: send
    10: evalue
    11: bitscore
    12: stitle (optional)
    13: sacc (optional)
    14: slen (optional)
    """
    if not output_text or not output_text.strip():
        return []

    hits: list[dict[str, Any]] = []
    lines = output_text.strip().splitlines()

    for rank, line in enumerate(lines, start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split("\t")
        if len(parts) < 12:
            raise LocalBlastParseError(
                f"Invalid blastp TSV row: expected at least 12 columns, got {len(parts)}",
                raw_snippet=line,
            )

        try:
            pident = float(parts[2])
            length = int(parts[3])
            mismatch = int(parts[4])
            gapopen = int(parts[5])
            qstart = int(parts[6])
            qend = int(parts[7])
            sstart = int(parts[8])
            send = int(parts[9])
            evalue = float(parts[10])
            bitscore = float(parts[11])
        except ValueError as exc:
            raise LocalBlastParseError(
                f"Failed to parse numeric column in blastp output: {exc}",
                raw_snippet=line,
            ) from exc

        stitle = parts[12] if len(parts) > 12 else parts[1]
        sacc = parts[13] if len(parts) > 13 else parts[1]
        if sacc == "N/A" or not sacc.strip():
            sacc = parts[1]

        slen = int(parts[14]) if len(parts) > 14 and parts[14].isdigit() else 0

        # Extract organism name from title if in brackets (e.g. "[Lactococcus lactis]")
        org_match = re.search(r"\[(.*?)\]", stitle)
        organism = org_match.group(1).strip() if org_match else None

        hits.append(
            {
                "rank": rank,
                "accession": sacc,
                "title": stitle,
                "organism": organism,
                "identity_percent": round(pident, 2),
                "positive_percent": round(pident, 2),
                "alignment_length": length,
                "mismatch": mismatch,
                "gap_opens": gapopen,
                "e_value": evalue,
                "bit_score": round(bitscore, 2),
                "query_start": qstart,
                "query_end": qend,
                "subject_start": sstart,
                "subject_end": send,
                "subject_length": slen,
            }
        )

    return hits


def build_local_blast_db(
    fasta_path: str | Path,
    output_prefix: str | Path,
    dbtype: str = "prot",
    title: str | None = None,
    makeblastdb_executable: str | None = None,
) -> dict[str, Any]:
    """Build a local BLAST database using makeblastdb.

    Args:
        fasta_path: Path to source FASTA file.
        output_prefix: Target database path prefix.
        dbtype: Database type, either 'prot' or 'nucl'.
        title: Optional title for the database.
        makeblastdb_executable: Path or name of makeblastdb executable.

    Raises:
        LocalBlastUnavailableError: If makeblastdb is not found.
        LocalBlastDatabaseError: If fasta_path does not exist or makeblastdb fails.
    """
    fasta_p = Path(fasta_path)
    if not fasta_p.is_file():
        raise LocalBlastDatabaseError(f"FASTA input file not found: {fasta_path}")

    if dbtype not in ("prot", "nucl"):
        raise ValueError(f"Invalid dbtype: {dbtype!r}. Must be 'prot' or 'nucl'.")

    exe = makeblastdb_executable or os.getenv("MAKEBLASTDB_EXECUTABLE", "makeblastdb")
    if not is_executable_available(exe):
        raise LocalBlastUnavailableError(f"makeblastdb executable '{exe}' not found on PATH")

    out_p = Path(output_prefix)
    try:
        out_p.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LocalBlastDatabaseError(f"Failed to create output directory {out_p.parent}: {exc}") from exc

    cmd: list[str] = [
        exe,
        "-in",
        str(fasta_p),
        "-dbtype",
        dbtype,
        "-out",
        str(out_p),
    ]
    if title:
        cmd.extend(["-title", title])

    try:
        proc = subprocess.run(
            cmd,
            shell=False,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise LocalBlastDatabaseError(f"Failed to execute makeblastdb: {exc}") from exc

    if proc.returncode != 0:
        raise LocalBlastDatabaseError(
            f"makeblastdb failed with returncode {proc.returncode}: {proc.stderr.strip()}"
        )

    return {
        "output_prefix": str(out_p),
        "dbtype": dbtype,
        "status": "created",
        "stdout": proc.stdout,
    }
