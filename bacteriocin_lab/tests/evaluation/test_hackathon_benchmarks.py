from __future__ import annotations

import json

from benchmarks.run_hackathon_benchmarks import run_benchmarks, write_results


def test_hackathon_benchmarks_are_bounded_and_writeable(tmp_path) -> None:
    report = run_benchmarks()
    adaptive = report["adaptive_vs_static"]
    assert adaptive["adaptive_experiment_count"] == 2
    assert adaptive["static_experiment_count"] == 6
    assert adaptive["experiment_reduction_factor"] == 3.0
    assert adaptive["iteration_2_changed"] is True
    assert adaptive["state_integrity"] == "PASS"
    assert report["homolog_retrieval"]["self_hits_excluded"] is True
    assert report["homolog_retrieval"]["recall_at_1"] == 1.0
    assert report["synthetic_variant_accuracy"]["substitution_precision"] == 1.0
    assert report["synthetic_variant_accuracy"]["indel_recall"] == 1.0

    json_path, csv_path, markdown_path = write_results(report, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["schema_version"] == 1
    assert "experiment_reduction_factor" in csv_path.read_text(encoding="utf-8")
    assert "Hackathon benchmark summary" in markdown_path.read_text(encoding="utf-8")
