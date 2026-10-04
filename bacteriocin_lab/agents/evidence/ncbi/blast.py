from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from .blast_parser import parse_blast_status, parse_blast_submission, parse_blast_xml
from .client import NcbiClient
from .errors import (
    BlastRemoteFailure,
    BlastTimeoutError,
    BlastValidationError,
)

logger = logging.getLogger("b4_literature.blast")

# Standard 20 amino acids + standard IUPAC ambiguity codes + stop codon
VALID_PROTEIN_RESIDUES = frozenset("ACDEFGHIKLMNPQRSTVWYBXZJUO*")

# In-memory BLAST cache
_BLAST_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()


class BlastBudgetTracker:
    """Thread-safe tracker for bounding BLAST queries per run."""

    def __init__(self) -> None:
        self._count = 0
        self._lock = threading.Lock()

    def increment(self) -> int:
        with self._lock:
            self._count += 1
            return self._count

    def get_count(self) -> int:
        with self._lock:
            return self._count

    def reset(self) -> None:
        with self._lock:
            self._count = 0


_BUDGET_TRACKER = BlastBudgetTracker()
_CONCURRENCY_SEMAPHORE = threading.Semaphore(2)


def reset_blast_budget() -> None:
    """Reset the run-level BLAST query budget counter."""
    _BUDGET_TRACKER.reset()


def clear_blast_cache() -> None:
    """Clear all cached BLAST results."""
    with _CACHE_LOCK:
        _BLAST_CACHE.clear()


def normalize_protein_sequence(sequence: str) -> str:
    """Validate and normalize a protein sequence for BLAST submission.

    Strips FASTA headers, newlines, and whitespace; converts to uppercase.
    Rejects malformed sequences, empty strings, and non-protein characters.

    Raises:
        BlastValidationError: If sequence is empty, too short, or contains invalid characters.
    """
    if not sequence or not isinstance(sequence, str):
        raise BlastValidationError("Protein sequence must be a non-empty string")

    # Strip FASTA header line if present (>header\n...)
    lines = sequence.strip().splitlines()
    if lines and lines[0].startswith(">"):
        lines = lines[1:]

    raw = "".join(lines)
    cleaned = "".join(raw.split()).upper()

    if not cleaned:
        raise BlastValidationError("Protein sequence cannot be empty")

    if len(cleaned) < 3:
        raise BlastValidationError(
            f"Protein sequence too short for BLAST analysis ({len(cleaned)} residues, minimum 3)"
        )

    invalid_chars = set(cleaned) - VALID_PROTEIN_RESIDUES
    if invalid_chars:
        raise BlastValidationError(
            f"Invalid characters in protein sequence: {sorted(invalid_chars)}"
        )

    return cleaned


def _compute_cache_key(sequence: str, program: str, database: str, options: dict[str, Any]) -> str:
    serialized_opts = json.dumps(options, sort_keys=True, default=str)
    key_src = f"{sequence}:{program}:{database}:{serialized_opts}"
    return hashlib.sha256(key_src.encode("utf-8")).hexdigest()


def submit_blastp(
    sequence: str,
    database: str = "nr",
    candidate_id: str | None = None,
    client: NcbiClient | None = None,
    **options: Any,
) -> dict[str, Any]:
    """Submit a protein sequence similarity search (blastp) to the NCBI BLAST URL API.

    Returns structured dict containing 'rid', 'rtoe', 'program', 'database', and 'candidate_id'.

    Raises:
        BlastValidationError: If the sequence is malformed.
        BlastSubmissionError: If submission fails or RID cannot be extracted.
    """
    normalized_seq = normalize_protein_sequence(sequence)
    c = client or NcbiClient()

    params: dict[str, Any] = {
        "CMD": "Put",
        "PROGRAM": "blastp",
        "DATABASE": database,
        "QUERY": normalized_seq,
        "FORMAT_TYPE": "XML",
    }

    # Map optional options
    if "hitlist_size" in options:
        params["HITLIST_SIZE"] = options["hitlist_size"]
    elif "HITLIST_SIZE" in options:
        params["HITLIST_SIZE"] = options["HITLIST_SIZE"]

    if "evalue_cutoff" in options:
        params["EXPECT"] = options["evalue_cutoff"]
    elif "EXPECT" in options:
        params["EXPECT"] = options["EXPECT"]

    for k, v in options.items():
        if k.upper() not in params and k not in ("hitlist_size", "evalue_cutoff"):
            params[k.upper()] = v

    resp_text = c.get(c.config.blast_url, params)
    parsed = parse_blast_submission(resp_text)

    return {
        "rid": parsed["rid"],
        "rtoe": parsed["rtoe"],
        "program": "blastp",
        "database": database,
        "candidate_id": candidate_id,
        "query_length": len(normalized_seq),
    }


def check_blast_status(rid: str, client: NcbiClient | None = None) -> dict[str, Any]:
    """Check the status of a submitted BLAST search by RID.

    Returns dict containing:
        - rid: str
        - status: "WAITING" | "READY" | "FAILED" | "UNKNOWN"
        - has_hits: bool | None
    """
    clean_rid = str(rid).strip()
    c = client or NcbiClient()
    params = {
        "CMD": "Get",
        "FORMAT_OBJECT": "SearchInfo",
        "RID": clean_rid,
    }
    resp_text = c.get(c.config.blast_url, params)
    parsed = parse_blast_status(resp_text)
    return {
        "rid": clean_rid,
        "status": parsed["status"],
        "has_hits": parsed["has_hits"],
    }


def fetch_blast_results(
    rid: str,
    format_type: str = "XML",
    client: NcbiClient | None = None,
) -> str:
    """Retrieve raw formatted results for a completed BLAST search by RID.

    Default format is 'XML'.
    """
    clean_rid = str(rid).strip()
    c = client or NcbiClient()
    params = {
        "CMD": "Get",
        "FORMAT_TYPE": format_type,
        "RID": clean_rid,
    }
    return c.get(c.config.blast_url, params)


def blastp(
    sequence: str,
    database: str = "nr",
    candidate_id: str | None = None,
    timeout_seconds: float | None = None,
    poll_interval: float | None = None,
    max_poll_attempts: int | None = None,
    client: NcbiClient | None = None,
    use_cache: bool = True,
    sleep_fn: Callable[[float], None] = time.sleep,
    time_fn: Callable[[], float] = time.monotonic,
    **options: Any,
) -> dict[str, Any]:
    """Execute complete BLASTP workflow: submit, poll, retrieve, parse, and structure hits.

    Respects RTOE wait time, bounds polling attempts and timeout, enforces query budgets,
    and caches results keyed by sequence, database, and parameters.

    Returns:
        Structured result dict matching the database-derived provenance schema.

    Raises:
        BlastValidationError: If the sequence is malformed.
        BlastTimeoutError: If the search times out before completing.
        BlastRemoteFailure: If the remote search fails or RID is unknown/expired.
        BlastParseError: If XML output cannot be parsed.
    """
    normalized_seq = normalize_protein_sequence(sequence)
    c = client or NcbiClient()

    # Safety: check Omnigent query budget
    max_queries = c.config.max_blast_queries_per_run
    current_count = _BUDGET_TRACKER.get_count()
    if current_count >= max_queries:
        logger.warning(
            "BLAST query budget exceeded (%d >= %d)", current_count, max_queries
        )
        return {
            "query_id": "query",
            "candidate_id": candidate_id,
            "program": "blastp",
            "database": database,
            "rid": "",
            "status": "budget_exhausted",
            "error": f"BLAST query budget exceeded ({max_queries} queries allowed per run)",
            "query_length": len(normalized_seq),
            "hits": [],
            "provenance": "database-derived",
            "source": "ncbi_blast",
        }

    # Cache check
    cache_enabled = use_cache and c.config.blast_cache_enabled
    cache_key = _compute_cache_key(normalized_seq, "blastp", database, options)
    if cache_enabled:
        with _CACHE_LOCK:
            if cache_key in _BLAST_CACHE:
                cached = dict(_BLAST_CACHE[cache_key])
                cached["candidate_id"] = candidate_id
                return cached

    # Resolve timing & limits
    effective_timeout = (
        timeout_seconds if timeout_seconds is not None else c.config.blast_timeout_seconds
    )
    effective_interval = (
        poll_interval if poll_interval is not None else c.config.blast_poll_interval_seconds
    )
    effective_max_attempts = (
        max_poll_attempts
        if max_poll_attempts is not None
        else c.config.blast_max_poll_attempts
    )

    # Concurrency guard
    _CONCURRENCY_SEMAPHORE.acquire()
    try:
        # Submit search
        sub = submit_blastp(
            normalized_seq,
            database=database,
            candidate_id=candidate_id,
            client=c,
            **options,
        )
        _BUDGET_TRACKER.increment()
        rid = sub["rid"]
        rtoe = sub.get("rtoe", 5)

        start_time = time_fn()

        # Initial wait: honor server-estimated RTOE bounded by timeout
        initial_wait = min(float(rtoe), effective_timeout)
        if initial_wait > 0:
            sleep_fn(initial_wait)

        # Polling loop
        attempt = 0
        while attempt < effective_max_attempts:
            attempt += 1
            elapsed = time_fn() - start_time
            if elapsed >= effective_timeout:
                raise BlastTimeoutError(
                    f"BLAST search timed out after {elapsed:.1f}s for RID {rid} (limit: {effective_timeout:.1f}s)"
                )

            status_info = check_blast_status(rid, client=c)
            status = status_info["status"]

            if status == "READY":
                xml_text = fetch_blast_results(rid, format_type="XML", client=c)
                parsed = parse_blast_xml(xml_text, candidate_id=candidate_id, rid=rid)
                if cache_enabled:
                    with _CACHE_LOCK:
                        _BLAST_CACHE[cache_key] = parsed
                return parsed

            if status == "WAITING":
                # Wait poll interval before next check
                sleep_fn(effective_interval)
                continue

            if status == "FAILED":
                raise BlastRemoteFailure(
                    f"NCBI BLAST search failed remotely on NCBI server for RID {rid}"
                )

            if status == "UNKNOWN":
                raise BlastRemoteFailure(
                    f"NCBI BLAST search RID {rid} is unknown or expired"
                )

            raise BlastRemoteFailure(
                f"Unexpected NCBI BLAST status {status!r} for RID {rid}"
            )

        raise BlastTimeoutError(
            f"BLAST search exceeded max polling attempts ({effective_max_attempts}) for RID {rid}"
        )
    finally:
        _CONCURRENCY_SEMAPHORE.release()


def summarize_blast_similarity(result: dict[str, Any]) -> dict[str, Any]:
    """Estimate a heuristic sequence novelty and homology signal from BLAST results.

    Classification:
        - 'low' novelty (high similarity): top hit >= 95% identity, e_value < 1e-4
        - 'moderate' novelty: top hit between 60% and 95% identity
        - 'high' novelty: no hits found or top hit < 60% identity
        - 'unknown': search failed or was not completed

    Returns:
        Structured novelty analysis dictionary with provenance='database-derived'.
    """
    status = result.get("status")
    candidate_id = result.get("candidate_id")
    query_id = result.get("query_id")
    database = result.get("database", "nr")
    hits = result.get("hits", [])

    if status != "complete":
        return {
            "candidate_id": candidate_id,
            "query_id": query_id,
            "novelty": "unknown",
            "max_identity_percent": None,
            "top_hit": None,
            "hit_count": 0,
            "database": database,
            "reason": f"BLAST search did not complete successfully (status: {status})",
            "provenance": "database-derived",
            "source": "ncbi_blast",
        }

    if not hits:
        return {
            "candidate_id": candidate_id,
            "query_id": query_id,
            "novelty": "high",
            "max_identity_percent": 0.0,
            "top_hit": None,
            "hit_count": 0,
            "database": database,
            "reason": f"No homologous sequences found in database '{database}'; candidate appears novel",
            "provenance": "database-derived",
            "source": "ncbi_blast",
        }

    top_hit = hits[0]
    max_ident = float(top_hit.get("identity_percent", 0.0))
    e_val = float(top_hit.get("e_value", 1.0))
    top_title = top_hit.get("title", "unknown")

    if max_ident >= 95.0 and e_val < 1e-4:
        novelty = "low"
        reason = f"High sequence identity ({max_ident:.1f}%) to known sequence: {top_title}"
    elif max_ident >= 60.0:
        novelty = "moderate"
        reason = f"Moderate sequence identity ({max_ident:.1f}%) to known homolog: {top_title}"
    else:
        novelty = "high"
        reason = f"Distant homology only (closest match {max_ident:.1f}% identity: {top_title})"

    return {
        "candidate_id": candidate_id,
        "query_id": query_id,
        "novelty": novelty,
        "max_identity_percent": max_ident,
        "top_hit": top_hit,
        "hit_count": len(hits),
        "database": database,
        "reason": reason,
        "provenance": "database-derived",
        "source": "ncbi_blast",
    }
