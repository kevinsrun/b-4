from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import pytest

from bacteriocin_lab.agents.candidate.agent import CandidateGenerationAgent
from bacteriocin_lab.agents.evidence import (
    BlastError,
    BlastParseError,
    BlastRemoteFailure,
    BlastSubmissionError,
    BlastTimeoutError,
    BlastValidationError,
    LiteratureEvidenceAgent,
    NcbiClient,
    NCBIConfig,
    NCBIRequestError,
    blastp,
    check_blast_status,
    clear_blast_cache,
    fetch_blast_results,
    normalize_protein_sequence,
    reset_blast_budget,
    submit_blastp,
    summarize_blast_similarity,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _read_fixture(filename: str) -> str:
    return (FIXTURES_DIR / filename).read_text(encoding="utf-8")


def _mock_transport_factory(responses: list[tuple[int, dict[str, str], str]]):
    """Create a transport function that sequentially pops responses."""
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
    """Ensure clean cache and budget before each test."""
    clear_blast_cache()
    reset_blast_budget()
    yield
    clear_blast_cache()
    reset_blast_budget()


# --------------------------------------------------------------------------
# TEST 1: VALID SEQUENCE NORMALIZATION
# --------------------------------------------------------------------------
def test_1_valid_sequence_normalization() -> None:
    raw_sequence = "\n  itsislctpg cktgalmgcn\n  mktatchcsi hvsk \n"
    normalized = normalize_protein_sequence(raw_sequence)
    expected = "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK"
    assert normalized == expected
    assert len(normalized) == 34

    # Also verify FASTA header stripping
    fasta_seq = ">candidate_nisin_a\nITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK\n"
    assert normalize_protein_sequence(fasta_seq) == expected


# --------------------------------------------------------------------------
# TEST 2: INVALID SEQUENCE
# --------------------------------------------------------------------------
def test_2_invalid_sequence() -> None:
    # Digits are rejected
    with pytest.raises(BlastValidationError) as exc_info:
        normalize_protein_sequence("MKT123L")
    assert "Invalid characters" in str(exc_info.value)

    # Malformed symbols are rejected
    with pytest.raises(BlastValidationError):
        normalize_protein_sequence("MKT@#$%")

    # Empty string is rejected
    with pytest.raises(BlastValidationError):
        normalize_protein_sequence("   \n\t  ")

    # Too short is rejected (< 3 residues)
    with pytest.raises(BlastValidationError) as exc_info:
        normalize_protein_sequence("MK")
    assert "too short" in str(exc_info.value).lower()


# --------------------------------------------------------------------------
# TEST 3: BLAST SUBMISSION PARSING
# --------------------------------------------------------------------------
def test_3_blast_submission_parsing() -> None:
    submit_txt = _read_fixture("blast_submit.txt")

    def transport(url: str, headers: dict, timeout: float):
        assert "CMD=Put" in url
        assert "PROGRAM=blastp" in url
        return 200, {}, submit_txt

    client = NcbiClient(transport=transport)
    res = submit_blastp(
        "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
        database="nr",
        candidate_id="cand_1",
        client=client,
    )
    assert res["rid"] == "TEST-RID-12345"
    assert res["rtoe"] == 15
    assert res["program"] == "blastp"
    assert res["database"] == "nr"
    assert res["candidate_id"] == "cand_1"


# --------------------------------------------------------------------------
# TEST 4: STATUS WAITING
# --------------------------------------------------------------------------
def test_4_status_waiting() -> None:
    waiting_txt = _read_fixture("blast_status_waiting.txt")

    def transport(url: str, headers: dict, timeout: float):
        assert "FORMAT_OBJECT=SearchInfo" in url
        assert "RID=TEST-RID-12345" in url
        return 200, {}, waiting_txt

    client = NcbiClient(transport=transport)
    status_info = check_blast_status("TEST-RID-12345", client=client)
    assert status_info["status"] == "WAITING"
    assert status_info["has_hits"] is None


# --------------------------------------------------------------------------
# TEST 5: STATUS READY
# --------------------------------------------------------------------------
def test_5_status_ready() -> None:
    ready_txt = _read_fixture("blast_status_ready.txt")

    def transport(url: str, headers: dict, timeout: float):
        assert "FORMAT_OBJECT=SearchInfo" in url
        return 200, {}, ready_txt

    client = NcbiClient(transport=transport)
    status_info = check_blast_status("TEST-RID-12345", client=client)
    assert status_info["status"] == "READY"
    assert status_info["has_hits"] is True


# --------------------------------------------------------------------------
# TEST 6: STATUS FAILED
# --------------------------------------------------------------------------
def test_6_status_failed() -> None:
    submit_txt = _read_fixture("blast_submit.txt")
    failed_txt = _read_fixture("blast_status_failed.txt")

    responses = [
        (200, {}, submit_txt),  # submit
        (200, {}, failed_txt),  # poll 1: FAILED
    ]
    transport, _ = _mock_transport_factory(responses)
    client = NcbiClient(transport=transport)

    with pytest.raises(BlastRemoteFailure) as exc_info:
        blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            client=client,
            sleep_fn=lambda _: None,
        )
    assert "failed remotely" in str(exc_info.value)


# --------------------------------------------------------------------------
# TEST 7: STATUS UNKNOWN
# --------------------------------------------------------------------------
def test_7_status_unknown() -> None:
    submit_txt = _read_fixture("blast_submit.txt")
    unknown_txt = _read_fixture("blast_status_unknown.txt")

    responses = [
        (200, {}, submit_txt),  # submit
        (200, {}, unknown_txt),  # poll 1: UNKNOWN
    ]
    transport, _ = _mock_transport_factory(responses)
    client = NcbiClient(transport=transport)

    with pytest.raises(BlastRemoteFailure) as exc_info:
        blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            client=client,
            sleep_fn=lambda _: None,
        )
    assert "unknown or expired" in str(exc_info.value)


# --------------------------------------------------------------------------
# TEST 8: POLL TIMEOUT
# --------------------------------------------------------------------------
def test_8_poll_timeout() -> None:
    submit_txt = _read_fixture("blast_submit.txt")
    waiting_txt = _read_fixture("blast_status_waiting.txt")

    # Queue submission plus multiple WAITING responses
    responses = [(200, {}, submit_txt)] + [(200, {}, waiting_txt)] * 10
    transport, _ = _mock_transport_factory(responses)
    client = NcbiClient(transport=transport)

    # Use a simulated clock that advances past timeout
    current_time = [0.0]

    def fake_time():
        return current_time[0]

    def fake_sleep(seconds: float):
        current_time[0] += seconds + 10.0

    with pytest.raises(BlastTimeoutError) as exc_info:
        blastp(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            client=client,
            timeout_seconds=25.0,
            poll_interval=5.0,
            sleep_fn=fake_sleep,
            time_fn=fake_time,
        )
    assert "timed out" in str(exc_info.value).lower()


# --------------------------------------------------------------------------
# TEST 9: XML RESULT PARSING
# --------------------------------------------------------------------------
def test_9_xml_result_parsing() -> None:
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
        candidate_id="nisin_a",
        client=client,
        sleep_fn=lambda _: None,
    )

    assert result["status"] == "complete"
    assert result["candidate_id"] == "nisin_a"
    assert result["provenance"] == "database-derived"
    assert result["source"] == "ncbi_blast"
    assert result["query_length"] == 34
    assert len(result["hits"]) == 2

    # Hit 1 checks
    h1 = result["hits"][0]
    assert h1["rank"] == 1
    assert h1["accession"] == "WP_001234.1"
    assert "nisin A" in h1["title"]
    assert h1["organism"] == "Lactococcus lactis"
    assert h1["identity_percent"] == 100.0
    assert h1["positive_percent"] == 100.0
    assert h1["alignment_length"] == 34
    assert h1["e_value"] == 1.2e-15
    assert h1["bit_score"] == 68.2
    assert h1["query_start"] == 1
    assert h1["query_end"] == 34
    assert h1["subject_start"] == 24
    assert h1["subject_end"] == 57

    # Hit 2 checks
    h2 = result["hits"][1]
    assert h2["rank"] == 2
    assert h2["accession"] == "WP_005678.1"
    assert "nisin Z" in h2["title"]
    assert h2["identity_percent"] == pytest.approx(97.06, abs=0.01)


# --------------------------------------------------------------------------
# TEST 10: NO HITS
# --------------------------------------------------------------------------
def test_10_no_hits() -> None:
    submit_txt = _read_fixture("blast_submit.txt")
    ready_txt = _read_fixture("blast_status_ready.txt")
    no_hits_xml = _read_fixture("blast_results_no_hits.xml")

    responses = [
        (200, {}, submit_txt),
        (200, {}, ready_txt),
        (200, {}, no_hits_xml),
    ]
    transport, _ = _mock_transport_factory(responses)
    client = NcbiClient(transport=transport)

    result = blastp(
        "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
        candidate_id="novel_candidate",
        client=client,
        sleep_fn=lambda _: None,
    )

    assert result["status"] == "complete"
    assert result["hits"] == []
    assert result["provenance"] == "database-derived"
    assert result["source"] == "ncbi_blast"


# --------------------------------------------------------------------------
# TEST 11: RETRY TRANSIENT ERROR
# --------------------------------------------------------------------------
def test_11_retry_transient_error() -> None:
    submit_txt = _read_fixture("blast_submit.txt")

    # First attempt: 503 Service Unavailable, Second: 200 Success
    responses = [
        (503, {}, "Service Unavailable"),
        (200, {}, submit_txt),
    ]
    transport, history = _mock_transport_factory(responses)
    client = NcbiClient(transport=transport, backoff_factor=0.0)

    res = submit_blastp("ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK", client=client)
    assert res["rid"] == "TEST-RID-12345"
    assert len(history) == 2


# --------------------------------------------------------------------------
# TEST 12: PERMANENT ERROR
# --------------------------------------------------------------------------
def test_12_permanent_error() -> None:
    responses = [
        (400, {}, "Bad Request"),
    ]
    transport, history = _mock_transport_factory(responses)
    client = NcbiClient(transport=transport, backoff_factor=0.0)

    with pytest.raises(NCBIRequestError) as exc_info:
        submit_blastp("ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK", client=client)

    assert exc_info.value.status_code == 400
    assert len(history) == 1  # No endless retry on 400


# --------------------------------------------------------------------------
# TEST 13: CREDENTIAL REDACTION
# --------------------------------------------------------------------------
def test_13_credential_redaction(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret_key = "SUPER_SECRET_TEST_KEY"
    monkeypatch.setenv("NCBI_API_KEY", secret_key)

    config = NCBIConfig.from_env()
    assert config.api_key == secret_key

    # Repr must mask the key
    repr_str = repr(config)
    assert secret_key not in repr_str
    assert "***REDACTED***" in repr_str

    # Logging must never expose the raw key
    caplog.set_level(logging.DEBUG)
    submit_txt = _read_fixture("blast_submit.txt")

    def transport(url: str, headers: dict, timeout: float):
        return 200, {}, submit_txt

    client = NcbiClient(config=config, transport=transport)
    submit_blastp("ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK", client=client)

    logged_text = caplog.text
    assert secret_key not in logged_text


# --------------------------------------------------------------------------
# TEST 14: ENV CONFIG
# --------------------------------------------------------------------------
def test_14_env_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NCBI_API_KEY", "env_test_key")
    monkeypatch.setenv("NCBI_EMAIL", "test_user@lab.org")
    monkeypatch.setenv("NCBI_TOOL", "test-b4-tool")
    monkeypatch.setenv("BLAST_TIMEOUT_SECONDS", "45.0")
    monkeypatch.setenv("BLAST_POLL_INTERVAL_SECONDS", "3.5")

    config = NCBIConfig.from_env()
    assert config.api_key == "env_test_key"
    assert config.email == "test_user@lab.org"
    assert config.tool == "test-b4-tool"
    assert config.blast_timeout_seconds == 45.0
    assert config.blast_poll_interval_seconds == 3.5

    # Also test NCBIConfig() instantiation reads from environment
    default_config = NCBIConfig()
    assert default_config.api_key == "env_test_key"
    assert default_config.email == "test_user@lab.org"
    assert default_config.blast_timeout_seconds == 45.0
    assert default_config.blast_poll_interval_seconds == 3.5


# --------------------------------------------------------------------------
# TEST 15: AGENT TOOL INTEGRATION
# --------------------------------------------------------------------------
def test_15_agent_tool_integration() -> None:
    submit_txt = _read_fixture("blast_submit.txt")
    ready_txt = _read_fixture("blast_status_ready.txt")
    results_xml = _read_fixture("blast_results.xml")

    # 1. LiteratureEvidenceAgent call
    responses = [
        (200, {}, submit_txt),
        (200, {}, ready_txt),
        (200, {}, results_xml),
    ]
    transport, _ = _mock_transport_factory(responses)
    client = NcbiClient(transport=transport)
    evidence_agent = LiteratureEvidenceAgent(ncbi_client=client)

    ev_result = evidence_agent.check_sequence_similarity(
        sequence="ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
        candidate_id="cand_b4_01",
        sleep_fn=lambda _: None,
    )
    assert ev_result["candidate_id"] == "cand_b4_01"
    assert ev_result["provenance"] == "database-derived"
    assert ev_result["source"] == "ncbi_blast"
    assert len(ev_result["hits"]) == 2

    # 2. CandidateGenerationAgent call
    responses_cand = [
        (200, {}, submit_txt),
        (200, {}, ready_txt),
        (200, {}, results_xml),
    ]
    transport_cand, _ = _mock_transport_factory(responses_cand)
    client_cand = NcbiClient(transport=transport_cand)
    cand_agent = CandidateGenerationAgent(ncbi_client=client_cand)

    cand_result = cand_agent.check_candidate_similarity(
        candidate_id="cand_b4_02",
        sequence="ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
        sleep_fn=lambda _: None,
    )
    assert cand_result["candidate_id"] == "cand_b4_02"
    assert cand_result["provenance"] == "database-derived"
    assert cand_result["source"] == "ncbi_blast"
    assert len(cand_result["hits"]) == 2


# --------------------------------------------------------------------------
# TEST 16: CACHE
# --------------------------------------------------------------------------
def test_16_cache() -> None:
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

    seq = "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK"
    # Call 1: Remote submission
    res1 = blastp(seq, candidate_id="c1", client=client, sleep_fn=lambda _: None)
    assert len(history) == 3
    assert res1["candidate_id"] == "c1"

    # Call 2: Identical sequence + database -> Uses cache, no additional remote calls
    res2 = blastp(seq, candidate_id="c2", client=client, sleep_fn=lambda _: None)
    assert len(history) == 3  # unchanged
    assert res2["candidate_id"] == "c2"
    assert len(res2["hits"]) == 2


# --------------------------------------------------------------------------
# TEST 17: DIFFERENT PARAMETERS DO NOT COLLIDE
# --------------------------------------------------------------------------
def test_17_different_parameters_do_not_collide() -> None:
    submit_txt = _read_fixture("blast_submit.txt")
    ready_txt = _read_fixture("blast_status_ready.txt")
    results_xml = _read_fixture("blast_results.xml")

    responses = [
        # Call 1 (database=nr)
        (200, {}, submit_txt),
        (200, {}, ready_txt),
        (200, {}, results_xml),
        # Call 2 (database=swissprot)
        (200, {}, submit_txt),
        (200, {}, ready_txt),
        (200, {}, results_xml),
    ]
    transport, history = _mock_transport_factory(responses)
    client = NcbiClient(transport=transport)

    seq = "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK"
    blastp(seq, database="nr", client=client, sleep_fn=lambda _: None)
    assert len(history) == 3

    # Different database must issue a separate request rather than returning nr cache
    blastp(seq, database="swissprot", client=client, sleep_fn=lambda _: None)
    assert len(history) == 6


# --------------------------------------------------------------------------
# TEST 18: FULL REPOSITORY REGRESSION
# --------------------------------------------------------------------------
def test_18_similarity_novelty_summarizer() -> None:
    """Unit test for heuristic sequence novelty summarization."""
    # Test high similarity / low novelty (100% identity)
    results_xml = _read_fixture("blast_results.xml")
    from bacteriocin_lab.agents.evidence.ncbi.blast_parser import parse_blast_xml

    high_sim_result = parse_blast_xml(results_xml, candidate_id="cand_nisin")
    summary_low_novelty = summarize_blast_similarity(high_sim_result)
    assert summary_low_novelty["novelty"] == "low"
    assert summary_low_novelty["candidate_id"] == "cand_nisin"
    assert summary_low_novelty["max_identity_percent"] == 100.0

    # Test no hits / high novelty
    no_hits_xml = _read_fixture("blast_results_no_hits.xml")
    no_hits_result = parse_blast_xml(no_hits_xml, candidate_id="cand_novel")
    summary_high_novelty = summarize_blast_similarity(no_hits_result)
    assert summary_high_novelty["novelty"] == "high"
    assert summary_high_novelty["max_identity_percent"] == 0.0

    # Test moderate novelty (mock 75% identity)
    mod_hit_result = dict(high_sim_result)
    mod_hit_result["hits"] = [dict(high_sim_result["hits"][0])]
    mod_hit_result["hits"][0]["identity_percent"] = 75.0
    summary_mod = summarize_blast_similarity(mod_hit_result)
    assert summary_mod["novelty"] == "moderate"


def test_budget_exhaustion() -> None:
    """Test Omnigent BLAST query budget enforcement."""
    config = NCBIConfig(max_blast_queries_per_run=1)
    submit_txt = _read_fixture("blast_submit.txt")
    ready_txt = _read_fixture("blast_status_ready.txt")
    results_xml = _read_fixture("blast_results.xml")

    responses = [
        (200, {}, submit_txt),
        (200, {}, ready_txt),
        (200, {}, results_xml),
    ]
    transport, _ = _mock_transport_factory(responses)
    client = NcbiClient(config=config, transport=transport)

    # First query succeeds
    res1 = blastp("ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK", client=client, sleep_fn=lambda _: None)
    assert res1["status"] == "complete"

    # Second query exceeds budget of 1
    res2 = blastp(
        "KCNTATCATQSLIQCVK",
        client=client,
        use_cache=False,
        sleep_fn=lambda _: None,
    )
    assert res2["status"] == "budget_exhausted"
    assert "budget exceeded" in res2["error"].lower()
    assert res2["hits"] == []


def test_fetch_blast_results_direct() -> None:
    """Test fetch_blast_results utility function."""
    def transport(url: str, headers: dict, timeout: float):
        assert "CMD=Get" in url
        assert "FORMAT_TYPE=XML" in url
        assert "RID=XYZ123" in url
        return 200, {}, "<BlastOutput></BlastOutput>"

    client = NcbiClient(transport=transport)
    res = fetch_blast_results("XYZ123", client=client)
    assert res == "<BlastOutput></BlastOutput>"


def test_blast_submission_error_on_missing_rid() -> None:
    """Test BlastSubmissionError when server response lacks an RID."""
    def transport(url: str, headers: dict, timeout: float):
        return 200, {}, "<html><body>Error: invalid request</body></html>"

    client = NcbiClient(transport=transport)
    with pytest.raises(BlastSubmissionError) as exc_info:
        submit_blastp("ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK", client=client)
    assert issubclass(BlastSubmissionError, BlastError)
    assert "Failed to obtain RID" in str(exc_info.value)


def test_blast_parse_error_on_corrupt_xml() -> None:
    """Test BlastParseError when BLAST XML is invalid or unparseable."""
    from bacteriocin_lab.agents.evidence.ncbi.blast_parser import parse_blast_xml

    with pytest.raises(BlastParseError) as exc_info:
        parse_blast_xml("<corrupt>no closing tag", candidate_id="c1")
    assert issubclass(BlastParseError, BlastError)
    assert "Failed to parse BLAST XML" in str(exc_info.value)


# --------------------------------------------------------------------------
# OPTIONAL LIVE BLAST SMOKE TEST
# --------------------------------------------------------------------------
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_NCBI_BLAST_TESTS") != "1",
    reason="Live NCBI BLAST tests disabled by default. Enable with RUN_LIVE_NCBI_BLAST_TESTS=1",
)
def test_live_ncbi_blast_smoke() -> None:
    """Opt-in live smoke test against the live NCBI BLAST URL API.

    Uses a short bacteriocin sequence (Nisin A: 34 residues).
    Asserts valid structured response without pinning exact hit counts.
    """
    client = NcbiClient()
    seq = "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK"
    db = os.getenv("LIVE_BLAST_DATABASE", "swissprot")
    result = blastp(
        sequence=seq,
        database=db,
        candidate_id="live_test_nisin",
        timeout_seconds=180.0,
        poll_interval=5.0,
        client=client,
    )
    assert result["status"] == "complete"
    assert result["candidate_id"] == "live_test_nisin"
    assert result["provenance"] == "database-derived"
    assert result["source"] == "ncbi_blast"
    assert isinstance(result["hits"], list)
    assert result["query_length"] == 34
    if result["hits"]:
        top = result["hits"][0]
        assert "identity_percent" in top
        assert "accession" in top
