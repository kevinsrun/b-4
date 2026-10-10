"""Versioned labels, fail-closed leakage audits and model-specific evaluation arithmetic."""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .adapters import SubprocessAdapter, digest, file_hash


class BenchmarkRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence_id: str = Field(min_length=1, max_length=512)
    sequence: str = Field(min_length=1, max_length=10000, pattern="^[ACDEFGHIKLMNPQRSTVWY]+$")
    sequence_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    label: Literal[0, 1]
    original_header: str

    @model_validator(mode="after")
    def checksum_matches(self):
        if hashlib.sha256(self.sequence.encode("ascii")).hexdigest() != self.sequence_sha256:
            raise ValueError("sequence checksum mismatch")
        return self


class DatasetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["amp-dataset/1"] = "amp-dataset/1"
    dataset_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    source_file_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    permitted_usage: str = Field(min_length=1)
    partition: Literal["training", "published_test", "benchmark", "reference"]
    population: Literal["mature", "precursor", "mixed", "unresolved"]
    label_definition: str = Field(min_length=1)
    label_quality: Literal["experimentally_assessed_binary", "curated_proxy", "unresolved"]
    source_files: dict[str, str] = Field(default_factory=dict)
    selection: str = "entire source file"
    records: list[BenchmarkRecord] = Field(min_length=1, max_length=250000)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [r.sequence_id for r in self.records]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate sequence identifiers; preserve aliases with distinct IDs")
        return self

    @property
    def identity(self) -> str:
        return digest(self.model_dump())


class TrainingInventory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str
    model_variant: str
    checkpoint_sha256: dict[str, str]
    coverage: Literal["complete", "partial", "unavailable", "unresolved"]
    completeness_evidence: str
    datasets: list[DatasetManifest]

    @model_validator(mode="after")
    def training_partitions(self):
        if any(d.partition != "training" for d in self.datasets):
            raise ValueError("training inventory cannot contain non-training partitions")
        if any(
            len(v) != 64 or any(c not in "0123456789abcdef" for c in v)
            for v in self.checkpoint_sha256.values()
        ):
            raise ValueError("checkpoint identities must be SHA256 digests")
        return self


def fasta_manifest(
    path: Path, *, label: int, metadata: dict[str, Any], limit: int | None = None
) -> DatasetManifest:
    """Import source labels explicitly; do not infer labels from peptide names or DRAMP."""
    if label not in (0, 1):
        raise ValueError("binary source label required")
    records, header, pieces = [], None, []

    def add():
        if header is None:
            return
        sequence = "".join(pieces)
        records.append(
            BenchmarkRecord(
                sequence_id=header.split()[0],
                original_header=header,
                sequence=sequence,
                sequence_sha256=hashlib.sha256(sequence.encode("ascii")).hexdigest(),
                label=label,
            )
        )

    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        if line.startswith(">"):
            add()
            if limit is not None and len(records) >= limit:
                break
            header, pieces = line[1:].strip(), []
        else:
            if header is None:
                raise ValueError("FASTA sequence before header")
            pieces.append(line.strip())
    else:
        add()
    return DatasetManifest(source_file_sha256=file_hash(path), records=records, **metadata)


def one_edit_apart(a: str, b: str) -> bool:
    """Full-sequence Levenshtein distance <=1, without confusing this with homology."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) <= 1
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1 :]


def alignment_audit(
    query: list[BenchmarkRecord],
    reference: list[BenchmarkRecord],
    *,
    python: Path,
    identity_cutoff: float = 0.85,
    coverage_cutoff: float = 0.8,
    pair_budget: int = 1000000,
    timeout: float = 120,
) -> dict:
    if not 0 < identity_cutoff <= 1 or not 0 < coverage_cutoff <= 1 or pair_budget < 1:
        raise ValueError("invalid homology thresholds or comparison budget")
    with tempfile.TemporaryDirectory(prefix="b4-leakage-") as directory:
        cwd = Path(directory)
        source, target = cwd / "alignment.json", cwd / "result.json"
        source.write_text(
            json.dumps(
                {
                    "query": [r.model_dump() for r in query],
                    "reference": [r.model_dump() for r in reference],
                    "identity_cutoff": identity_cutoff,
                    "coverage_cutoff": coverage_cutoff,
                    "pair_budget": pair_budget,
                }
            )
        )
        worker = Path(__file__).with_name("alignment_worker.py")
        SubprocessAdapter._execute(
            [str(python), str(worker), str(source), str(target)], cwd, timeout
        )
        result = json.loads(target.read_text())
        if result.get("schema_version") != "amp-alignment-audit/1":
            raise ValueError("invalid alignment audit schema")
        result["worker_sha256"] = file_hash(worker)
        result["executable_sha256"] = file_hash(python)
        return result


def leakage_audit(
    benchmark: DatasetManifest,
    inventory: TrainingInventory,
    *,
    homology: dict | None = None,
    near_pair_budget: int = 1000000,
) -> dict:
    """Separate contaminated, unresolved, and independently eligible records."""
    training = [r for dataset in inventory.datasets for r in dataset.records]
    by_checksum, by_length, within = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in training:
        by_checksum[r.sequence_sha256].append(r)
        by_length[len(r.sequence)].append(r)
    for r in benchmark.records:
        within[r.sequence_sha256].append(r)
    valid_homology = (
        homology is not None
        and homology.get("schema_version") == "amp-alignment-audit/1"
        and homology.get("complete") is True
        and homology.get("within_benchmark_complete") is True
        and homology.get("method") == "highest-scoring local BLOSUM62 alignment"
        and homology.get("biopython_version") == "1.83"
        and homology.get("identity_cutoff") == 0.85
        and homology.get("coverage_cutoff") == 0.8
        and homology.get("gap_open") == -10
        and homology.get("gap_extend") == -0.5
        and homology.get("query_digest") == digest([r.model_dump() for r in benchmark.records])
        and homology.get("reference_digest") == digest([r.model_dump() for r in training])
    )
    hits = defaultdict(list)
    if valid_homology:
        for hit in homology["hits"]:
            hits[hit["query_id"]].append(hit)
    within_hits = defaultdict(list)
    if valid_homology:
        for hit in homology["within_benchmark_hits"]:
            within_hits[hit["query_id"]].append(hit)
            for reference_id in hit["reference_ids"]:
                within_hits[reference_id].append(hit)
    comparisons, outcomes = 0, []
    near_complete = True
    for record in benchmark.records:
        reasons, exact, near = [], by_checksum[record.sequence_sha256], []
        if exact:
            reasons.append("exact_training_overlap")
        else:
            candidates = [
                r
                for n in range(len(record.sequence) - 1, len(record.sequence) + 2)
                for r in by_length[n]
            ]
            for candidate in candidates:
                if comparisons >= near_pair_budget:
                    near_complete = False
                    break
                comparisons += 1
                if one_edit_apart(record.sequence, candidate.sequence):
                    near.append(candidate.sequence_id)
            if near:
                reasons.append("near_training_duplicate")
        aliases = within[record.sequence_sha256]
        if len(aliases) > 1:
            reasons.append("within_benchmark_duplicate")
        if len({r.label for r in aliases}) > 1:
            reasons.append("conflicting_benchmark_labels")
        if within_hits[record.sequence_id]:
            reasons.append("within_benchmark_sequence_similarity")
        if hits[record.sequence_id]:
            reasons.append("training_sequence_similarity")
        outcomes.append(
            {
                "sequence_id": record.sequence_id,
                "label": record.label,
                "sequence_sha256": record.sequence_sha256,
                "exact_training_ids": [r.sequence_id for r in exact],
                "near_training_ids": near,
                "homology_hits": hits[record.sequence_id],
                "within_benchmark_hits": within_hits[record.sequence_id],
                "contamination_reasons": reasons,
            }
        )
    unresolved = []
    if (
        inventory.coverage != "complete"
        or not inventory.datasets
        or not inventory.checkpoint_sha256
    ):
        unresolved.append("training population/checkpoint linkage incomplete")
    if not valid_homology:
        unresolved.append("homology audit absent, incomplete or bound to different records")
    if not near_complete:
        unresolved.append("near-duplicate comparison budget exhausted")
    if benchmark.permitted_usage.lower() == "unresolved":
        unresolved.append("benchmark permitted usage unresolved")
    if benchmark.label_quality != "experimentally_assessed_binary":
        unresolved.append("binary biological labels not independently experimentally assessed")
    if benchmark.population == "unresolved":
        unresolved.append("benchmark sequence population unresolved")
    for row in outcomes:
        row["partition"] = (
            "contaminated"
            if row["contamination_reasons"]
            else "unresolved"
            if unresolved
            else "independently_eligible"
        )
    eligible = [r["sequence_id"] for r in outcomes if r["partition"] == "independently_eligible"]
    return {
        "schema_version": "amp-leakage-audit/1",
        "model_id": inventory.model_id,
        "model_variant": inventory.model_variant,
        "checkpoint_sha256": inventory.checkpoint_sha256,
        "benchmark_identity": benchmark.identity,
        "training_identity": digest(inventory.model_dump()),
        "independent_benchmark_status": "ELIGIBLE_UNDER_DECLARED_AUDIT" if eligible else "BLOCKED",
        "unresolved_reasons": unresolved,
        "records": outcomes,
        "eligible_ids": eligible,
        "near_duplicate_pair_budget": near_pair_budget,
        "near_duplicate_comparisons": comparisons,
        "near_duplicate_complete": near_complete,
        "homology": homology,
        "population": benchmark.population,
        "label_definition": benchmark.label_definition,
        "interpretation": (
            "sequence-similarity exclusion under stated method, not proof of absolute independence"
        ),
    }


def classification_metrics(
    labels: list[int],
    scores: list[float],
    classes: list[bool],
    *,
    score_semantics: str = "uncalibrated_score",
) -> dict:
    if not labels or not (len(labels) == len(scores) == len(classes)):
        raise ValueError("nonempty paired labels/scores/classes required")
    if any(y not in (0, 1) for y in labels) or any(type(c) is not bool for c in classes):
        raise ValueError("binary labels and boolean classes required")
    if any(not math.isfinite(s) for s in scores):
        raise ValueError("finite scores required")
    tp = sum(y == 1 and c for y, c in zip(labels, classes, strict=True))
    tn = sum(y == 0 and not c for y, c in zip(labels, classes, strict=True))
    fp, fn = sum(classes) - tp, sum(labels) - tp

    def divide(n, d):
        return n / d if d else None

    sensitivity, specificity, precision = (
        divide(tp, tp + fn),
        divide(tn, tn + fp),
        divide(tp, tp + fp),
    )
    denominator = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    # Tie groups are processed together; ROC uses trapezoids, PR also reports AP separately.
    groups = defaultdict(lambda: [0, 0])
    for y, score in zip(labels, scores, strict=True):
        groups[score][y] += 1
    positives, negatives = sum(labels), len(labels) - sum(labels)
    roc, pr, ap, tps, fps, prev_tpr, prev_fpr, prev_precision = 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0, 1.0
    for score in sorted(groups, reverse=True):
        fps += groups[score][0]
        tps += groups[score][1]
        tpr = tps / positives if positives else 0
        fpr = fps / negatives if negatives else 0
        current_precision = tps / (tps + fps)
        roc += (fpr - prev_fpr) * (tpr + prev_tpr) / 2
        pr += (tpr - prev_tpr) * (current_precision + prev_precision) / 2
        ap += (tpr - prev_tpr) * current_precision
        prev_tpr, prev_fpr, prev_precision = tpr, fpr, current_precision
    calibration = None
    if score_semantics == "probability_estimate":
        if any(not 0 <= s <= 1 for s in scores):
            raise ValueError("probability estimates must lie in [0,1]")
        bins = defaultdict(list)
        for y, s in zip(labels, scores, strict=True):
            bins[min(int(s * 10), 9)].append((y, s))
        reliability = [
            {
                "bin": i,
                "n": len(rows),
                "mean_score": statistics.mean(s for _, s in rows),
                "observed_fraction": statistics.mean(y for y, _ in rows),
            }
            for i, rows in sorted(bins.items())
        ]
        calibration = {
            "brier_score": statistics.mean(
                (s - y) ** 2 for y, s in zip(labels, scores, strict=True)
            ),
            "ece_10_equal_width_bins": sum(
                r["n"] * abs(r["mean_score"] - r["observed_fraction"]) for r in reliability
            )
            / len(labels),
            "reliability_bins": reliability,
            "interpretation": (
                "evaluation of model probability estimates; "
                "transportable calibration is not established"
            ),
        }
    return {
        "sample_size": len(labels),
        "positive_count": positives,
        "negative_count": negatives,
        "class_prevalence": positives / len(labels),
        "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
        "sensitivity": sensitivity,
        "recall": sensitivity,
        "specificity": specificity,
        "precision": precision,
        "f1": divide(2 * tp, 2 * tp + fp + fn),
        "mcc": divide(tp * tn - fp * fn, denominator),
        "roc_auc": roc if positives and negatives else None,
        "pr_auc_trapezoidal": pr if positives and negatives else None,
        "average_precision": ap if positives and negatives else None,
        "calibration": calibration,
        "undefined_values": "null; no denominator or absent class",
    }


def bootstrap_intervals(
    labels, scores, classes, *, repetitions: int = 200, seed: int = 2012
) -> dict:
    if not 1 <= repetitions <= 1000:
        raise ValueError("bootstrap repetitions must be 1..1000")
    classification_metrics(labels, scores, classes)
    strata = [[i for i, y in enumerate(labels) if y == c] for c in (0, 1)]
    if not all(strata):
        return {"status": "BLOCKED", "reason": "both classes required"}
    rng, values = random.Random(seed), defaultdict(list)
    for _ in range(repetitions):
        indices = [rng.choice(stratum) for stratum in strata for _ in stratum]
        result = classification_metrics(
            [labels[i] for i in indices],
            [scores[i] for i in indices],
            [classes[i] for i in indices],
        )
        for k in (
            "sensitivity",
            "specificity",
            "precision",
            "recall",
            "f1",
            "mcc",
            "roc_auc",
            "pr_auc_trapezoidal",
        ):
            if result[k] is not None:
                values[k].append(result[k])

    def percentile(data, fraction):
        ordered = sorted(data)
        position = (len(ordered) - 1) * fraction
        left, right = math.floor(position), math.ceil(position)
        return ordered[left] + (ordered[right] - ordered[left]) * (position - left)

    return {
        "status": "calculated",
        "method": "class-stratified sequence bootstrap, percentile 95%",
        "seed": seed,
        "repetitions": repetitions,
        "intervals": {
            k: {
                "lower": percentile(v, 0.025),
                "upper": percentile(v, 0.975),
                "valid_repetitions": len(v),
            }
            for k, v in values.items()
        },
        "limitation": (
            "assumes audited records are independent sampling units; no species-level inference"
        ),
    }


def evaluate_predictions(
    manifest: DatasetManifest,
    inventory: TrainingInventory,
    audit: dict,
    predictions: list[dict],
    *,
    score_semantics="uncalibrated_score",
    bootstrap_repetitions=200,
) -> dict:
    if audit.get("benchmark_identity") != manifest.identity or audit.get(
        "training_identity"
    ) != digest(inventory.model_dump()):
        raise ValueError("audit identity does not match benchmark and training manifests")
    if audit["independent_benchmark_status"] != "ELIGIBLE_UNDER_DECLARED_AUDIT":
        return {
            "status": "BLOCKED",
            "metrics": None,
            "reasons": audit["unresolved_reasons"],
            "contaminated_records": sum(r["partition"] == "contaminated" for r in audit["records"]),
        }
    verified_audit = leakage_audit(
        manifest,
        inventory,
        homology=audit.get("homology"),
        near_pair_budget=audit.get("near_duplicate_pair_budget", 1000000),
    )
    if (
        verified_audit["eligible_ids"] != audit["eligible_ids"]
        or verified_audit["records"] != audit["records"]
    ):
        raise ValueError("audit partition identity does not match recomputed leakage assessment")
    expected = set(audit["eligible_ids"])
    paired = {p["sequence_id"]: p for p in predictions}
    if len(paired) != len(predictions) or set(paired) != expected:
        raise ValueError("predictions must cover each eligible record exactly once")
    labels, scores, classes = [], [], []
    for record in manifest.records:
        if record.sequence_id not in expected:
            continue
        p = paired[record.sequence_id]
        if (
            p["model_id"] != inventory.model_id
            or p["sequence_checksum"] != record.sequence_sha256
            or p["status"] != "succeeded"
            or p.get("model_variant") != inventory.model_variant
        ):
            raise ValueError("model/variant/sequence identity or execution status mismatch")
        actual_artifacts = p.get("reproducibility", {}).get("artifacts", {})
        if any(actual_artifacts.get(k) != v for k, v in inventory.checkpoint_sha256.items()):
            raise ValueError(
                "prediction checkpoint identity differs from audited training inventory"
            )
        labels.append(record.label)
        scores.append(p["raw_score"])
        classes.append(p["binary_prediction"])
    return {
        "status": "evaluated_under_declared_audit",
        "model_id": inventory.model_id,
        "model_variant": inventory.model_variant,
        "benchmark_identity": manifest.identity,
        "population": manifest.population,
        "label_definition": manifest.label_definition,
        "metrics": classification_metrics(labels, scores, classes, score_semantics=score_semantics),
        "bootstrap": bootstrap_intervals(
            labels, scores, classes, repetitions=bootstrap_repetitions
        ),
        "excluded_records": len(manifest.records) - len(expected),
        "published_metrics_reproduced": False,
    }
