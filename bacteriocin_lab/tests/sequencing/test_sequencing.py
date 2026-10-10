"""Unit and integration tests for universal sequencing platform integrations."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bacteriocin_lab.api.app import create_app
from bacteriocin_lab.sequencing.handoff import evaluate_analysis_handoff, translate_dna
from bacteriocin_lab.sequencing.illumina_connector import IlluminaBaseSpaceConnector
from bacteriocin_lab.sequencing.local_connector import LocalFolderConnector
from bacteriocin_lab.sequencing.nanopore_connector import OxfordNanoporeConnector
from bacteriocin_lab.sequencing.pacbio_connector import PacBioConnector
from bacteriocin_lab.sequencing.schemas import ConnectionCreateRequest, ImportRequest
from bacteriocin_lab.sequencing.service import SequencingService
from bacteriocin_lab.sequencing.store import SequencingStore


@pytest.fixture
def tmp_env(tmp_path: Path):
    """Provides isolated storage and test directories for sequencing tests."""
    db_path = tmp_path / "test_sequencing.sqlite3"
    imports_dir = tmp_path / "imports"
    allowlist_dir = tmp_path / "incoming"
    imports_dir.mkdir(parents=True, exist_ok=True)
    allowlist_dir.mkdir(parents=True, exist_ok=True)

    service = SequencingService(db_path=db_path, imports_dir=imports_dir)
    return {
        "tmp_path": tmp_path,
        "db_path": db_path,
        "imports_dir": imports_dir,
        "allowlist_dir": allowlist_dir,
        "service": service,
    }


# ======================================================================
# 1. Platform Connectors & Metadata
# ======================================================================


def test_connector_metadata():
    local = LocalFolderConnector()
    assert local.connector_id == "local_folder"
    assert local.vendor == "local"
    assert ".fastq.gz" in local.supported_file_types()

    illumina = IlluminaBaseSpaceConnector()
    assert illumina.connector_id == "illumina_basespace"
    assert illumina.vendor == "illumina"
    assert "oauth_token_auth" in illumina.capabilities()

    ont = OxfordNanoporeConnector()
    assert ont.connector_id == "oxford_nanopore"
    assert ont.vendor == "nanopore"
    assert ".pod5" in ont.supported_file_types()

    pb = PacBioConnector()
    assert pb.connector_id == "pacbio_smrtlink"
    assert pb.vendor == "pacbio"
    assert "hifi_ccs_detection" in pb.capabilities()


# ======================================================================
# 2. Local Connector Security & File Ingestion
# ======================================================================


def test_local_connector_path_traversal_prevention(tmp_path: Path):
    safe_root = tmp_path / "safe"
    safe_root.mkdir()
    connector = LocalFolderConnector(allowlisted_roots=[safe_root])

    # Path outside allowlist must raise PermissionError or fail validation
    outside_path = tmp_path / "outside"
    outside_path.mkdir()
    val = connector.validate_connection({"directory_path": str(outside_path)})
    assert val["valid"] is False
    assert "Access denied" in val["message"]


def test_local_connector_stability_and_completion_detection(tmp_path: Path):
    safe_root = tmp_path / "safe"
    safe_root.mkdir()
    connector = LocalFolderConnector(allowlisted_roots=[safe_root])

    run_dir = safe_root / "20261009_RunA"
    run_dir.mkdir()
    fq_file = run_dir / "sample1_R1.fastq.gz"
    fq_file.write_bytes(b"@SEQ1\nACGT\n+\nIIII\n")

    # When require_stability is True, file must be older than threshold
    res = connector.discover_runs({"directory_path": str(run_dir), "stability_threshold_seconds": 10.0})
    assert len(res) == 1
    # Run status is running because neither completion marker nor file stability threshold met
    assert res[0]["status"] == "running"

    # Add completion marker
    (run_dir / ".complete").write_text("done")
    res_completed = connector.discover_runs({"directory_path": str(run_dir)})
    assert res_completed[0]["status"] == "completed"

    datasets = connector.list_datasets({"directory_path": str(run_dir)}, res[0]["external_run_id"])
    assert len(datasets) == 1
    assert datasets[0]["file_name"] == "sample1_R1.fastq.gz"
    assert datasets[0]["read_type"] == "paired_end_R1"


# ======================================================================
# 3. Illumina BaseSpace Connector
# ======================================================================


def test_illumina_basespace_fixture_contract():
    connector = IlluminaBaseSpaceConnector()
    config = {"use_fixtures": True}

    val = connector.validate_connection(config)
    assert val["valid"] is True

    runs = connector.discover_runs(config)
    assert len(runs) >= 2
    miseq_run = next(r for r in runs if "miseq" in r["external_run_id"].lower())
    assert miseq_run["instrument_model"] == "Illumina MiSeq"

    datasets = connector.list_datasets(config, miseq_run["external_run_id"])
    assert len(datasets) >= 2
    r1 = next(d for d in datasets if d["read_type"] == "paired_end_R1")
    r2 = next(d for d in datasets if d["read_type"] == "paired_end_R2")
    assert r1["file_name"].endswith("R1_001.fastq.gz")
    assert r2["file_name"].endswith("R2_001.fastq.gz")


# ======================================================================
# 4. Oxford Nanopore MinKNOW Connector
# ======================================================================


def test_nanopore_minknow_signal_vs_basecalls():
    connector = OxfordNanoporeConnector()
    config = {"use_fixtures": True}

    val = connector.validate_connection(config)
    assert val["valid"] is True

    runs = connector.discover_runs(config)
    assert len(runs) >= 2

    promethion_run = next(r for r in runs if "promethion" in r["external_run_id"].lower())
    datasets = connector.list_datasets(config, promethion_run["external_run_id"])

    # Must contain both raw signal (POD5) and basecalled reads (FASTQ)
    pod5_ds = next(d for d in datasets if d["file_format"] == "pod5")
    fastq_ds = next(d for d in datasets if d["file_format"] == "fastq_gz")

    assert pod5_ds["read_type"] == "raw_signal"
    assert pod5_ds["analysis_eligibility"]["requires_basecalling"] is True

    assert fastq_ds["read_type"] == "long_read"
    assert fastq_ds["analysis_eligibility"]["requires_basecalling"] is False


# ======================================================================
# 5. PacBio SMRT Link Connector
# ======================================================================


def test_pacbio_smrtlink_hifi_ccs_detection():
    connector = PacBioConnector()
    config = {"use_fixtures": True}

    val = connector.validate_connection(config)
    assert val["valid"] is True

    runs = connector.discover_runs(config)
    assert len(runs) >= 2

    revio_run = next(r for r in runs if "revio" in r["external_run_id"].lower())
    datasets = connector.list_datasets(config, revio_run["external_run_id"])

    hifi_ds = next(d for d in datasets if d["read_type"] == "hifi_ccs")
    subreads_ds = next(d for d in datasets if d["read_type"] == "raw_signal")

    assert "hifi_reads" in hifi_ds["file_name"]
    assert hifi_ds["analysis_eligibility"]["is_hifi"] is True
    assert "subreads" in subreads_ds["file_name"]
    assert subreads_ds["analysis_eligibility"]["is_hifi"] is False


# ======================================================================
# 6. Scientific Analysis Handoff & Translation
# ======================================================================


def test_scientific_handoff_rules_for_raw_fastq():
    raw_fastq_dataset = {
        "dataset_id": "test_ds_01",
        "file_name": "reads_R1.fastq.gz",
        "file_format": "fastq_gz",
        "read_type": "paired_end_R1",
    }
    handoff = evaluate_analysis_handoff(raw_fastq_dataset)

    # Scientific invariant: Raw reads must NEVER be eligible for direct AMP classification
    assert handoff.direct_amp_eligible is False
    assert handoff.data_type == "raw_short_reads"

    stage_ids = [s.stage_id for s in handoff.pipeline_stages]
    assert stage_ids == ["qc", "assembly", "gene_calling", "translation", "amp_screening"]
    assert "CRITICAL: Raw nucleotide reads cannot be classified by ampir or amPEPpy" in handoff.prerequisite_notice


def test_scientific_handoff_rules_for_peptides():
    peptide_dataset = {
        "dataset_id": "test_ds_pep_01",
        "file_name": "candidate_bacteriocins.faa",
        "file_format": "fasta",
        "read_type": "unknown",
    }
    handoff = evaluate_analysis_handoff(peptide_dataset)
    assert handoff.direct_amp_eligible is True
    assert handoff.data_type == "translated_proteins"
    assert len(handoff.extracted_peptides_preview) > 0


def test_dna_translation_utility():
    # Bacteriocin core peptide coding sequence
    dna = "ATGAAGAAAGCAGCCATATTTTTACTGCTATTATCAGTAACTGTCTTTGCTTAA"
    peptides = translate_dna(dna, min_peptide_len=5, max_peptide_len=50)
    assert len(peptides) > 0
    # First peptide translated should start with M
    assert any(p["sequence"].startswith("M") for p in peptides)


# ======================================================================
# 7. End-to-End FastAPI Integration Tests
# ======================================================================


def test_fastapi_sequencing_endpoints():
    app = create_app()
    client = TestClient(app)

    # 1. List Connectors
    r_connectors = client.get("/api/v1/sequencing/connectors")
    assert r_connectors.status_code == 200
    connectors = r_connectors.json()
    assert len(connectors) == 4
    connector_ids = {c["connector_id"] for c in connectors}
    assert "local_folder" in connector_ids
    assert "illumina_basespace" in connector_ids
    assert "oxford_nanopore" in connector_ids
    assert "pacbio_smrtlink" in connector_ids

    # 2. List Connections (pre-seeded)
    r_conns = client.get("/api/v1/sequencing/connections")
    assert r_conns.status_code == 200
    conns = r_conns.json()
    assert len(conns) >= 3

    # 3. List Runs
    r_runs = client.get("/api/v1/sequencing/runs")
    assert r_runs.status_code == 200
    runs = r_runs.json()
    assert len(runs) > 0

    run = next(r for r in runs if r.get("dataset_count", 0) > 0)
    run_id = run["run_id"]

    # 4. Get Run Datasets
    r_datasets = client.get(f"/api/v1/sequencing/runs/{run_id}/datasets")
    assert r_datasets.status_code == 200
    datasets = r_datasets.json()
    assert len(datasets) > 0

    first_ds = datasets[0]
    ds_id = first_ds["dataset_id"]

    # 5. Scientific Handoff Analysis
    r_handoff = client.get(f"/api/v1/sequencing/datasets/{ds_id}/handoff")
    assert r_handoff.status_code == 200
    handoff = r_handoff.json()
    assert "direct_amp_eligible" in handoff
    assert "pipeline_stages" in handoff

    # 6. Import Dataset
    r_import = client.post(
        f"/api/v1/sequencing/datasets/{ds_id}/import",
        json={"destination_subfolder": "test_batch", "verify_checksum": True},
    )
    assert r_import.status_code == 200
    import_job = r_import.json()
    assert import_job["status"] == "completed"
    assert import_job["dataset_id"] == ds_id

    # 7. Check Import Status
    r_job = client.get(f"/api/v1/sequencing/imports/{import_job['import_id']}")
    assert r_job.status_code == 200
    assert r_job.json()["status"] == "completed"
