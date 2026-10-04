from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("benchmarks.homolog")

BENCHMARK_DIR = Path(__file__).resolve().parent.parent
SEEDS_FILE = BENCHMARK_DIR / "seeds" / "bacteriocins.csv"
EXPECTATIONS_FILE = BENCHMARK_DIR / "expected" / "homolog_expectations.json"
FIXTURES_FILE = BENCHMARK_DIR / "fixtures" / "homolog_search_fixtures.json"


def load_seeds(csv_path: Path = SEEDS_FILE) -> list[dict[str, str]]:
    seeds: list[dict[str, str]] = []
    if not csv_path.exists():
        return seeds
    with csv_path.open(mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            seeds.append(dict(row))
    return seeds


def load_expectations(json_path: Path = EXPECTATIONS_FILE) -> dict[str, Any]:
    if not json_path.exists():
        return {}
    with json_path.open(mode="r", encoding="utf-8") as f:
        return json.load(f)


def load_fixtures(json_path: Path = FIXTURES_FILE) -> dict[str, list[dict[str, Any]]]:
    if not json_path.exists():
        return {}
    with json_path.open(mode="r", encoding="utf-8") as f:
        return json.load(f)


def compute_recall_at_k(
    hits: list[dict[str, Any]],
    expected_accessions: list[str],
    k: int,
    query_accession: str | None = None,
) -> float:
    """Compute Recall@K against expected accessions.

    Excludes the query self-accession from the ranked list.
    """
    if not expected_accessions:
        return 1.0

    filtered_hits = [
        h for h in hits if str(h.get("accession", "")).upper() != str(query_accession or "").upper()
    ]
    top_k_accessions = {
        str(h.get("accession", "")).upper() for h in filtered_hits[:k] if h.get("accession")
    }

    expected_set = {str(acc).upper() for acc in expected_accessions}
    matched = expected_set.intersection(top_k_accessions)
    return len(matched) / len(expected_set)


def run_homolog_benchmark(
    live: bool = False,
    blast_backend: Any | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute homolog retrieval benchmark.

    Returns:
        tuple (summary_metrics_dict, detailed_csv_rows)
    """
    seeds = load_seeds()
    expectations = load_expectations()
    fixtures = load_fixtures()

    csv_rows: list[dict[str, Any]] = []
    per_seed_results: dict[str, Any] = {}

    recall_at_1_list: list[float] = []
    recall_at_5_list: list[float] = []
    recall_at_10_list: list[float] = []

    for seed in seeds:
        name = seed.get("name", "")
        if name not in expectations:
            continue

        exp = expectations[name]
        expected_accessions = exp.get("expected_family_accessions", [])
        query_acc = seed.get("accession", "")
        seq = seed.get("reference_sequence", "")

        hits: list[dict[str, Any]] = []
        if live and blast_backend is not None:
            try:
                res = blast_backend.blastp(sequence=seq, candidate_id=name)
                hits = res.get("hits", [])
            except Exception as exc:
                logger.warning("Live BLAST failed for seed %s: %s", name, exc)
                hits = fixtures.get(name, [])
        else:
            hits = fixtures.get(name, [])

        r1 = compute_recall_at_k(hits, expected_accessions, k=1, query_accession=query_acc)
        r5 = compute_recall_at_k(hits, expected_accessions, k=5, query_accession=query_acc)
        r10 = compute_recall_at_k(hits, expected_accessions, k=10, query_accession=query_acc)

        recall_at_1_list.append(r1)
        recall_at_5_list.append(r5)
        recall_at_10_list.append(r10)

        # Top non-self hit metrics
        non_self_hits = [
            h for h in hits if str(h.get("accession", "")).upper() != query_acc.upper()
        ]
        top_hit = non_self_hits[0] if non_self_hits else {}
        top_ident = top_hit.get("identity_percent", 0.0)
        top_cov = top_hit.get("coverage_percent", 0.0)
        top_eval = top_hit.get("evalue", None)

        all_hit_accessions = {str(h.get("accession", "")).upper() for h in hits}
        recovered_count = sum(
            1 for acc in expected_accessions if str(acc).upper() in all_hit_accessions
        )

        detail = {
            "seed_name": name,
            "seed_accession": query_acc,
            "expected_count": len(expected_accessions),
            "recovered_count": recovered_count,
            "recall_at_1": round(r1, 4),
            "recall_at_5": round(r5, 4),
            "recall_at_10": round(r10, 4),
            "top_hit_accession": top_hit.get("accession", ""),
            "top_hit_identity": top_ident,
            "top_hit_coverage": top_cov,
            "top_hit_evalue": top_eval,
            "category": exp.get("category", "unknown"),
        }
        per_seed_results[name] = detail

        csv_rows.append(
            {
                "benchmark": "homolog_retrieval",
                "item_id": name,
                "accession": query_acc,
                "metric_recall_at_1": detail["recall_at_1"],
                "metric_recall_at_5": detail["recall_at_5"],
                "metric_recall_at_10": detail["recall_at_10"],
                "metric_top_hit_identity": top_ident,
                "metric_top_hit_coverage": top_cov,
                "metric_top_hit_evalue": top_eval,
                "metric_recovered_ratio": (
                    f"{recovered_count}/{len(expected_accessions)}"
                    if expected_accessions
                    else "0/0"
                ),
            }
        )

    n = max(len(recall_at_1_list), 1)
    summary = {
        "seeds_evaluated": len(recall_at_1_list),
        "mean_recall_at_1": round(sum(recall_at_1_list) / n, 4),
        "mean_recall_at_5": round(sum(recall_at_5_list) / n, 4),
        "mean_recall_at_10": round(sum(recall_at_10_list) / n, 4),
        "provenance": "database-derived",
        "details": per_seed_results,
    }

    return summary, csv_rows
