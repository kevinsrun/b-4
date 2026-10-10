"""Unit and integration tests for projects, biological samples, sequence annotations, and CRISPR studies."""

from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from bacteriocin_lab.api.app import create_app
from bacteriocin_lab.projects.service import ProjectService


@pytest.fixture
def tmp_project_service(tmp_path: Path):
    db_path = tmp_path / "test_projects.sqlite3"
    return ProjectService(db_path=db_path)


def test_seed_projects_and_samples(tmp_project_service: ProjectService):
    projects = tmp_project_service.list_projects()
    assert len(projects) >= 3

    nisin_proj = next(p for p in projects if "nisin" in p.project_id.lower())
    assert nisin_proj.target_organism == "Lactococcus lactis"
    assert len(nisin_proj.sample_ids) > 0
    assert len(nisin_proj.sequencing_run_ids) > 0
    assert len(nisin_proj.dataset_ids) > 0

    samples = tmp_project_service.list_samples(nisin_proj.project_id)
    assert len(samples) > 0
    assert samples[0].gram_stain == "positive"


def test_annotated_sequence_and_crispr_studies(tmp_project_service: ProjectService):
    sequences = tmp_project_service.list_sequences()
    assert len(sequences) >= 3

    nisin_seq = next(s for s in sequences if "nisin" in s.sequence_id.lower())
    assert nisin_seq.molecule_type == "dna"
    assert len(nisin_seq.annotations) >= 3

    # Check annotations
    ann_types = {a.feature_type for a in nisin_seq.annotations}
    assert "cds" in ann_types
    assert "core_peptide" in ann_types
    assert "immunity_protein" in ann_types

    # Check CRISPR studies
    studies = tmp_project_service.list_crispr_studies()
    assert len(studies) >= 2
    nisi_study = next(s for s in studies if "nisi" in s.study_id.lower())
    assert nisi_study.target_gene == "nisI"
    assert len(nisi_study.target_regions) > 0
    assert len(nisi_study.variants) > 0
    assert nisi_study.review_status == "approved"


def test_sequence_comparison_logic(tmp_project_service: ProjectService):
    seqs = tmp_project_service.list_sequences()
    ref_seq = seqs[0]

    # Identical sequence -> 100% identity
    comp_identical = tmp_project_service.compare_sequences(ref_seq.sequence_id, ref_seq.sequence)
    assert comp_identical.identity_percentage == 100.0
    assert comp_identical.mismatches_count == 0
    assert len(comp_identical.variants) == 0

    # Introduce a single SNV
    mutated = list(ref_seq.sequence)
    mutated[10] = "G" if mutated[10] != "G" else "C"
    mutated_str = "".join(mutated)

    comp_mut = tmp_project_service.compare_sequences(ref_seq.sequence_id, mutated_str)
    assert comp_mut.identity_percentage < 100.0
    assert comp_mut.mismatches_count == 1
    assert len(comp_mut.variants) == 1
    assert comp_mut.variants[0].position == 11
    assert comp_mut.variants[0].variant_type == "snv"


def test_fastapi_projects_and_crispr_endpoints():
    app = create_app()
    client = TestClient(app)

    # 1. List Projects
    r_proj = client.get("/api/v1/projects")
    assert r_proj.status_code == 200
    projects = r_proj.json()
    assert len(projects) >= 3

    first_proj = projects[0]
    p_id = first_proj["project_id"]

    # 2. Get Project details
    r_detail = client.get(f"/api/v1/projects/{p_id}")
    assert r_detail.status_code == 200
    assert r_detail.json()["project_id"] == p_id

    # 3. Project Samples
    r_samples = client.get(f"/api/v1/projects/{p_id}/samples")
    assert r_samples.status_code == 200
    samples = r_samples.json()
    assert len(samples) > 0

    # 4. Project Sequences
    r_seqs = client.get(f"/api/v1/projects/{p_id}/sequences")
    assert r_seqs.status_code == 200
    seqs = r_seqs.json()
    assert len(seqs) > 0

    first_seq = seqs[0]
    seq_id = first_seq["sequence_id"]

    # 5. Sequence Comparison
    r_comp = client.post(
        f"/api/v1/sequences/{seq_id}/compare",
        json={"reference_sequence_id": seq_id, "query_sequence": first_seq["sequence"]},
    )
    assert r_comp.status_code == 200
    comp_res = r_comp.json()
    assert comp_res["identity_percentage"] == 100.0

    # 6. CRISPR studies
    r_crispr = client.get("/api/v1/crispr/studies")
    assert r_crispr.status_code == 200
    studies = r_crispr.json()
    assert len(studies) > 0

    c_id = studies[0]["study_id"]
    r_study = client.get(f"/api/v1/crispr/studies/{c_id}")
    assert r_study.status_code == 200
    assert r_study.json()["study_id"] == c_id
