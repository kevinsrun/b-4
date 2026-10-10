"""Arithmetic/contract fixtures, not biological performance observations."""

import hashlib

import pytest
from pydantic import ValidationError

from bacteriocin_lab.amp.adapters import digest
from bacteriocin_lab.amp.benchmark import (
    BenchmarkRecord,
    DatasetManifest,
    TrainingInventory,
    bootstrap_intervals,
    classification_metrics,
    evaluate_predictions,
    fasta_manifest,
    leakage_audit,
    one_edit_apart,
)


def record(name, sequence="ACDEFGHIKL", label=1):
    return BenchmarkRecord(
        sequence_id=name,
        original_header=name,
        sequence=sequence,
        sequence_sha256=hashlib.sha256(sequence.encode()).hexdigest(),
        label=label,
    )


def dataset(records=None, partition="benchmark", **kwargs):
    return DatasetManifest(
        dataset_id="arithmetic-fixture",
        version="1",
        source_url="fixture",
        source_revision="fixture",
        source_file_sha256="0" * 64,
        permitted_usage="engineering fixture only",
        partition=partition,
        population="mature",
        label_definition="test fixture binary values",
        label_quality="experimentally_assessed_binary",
        records=records or [record("one")],
        **kwargs,
    )


def inventory(records=None, coverage="complete"):
    return TrainingInventory(
        model_id="ampir",
        model_variant="mature",
        checkpoint_sha256={"weights": "a" * 64},
        completeness_evidence="engineering fixture only",
        coverage=coverage,
        datasets=[dataset(records or [record("train", "MNPQRSTVWY")], partition="training")],
    )


def alignment(benchmark, train, complete=True):
    return {
        "schema_version": "amp-alignment-audit/1",
        "complete": complete,
        "hits": [],
        "within_benchmark_hits": [],
        "within_benchmark_complete": complete,
        "method": "highest-scoring local BLOSUM62 alignment",
        "biopython_version": "1.83",
        "identity_cutoff": 0.85,
        "coverage_cutoff": 0.8,
        "gap_open": -10,
        "gap_extend": -0.5,
        "query_digest": digest([r.model_dump() for r in benchmark.records]),
        "reference_digest": digest([r.model_dump() for d in train.datasets for r in d.records]),
    }


def test_hand_computed_metrics_and_probability_semantics():
    m = classification_metrics(
        [1, 0, 1, 0],
        [0.9, 0.8, 0.3, 0.1],
        [True, True, False, False],
        score_semantics="probability_estimate",
    )
    assert m["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 1, "tp": 1}
    assert m["f1"] == m["specificity"] == m["recall"] == m["precision"] == 0.5
    assert m["mcc"] == 0 and m["roc_auc"] == 0.75
    assert m["pr_auc_trapezoidal"] == pytest.approx(19 / 24)
    assert m["average_precision"] == pytest.approx(5 / 6)
    assert m["calibration"]["brier_score"] == pytest.approx(0.2875)
    assert classification_metrics([1, 0], [10, -10], [True, False])["calibration"] is None


def test_score_ties_absent_classes_and_bad_inputs():
    m = classification_metrics([1, 0], [0.5, 0.5], [False, False])
    assert m["roc_auc"] == 0.5 and m["average_precision"] == 0.5
    assert m["mcc"] is None and m["precision"] is None
    assert classification_metrics([1], [0.9], [True])["roc_auc"] is None
    with pytest.raises(ValueError):
        classification_metrics([1], [float("nan")], [True])
    with pytest.raises(ValueError):
        classification_metrics([1], [1.1], [True], score_semantics="probability_estimate")
    with pytest.raises(ValueError):
        classification_metrics([1], [0.9], [1])


def test_seeded_stratified_bootstrap():
    args = ([1, 0, 1, 0], [0.9, 0.8, 0.3, 0.1], [True, True, False, False])
    assert bootstrap_intervals(*args, repetitions=20) == bootstrap_intervals(*args, repetitions=20)
    assert bootstrap_intervals([1], [0.9], [True])["status"] == "BLOCKED"


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("ACDEF", "ACDEF", True),
        ("ACDEF", "ACDEG", True),
        ("ACDEF", "ACDF", True),
        ("ACDEF", "ACDEFG", True),
        ("ACDEF", "ACD", False),
        ("ACDEF", "AGDRF", False),
    ],
)
def test_near_duplicate_definition(a, b, expected):
    assert one_edit_apart(a, b) is expected


def test_manifest_checksums_ids_and_source_provenance(tmp_path):
    with pytest.raises(ValidationError):
        record("one").model_copy(update={"sequence_sha256": "0" * 64}).__class__.model_validate(
            record("one").model_dump() | {"sequence_sha256": "0" * 64}
        )
    with pytest.raises(ValidationError):
        dataset([record("same"), record("same")])
    p = tmp_path / "source.fa"
    p.write_text(">source-id description\nACDEFGHIKL\n>other\nMNPQRSTVWY\n")
    metadata = dataset().model_dump(exclude={"records", "source_file_sha256"})
    manifest = fasta_manifest(p, label=0, metadata=metadata, limit=1)
    assert len(manifest.records) == 1
    assert manifest.records[0].original_header == "source-id description"
    assert manifest.records[0].label == 0


def test_exact_near_and_conflicting_partitioning():
    b = dataset([record("exact"), record("near", "ACDEFGHIKM"), record("alias", label=0)])
    t = inventory([record("training")])
    report = leakage_audit(b, t, homology=alignment(b, t))
    assert report["independent_benchmark_status"] == "BLOCKED"
    assert "exact_training_overlap" in report["records"][0]["contamination_reasons"]
    assert "near_training_duplicate" in report["records"][1]["contamination_reasons"]
    assert "conflicting_benchmark_labels" in report["records"][0]["contamination_reasons"]


@pytest.mark.parametrize("missing", ["training", "homology", "labels", "identity", "budget"])
def test_fail_closed_independence(missing):
    b, t = dataset(), inventory()
    h = alignment(b, t)
    options = {}
    if missing == "training":
        t.coverage = "partial"
    elif missing == "homology":
        h["complete"] = False
    elif missing == "labels":
        b.label_quality = "curated_proxy"
    elif missing == "identity":
        h["reference_digest"] = "wrong"
    elif missing == "budget":
        options["near_pair_budget"] = 0
    report = leakage_audit(b, t, homology=h, **options)
    assert report["independent_benchmark_status"] == "BLOCKED"
    assert evaluate_predictions(b, t, report, [])["metrics"] is None


def test_checkpoint_bound_evaluation_uses_only_eligible_records():
    b = dataset([record("positive"), record("negative", "YWVTSRQPNM", label=0)])
    t = inventory([record("training", "GHIKLMNPQR")])
    audit = leakage_audit(b, t, homology=alignment(b, t))
    assert audit["independent_benchmark_status"] == "ELIGIBLE_UNDER_DECLARED_AUDIT"
    predictions = [
        {
            "sequence_id": r.sequence_id,
            "sequence_checksum": r.sequence_sha256,
            "model_id": "ampir",
            "model_variant": "mature",
            "status": "succeeded",
            "raw_score": 0.9 if r.label else 0.1,
            "binary_prediction": bool(r.label),
            "reproducibility": {"artifacts": {"weights": "a" * 64}},
        }
        for r in b.records
    ]
    assert (
        evaluate_predictions(b, t, audit, predictions, bootstrap_repetitions=10)["metrics"]["f1"]
        == 1
    )
    predictions[0]["reproducibility"]["artifacts"]["weights"] = "changed"
    with pytest.raises(ValueError, match="checkpoint"):
        evaluate_predictions(b, t, audit, predictions)
    audit["benchmark_identity"] = "different"
    with pytest.raises(ValueError, match="identity"):
        evaluate_predictions(b, t, audit, predictions)


def test_incomplete_within_family_screen_cannot_certify_independence():
    b, t = dataset(), inventory()
    h = alignment(b, t)
    h["within_benchmark_complete"] = False
    assert leakage_audit(b, t, homology=h)["independent_benchmark_status"] == "BLOCKED"
    h["within_benchmark_complete"] = True
    h["within_benchmark_hits"] = [
        {
            "query_id": "one",
            "reference_ids": ["one"],
            "identity": 1,
            "query_coverage": 1,
            "reference_coverage": 1,
        }
    ]
    assert leakage_audit(b, t, homology=h)["records"][0]["partition"] == "contaminated"


def test_wrong_training_partition_and_checkpoint_identity():
    with pytest.raises(ValidationError, match="non-training"):
        TrainingInventory.model_validate(
            inventory().model_dump() | {"datasets": [dataset().model_dump()]}
        )
    with pytest.raises(ValidationError, match="SHA256"):
        TrainingInventory.model_validate(
            inventory().model_dump() | {"checkpoint_sha256": {"weights": "unverified"}}
        )


def test_real_isolated_alignment_worker_when_reference_runtime_is_installed():
    from pathlib import Path

    from bacteriocin_lab.amp.benchmark import alignment_audit

    python = Path("artifacts/amp/runtime/ampeppy/bin/python").absolute()
    if not python.is_file():
        pytest.skip("optional isolated Biopython 1.83 environment not provisioned")
    query = [record("query", "ACDEFGHIKLMNPQRSTVWY")]
    reference = [record("same", "ACDEFGHIKLMNPQRSTVWY"), record("near", "ACDEFGHIKLMNPQRSTVWF")]
    result = alignment_audit(query, reference, python=python)
    assert result["complete"] and result["within_benchmark_complete"]
    assert {r["reference_ids"][0] for r in result["hits"]} == {"same", "near"}
    assert result["biopython_version"] == "1.83"
    assert result["worker_sha256"] and result["executable_sha256"]
    limited = alignment_audit(query, reference, python=python, pair_budget=1)
    assert limited["complete"] is False
