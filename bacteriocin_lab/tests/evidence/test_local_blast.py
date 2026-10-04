from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from bacteriocin_lab.agents.candidate.agent import CandidateGenerationAgent
from bacteriocin_lab.agents.evidence import (
    AutoBlastBackend,
    BlastBackend,
    BlastTimeoutError,
    BlastValidationError,
    LocalBlastBackend,
    LocalBlastDatabaseError,
    LocalBlastError,
    LocalBlastExecutionError,
    LocalBlastParseError,
    LocalBlastTimeoutError,
    LocalBlastUnavailableError,
    NcbiClient,
    NCBIConfig,
    RemoteNcbiBlastBackend,
    blastp,
    build_local_blast_db,
    clear_blast_cache,
    parse_blast_tsv,
    reset_blast_budget,
    resolve_local_db,
    summarize_blast_similarity,
)
from bacteriocin_lab.agents.evidence.ncbi.blast import _BLAST_CACHE

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# Deterministic outfmt 6 fixture matching Nisin A / Nisin Z hits
SAMPLE_OUTFMT_6_TSV = (
    "query\tsp|P0A334|NISN_LACLA\t100.00\t34\t0\t0\t1\t34\t24\t57\t1.20e-15\t68.2\t"
    "RecName: Full=Nisin-A; Flags: Precursor [Lactococcus lactis]\tP0A334\t57\n"
    "query\tsp|P29559|NISZ_LACLA\t97.06\t34\t1\t0\t1\t34\t24\t57\t3.40e-14\t64.5\t"
    "RecName: Full=Nisin-Z; Flags: Precursor [Lactococcus lactis]\tP29559\t57\n"
)

BLAST_EXEC_PATCH = "bacteriocin_lab.agents.evidence.ncbi.blast.is_executable_available"
LOCAL_EXEC_PATCH = "bacteriocin_lab.agents.evidence.ncbi.local_blast.is_executable_available"


def _read_fixture(filename: str) -> str:
    return (FIXTURES_DIR / filename).read_text(encoding="utf-8")


def _mock_transport_factory(responses: list[tuple[int, dict[str, str], str]]):
    history: list[dict[str, Any]] = []
    resp_queue = list(responses)

    def transport(
        url: str, headers: dict[str, str], timeout_seconds: float
    ) -> tuple[int, dict[str, str], str]:
        history.append({"url": url, "headers": headers, "timeout": timeout_seconds})
        if not resp_queue:
            raise RuntimeError(f"No more mocked responses for {url}")
        return resp_queue.pop(0)

    return transport, history


@pytest.fixture(autouse=True)
def _clean_state():
    """Ensure clean cache and budget before and after each test."""
    clear_blast_cache()
    reset_blast_budget()
    yield
    clear_blast_cache()
    reset_blast_budget()


# --------------------------------------------------------------------------
# TEST 1 — BACKEND SELECTION
# --------------------------------------------------------------------------
def test_1_backend_selection(tmp_path: Path) -> None:
    """When local blastp executable and database exist, backend='auto' selects LocalBlastBackend."""
    db_file = tmp_path / "swissprot.pin"
    db_file.touch()

    config = NCBIConfig(
        blast_backend="auto",
        blast_local_swissprot_db=str(tmp_path / "swissprot"),
        blastp_executable="blastp",
    )

    completed = subprocess.CompletedProcess(
        args=["blastp"],
        returncode=0,
        stdout=SAMPLE_OUTFMT_6_TSV,
        stderr="",
    )

    with (
        patch(BLAST_EXEC_PATCH, return_value=True),
        patch("subprocess.run", return_value=completed) as mock_run,
    ):
        result = blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            database="swissprot",
            backend="auto",
            candidate_id="cand_test_1",
            client=NcbiClient(config=config),
        )

        assert mock_run.called
        assert result["backend_requested"] == "auto"
        assert result["backend_used"] == "local"
        assert result["source"] == "local_blast"
        assert result["provenance"] == "database-derived"
        assert result["status"] == "complete"
        assert len(result["hits"]) == 2


# --------------------------------------------------------------------------
# TEST 2 — AUTO FALLBACK
# --------------------------------------------------------------------------
def test_2_auto_fallback() -> None:
    """When local executable is missing, backend='auto' falls back to remote NCBI backend."""
    submit_txt = _read_fixture("blast_submit.txt")
    ready_txt = _read_fixture("blast_status_ready.txt")
    results_xml = _read_fixture("blast_results.xml")

    responses = [
        (200, {}, submit_txt),
        (200, {}, ready_txt),
        (200, {}, results_xml),
    ]
    transport, history = _mock_transport_factory(responses)
    client = NcbiClient(transport=transport)

    with (
        patch(BLAST_EXEC_PATCH, return_value=False),
        patch("subprocess.run") as mock_subprocess,
    ):
        result = blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            database="nr",
            backend="auto",
            candidate_id="cand_test_2",
            client=client,
            sleep_fn=lambda _: None,
        )

        assert not mock_subprocess.called
        assert len(history) == 3
        assert result["backend_requested"] == "auto"
        assert result["backend_used"] == "remote"
        assert result["source"] == "ncbi_blast"
        assert result["provenance"] == "database-derived"
        assert result["status"] == "complete"


# --------------------------------------------------------------------------
# TEST 3 — LOCAL REQUIRED
# --------------------------------------------------------------------------
def test_3_local_required() -> None:
    """When backend='local' is requested and local is unavailable, raises error."""
    with (
        patch(BLAST_EXEC_PATCH, return_value=False),
        pytest.raises(LocalBlastUnavailableError) as exc_info,
    ):
        blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            database="swissprot",
            backend="local",
        )
    assert issubclass(LocalBlastUnavailableError, LocalBlastError)
    assert "unavailable" in str(exc_info.value).lower()


# --------------------------------------------------------------------------
# TEST 4 — SUBPROCESS COMMAND
# --------------------------------------------------------------------------
def test_4_subprocess_command(tmp_path: Path) -> None:
    """Subprocess command list includes blastp, -query, -db, -outfmt, -num_threads."""
    db_file = tmp_path / "swissprot.pin"
    db_file.touch()

    config = NCBIConfig(
        blast_local_swissprot_db=str(tmp_path / "swissprot"),
        blast_local_num_threads=8,
    )

    completed = subprocess.CompletedProcess(
        args=["blastp"],
        returncode=0,
        stdout="",
        stderr="",
    )

    with (
        patch(BLAST_EXEC_PATCH, return_value=True),
        patch("subprocess.run", return_value=completed) as mock_run,
    ):
        blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            database="swissprot",
            backend="local",
            client=NcbiClient(config=config),
        )

        assert mock_run.called
        cmd = mock_run.call_args[0][0]
        kwargs = mock_run.call_args[1]

        assert isinstance(cmd, list)
        assert cmd[0] == "blastp"
        assert "-query" in cmd
        assert "-db" in cmd
        assert str(tmp_path / "swissprot") in cmd
        assert "-outfmt" in cmd
        assert "-num_threads" in cmd
        assert "8" in cmd
        assert kwargs.get("shell") is not True


# --------------------------------------------------------------------------
# TEST 5 — LOCAL TSV PARSING
# --------------------------------------------------------------------------
def test_5_local_tsv_parsing() -> None:
    """Parse outfmt 6 TSV into structured hits with accession, identity, coords, evalue."""
    hits = parse_blast_tsv(
        SAMPLE_OUTFMT_6_TSV,
        candidate_id="cand_test_5",
        query_id="query",
        query_length=34,
        database="swissprot",
    )

    assert len(hits) == 2

    h1 = hits[0]
    assert h1["rank"] == 1
    assert h1["accession"] == "P0A334"
    assert h1["identity_percent"] == 100.0
    assert h1["alignment_length"] == 34
    assert h1["mismatch"] == 0
    assert h1["gap_opens"] == 0
    assert h1["query_start"] == 1
    assert h1["query_end"] == 34
    assert h1["subject_start"] == 24
    assert h1["subject_end"] == 57
    assert h1["e_value"] == 1.2e-15
    assert h1["bit_score"] == 68.2
    assert "Nisin-A" in h1["title"]
    assert h1["organism"] == "Lactococcus lactis"
    assert h1["subject_length"] == 57

    h2 = hits[1]
    assert h2["rank"] == 2
    assert h2["accession"] == "P29559"
    assert h2["identity_percent"] == 97.06
    assert h2["alignment_length"] == 34
    assert h2["mismatch"] == 1
    assert h2["e_value"] == 3.4e-14
    assert h2["bit_score"] == 64.5
    assert "Nisin-Z" in h2["title"]


# --------------------------------------------------------------------------
# TEST 6 — ZERO HITS
# --------------------------------------------------------------------------
def test_6_zero_hits(tmp_path: Path) -> None:
    """Empty valid stdout returns hits=[] and status='complete' without failing."""
    db_file = tmp_path / "swissprot.pin"
    db_file.touch()

    config = NCBIConfig(blast_local_swissprot_db=str(tmp_path / "swissprot"))
    completed = subprocess.CompletedProcess(
        args=["blastp"],
        returncode=0,
        stdout="",
        stderr="",
    )

    with (
        patch(BLAST_EXEC_PATCH, return_value=True),
        patch("subprocess.run", return_value=completed),
    ):
        result = blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            database="swissprot",
            backend="local",
            client=NcbiClient(config=config),
        )

        assert result["status"] == "complete"
        assert result["hits"] == []
        assert result["backend_used"] == "local"
        assert result["source"] == "local_blast"
        assert result["provenance"] == "database-derived"


# --------------------------------------------------------------------------
# TEST 7 — NONZERO EXIT
# --------------------------------------------------------------------------
def test_7_nonzero_exit(tmp_path: Path) -> None:
    """Subprocess nonzero exit code raises structured LocalBlastExecutionError."""
    db_file = tmp_path / "swissprot.pin"
    db_file.touch()

    config = NCBIConfig(blast_local_swissprot_db=str(tmp_path / "swissprot"))
    failed_proc = subprocess.CompletedProcess(
        args=["blastp"],
        returncode=2,
        stdout="",
        stderr="BLAST Database error: Cannot open index file",
    )

    with (
        patch(BLAST_EXEC_PATCH, return_value=True),
        patch("subprocess.run", return_value=failed_proc),
        pytest.raises(LocalBlastExecutionError) as exc_info,
    ):
        blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            database="swissprot",
            backend="local",
            client=NcbiClient(config=config),
        )

    err = exc_info.value
    assert err.returncode == 2
    assert "Cannot open index file" in (err.stderr or "")
    assert err.cmd is not None
    assert issubclass(LocalBlastExecutionError, LocalBlastError)


# --------------------------------------------------------------------------
# TEST 8 — TIMEOUT
# --------------------------------------------------------------------------
def test_8_timeout(tmp_path: Path) -> None:
    """Subprocess timeout raises structured LocalBlastTimeoutError."""
    db_file = tmp_path / "swissprot.pin"
    db_file.touch()

    config = NCBIConfig(blast_local_swissprot_db=str(tmp_path / "swissprot"))

    def timeout_mock(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["blastp"], timeout=10.0)

    with (
        patch(BLAST_EXEC_PATCH, return_value=True),
        patch("subprocess.run", side_effect=timeout_mock),
        pytest.raises(LocalBlastTimeoutError) as exc_info,
    ):
        blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            database="swissprot",
            backend="local",
            client=NcbiClient(config=config),
        )

    assert issubclass(LocalBlastTimeoutError, LocalBlastError)
    assert issubclass(LocalBlastTimeoutError, BlastTimeoutError)
    assert "timed out" in str(exc_info.value).lower()


# --------------------------------------------------------------------------
# TEST 9 — TEMP FILE CLEANUP
# --------------------------------------------------------------------------
def test_9_temp_file_cleanup(tmp_path: Path) -> None:
    """Temporary query file is deleted after success, execution failure, and timeout."""
    db_file = tmp_path / "swissprot.pin"
    db_file.touch()

    config = NCBIConfig(blast_local_swissprot_db=str(tmp_path / "swissprot"))
    observed_query_paths: list[str] = []

    # Case A: Success
    def success_mock(cmd, **kwargs):
        query_idx = cmd.index("-query")
        query_path = cmd[query_idx + 1]
        observed_query_paths.append(query_path)
        assert Path(query_path).is_file()
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with (
        patch(BLAST_EXEC_PATCH, return_value=True),
        patch("subprocess.run", side_effect=success_mock),
    ):
        blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            database="swissprot",
            backend="local",
            client=NcbiClient(config=config),
            use_cache=False,
        )

    assert len(observed_query_paths) == 1
    assert not Path(observed_query_paths[0]).exists()

    # Case B: Execution Failure
    observed_query_paths.clear()

    def fail_mock(cmd, **kwargs):
        query_idx = cmd.index("-query")
        query_path = cmd[query_idx + 1]
        observed_query_paths.append(query_path)
        assert Path(query_path).is_file()
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="Error")

    with (
        patch(BLAST_EXEC_PATCH, return_value=True),
        patch("subprocess.run", side_effect=fail_mock),
        pytest.raises(LocalBlastExecutionError),
    ):
        blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            database="swissprot",
            backend="local",
            client=NcbiClient(config=config),
            use_cache=False,
        )

    assert len(observed_query_paths) == 1
    assert not Path(observed_query_paths[0]).exists()

    # Case C: Timeout
    observed_query_paths.clear()

    def timeout_mock(cmd, **kwargs):
        query_idx = cmd.index("-query")
        query_path = cmd[query_idx + 1]
        observed_query_paths.append(query_path)
        assert Path(query_path).is_file()
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=5.0)

    with (
        patch(BLAST_EXEC_PATCH, return_value=True),
        patch("subprocess.run", side_effect=timeout_mock),
        pytest.raises(LocalBlastTimeoutError),
    ):
        blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            database="swissprot",
            backend="local",
            client=NcbiClient(config=config),
            use_cache=False,
        )

    assert len(observed_query_paths) == 1
    assert not Path(observed_query_paths[0]).exists()


# --------------------------------------------------------------------------
# TEST 10 — RESULT PROVENANCE
# --------------------------------------------------------------------------
def test_10_result_provenance(tmp_path: Path) -> None:
    """Local result strictly enforces provenance='database-derived' and source='local_blast'."""
    db_file = tmp_path / "swissprot.pin"
    db_file.touch()

    config = NCBIConfig(blast_local_swissprot_db=str(tmp_path / "swissprot"))
    completed = subprocess.CompletedProcess(
        args=["blastp"],
        returncode=0,
        stdout=SAMPLE_OUTFMT_6_TSV,
        stderr="",
    )

    with (
        patch(BLAST_EXEC_PATCH, return_value=True),
        patch("subprocess.run", return_value=completed),
    ):
        result = blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            database="swissprot",
            backend="local",
            client=NcbiClient(config=config),
        )

        assert result["provenance"] == "database-derived"
        assert result["source"] == "local_blast"
        assert result["status"] == "complete"
        assert result["backend_used"] == "local"
        assert "duration_ms" in result
        assert isinstance(result["duration_ms"], float)


# --------------------------------------------------------------------------
# TEST 11 — AGENT INTEGRATION
# --------------------------------------------------------------------------
def test_11_agent_integration(tmp_path: Path) -> None:
    """Candidate Generation Agent calls similarity tool with backend='local'."""
    db_file = tmp_path / "bacteriocins.pin"
    db_file.touch()

    config = NCBIConfig(blast_local_bacteriocin_db=str(tmp_path / "bacteriocins"))
    client = NcbiClient(config=config)
    agent = CandidateGenerationAgent(ncbi_client=client)

    completed = subprocess.CompletedProcess(
        args=["blastp"],
        returncode=0,
        stdout=SAMPLE_OUTFMT_6_TSV,
        stderr="",
    )

    with (
        patch(BLAST_EXEC_PATCH, return_value=True),
        patch("subprocess.run", return_value=completed),
    ):
        cand_result = agent.check_candidate_similarity(
            candidate_id="cand_b4_01",
            sequence="ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            database="bacteriocin",
            backend="local",
        )

        assert cand_result["candidate_id"] == "cand_b4_01"
        assert cand_result["provenance"] == "database-derived"
        assert cand_result["source"] == "local_blast"
        assert cand_result["backend_used"] == "local"
        assert len(cand_result["hits"]) == 2

        # Summarizer also consumes it seamlessly
        summary = summarize_blast_similarity(cand_result)
        assert summary["novelty"] == "low"  # 100% identity hit
        assert summary["provenance"] == "database-derived"
        assert summary["source"] == "local_blast"


# --------------------------------------------------------------------------
# TEST 12 — CACHE SEPARATION
# --------------------------------------------------------------------------
def test_12_cache_separation(tmp_path: Path) -> None:
    """Local and remote searches for identical sequences produce distinct cache entries."""
    db_file = tmp_path / "swissprot.pin"
    db_file.touch()

    config = NCBIConfig(blast_local_swissprot_db=str(tmp_path / "swissprot"))

    # 1. Local execution
    completed = subprocess.CompletedProcess(
        args=["blastp"],
        returncode=0,
        stdout=SAMPLE_OUTFMT_6_TSV,
        stderr="",
    )
    with (
        patch(BLAST_EXEC_PATCH, return_value=True),
        patch("subprocess.run", return_value=completed),
    ):
        res_local = blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            database="swissprot",
            backend="local",
            client=NcbiClient(config=config),
            use_cache=True,
        )

    # 2. Remote execution
    submit_txt = _read_fixture("blast_submit.txt")
    ready_txt = _read_fixture("blast_status_ready.txt")
    results_xml = _read_fixture("blast_results.xml")

    responses = [
        (200, {}, submit_txt),
        (200, {}, ready_txt),
        (200, {}, results_xml),
    ]
    transport, _ = _mock_transport_factory(responses)
    client_remote = NcbiClient(config=config, transport=transport)

    res_remote = blastp(
        "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
        database="swissprot",
        backend="remote",
        client=client_remote,
        use_cache=True,
        sleep_fn=lambda _: None,
    )

    assert res_local["source"] == "local_blast"
    assert res_remote["source"] == "ncbi_blast"
    assert len(_BLAST_CACHE) == 2


# --------------------------------------------------------------------------
# TEST 13 — DIFFERENT LOCAL DATABASES
# --------------------------------------------------------------------------
def test_13_different_local_databases(tmp_path: Path) -> None:
    """Different local databases produce distinct cache entries."""
    (tmp_path / "bacteriocins.pin").touch()
    (tmp_path / "swissprot.pin").touch()

    config = NCBIConfig(
        blast_local_bacteriocin_db=str(tmp_path / "bacteriocins"),
        blast_local_swissprot_db=str(tmp_path / "swissprot"),
    )

    completed = subprocess.CompletedProcess(
        args=["blastp"],
        returncode=0,
        stdout=SAMPLE_OUTFMT_6_TSV,
        stderr="",
    )

    with (
        patch(BLAST_EXEC_PATCH, return_value=True),
        patch("subprocess.run", return_value=completed),
    ):
        blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            database="bacteriocin",
            backend="local",
            client=NcbiClient(config=config),
            use_cache=True,
        )
        blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            database="swissprot",
            backend="local",
            client=NcbiClient(config=config),
            use_cache=True,
        )

    assert len(_BLAST_CACHE) == 2


# --------------------------------------------------------------------------
# TEST 14 — BUILD DATABASE COMMAND
# --------------------------------------------------------------------------
def test_14_build_database_command(tmp_path: Path) -> None:
    """makeblastdb is called with a safe argument list and correct dbtype."""
    fasta_file = tmp_path / "peptides.fasta"
    fasta_file.write_text(">p1\nACDEFGHIKLMNPQRSTVWY\n")
    out_prefix = tmp_path / "dbs" / "peptides_db"

    completed = subprocess.CompletedProcess(
        args=["makeblastdb"],
        returncode=0,
        stdout="Database created.",
        stderr="",
    )

    with (
        patch(LOCAL_EXEC_PATCH, return_value=True),
        patch("subprocess.run", return_value=completed) as mock_run,
    ):
        res = build_local_blast_db(
            fasta_path=fasta_file,
            output_prefix=out_prefix,
            dbtype="prot",
            title="Peptides DB",
        )

        assert res["status"] == "created"
        assert mock_run.called

        cmd = mock_run.call_args[0][0]
        kwargs = mock_run.call_args[1]

        assert isinstance(cmd, list)
        assert cmd[0] == "makeblastdb"
        assert "-in" in cmd
        assert str(fasta_file) in cmd
        assert "-dbtype" in cmd
        assert "prot" in cmd
        assert "-out" in cmd
        assert str(out_prefix) in cmd
        assert "-title" in cmd
        assert "Peptides DB" in cmd
        assert kwargs.get("shell") is not True


# --------------------------------------------------------------------------
# TEST 15 — NO SHELL INJECTION
# --------------------------------------------------------------------------
def test_15_no_shell_injection(tmp_path: Path) -> None:
    """Malicious-looking strings cannot inject shell commands."""
    # Sequence with shell metacharacters is rejected by validation
    with pytest.raises(BlastValidationError):
        blastp("MKT; rm -rf /; LLL", backend="local")

    # Unsafe database path containing null bytes is safely rejected
    unsafe_db = "swissprot\x00; rm -rf /"
    config = NCBIConfig()
    resolved = resolve_local_db(unsafe_db, config)
    assert resolved is None

    # Even with unusual candidate_id or characters, command remains argument list
    db_file = tmp_path / "swissprot.pin"
    db_file.touch()
    config = NCBIConfig(blast_local_swissprot_db=str(tmp_path / "swissprot"))

    completed = subprocess.CompletedProcess(
        args=["blastp"],
        returncode=0,
        stdout="",
        stderr="",
    )

    with (
        patch(BLAST_EXEC_PATCH, return_value=True),
        patch("subprocess.run", return_value=completed) as mock_run,
    ):
        res = blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            database="swissprot",
            candidate_id="malicious; cat /etc/passwd | sh",
            backend="local",
            client=NcbiClient(config=config),
        )

        assert res["status"] == "complete"
        assert mock_run.called
        kwargs = mock_run.call_args[1]
        assert kwargs.get("shell") is not True
        cmd = mock_run.call_args[0][0]
        assert isinstance(cmd, list)
        assert "malicious; cat /etc/passwd | sh" not in cmd


# --------------------------------------------------------------------------
# TEST 16 — BACKWARD COMPATIBILITY
# --------------------------------------------------------------------------
def test_16_backward_compatibility() -> None:
    """Default blastp call preserves remote backend and existing XML output format."""
    submit_txt = _read_fixture("blast_submit.txt")
    ready_txt = _read_fixture("blast_status_ready.txt")
    results_xml = _read_fixture("blast_results.xml")

    responses = [
        (200, {}, submit_txt),
        (200, {}, ready_txt),
        (200, {}, results_xml),
    ]
    transport, _ = _mock_transport_factory(responses)
    client = NcbiClient(transport=transport)

    result = blastp(
        "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
        candidate_id="cand_test_16",
        client=client,
        sleep_fn=lambda _: None,
    )

    assert result["status"] == "complete"
    assert result["candidate_id"] == "cand_test_16"
    assert result["source"] == "ncbi_blast"
    assert result["provenance"] == "database-derived"
    assert len(result["hits"]) == 2
    assert result["hits"][0]["accession"] == "WP_001234.1"


# --------------------------------------------------------------------------
# TEST 17 — FULL REPO REGRESSION / HELPER VERIFICATIONS
# --------------------------------------------------------------------------
def test_17_helper_verifications() -> None:
    """Verify backend class hierarchy and error mapping."""
    assert issubclass(LocalBlastBackend, BlastBackend)
    assert issubclass(RemoteNcbiBlastBackend, BlastBackend)
    assert issubclass(AutoBlastBackend, BlastBackend)

    assert issubclass(LocalBlastUnavailableError, LocalBlastError)
    assert issubclass(LocalBlastDatabaseError, LocalBlastError)
    assert issubclass(LocalBlastExecutionError, LocalBlastError)
    assert issubclass(LocalBlastTimeoutError, LocalBlastError)
    assert issubclass(LocalBlastTimeoutError, BlastTimeoutError)
    assert issubclass(LocalBlastParseError, LocalBlastError)

    # Malformed TSV row raises LocalBlastParseError
    with pytest.raises(LocalBlastParseError):
        parse_blast_tsv("short\trow\twith\tfew\tcols\n")


# --------------------------------------------------------------------------
# OPTIONAL LIVE LOCAL SMOKE TEST
# --------------------------------------------------------------------------
@pytest.mark.skipif(
    os.getenv("RUN_LOCAL_BLAST_TESTS") != "1",
    reason="Live local BLAST tests disabled by default. Enable with RUN_LOCAL_BLAST_TESTS=1",
)
def test_live_local_blast_smoke() -> None:
    """Opt-in live smoke test verifying local BLAST+ execution on system."""
    config = NCBIConfig.from_env()
    backend = LocalBlastBackend(config=config)
    db = (
        os.getenv("BLAST_LOCAL_DEFAULT_DB")
        or os.getenv("BLAST_LOCAL_BACTERIOCIN_DB")
        or "bacteriocin"
    )

    if not backend.is_available(database=db):
        pytest.skip(f"Local blastp executable or database '{db}' not available on system")

    seq = "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK"
    res = blastp(sequence=seq, database=db, backend="local", candidate_id="live_nisin_a")

    assert res["status"] == "complete"
    assert res["backend_used"] == "local"
    assert res["source"] == "local_blast"
    assert res["provenance"] == "database-derived"
    assert isinstance(res["hits"], list)
