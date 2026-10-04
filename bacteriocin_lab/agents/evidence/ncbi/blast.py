from __future__ import annotations

import abc
import contextlib
import hashlib
import json
import logging
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .blast_parser import parse_blast_status, parse_blast_submission, parse_blast_xml
from .client import NcbiClient
from .config import NCBIConfig
from .errors import (
    BlastRemoteFailure,
    BlastTimeoutError,
    BlastValidationError,
    LocalBlastExecutionError,
    LocalBlastTimeoutError,
    LocalBlastUnavailableError,
)
from .local_blast import (
    OUTFMT_6_SPEC,
    get_local_db_identifier,
    is_executable_available,
    parse_blast_tsv,
    resolve_local_db,
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


def _compute_cache_key(
    sequence: str,
    program: str,
    database: str,
    options: dict[str, Any] | None = None,
    backend: str = "remote",
    db_ident: str = "",
) -> str:
    """Compute a cache key separating local and remote backends as well as local databases."""
    opts = options or {}
    # Filter out runtime/transport parameters from cache identity
    filtered_opts = {
        k: v
        for k, v in opts.items()
        if k
        not in (
            "client",
            "sleep_fn",
            "time_fn",
            "candidate_id",
            "use_cache",
            "backend_requested",
            "backend",
        )
    }
    serialized_opts = json.dumps(filtered_opts, sort_keys=True, default=str)
    key_src = f"{sequence}:{program}:{backend}:{database}:{db_ident}:{serialized_opts}"
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


# ---------------------------------------------------------------------------
# Backend Abstraction
# ---------------------------------------------------------------------------


class BlastBackend(abc.ABC):
    """Abstract base class for sequence similarity search backends."""

    @abc.abstractmethod
    def blastp(
        self,
        sequence: str,
        database: str = "swissprot",
        candidate_id: str | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        """Execute BLASTP search and return normalized result dictionary."""

    @abc.abstractmethod
    def is_available(self, database: str | None = None) -> bool:
        """Return True if backend is available for execution."""


class LocalBlastBackend(BlastBackend):
    """Local BLAST+ execution backend using native blastp."""

    def __init__(
        self,
        config: NCBIConfig | None = None,
        executable: str | None = None,
    ) -> None:
        self.config = config or NCBIConfig()
        self.executable = executable or self.config.blastp_executable

    def is_available(self, database: str | None = None) -> bool:
        if not is_executable_available(self.executable):
            return False
        if database is not None:
            db_path = resolve_local_db(database, self.config)
            return db_path is not None
        return True

    def blastp(
        self,
        sequence: str,
        database: str = "swissprot",
        candidate_id: str | None = None,
        timeout_seconds: float | None = None,
        num_threads: int | None = None,
        evalue_cutoff: float | None = None,
        hitlist_size: int | None = None,
        backend_requested: str = "local",
        **options: Any,
    ) -> dict[str, Any]:
        normalized_seq = normalize_protein_sequence(sequence)

        if not is_executable_available(self.executable):
            raise LocalBlastUnavailableError(
                f"Local blastp executable '{self.executable}' not found on PATH"
            )

        db_path = resolve_local_db(database, self.config)
        if not db_path:
            raise LocalBlastUnavailableError(
                f"Local BLAST database '{database}' could not be resolved or does not exist"
            )

        effective_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else self.config.blast_local_timeout_seconds
        )
        threads = (
            num_threads
            if num_threads is not None
            else self.config.blast_local_num_threads
        )

        # Safely create temporary query FASTA file
        temp_path: str | None = None
        with tempfile.NamedTemporaryFile(mode="w", suffix=".fasta", delete=False) as tf:
            temp_path = tf.name
            tf.write(f">query\n{normalized_seq}\n")

        cmd: list[str] = [
            self.executable,
            "-query",
            temp_path,
            "-db",
            str(db_path),
            "-outfmt",
            OUTFMT_6_SPEC,
            "-num_threads",
            str(threads),
        ]

        if evalue_cutoff is not None:
            cmd.extend(["-evalue", str(evalue_cutoff)])
        elif "EXPECT" in options:
            cmd.extend(["-evalue", str(options["EXPECT"])])

        if hitlist_size is not None:
            cmd.extend(["-max_target_seqs", str(hitlist_size)])
        elif "HITLIST_SIZE" in options:
            cmd.extend(["-max_target_seqs", str(options["HITLIST_SIZE"])])

        start_time = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LocalBlastTimeoutError(
                f"Local blastp search timed out after {effective_timeout:.1f}s"
            ) from exc
        except OSError as exc:
            raise LocalBlastExecutionError(
                f"Failed to execute local blastp: {exc}",
                cmd=cmd,
            ) from exc
        finally:
            if temp_path:
                with contextlib.suppress(OSError):
                    Path(temp_path).unlink(missing_ok=True)

        if proc.returncode != 0:
            raise LocalBlastExecutionError(
                f"Local blastp failed with exit code {proc.returncode}: {proc.stderr.strip()}",
                returncode=proc.returncode,
                stderr=proc.stderr,
                cmd=cmd,
            )

        hits = parse_blast_tsv(
            proc.stdout,
            candidate_id=candidate_id,
            query_id="query",
            query_length=len(normalized_seq),
            database=database,
        )

        duration_ms = round((time.monotonic() - start_time) * 1000.0, 2)

        return {
            "query_id": "query",
            "candidate_id": candidate_id,
            "program": "blastp",
            "database": database,
            "backend_requested": backend_requested,
            "backend_used": "local",
            "rid": "",
            "status": "complete",
            "query_length": len(normalized_seq),
            "duration_ms": duration_ms,
            "hits": hits,
            "provenance": "database-derived",
            "source": "local_blast",
        }


class RemoteNcbiBlastBackend(BlastBackend):
    """Remote NCBI BLAST URL API backend."""

    def __init__(
        self,
        config: NCBIConfig | None = None,
        client: NcbiClient | None = None,
    ) -> None:
        self.config = config or NCBIConfig()
        self.client = client

    def is_available(self, database: str | None = None) -> bool:
        return True

    def blastp(
        self,
        sequence: str,
        database: str = "nr",
        candidate_id: str | None = None,
        timeout_seconds: float | None = None,
        poll_interval: float | None = None,
        max_poll_attempts: int | None = None,
        client: NcbiClient | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        time_fn: Callable[[], float] = time.monotonic,
        backend_requested: str = "remote",
        **options: Any,
    ) -> dict[str, Any]:
        normalized_seq = normalize_protein_sequence(sequence)
        c = client or self.client or NcbiClient(config=self.config)

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
                "backend_requested": backend_requested,
                "backend_used": "remote",
                "rid": "",
                "status": "budget_exhausted",
                "error": f"BLAST query budget exceeded ({max_queries} queries allowed per run)",
                "query_length": len(normalized_seq),
                "duration_ms": 0.0,
                "hits": [],
                "provenance": "database-derived",
                "source": "ncbi_blast",
            }

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

        _CONCURRENCY_SEMAPHORE.acquire()
        start_time = time_fn()
        try:
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

            initial_wait = min(float(rtoe), effective_timeout)
            if initial_wait > 0:
                sleep_fn(initial_wait)

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
                    duration_ms = round((time_fn() - start_time) * 1000.0, 2)
                    parsed["duration_ms"] = duration_ms
                    parsed["backend_requested"] = backend_requested
                    parsed["backend_used"] = "remote"
                    parsed["source"] = "ncbi_blast"
                    parsed["provenance"] = "database-derived"
                    return parsed

                if status == "WAITING":
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


class AutoBlastBackend(BlastBackend):
    """Composite backend that automatically selects local BLAST+ if available,
    falling back to remote NCBI BLAST URL API otherwise."""

    def __init__(
        self,
        local_backend: LocalBlastBackend | None = None,
        remote_backend: RemoteNcbiBlastBackend | None = None,
        config: NCBIConfig | None = None,
    ) -> None:
        self.config = config or NCBIConfig()
        self.local_backend = local_backend or LocalBlastBackend(config=self.config)
        self.remote_backend = remote_backend or RemoteNcbiBlastBackend(config=self.config)

    def is_available(self, database: str | None = None) -> bool:
        return self.local_backend.is_available(database) or self.remote_backend.is_available(database)

    def blastp(
        self,
        sequence: str,
        database: str = "swissprot",
        candidate_id: str | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        backend_req = options.get("backend_requested", "auto")
        opts = dict(options)
        opts["backend_requested"] = backend_req

        if self.local_backend.is_available(database=database):
            logger.info("AutoBlastBackend: using LocalBlastBackend for database %r", database)
            return self.local_backend.blastp(
                sequence=sequence,
                database=database,
                candidate_id=candidate_id,
                **opts,
            )

        logger.info(
            "AutoBlastBackend: local BLAST unavailable for database %r; falling back to RemoteNcbiBlastBackend",
            database,
        )
        return self.remote_backend.blastp(
            sequence=sequence,
            database=database,
            candidate_id=candidate_id,
            **opts,
        )


def blastp(
    sequence: str,
    database: str = "nr",
    candidate_id: str | None = None,
    backend: str | None = None,
    timeout_seconds: float | None = None,
    poll_interval: float | None = None,
    max_poll_attempts: int | None = None,
    client: NcbiClient | None = None,
    use_cache: bool = True,
    sleep_fn: Callable[[float], None] = time.sleep,
    time_fn: Callable[[], float] = time.monotonic,
    **options: Any,
) -> dict[str, Any]:
    """Execute BLASTP sequence similarity search using the chosen backend (auto, local, remote).

    Args:
        sequence: Protein amino acid sequence.
        database: Target database name (e.g. 'nr', 'swissprot', 'bacteriocin') or local path.
        candidate_id: Optional candidate ID to associate with the query.
        backend: Backend mode: 'auto' (default), 'local', or 'remote'.
        timeout_seconds: Execution or polling timeout.
        poll_interval: Polling interval for remote searches.
        max_poll_attempts: Max polling attempts for remote searches.
        client: NcbiClient instance for remote queries.
        use_cache: If True, reuse cached results for identical query parameters.
        sleep_fn: Sleep function for pacing/polling.
        time_fn: Time provider for measuring durations.
        **options: Additional BLAST options (e.g. evalue_cutoff, hitlist_size).

    Returns:
        Structured result dict matching database-derived provenance schema.

    Raises:
        BlastValidationError: If the sequence is malformed.
        LocalBlastUnavailableError: If backend='local' is requested and unavailable.
        LocalBlastExecutionError: If local blastp execution fails.
        LocalBlastTimeoutError / BlastTimeoutError: If search times out.
        BlastRemoteFailure: If remote NCBI BLAST search fails.
        BlastParseError / LocalBlastParseError: If output cannot be parsed.
    """
    normalized_seq = normalize_protein_sequence(sequence)
    c = client or NcbiClient()

    backend_req = (backend or c.config.blast_backend or "auto").strip().lower()
    if backend_req not in ("auto", "local", "remote"):
        raise ValueError(
            f"Invalid BLAST backend: {backend!r}. Must be 'auto', 'local', or 'remote'."
        )

    # Resolve local database path and identifier if local is to be evaluated
    local_backend = LocalBlastBackend(config=c.config)
    local_available = local_backend.is_available(database=database)

    if backend_req == "local":
        if not local_available:
            raise LocalBlastUnavailableError(
                f"Local BLAST backend requested but unavailable for database {database!r} "
                f"(executable '{local_backend.executable}' or database files missing)"
            )
        effective_backend = "local"
        db_path = resolve_local_db(database, c.config)
        db_ident = get_local_db_identifier(db_path) if db_path else ""
    elif backend_req == "remote":
        effective_backend = "remote"
        db_ident = ""
    else:  # auto
        if local_available:
            effective_backend = "local"
            db_path = resolve_local_db(database, c.config)
            db_ident = get_local_db_identifier(db_path) if db_path else ""
        else:
            effective_backend = "remote"
            db_ident = ""

    # Cache check
    cache_enabled = use_cache and c.config.blast_cache_enabled
    cache_key = _compute_cache_key(
        sequence=normalized_seq,
        program="blastp",
        database=database,
        options=options,
        backend=effective_backend,
        db_ident=db_ident,
    )

    if cache_enabled:
        with _CACHE_LOCK:
            if cache_key in _BLAST_CACHE:
                cached = dict(_BLAST_CACHE[cache_key])
                cached["candidate_id"] = candidate_id
                cached["backend_requested"] = backend_req
                return cached

    # Dispatch to effective backend
    if effective_backend == "local":
        result = local_backend.blastp(
            sequence=normalized_seq,
            database=database,
            candidate_id=candidate_id,
            timeout_seconds=timeout_seconds,
            backend_requested=backend_req,
            **options,
        )
    else:
        remote_backend = RemoteNcbiBlastBackend(config=c.config, client=c)
        result = remote_backend.blastp(
            sequence=normalized_seq,
            database=database,
            candidate_id=candidate_id,
            timeout_seconds=timeout_seconds,
            poll_interval=poll_interval,
            max_poll_attempts=max_poll_attempts,
            client=c,
            sleep_fn=sleep_fn,
            time_fn=time_fn,
            backend_requested=backend_req,
            **options,
        )

    if cache_enabled and result.get("status") == "complete":
        with _CACHE_LOCK:
            _BLAST_CACHE[cache_key] = result

    return result


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
    source = result.get("source", "ncbi_blast")

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
            "source": source,
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
            "source": source,
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
        "source": source,
    }


__all__ = [
    "VALID_PROTEIN_RESIDUES",
    "AutoBlastBackend",
    "BlastBackend",
    "BlastBudgetTracker",
    "LocalBlastBackend",
    "RemoteNcbiBlastBackend",
    "blastp",
    "check_blast_status",
    "clear_blast_cache",
    "fetch_blast_results",
    "normalize_protein_sequence",
    "reset_blast_budget",
    "submit_blastp",
    "summarize_blast_similarity",
]
