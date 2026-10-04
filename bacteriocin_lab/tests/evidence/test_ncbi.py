from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import URLError

import pytest

from bacteriocin_lab.agents.evidence import (
    LiteratureEvidenceAgent,
    LiteratureResponse,
    NcbiClient,
    NCBIConfig,
    NCBIParseError,
    NCBIRequestError,
    fetch_fasta,
    fetch_pmc_article,
    fetch_pubmed_records,
    search_protein,
    search_pubmed,
)
from bacteriocin_lab.agents.evidence.models import SourceDocument, SourceReference

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
            raise RuntimeError(f"No more mocked responses available for call to {url}")
        return resp_queue.pop(0)

    return transport, history


# --------------------------------------------------------------------------
# TEST 1: PUBMED SEARCH PARSING
# --------------------------------------------------------------------------
def test_1_pubmed_search_parsing() -> None:
    esearch_json = _read_fixture("pubmed_esearch.json")

    def transport(url: str, headers: dict, timeout: float):
        assert "esearch.fcgi" in url
        assert "db=pubmed" in url
        assert "retmode=json" in url
        return 200, {}, esearch_json

    client = NcbiClient(transport=transport)
    result = search_pubmed("bacteriocin cell density", limit=10, client=client)

    assert result["query"] == "bacteriocin cell density"
    assert result["pmids"] == ["31234567", "32345678"]
    assert result["count"] == 2
    assert result["source"] == "ncbi_pubmed"


# --------------------------------------------------------------------------
# TEST 2: PUBMED RECORD PARSING
# --------------------------------------------------------------------------
def test_2_pubmed_record_parsing() -> None:
    efetch_xml = _read_fixture("pubmed_efetch.xml")

    def transport(url: str, headers: dict, timeout: float):
        assert "efetch.fcgi" in url
        assert "db=pubmed" in url
        assert "retmode=xml" in url
        return 200, {}, efetch_xml

    client = NcbiClient(transport=transport)
    records = fetch_pubmed_records(["31234567", "32345678"], client=client)

    assert len(records) == 2

    # Article 1: Complete record
    r1 = records[0]
    assert r1["pmid"] == "31234567"
    assert "Antimicrobial activity of nisin against Listeria monocytogenes" in r1["title"]
    assert "10^6 CFU/mL Listeria monocytogenes in BHI broth" in r1["abstract"]
    assert r1["journal"] == "Journal of Applied Microbiology"
    assert r1["year"] == 2020
    assert "Smith John" in r1["authors"] or "Smith J" in r1["authors"]
    assert r1["doi"] == "10.1111/jam.12345"
    assert r1["pmcid"] == "PMC7654321"
    assert r1["source_url"] == "https://pubmed.ncbi.nlm.nih.gov/31234567/"
    assert r1["provenance"] == "literature-derived"

    # Article 2: Missing optional fields (DOI, PMCID) remain None rather than fabricated
    r2 = records[1]
    assert r2["pmid"] == "32345678"
    assert r2["doi"] is None
    assert r2["pmcid"] is None
    assert r2["year"] == 2022
    assert r2["journal"] == "Frontiers in Microbiology"


# --------------------------------------------------------------------------
# TEST 3: PMC ARTICLE PARSING
# --------------------------------------------------------------------------
def test_3_pmc_article_parsing() -> None:
    pmc_xml = _read_fixture("pmc_article.xml")

    def transport(url: str, headers: dict, timeout: float):
        assert "efetch.fcgi" in url
        assert "db=pmc" in url
        return 200, {}, pmc_xml

    client = NcbiClient(transport=transport)
    article = fetch_pmc_article("PMC7654321", client=client)

    assert article["pmcid"] == "PMC7654321"
    assert article["pmid"] == "31234567"
    assert article["doi"] == "10.1111/jam.12345"
    assert "Antimicrobial activity of nisin against Listeria monocytogenes" in article["title"]
    assert len(article["sections"]) >= 2
    section_titles = [s["title"] for s in article["sections"]]
    assert "Introduction" in section_titles
    assert "Results" in section_titles
    assert article["provenance"] == "literature-derived"
    assert "MIC of nisin was 2.5 mg/L" in article["full_text"]
    assert article["raw_xml"] == pmc_xml


# --------------------------------------------------------------------------
# TEST 4: PROTEIN SEARCH
# --------------------------------------------------------------------------
def test_4_protein_search() -> None:
    esearch_json = _read_fixture("protein_esearch.json")
    esummary_json = _read_fixture("protein_esummary.json")

    responses = [(200, {}, esearch_json), (200, {}, esummary_json)]
    transport, _history = _mock_transport_factory(responses)
    client = NcbiClient(transport=transport)

    results = search_protein("nisin", limit=10, client=client)

    assert len(results) == 2
    assert results[0]["id"] == "1234567"
    assert results[0]["accession"] == "NP_046340.1"
    assert "nisin A precursor" in results[0]["title"]
    assert "Lactococcus lactis" in (results[0]["organism"] or "")
    assert results[0]["source"] == "ncbi_protein"

    assert results[1]["id"] == "7654321"
    assert results[1]["accession"] == "AAA25206.1"
    assert "pediocin PA-1" in results[1]["title"]
    assert "Pediococcus acidilactici" in (results[1]["organism"] or "")


# --------------------------------------------------------------------------
# TEST 5: FASTA RETRIEVAL
# --------------------------------------------------------------------------
def test_5_fasta_retrieval() -> None:
    fasta_text = _read_fixture("protein.fasta")

    def transport(url: str, headers: dict, timeout: float):
        assert "efetch.fcgi" in url
        assert "db=protein" in url
        assert "rettype=fasta" in url
        return 200, {}, fasta_text

    client = NcbiClient(transport=transport)
    result = fetch_fasta(db="protein", ids=["NP_046340.1", "AAA25206.1"], client=client)

    assert result["db"] == "protein"
    assert len(result["records"]) == 2
    assert result["records"][0]["accession"] == "NP_046340.1"
    assert result["records"][0]["sequence"].startswith("MSTKDFN")
    assert result["records"][0]["source_database"] == "protein"
    assert result["records"][1]["accession"] == "AAA25206.1"
    assert result["records"][1]["sequence"].startswith("MKKIEKL")
    assert result["raw_fasta"] == fasta_text


# --------------------------------------------------------------------------
# TEST 6: RATE LIMIT / RETRY
# --------------------------------------------------------------------------
def test_6_rate_limit_and_retry() -> None:
    # Scenario A: First 429, then 200 -> Bounded retry succeeds
    responses_a = [
        (429, {"retry-after": "0"}, "Rate limited"),
        (200, {}, json.dumps({"esearchresult": {"idlist": ["999"], "count": "1"}})),
    ]
    transport_a, history_a = _mock_transport_factory(responses_a)
    client_a = NcbiClient(transport=transport_a, backoff_factor=0.0)

    res = client_a.esearch(db="pubmed", term="test")
    assert res["esearchresult"]["idlist"] == ["999"]
    assert len(history_a) == 2

    # Scenario B: Repeated 503 beyond retry limit -> Structured error
    config = NCBIConfig(max_retries=2)
    responses_b = [
        (503, {}, "Service unavailable"),
        (503, {}, "Service unavailable"),
        (503, {}, "Service unavailable"),
    ]
    transport_b, history_b = _mock_transport_factory(responses_b)
    client_b = NcbiClient(config=config, transport=transport_b, backoff_factor=0.0)

    with pytest.raises(NCBIRequestError) as exc_info:
        client_b.esearch(db="pubmed", term="test")

    assert exc_info.value.status_code == 503
    assert len(history_b) == 3


# --------------------------------------------------------------------------
# TEST 7: TIMEOUT & NETWORK FAILURE
# --------------------------------------------------------------------------
def test_7_timeout_and_network_failure() -> None:
    attempts: list[int] = []

    def failing_transport(url: str, headers: dict, timeout: float):
        attempts.append(1)
        raise URLError("Connection timed out")

    config = NCBIConfig(max_retries=2)
    client = NcbiClient(config=config, transport=failing_transport, backoff_factor=0.0)

    with pytest.raises(NCBIRequestError) as exc_info:
        client.esearch(db="pubmed", term="test")

    assert "Connection timed out" in str(exc_info.value)
    assert len(attempts) == 3  # Initial + 2 retries


# --------------------------------------------------------------------------
# TEST 8: MALFORMED XML
# --------------------------------------------------------------------------
def test_8_malformed_xml() -> None:
    malformed_xml = "<PubmedArticleSet><PubmedArticle><UnclosedTag></PubmedArticleSet>"

    def transport(url: str, headers: dict, timeout: float):
        return 200, {}, malformed_xml

    client = NcbiClient(transport=transport)
    with pytest.raises(NCBIParseError) as exc_info:
        fetch_pubmed_records(["12345"], client=client)

    assert "Malformed PubMed XML" in str(exc_info.value)


# --------------------------------------------------------------------------
# TEST 9: EMPTY SEARCH
# --------------------------------------------------------------------------
def test_9_empty_search() -> None:
    empty_esearch = json.dumps({"esearchresult": {"idlist": [], "count": "0"}})

    def transport(url: str, headers: dict, timeout: float):
        return 200, {}, empty_esearch

    client = NcbiClient(transport=transport)
    result = search_pubmed("nonexistent_bacteriocin_12345", client=client)

    assert result["count"] == 0
    assert result["pmids"] == []

    # Verify LiteratureEvidenceAgent handles empty knowledge gap cleanly
    agent = LiteratureEvidenceAgent(mode="live_ncbi", ncbi_client=client)
    response = agent.run(
        {"question": "nonexistent_bacteriocin_12345", "retrieval": {"enabled": True}}
    )

    assert response.decision["status"] == "insufficient-evidence"
    assert response.evidence == []
    assert len(response.knowledge_gaps) > 0


# --------------------------------------------------------------------------
# TEST 10: LOCAL MODE UNAFFECTED
# --------------------------------------------------------------------------
def test_10_local_mode_unaffected() -> None:
    local_doc = SourceDocument(
        source=SourceReference(
            source_id="local-doc-1",
            title="Local Curated Bacteriocin Study",
            doi_or_url="https://doi.org/10.1000/local",
            year=2024,
        ),
        text=(
            "In a broth microdilution assay, 10^6 CFU/mL Listeria monocytogenes in BHI broth "
            "was exposed to nisin at 2.5 mg/L. The MIC of nisin was 2.5 mg/L."
        ),
        locator="Section 3, Paragraph 1",
    )

    agent = LiteratureEvidenceAgent(mode="local")
    response = agent.run(
        {
            "question": "What is the MIC of nisin against Listeria monocytogenes?",
            "bacteriocin": "nisin",
            "target_organism": "Listeria monocytogenes",
            "source_documents": [local_doc.model_dump()],
        }
    )

    assert response.decision["status"] == "evidence-collected"
    assert len(response.evidence) == 1
    ev = response.evidence[0]
    assert ev.evidence_type == "literature-derived"
    assert ev.measurement.value == 2.5
    assert ev.provenance.locator == "Section 3, Paragraph 1"


# --------------------------------------------------------------------------
# TEST 11: HYBRID DEDUPLICATION
# --------------------------------------------------------------------------
def test_11_hybrid_deduplication() -> None:
    # Local curated document with partial metadata
    local_doc = SourceDocument(
        source=SourceReference(
            source_id="curated_nisin_jam",
            title=(
                "Antimicrobial activity of nisin against Listeria monocytogenes "
                "in broth microdilution assay"
            ),
            doi_or_url="https://doi.org/10.1111/jam.12345",
            year=2020,
            authors=["Smith John"],
        ),
        text=(
            "In a broth microdilution assay, 10^6 CFU/mL Listeria monocytogenes in BHI broth "
            "was exposed to nisin at 2.5 mg/L. The MIC of nisin was 2.5 mg/L."
        ),
        locator="curated excerpt",
    )

    esearch_json = _read_fixture("pubmed_esearch.json")
    efetch_xml = _read_fixture("pubmed_efetch.xml")

    # PubMed article 1 has the same DOI: 10.1111/jam.12345
    responses = [(200, {}, esearch_json), (200, {}, efetch_xml)]
    transport, _history = _mock_transport_factory(responses)
    client = NcbiClient(transport=transport, backoff_factor=0.0)

    agent = LiteratureEvidenceAgent(mode="hybrid", ncbi_client=client)
    response = agent.run(
        {
            "question": "nisin Listeria cell density",
            "bacteriocin": "nisin",
            "target_organism": "Listeria monocytogenes",
            "source_documents": [local_doc.model_dump()],
            "retrieval": {"enabled": True, "sources": ["ncbi"], "max_results": 2},
        }
    )

    # Article 1 matches local doc (deduplicated into 1 logical record)
    # Article 2 is separate (from efetch_xml)
    # Overall documents considered: 2 (1 merged, 1 distinct from NCBI)
    assert response.decision["documents_considered"] == 2
    # Verify that the merged document preserved both local source id and NCBI id
    source_ids = response.artifacts["source_ids"]
    assert any("curated_nisin_jam" in sid and "pmid:31234567" in sid for sid in source_ids)


# --------------------------------------------------------------------------
# TEST 12: NO API KEY CONFIGURATION
# --------------------------------------------------------------------------
def test_12_no_api_key_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    client = NcbiClient(config=NCBIConfig(api_key=None))

    assert client.config.api_key is None
    assert client.rate_limiter.min_interval >= 0.3  # <= 3 req/sec conservative default


# --------------------------------------------------------------------------
# TEST 13: OPTIONAL API KEY CONFIGURATION
# --------------------------------------------------------------------------
def test_13_optional_api_key_configuration() -> None:
    captured_urls: list[str] = []

    def transport(url: str, headers: dict, timeout: float):
        captured_urls.append(url)
        return 200, {}, json.dumps({"esearchresult": {"idlist": [], "count": "0"}})

    config = NCBIConfig(api_key="fake_secret_key_12345")
    client = NcbiClient(config=config, transport=transport)
    client.esearch(db="pubmed", term="test")

    assert len(captured_urls) == 1
    assert "api_key=fake_secret_key_12345" in captured_urls[0]


# --------------------------------------------------------------------------
# TEST 14: TOOL AND EMAIL CONFIGURATION
# --------------------------------------------------------------------------
def test_14_tool_and_email_configuration() -> None:
    captured_urls: list[str] = []

    def transport(url: str, headers: dict, timeout: float):
        captured_urls.append(url)
        return 200, {}, json.dumps({"esearchresult": {"idlist": [], "count": "0"}})

    config = NCBIConfig(tool="CustomBacteriocinBot", email="lab@example.com")
    client = NcbiClient(config=config, transport=transport)
    client.esearch(db="pubmed", term="test")

    assert len(captured_urls) == 1
    assert "tool=CustomBacteriocinBot" in captured_urls[0]
    assert "email=lab%40example.com" in captured_urls[0]


# --------------------------------------------------------------------------
# TEST 15: FULL EVIDENCE AGENT INTEGRATION
# --------------------------------------------------------------------------
def test_15_full_evidence_agent_integration() -> None:
    esearch_json = _read_fixture("pubmed_esearch.json")
    efetch_xml = _read_fixture("pubmed_efetch.xml")

    responses = [(200, {}, esearch_json), (200, {}, efetch_xml)]
    transport, _ = _mock_transport_factory(responses)
    client = NcbiClient(transport=transport, backoff_factor=0.0)

    agent = LiteratureEvidenceAgent(mode="live_ncbi", ncbi_client=client)
    raw_response = agent.run(
        {
            "question": "nisin Listeria cell density",
            "bacteriocin": "nisin",
            "target_organism": "Listeria monocytogenes",
            "retrieval": {"enabled": True, "sources": ["ncbi"], "max_results": 2},
        }
    )

    # Downstream validation passes
    assert isinstance(raw_response, LiteratureResponse)
    dumped = raw_response.model_dump(mode="json")
    validated = LiteratureResponse.model_validate(dumped)

    assert validated.agent == "literature-evidence-agent"
    assert validated.decision["status"] == "evidence-collected"
    assert len(validated.evidence) >= 1

    ev = validated.evidence[0]
    assert ev.evidence_type == "literature-derived"
    assert ev.bacteriocin.name == "nisin"
    assert ev.target.organism == "Listeria monocytogenes"
    assert ev.measurement.data_role in ("measured", "author-interpretation")
    assert ev.provenance.extraction_method == "deterministic-rule"


# --------------------------------------------------------------------------
# OPTIONAL LIVE SMOKE TEST (Opt-in only)
# --------------------------------------------------------------------------
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_NCBI_TESTS") != "1",
    reason="Live NCBI network tests skipped unless RUN_LIVE_NCBI_TESTS=1",
)
def test_optional_live_ncbi_smoke() -> None:
    """Live smoke test verifying connectivity and real parsing against NCBI E-utilities."""
    client = NcbiClient()
    search_res = search_pubmed(
        "nisin[Title/Abstract] AND Listeria[Title/Abstract]", limit=3, client=client
    )

    assert search_res["source"] == "ncbi_pubmed"
    assert search_res["count"] > 0
    assert len(search_res["pmids"]) > 0

    records = fetch_pubmed_records(search_res["pmids"][:2], client=client)
    assert len(records) > 0
    for rec in records:
        assert rec["pmid"] is not None
        assert rec["title"] != ""
        assert rec["provenance"] == "literature-derived"
