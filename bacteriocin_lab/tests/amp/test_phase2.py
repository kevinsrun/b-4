"""Engineering fixtures only. No fixture proves biological validity or legacy inference."""

from __future__ import annotations

import ast
import json
import os
import sys
import time
from pathlib import Path

import pytest

from bacteriocin_lab.amp.adapters import AdapterError, SubprocessAdapter, file_hash, process_env
from bacteriocin_lab.amp.dramp import ingest
from bacteriocin_lab.amp.legacy import LegacyTensorFlowAdapter
from bacteriocin_lab.amp.schemas import PredictRequest, SequenceInput
from bacteriocin_lab.amp.store import Store


def test_memory_limit_kills_worker_and_reaps(tmp_path):
    pid_file = tmp_path / "pid"
    code = (
        f"import os,time;open({str(pid_file)!r},'w').write(str(os.getpid())); "
        "x=bytearray(128*1024*1024);time.sleep(10)"
    )
    statistics = {}
    with pytest.raises(AdapterError) as error:
        SubprocessAdapter._execute(
            [sys.executable, "-c", code], tmp_path, 4, statistics, memory_limit_mib=32
        )
    assert error.value.code == "MODEL_MEMORY_LIMIT"
    if pid_file.exists():
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)


@pytest.mark.parametrize("value", [0, -1, True, 2.5, 20000])
def test_invalid_memory_limits_never_start(tmp_path, value):
    with pytest.raises(ValueError):
        SubprocessAdapter._execute(["not-a-command"], tmp_path, 1, memory_limit_mib=value)


def test_worker_environment_threads_and_secret_isolation(monkeypatch):
    monkeypatch.setenv("MODEL_SECRET", "not-for-worker")
    env = process_env()
    assert "MODEL_SECRET" not in env
    assert all(
        env[name] == "1"
        for name in [
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "TF_NUM_INTEROP_THREADS",
            "TF_NUM_INTRAOP_THREADS",
        ]
    )


def test_legacy_worker_python36_and_no_fit_path():
    worker = Path(__file__).parents[2] / "amp/tf1_worker.py"
    tree = ast.parse(worker.read_text(), feature_version=(3, 6))
    assert not any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in {"fit", "fit_generator", "train_on_batch"}
        for n in ast.walk(tree)
    )
    assert "intra_op_parallelism_threads=1" in worker.read_text()
    assert "inter_op_parallelism_threads=1" in worker.read_text()


@pytest.mark.parametrize("model", ["amplify", "ampscanner_v2"])
def test_partial_legacy_gate_never_executes_without_proof(tmp_path, monkeypatch, model):
    adapter = LegacyTensorFlowAdapter(model, {})
    monkeypatch.setattr(adapter, "_unverified_identity", lambda: {"fingerprint": "fixture"})
    assert adapter.health()["status"] == "PARTIAL"
    assert adapter.health()["available"] is False
    with pytest.raises(AdapterError, match="disabled") as error:
        adapter.identity()
    assert error.value.code == "REFERENCE_NOT_VERIFIED"
    proof = tmp_path / "evidence.json"
    proof.write_text("{}")
    adapter.config["verification"] = {
        "fingerprint": "fixture",
        "reference_agreement": True,
        "inference_passed": True,
        "evidence_path": str(proof),
        "evidence_sha256": file_hash(proof),
    }
    assert adapter.identity()["fingerprint"] == "fixture"
    proof.write_text("changed")
    assert adapter.health()["available"] is False
    with pytest.raises(AdapterError):
        adapter.identity()


def test_native_amplify_scores_preserved_and_nonfinite_rejected():
    adapter = LegacyTensorFlowAdapter("amplify", {})
    row = {"log_scaled_score": "3.01", **{f"submodel_{i}": ".5" for i in range(1, 6)}}
    assert adapter._native_scores(row, 0.5)["log_scaled_score"] == 3.01
    row["submodel_1"] = "nan"
    with pytest.raises(ValueError):
        adapter._native_scores(row, 0.5)


def test_legacy_batch_transport_parsing_mock_only(tmp_path, monkeypatch):
    adapter = LegacyTensorFlowAdapter(
        "ampscanner_v2",
        {"executable": sys.executable, "variant": "021820_FULL_MODEL", "artifacts": {}},
    )
    request = PredictRequest(
        sequences=[
            SequenceInput(sequence_id="one", sequence="ACDEFGHIKL"),
            SequenceInput(sequence_id="two", sequence="MNPQRSTVWY"),
        ],
        models=["ampscanner_v2"],
    )

    def fixture(command, cwd, timeout, statistics, **kwargs):
        Path(command[3]).write_text(
            "seq_id\tprobability_AMP\tpredicted\nq0\t0.9\tAMP\nq1\t0.1\tnonAMP\n"
        )

    monkeypatch.setattr(adapter, "_execute", fixture)
    results = adapter.run(request.sequences, request, {"fixture": True})
    assert [r.binary_prediction for r in results] == [True, False]
    assert all(r.model_variant == "021820_FULL_MODEL" for r in results)
    assert all(r.benchmark_validation["status"] == "BLOCKED" for r in results)


def test_checkpoint_source_selection_rejects_wrong_variant():
    adapter = LegacyTensorFlowAdapter(
        "ampscanner_v2",
        {"variant": "original-tf1.2", "artifacts": {"predictor.py": {}, "weights": {}}},
    )
    with pytest.raises(AdapterError) as error:
        adapter._unverified_identity()
    assert error.value.code == "MODEL_VARIANT_MISMATCH"


def test_runtime_probe_failure_is_structured(monkeypatch):
    adapter = LegacyTensorFlowAdapter("amplify", {"executable": "fixture"})

    def abort(*args, **kwargs):
        raise AdapterError("WORKER_FAILED", "exit -6")

    monkeypatch.setattr(adapter, "_execute", abort)
    with pytest.raises(AdapterError) as error:
        adapter._runtime()
    assert error.value.code == "LEGACY_RUNTIME_UNAVAILABLE"


def test_original_artifact_corruption_and_stale_probe(tmp_path, monkeypatch):
    weights = tmp_path / "weights"
    weights.write_bytes(b"original")
    adapter = SubprocessAdapter(
        "ampeppy",
        {
            "source_commit": "85aab3428b328d9fe4744052258746d8f4ba7bf6",
            "artifacts": {"weights": {"path": str(weights), "sha256": file_hash(weights)}},
            "executable": sys.executable,
            "runtime_versions": {"fixture": "1"},
        },
    )
    monkeypatch.setattr(adapter, "_runtime", lambda: {"fixture": "1"})
    original = adapter.identity()["fingerprint"]
    weights.write_bytes(b"corrupt")
    with pytest.raises(AdapterError) as error:
        adapter.identity()
    assert error.value.code == "ARTIFACT_MISMATCH"
    adapter.config["artifacts"]["weights"]["sha256"] = file_hash(weights)
    assert adapter.identity()["fingerprint"] != original
    monkeypatch.undo()
    adapter._probe = (time.monotonic() - 61, {"fixture": "1"})
    monkeypatch.setattr(adapter, "_execute", lambda *args, **kwargs: json.dumps({"fixture": "2"}))
    with pytest.raises(AdapterError) as error:
        adapter._runtime()
    assert error.value.code == "RUNTIME_MISMATCH"


def test_dramp_versioned_import_preserves_old_identity_and_raw_annotations(tmp_path):
    store = Store(tmp_path / "database.sqlite3")
    source = tmp_path / "general.tsv"
    source.write_text(
        "DRAMP_ID\tSequence\tActivity\tOther_Modifications\tReference\n"
        "DRAMP00001\tACDEFGHIKL\tpublisher activity\tcyclization\tPMID123\n"
        "DRAMP00002\tACDEFGHIKL\tcomputational prediction\t\tPMID124\n"
        "DRAMP00003\tACDX\tunknown\tmodified\tPMID125\n"
    )
    old = ingest(
        store,
        source,
        source_url="official",
        source_version="snapshot-unresolved",
        expected_sha256=file_hash(source),
    )
    provenance = {
        "source_artifact_sha256": "a" * 64,
        "normalized_tsv_sha256": file_hash(source),
        "release_version_status": "verified_publication_snapshot",
        "archive": "versioned-fixture",
    }
    new = ingest(
        store,
        source,
        source_url="publication-archive",
        source_version="fixture-v2",
        expected_sha256=file_hash(source),
        source_provenance=provenance,
    )
    assert new["dataset_id"] != old["dataset_id"]
    assert new == ingest(
        store,
        source,
        source_url="publication-archive",
        source_version="fixture-v2",
        expected_sha256=file_hash(source),
        source_provenance=provenance,
    )
    result = store.dramp_search(sequence="ACDEFGHIKL", dataset_id=new["dataset_id"])
    assert result["total"] == 2 and new["duplicate_sequence_records"] == 1
    assert result["records"][0]["metadata"]["Other_Modifications"] == "cyclization"
    assert result["records"][0]["experimental_verification"] == "not independently assessed"
    assert (
        result["records"][0]["provenance"]["release_version_status"]
        == "verified_publication_snapshot"
    )
    with store.connection() as db:
        assert (
            json.loads(
                db.execute(
                    "SELECT manifest_json FROM dramp_datasets WHERE dataset_id=?",
                    (old["dataset_id"],),
                ).fetchone()[0]
            )
            == old
        )
        assert db.execute("SELECT COUNT(*) FROM dramp_rejected").fetchone()[0] == 2
    old_view = store.dramp_search(record_id="DRAMP00001", dataset_id=old["dataset_id"])
    assert old_view["records"][0]["provenance"]["release_version_status"] == "unresolved"
    provenance["normalized_tsv_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="checksum"):
        ingest(
            store,
            source,
            source_url="archive",
            source_version="bad",
            expected_sha256=file_hash(source),
            source_provenance=provenance,
        )


def test_memory_monitor_fails_closed(tmp_path, monkeypatch):
    import subprocess

    def broken(*args, **kwargs):
        raise OSError("RSS monitor unavailable")

    monkeypatch.setattr(subprocess, "run", broken)
    with pytest.raises(AdapterError) as error:
        SubprocessAdapter._execute(
            [sys.executable, "-c", "import time;time.sleep(5)"], tmp_path, 1, memory_limit_mib=32
        )
    assert error.value.code == "RESOURCE_MONITOR_UNAVAILABLE"
