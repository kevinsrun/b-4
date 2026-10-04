from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from benchmarks.run_all import main as run_all_main
from benchmarks.runners.adaptive_runner import (
    run_adaptive_efficiency_benchmark,
    run_decision_adaptivity_benchmark,
)
from benchmarks.runners.homolog_runner import (
    EXPECTATIONS_FILE,
    SEEDS_FILE,
    compute_recall_at_k,
    load_expectations,
    load_seeds,
    run_homolog_benchmark,
)
from benchmarks.runners.latency_runner import compute_latency_stats, run_latency_benchmark
from benchmarks.runners.natural_runner import DISCLAIMER, run_natural_variant_benchmark
from benchmarks.runners.provenance_runner import run_provenance_benchmark
from benchmarks.runners.variant_runner import (
    CDS_FASTA,
    EXPECTED_VARIANTS_FILE,
    PROT_FASTA,
    load_expected_variants,
    load_fasta_sequences,
    run_variant_benchmark,
)


# 1. Seeds file integrity
def test_01_seeds_file_validity():
    assert SEEDS_FILE.exists(), f"Seeds file missing at {SEEDS_FILE}"
    seeds = load_seeds(SEEDS_FILE)
    assert len(seeds) >= 25, f"Expected at least 25 seeds, got {len(seeds)}"
    for row in seeds:
        assert row.get("name"), "Seed row missing name"
        assert row.get("reference_sequence"), f"Seed {row.get('name')} missing sequence"
        assert row.get("accession"), f"Seed {row.get('name')} missing accession"
        assert row.get("family_class"), f"Seed {row.get('name')} missing family_class"


# 2. Homolog expectations integrity
def test_02_homolog_expectations_validity():
    assert EXPECTATIONS_FILE.exists()
    expectations = load_expectations(EXPECTATIONS_FILE)
    assert len(expectations) >= 10
    assert "nisin_a" in expectations
    assert "pediocin_pa1" in expectations
    nisin_exp = expectations["nisin_a"]
    assert "expected_family_accessions" in nisin_exp
    assert len(nisin_exp["expected_family_accessions"]) >= 3


# 3. Recall@K calculation logic (including query self-accession exclusion)
def test_03_compute_recall_at_k():
    hits = [
        {"accession": "SELF_ACC", "identity_percent": 100.0},
        {"accession": "ACC_1", "identity_percent": 90.0},
        {"accession": "ACC_2", "identity_percent": 85.0},
        {"accession": "ACC_3", "identity_percent": 80.0},
    ]
    expected = ["ACC_1", "ACC_2", "ACC_4"]

    # When query_accession='SELF_ACC', self hit is excluded
    r1 = compute_recall_at_k(hits, expected, k=1, query_accession="SELF_ACC")
    # Top 1 hit is ACC_1, which matches 1 of 3 expected -> recall = 1/3
    assert round(r1, 4) == round(1.0 / 3.0, 4)

    r2 = compute_recall_at_k(hits, expected, k=2, query_accession="SELF_ACC")
    # Top 2 hits are ACC_1 and ACC_2 -> recall = 2/3
    assert round(r2, 4) == round(2.0 / 3.0, 4)

    # Empty expected returns 1.0
    assert compute_recall_at_k(hits, [], k=5) == 1.0


# 4. Homolog runner smoke test
def test_04_homolog_benchmark_runner():
    summary, rows = run_homolog_benchmark(live=False)
    assert summary["seeds_evaluated"] >= 10
    assert summary["mean_recall_at_5"] >= 0.70
    assert summary["provenance"] == "database-derived"
    assert len(rows) >= 10
    assert rows[0]["benchmark"] == "homolog_retrieval"


# 5. Synthetic FASTA fixtures integrity
def test_05_synthetic_alignment_fixtures():
    assert PROT_FASTA.exists()
    assert CDS_FASTA.exists()
    prot_seqs = load_fasta_sequences(PROT_FASTA)
    cds_seqs = load_fasta_sequences(CDS_FASTA)

    assert "ref" in prot_seqs
    assert "ref" in cds_seqs
    # All aligned protein sequences must have identical length
    lengths = {len(s) for s in prot_seqs.values()}
    assert len(lengths) == 1, f"Inconsistent protein alignment lengths: {lengths}"


# 6. Variant benchmark runner (precision, recall, gold standard match)
def test_06_variant_benchmark_runner():
    summary, rows = run_variant_benchmark()
    assert summary["total_expected_variants"] == 10
    assert summary["substitution_precision"] == 1.0
    assert summary["substitution_recall"] == 1.0
    assert summary["indel_precision"] == 1.0
    assert summary["indel_recall"] == 1.0
    assert summary["coordinate_accuracy"] == 1.0
    assert summary["provenance"] == "synthetic-test-data"
    assert len(rows) >= 10


# 7. Coordinate accuracy and gap mapping
def test_07_variant_coordinate_accuracy():
    exp_variants = load_expected_variants(EXPECTED_VARIANTS_FILE)
    assert len(exp_variants) == 10

    # Verify key mutation coordinates match exact biological 1-indexed numbering
    changes = {v["protein_change"]: v for v in exp_variants}
    assert "M1A" in changes
    assert changes["M1A"]["protein_position"] == 1

    assert "ins5QQ" in changes
    assert changes["ins5QQ"]["protein_position"] == 5

    assert "del8_9" in changes
    assert changes["del8_9"]["protein_position"] == 8

    assert "R13K" in changes
    assert changes["R13K"]["protein_position"] == 13


# 8. Natural variant discovery runner (5 targets, reproducibility, disclaimer)
def test_08_natural_variant_benchmark_runner():
    summary, rows = run_natural_variant_benchmark()
    assert summary["targets_evaluated"] == 5
    assert summary["total_variants_discovered"] > 0
    assert summary["all_reproducible"] is True
    assert summary["provenance"] == "database-derived"
    assert summary["scientific_disclaimer"] == DISCLAIMER
    assert len(rows) >= 5


# 9. Latency stats computation unit test
def test_09_compute_latency_stats():
    # Empty case
    empty_stats = compute_latency_stats([])
    assert empty_stats["count"] == 0
    assert empty_stats["median_ms"] == 0.0

    # Standard distribution
    data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    stats = compute_latency_stats(data)
    assert stats["count"] == 10
    assert stats["min_ms"] == 1.0
    assert stats["max_ms"] == 10.0
    assert stats["mean_ms"] == 5.5
    assert stats["median_ms"] == 5.5
    assert stats["p95_ms"] > 9.0


# 10. Latency benchmark runner smoke test
def test_10_latency_benchmark_runner():
    summary, rows = run_latency_benchmark(offline=True, num_queries=5)
    assert summary["queries_evaluated"] == 5
    assert summary["cold_cache_latency_ms"]["count"] == 5
    assert summary["warm_cache_latency_ms"]["count"] == 5
    assert summary["measured_cache_speedup_factor"] >= 0.5
    assert summary["provenance"] == "database-derived"
    assert len(rows) == 10  # 5 cold + 5 warm


# 11. Adaptive loop efficiency & decision adaptivity
def test_11_adaptive_runners():
    eff_summary, eff_rows = run_adaptive_efficiency_benchmark()
    assert eff_summary["static_screening_experiments"] == 45
    assert eff_summary["adaptive_loop_experiments"] >= 1
    assert eff_summary["experiment_reduction_factor"] > 1.0
    assert eff_summary["wall_clock_speedup"] > 1.0
    assert len(eff_rows) >= 2

    adapt_summary, adapt_rows = run_decision_adaptivity_benchmark()
    assert adapt_summary["within_campaign_adaptation_verified"] is True
    assert adapt_summary["cross_target_adaptation_verified"] is True
    assert adapt_summary["overall_adaptivity_verified"] is True
    assert len(adapt_rows) >= 2


# 12. Provenance & scientific honesty verification
def test_12_provenance_runner():
    summary, rows = run_provenance_benchmark()
    assert summary["subsystems_audited"] >= 4
    assert summary["provenance_violations"] == 0
    assert summary["zero_wet_lab_claims_verified"] is True
    assert len(rows) >= 4


# 13. CLI integration smoke test
def test_13_run_all_cli_integration(tmp_path: Path):
    test_args = [
        "benchmarks.run_all",
        "--offline",
        "--only",
        "variant,provenance",
        "--output-dir",
        str(tmp_path),
    ]
    with patch("sys.argv", test_args):
        rc = run_all_main()
        assert rc == 0

    json_file = tmp_path / "benchmark_results.json"
    csv_file = tmp_path / "benchmark_results.csv"
    md_file = tmp_path / "benchmark_summary.md"

    assert json_file.exists()
    assert csv_file.exists()
    assert md_file.exists()

    with json_file.open(mode="r", encoding="utf-8") as f:
        data = json.load(f)
        assert "variant_correctness" in data["benchmarks"]
        assert "provenance_honesty" in data["benchmarks"]
