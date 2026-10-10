from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from bacteriocin_lab.amp.adapters import (
    AdapterError,
    DisabledAdapter,
    ModelAdapter,
    SubprocessAdapter,
    file_hash,
)
from bacteriocin_lab.amp.dramp import ingest
from bacteriocin_lab.amp.schemas import PredictRequest, SequenceInput
from bacteriocin_lab.amp.service import InferenceService
from bacteriocin_lab.amp.store import CapacityExceeded, JobConflict, Store
from bacteriocin_lab.api.amp import MAX_BODY_BYTES
from bacteriocin_lab.api.app import create_app

SEQUENCE = "MALTVRIQAACLLLLLLASLTSYSLLLSQTTQLADLQTQDTAGATAGLMPGLQRRRRRDTHFPICIFCCGCCYPSKCGICCKT"


def test_existing_api_cli_help():
    result = subprocess.run(
        [sys.executable, "-m", "bacteriocin_lab.api", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--host" in result.stdout


class FixtureAdapter(ModelAdapter):
    """Engineering fixture only: never reported as READY or scientific evidence."""

    def __init__(self, model_id="ampir", score=0.8, failure=None, delay=0):
        super().__init__(model_id)
        self.score, self.failure, self.delay = score, failure, delay
        self.calls = 0
        self.revision = "fixture-1"
        self.running = 0
        self.maximum = 0
        self.lock = threading.Lock()

    def identity(self):
        return {"fingerprint": self.revision, "fixture": True}

    def health(self):
        return {"model_id": self.model_id, "status": "PARTIAL", "fixture": True}

    def run(self, sequences, request, identity):
        with self.lock:
            self.calls += 1
            self.running += 1
            self.maximum = max(self.running, self.maximum)
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.failure:
                raise self.failure
            return [
                self.record(
                    s,
                    request,
                    status="succeeded",
                    raw_score=self.score,
                    binary_prediction=self.score > 0.5,
                    threshold=0.5,
                    reproducibility=identity.copy(),
                )
                for s in sequences
            ]
        finally:
            with self.lock:
                self.running -= 1


@pytest.fixture
def service(tmp_path):
    ampir, ampep = FixtureAdapter(), FixtureAdapter("ampeppy", score=0.2)
    svc = InferenceService(
        database_path=tmp_path / "amp.sqlite3",
        adapters={"ampir": ampir, "ampeppy": ampep, "apin": DisabledAdapter("apin")},
    )
    yield svc
    svc.close()


def request(**kwargs):
    return PredictRequest(sequences=[SequenceInput(sequence_id="hep", sequence=SEQUENCE)], **kwargs)


@pytest.mark.parametrize("sequence", ["", "acdef", "AXCDE", "ACD-E", "ACDE*", "AC DE", "\uff21CDE"])
def test_canonical_validation(sequence):
    with pytest.raises(ValidationError):
        SequenceInput(sequence_id="test", sequence=sequence)


def test_batch_limits_and_ids():
    seq = SequenceInput(sequence_id="same", sequence=SEQUENCE)
    with pytest.raises(ValidationError):
        PredictRequest(sequences=[seq, seq])
    with pytest.raises(ValidationError):
        request(models=["ampir", "ampir"])
    with pytest.raises(ValidationError):
        PredictRequest(
            sequences=[SequenceInput(sequence_id=str(i), sequence="A" * 8000) for i in range(17)]
        )
    with pytest.raises(ValidationError):
        SequenceInput(sequence_id="header\ninjection", sequence=SEQUENCE)


def test_independent_scores_agreement_and_cache(service):
    report = service.predict(request())
    row = report.sequences[0]
    assert [p.raw_score for p in row.predictions] == [0.8, 0.2]
    assert row.agreement["disagreement"]
    assert row.agreement["classified_models"] == 2
    assert "probability" not in row.agreement
    assert "not ingested" in row.warnings[0]
    second = service.predict(request())
    assert second.execution["cache_hits"] == 2
    assert all(p.cached for p in second.sequences[0].predictions)
    assert service.adapters["ampir"].calls == 1
    assert second.sequences[0].predictions[0].timestamp == row.predictions[0].timestamp


def test_failed_model_isolation_and_no_failure_cache(service):
    service.adapters["ampeppy"].failure = AdapterError("WORKER_FAILED", "fixture failure")
    for _ in range(2):
        result = service.predict(request())
        assert result.status == "partial_success"
        assert result.sequences[0].predictions[0].status == "succeeded"
        assert result.sequences[0].predictions[1].status == "failed"
        assert result.sequences[0].predictions[1].raw_score is None
    assert service.adapters["ampir"].calls == 1
    assert service.adapters["ampeppy"].calls == 2


def test_timeout_unavailable_and_eligibility(service):
    service.adapters["ampir"].failure = AdapterError("MODEL_TIMEOUT", "fixture timed out")
    result = service.predict(request(models=["ampir", "apin"]))
    assert result.status == "failed"
    assert [p.status for p in result.sequences[0].predictions] == ["timeout", "unavailable"]
    short = PredictRequest(
        sequences=[SequenceInput(sequence_id="short", sequence="ACD")], models=["ampir"]
    )
    assert service.predict(short).sequences[0].predictions[0].status == "ineligible"


def test_subprocess_hard_timeout(tmp_path):
    start = time.monotonic()
    with pytest.raises(AdapterError) as error:
        SubprocessAdapter._execute(
            [sys.executable, "-c", "import time; time.sleep(10)"], tmp_path, 0.1
        )
    assert error.value.code == "MODEL_TIMEOUT"
    assert time.monotonic() - start < 3


@pytest.mark.parametrize(
    "content",
    [
        "seq_name\tprob_AMP\nq0\tnan\n",
        "seq_name\tprob_AMP\nq0\t1.5\n",
        "seq_name\tprob_AMP\nq0\tNA\n",
        "seq_name\tprob_AMP\nwrong\t0.8\n",
        "seq_name\tprob_AMP\nq0\t0.8\nq0\t0.8\n",
        "wrong_header\n0.8\n",
    ],
)
def test_reject_malformed_native_output(tmp_path, content):
    adapter = SubprocessAdapter("ampir", {"executable": sys.executable})

    def output(command, cwd, timeout, statistics, **kwargs):
        Path(command[-2]).write_text(content)

    adapter._execute = output
    with pytest.raises(AdapterError) as error:
        adapter.run(request().sequences, request(), {"fixture": True})
    assert error.value.code == "OUTPUT_INVALID"


def test_wrong_sequence_checksum_isolated(service):
    adapter = service.adapters["ampeppy"]
    original = adapter.run

    def wrong(sequences, req, identity):
        records = original(sequences, req, identity)
        records[0].sequence_checksum = "wrong"
        return records

    adapter.run = wrong
    result = service.predict(request())
    assert result.status == "partial_success"
    assert result.sequences[0].predictions[1].error["code"] == "OUTPUT_INVALID"


def test_unexpected_exception_isolated(service):
    def broken(*_):
        raise RuntimeError("engineering fixture exception")

    service.adapters["ampeppy"].run = broken
    result = service.predict(request())
    assert result.status == "partial_success"
    assert result.sequences[0].predictions[1].error["code"] == "ADAPTER_FAILED"


def test_retry_only_transient_and_within_budget(service):
    adapter = service.adapters["ampir"]
    original = adapter.run
    calls = []

    def transient(sequences, req, identity):
        calls.append(req.timeout_seconds)
        if len(calls) == 1:
            raise AdapterError("RESOURCE_BUSY", "try again", retryable=True)
        return original(sequences, req, identity)

    adapter.run = transient
    report = service.predict(request(models=["ampir"], timeout_seconds=1))
    assert report.status == "succeeded"
    assert len(calls) == 2 and calls[1] < calls[0]
    assert report.sequences[0].predictions[0].reproducibility["attempts"] == 2


def test_cache_content_identity_and_configuration(service):
    service.predict(request(models=["ampir"]))
    alias = PredictRequest(
        sequences=[SequenceInput(sequence_id="renamed", sequence=SEQUENCE)], models=["ampir"]
    )
    p = service.predict(alias).sequences[0].predictions[0]
    assert p.cached and p.sequence_id == "renamed"
    assert (
        service.predict(request(models=["ampir"], ampir_model="precursor")).execution["cache_hits"]
        == 0
    )
    assert (
        service.predict(request(models=["ampir"], ampir_threshold=0.9)).execution["cache_hits"] == 0
    )
    service.adapters["ampir"].revision = "fixture-2"
    assert service.predict(request(models=["ampir"])).execution["cache_hits"] == 0


def test_global_model_concurrency_bound(service):
    adapter = service.adapters["ampir"]
    adapter.delay = 0.08
    reqs = [
        PredictRequest(
            sequences=[SequenceInput(sequence_id=str(i), sequence=SEQUENCE + "A" * i)],
            models=["ampir"],
        )
        for i in range(6)
    ]
    with ThreadPoolExecutor(max_workers=6) as executor:
        reports = list(executor.map(service.predict, reqs))
    assert all(r.status == "succeeded" for r in reports)
    assert adapter.maximum <= 2
    assert adapter.maximum == 2


def wait_job(service, job_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = service.store.job(job_id)
        if job["status"] not in {"running", "queued"}:
            return job
        time.sleep(0.01)
    pytest.fail("job did not complete")


def test_idempotency_persistence_and_conflicts(service):
    with ThreadPoolExecutor(max_workers=4) as executor:
        jobs = list(executor.map(lambda _: service.submit(request(), "same-key"), range(8)))
    assert len({j["job_id"] for j in jobs}) == 1
    job = wait_job(service, jobs[0]["job_id"])
    assert job["status"] == "succeeded"
    reopened = Store(service.database_path)
    assert reopened.job(job["job_id"]) == job
    with pytest.raises(JobConflict):
        service.submit(request(models=["ampir"]), "same-key")
    assert service.adapters["ampir"].calls == 1


def test_atomic_job_capacity_and_recovery(tmp_path, monkeypatch):
    store = Store(tmp_path / "jobs.sqlite3")
    records = [store.create_job({"request": i}, {}, f"key{i}")[0] for i in range(4)]
    with pytest.raises(CapacityExceeded):
        store.create_job({"request": 5}, {}, "new-key")
    assert store.create_job({"request": 0}, {}, "key0")[1] is False

    def dead_process(*_):
        raise ProcessLookupError

    monkeypatch.setattr("bacteriocin_lab.amp.store.os.kill", dead_process)
    assert store.recover_dead_jobs() == 4
    assert store.job(records[0]["job_id"])["status"] == "interrupted"


def test_runtime_and_artifact_integrity(tmp_path):
    source = tmp_path / "weights"
    source.write_text("pinned")
    config = {
        "source_commit": "93bcaa2d074d946eac5d66ef8d3640724e68d725",
        "executable": sys.executable,
        "runtime_versions": {},
        "artifacts": {"weights": {"path": str(source), "sha256": file_hash(source)}},
    }
    adapter = SubprocessAdapter("ampir", config)
    adapter._runtime = lambda: {}
    assert adapter.health()["status"] == "PARTIAL"
    source.write_text("changed")
    assert adapter.health()["status"] == "BLOCKED"
    assert adapter.health()["error_code"] == "ARTIFACT_MISMATCH"
    with pytest.raises(ValueError):
        SubprocessAdapter("apin", config)


def test_api_contract_and_existing_health(service):
    with TestClient(create_app(amp_service=service)) as client:
        assert client.get("/health").status_code == 200
        payload = request().model_dump()
        response = client.post("/api/v1/amp/predict", json=payload)
        assert response.status_code == 200
        assert response.json()["evidence_type"] == "computational-prediction"
        assert (
            client.post("/api/v1/amp/predict", json={**payload, "models": ["unknown"]}).status_code
            == 422
        )
        assert (
            client.get("/api/v1/amp/models/health").json()["resources"][
                "max_concurrent_model_processes"
            ]
            == 2
        )
        assert client.get("/api/v1/amp/jobs/missing").status_code == 404
        job = client.post("/api/v1/amp/batch", json=payload, headers={"Idempotency-Key": "api-key"})
        assert job.status_code == 202
        assert (
            client.post(
                "/api/v1/amp/batch",
                json={**payload, "models": ["ampir"]},
                headers={"Idempotency-Key": "api-key"},
            ).status_code
            == 409
        )
        assert "PredictionReport" in client.get("/openapi.json").json()["components"]["schemas"]


def test_declared_and_chunked_request_limits(service):
    with TestClient(create_app(amp_service=service)) as client:
        assert (
            client.post(
                "/api/v1/amp/predict",
                content=b"{}",
                headers={"Content-Length": str(MAX_BODY_BYTES + 1)},
            ).status_code
            == 413
        )
        response = client.post("/api/v1/amp/predict", content=iter([b"x" * MAX_BODY_BYTES, b"x"]))
        assert response.status_code == 413
        assert (
            client.post(
                "/api/v1/amp/predict", content=b"{}", headers={"Content-Length": "invalid"}
            ).status_code
            == 400
        )


def dramp_fixture(tmp_path, text=None):
    p = tmp_path / "dramp.tsv"
    p.write_text(
        text
        or (
            "DRAMP_ID\tSequence\tActivity\tTarget_Organism\n"
            "DRAMP1\tACDEFGHIKLMN\tAntibacterial\tReported MIC; unverified\n"
            "DRAMP2\tACDEFGHIKLMN\tPredicted\tUnknown\n"
            "DRAMP3\tACDX\tUnknown\tUnknown\n"
        )
    )
    return p


def test_dramp_reproducibility_metadata_duplicates_and_exact_lookup(tmp_path):
    store = Store(tmp_path / "reference.sqlite3")
    p = dramp_fixture(tmp_path)
    options = {
        "source_url": "https://dramp.cpu-bioinfor.org/test-fixture",
        "source_version": "fixture",
        "expected_sha256": file_hash(p),
    }
    manifest = ingest(store, p, **options)
    assert manifest == ingest(store, p, **options)
    assert (
        manifest["accepted_records"],
        manifest["rejected_records"],
        manifest["duplicate_sequence_records"],
    ) == (2, 1, 1)
    found = store.dramp_search(sequence="ACDEFGHIKLMN")
    assert found["total"] == 2
    assert found["records"][0]["metadata"]["Target_Organism"] == "Reported MIC; unverified"
    assert found["records"][0]["evidence_type"] == "reference-database-annotation"
    assert store.dramp_search(record_id="DRAMP1")["total"] == 1
    assert store.dramp_search(sequence="ACDEFGHIKLM")["total"] == 0
    with store.connection() as db:
        assert (
            json.loads(db.execute("SELECT metadata_json FROM dramp_rejected").fetchone()[0])[
                "Sequence"
            ]
            == "ACDX"
        )
    with pytest.raises(ValueError, match="checksum"):
        ingest(store, p, **{**options, "expected_sha256": "bad"})


def test_dramp_transaction_rollback_on_duplicate_source_id(tmp_path):
    p = dramp_fixture(tmp_path, "DRAMP_ID\tSequence\nDRAMP1\tACDEFGHIKL\nDRAMP1\tACDEFGHIKLM\n")
    store = Store(tmp_path / "reference.sqlite3")
    with pytest.raises(sqlite3.IntegrityError):
        ingest(
            store, p, source_url="fixture", source_version="fixture", expected_sha256=file_hash(p)
        )
    assert store.dramp_search(record_id="DRAMP1")["total"] == 0
    assert not store.dramp_search()["database_available"]


def test_dramp_link_and_api_preserve_reference_status(service, tmp_path):
    p = dramp_fixture(tmp_path, "DRAMP_ID\tSequence\tActivity\nDRAMP1\t" + SEQUENCE + "\tUnknown\n")
    ingest(
        service.store,
        p,
        source_url="fixture",
        source_version="fixture",
        expected_sha256=file_hash(p),
    )
    with TestClient(create_app(amp_service=service)) as client:
        result = client.post("/api/v1/amp/predict", json=request().model_dump()).json()
        match = result["sequences"][0]["dramp_matches"][0]
        assert match["experimental_verification"] == "not independently assessed"
        found = client.get("/api/v1/dramp/search", params={"sequence": SEQUENCE}).json()
        assert found["total"] == 1
        assert client.get("/api/v1/dramp/records/DRAMP1").status_code == 200
        assert client.get("/api/v1/dramp/records/missing").status_code == 404
        assert client.get("/api/v1/dramp/search").status_code == 422
        assert client.get("/api/v1/dramp/search", params={"sequence": "ACDX"}).status_code == 422
