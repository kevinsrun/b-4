"""Measure the narrow, defensible performance claims used in the hackathon demo.

The harness deliberately uses small, versioned fixtures.  It does not call remote
NCBI services, train a model, or assert biological efficacy.  Timings measure the
post-candidate simulation decision segment: evidence/candidate selection is shared
setup and is excluded from both adaptive and static wall-clock figures.
"""

from __future__ import annotations

import csv
import json
import platform
import statistics
import time
from pathlib import Path
from typing import Any

from bacteriocin_lab.agents.candidate.features import sequence_similarity
from bacteriocin_lab.agents.evidence import LocalBlastBackend, NCBIConfig, blastp
from bacteriocin_lab.agents.simulator.api import run_experiments
from bacteriocin_lab.agents.simulator.schemas import CandidateSpec, ExperimentSpec
from bacteriocin_lab.agents.variant import extract_variants_from_alignment
from bacteriocin_lab.orchestration import ResearchObjective, run_discovery
from bacteriocin_lab.orchestration.registry import AgentRegistry
from bacteriocin_lab.orchestration.state import check_state_integrity
from bacteriocin_lab.orchestration.types import ResearchState

RESULTS_DIR = Path(__file__).resolve().parent / "results"
STATIC_PH_GRID = (5.0, 6.0, 7.0, 8.0, 9.0, 10.0)


def _objective() -> ResearchObjective:
    return ResearchObjective(
        goal=(
            "Identify the most promising bacteriocin candidate for suppressing high-density "
            "Listeria monocytogenes and determine the most informative next computational "
            "experiment."
        ),
        target={"species": "Listeria monocytogenes", "gram": "positive"},
        desired_behavior={"high_inhibition": True, "target_cell_density": 1e8, "ph": 7.0},
        constraints={"max_candidates": 1},
    )


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


def _adaptive_and_static() -> dict[str, Any]:
    """Compare two actual adaptive specs against a precommitted static pH grid.

    Stopping criterion, fixed before execution: an informational decision requires two
    reviewed simulated experiments and a condition change selected after the first critic
    review.  The static comparator must exhaust its six fixed pH conditions before applying
    the same criterion, so its grid cannot quietly inherit adaptive information.
    """
    started = time.perf_counter()
    run = run_discovery(
        objective=_objective(), max_iterations=2, registry=AgentRegistry.default(), seed=42
    )
    workflow_seconds = time.perf_counter() - started
    state = ResearchState.model_validate(run.final_state)
    if len(state.experiments) != 2 or len(state.results) != 2:
        raise RuntimeError("adaptive fixture did not produce exactly two completed experiments")
    if not state.candidates or not state.candidates[0].sequence:
        raise RuntimeError("adaptive fixture did not supply a sequence-bearing candidate")
    if check_state_integrity(state):
        raise RuntimeError("adaptive fixture failed state-integrity validation")

    candidate = state.candidates[0]
    registry = {
        candidate.candidate_id: CandidateSpec(
            candidate_id=candidate.candidate_id, name=candidate.name, sequence=candidate.sequence
        )
    }
    adaptive_specs = [
        ExperimentSpec.model_validate(spec.model_dump(mode="json")) for spec in state.experiments
    ]
    started = time.perf_counter()
    adaptive_results = run_experiments(adaptive_specs, candidate_registry=registry)
    adaptive_seconds = time.perf_counter() - started

    base = adaptive_specs[0]
    static_specs = [
        ExperimentSpec(
            experiment_id=f"static-ph-{str(ph).replace('.', '_')}",
            hypothesis_id=base.hypothesis_id,
            candidate_id=candidate.candidate_id,
            target=base.target,
            conditions={
                **base.conditions.model_dump(mode="json"),
                "ph": ph,
            },
            notes="Precommitted static benchmark grid; not an adaptive recommendation.",
        )
        for ph in STATIC_PH_GRID
    ]
    started = time.perf_counter()
    static_results = run_experiments(static_specs, candidate_registry=registry)
    static_seconds = time.perf_counter() - started

    if any(result.status != "ok" for result in [*adaptive_results, *static_results]):
        raise RuntimeError("benchmark simulator execution failed")
    adaptive_count, static_count = len(adaptive_results), len(static_results)
    return {
        "stopping_criterion": (
            "Two critic-reviewed simulations with the second condition changed after the "
            "first review; static exhausts a precommitted six-point pH grid."
        ),
        "comparison_scope": "post-candidate simulation decision segment only",
        "adaptive_experiment_count": adaptive_count,
        "static_experiment_count": static_count,
        "experiment_reduction_factor": round(static_count / adaptive_count, 3),
        "redundant_static_experiments": static_count - adaptive_count,
        "adaptive_wall_seconds": round(adaptive_seconds, 6),
        "static_wall_seconds": round(static_seconds, 6),
        "wall_clock_speedup": round(static_seconds / adaptive_seconds, 3)
        if adaptive_seconds
        else None,
        "adaptive_simulation_tool_calls": adaptive_count,
        "static_simulation_tool_calls": static_count,
        "adaptive_workflow_agent_calls": len(run.execution_trace),
        "workflow_wall_seconds": round(workflow_seconds, 6),
        "iteration_1_conditions": adaptive_specs[0].conditions.model_dump(mode="json"),
        "iteration_2_conditions": adaptive_specs[1].conditions.model_dump(mode="json"),
        "iteration_2_changed": adaptive_specs[0].conditions.ph != adaptive_specs[1].conditions.ph,
        "critic_verdicts": [review.status for review in state.reviews],
        "state_integrity": "PASS",
        "provenance": sorted({result.evidence_type.value for result in adaptive_results}),
    }


def _retrieval() -> dict[str, Any]:
    """Fixture-only known-family recovery, excluding each query's self hit."""
    families = [
        {
            "query": {
                "accession": "P0A3E0",
                "name": "Nisin A",
                "sequence": "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            },
            "expected": "P29559",
            "corpus": [
                {
                    "accession": "P0A3E0",
                    "name": "Nisin A",
                    "sequence": "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
                },
                {
                    "accession": "P29559",
                    "name": "Nisin Z",
                    "sequence": "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
                },
                {
                    "accession": "P0A3F0",
                    "name": "Pediocin fixture",
                    "sequence": "KYYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC",
                },
            ],
        },
        {
            "query": {
                "accession": "P0A3F0",
                "name": "Pediocin PA-1",
                "sequence": "KYYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC",
            },
            "expected": "P0A3F1",
            "corpus": [
                {
                    "accession": "P0A3F0",
                    "name": "Pediocin PA-1",
                    "sequence": "KYYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC",
                },
                {
                    "accession": "P0A3F1",
                    "name": "Pediocin AcH fixture",
                    "sequence": "KYYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHRC",
                },
                {
                    "accession": "P0A3E0",
                    "name": "Nisin fixture",
                    "sequence": "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
                },
            ],
        },
        {
            "query": {
                "accession": "Q00001",
                "name": "Leucocin fixture",
                "sequence": "MKKYSGNGVYCNNSKCWVNWGEAKENIIGIVISGWASGLAGM",
            },
            "expected": "Q00002",
            "corpus": [
                {
                    "accession": "Q00001",
                    "name": "Leucocin fixture",
                    "sequence": "MKKYSGNGVYCNNSKCWVNWGEAKENIIGIVISGWASGLAGM",
                },
                {
                    "accession": "Q00002",
                    "name": "Leucocin homolog fixture",
                    "sequence": "MKKYSGNGVYCNNSKCWVNWGEAKENIIGIVISGWASGLVGM",
                },
                {
                    "accession": "P0A3E0",
                    "name": "Nisin fixture",
                    "sequence": "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
                },
            ],
        },
    ]
    ranks: list[int | None] = []
    for family in families:
        query = family["query"]
        ranked = sorted(
            (item for item in family["corpus"] if item["accession"] != query["accession"]),
            key=lambda item: (
                -sequence_similarity(query["sequence"], item["sequence"]),
                item["accession"],
            ),
        )
        ranks.append(
            next(
                (
                    index + 1
                    for index, item in enumerate(ranked)
                    if item["accession"] == family["expected"]
                ),
                None,
            )
        )
    return {
        "fixture_queries": len(families),
        "self_hits_excluded": True,
        "metric": "family recovery with deterministic 3-mer Jaccard ranking",
        "recall_at_1": round(sum(rank is not None and rank <= 1 for rank in ranks) / len(ranks), 3),
        "recall_at_5": round(sum(rank is not None and rank <= 5 for rank in ranks) / len(ranks), 3),
        "recall_at_10": round(
            sum(rank is not None and rank <= 10 for rank in ranks) / len(ranks), 3
        ),
        "ranks": ranks,
    }


def _variant_accuracy() -> dict[str, Any]:
    fixtures = [
        ({"ref": "MKTVFLG", "hom": "MKTVYLG"}, {"F5Y": ("missense", 5, 1.0)}),
        ({"ref": "MKTVF--LG", "hom": "MKTVFQQLG"}, {"ins5QQ": ("insertion", 5, 1.0)}),
        ({"ref": "MKTVFLGKL", "hom": "MKTVF--KL"}, {"del6_7": ("deletion", 6, 1.0)}),
    ]
    expected: dict[str, tuple[str, int, float]] = {}
    observed: dict[str, tuple[str, int, float]] = {}
    for aligned, truth in fixtures:
        expected.update(truth)
        for variant in extract_variants_from_alignment("benchmark", aligned, reference_id="ref"):
            observed[variant.protein_change] = (
                variant.variant_type,
                variant.protein_position,
                variant.frequency,
            )
    matched = set(expected) & set(observed)
    substitutions = {name for name, values in expected.items() if values[0] == "missense"}
    indels = {name for name, values in expected.items() if values[0] in {"insertion", "deletion"}}
    observed_substitutions = {name for name, values in observed.items() if values[0] == "missense"}
    observed_indels = {
        name for name, values in observed.items() if values[0] in {"insertion", "deletion"}
    }
    coordinate_ok = sum(observed[name][1] == expected[name][1] for name in matched)
    frequency_ok = sum(observed[name][2] == expected[name][2] for name in matched)
    return {
        "fixture_truth_count": len(expected),
        "substitution_precision": round(
            len(substitutions & observed_substitutions) / len(observed_substitutions), 3
        ),
        "substitution_recall": round(
            len(substitutions & observed_substitutions) / len(substitutions), 3
        ),
        "indel_precision": round(len(indels & observed_indels) / len(observed_indels), 3),
        "indel_recall": round(len(indels & observed_indels) / len(indels), 3),
        "coordinate_accuracy": round(coordinate_ok / len(expected), 3),
        "frequency_accuracy": round(frequency_ok / len(expected), 3),
        "observed_changes": sorted(observed),
    }


def _local_search_latency() -> dict[str, Any]:
    config = NCBIConfig.from_env()
    backend = LocalBlastBackend(config=config)
    database = config.blast_local_default_db or config.blast_local_bacteriocin_db or "bacteriocin"
    if not backend.is_available(database=database):
        return {
            "status": "unavailable",
            "database": database,
            "p50_seconds": None,
            "p95_seconds": None,
            "cold_seconds": None,
            "warm_seconds": None,
        }
    sequence = "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK"
    samples: list[float] = []
    for index in range(5):
        started = time.perf_counter()
        blastp(sequence, database=database, backend="local", candidate_id=f"latency-{index}")
        samples.append(time.perf_counter() - started)
    return {
        "status": "available",
        "database": database,
        "sample_count": len(samples),
        "cold_seconds": round(samples[0], 6),
        "warm_seconds": round(statistics.median(samples[1:]), 6),
        "p50_seconds": round(_quantile(samples, 0.50), 6),
        "p95_seconds": round(_quantile(samples, 0.95), 6),
    }


def run_benchmarks() -> dict[str, Any]:
    """Execute deterministic benchmark fixtures and return JSON-serializable measurements."""
    return {
        "schema_version": 1,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "adaptive_vs_static": _adaptive_and_static(),
        "homolog_retrieval": _retrieval(),
        "synthetic_variant_accuracy": _variant_accuracy(),
        "local_sequence_search_latency": _local_search_latency(),
        "remote_blast": {"status": "not_run", "reason": "outside bounded deterministic benchmark"},
        "limitations": [
            "All activity results are simulation-derived predictions, not wet-lab validation.",
            "Retrieval and variant metrics use compact deterministic fixtures for CI.",
            "Wall-clock values are host measurements and should not be generalized "
            "across machines.",
        ],
    }


def write_results(
    report: dict[str, Any], output_dir: Path = RESULTS_DIR
) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "benchmark_results.json"
    csv_path = output_dir / "benchmark_results.csv"
    markdown_path = output_dir / "benchmark_summary.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows = [
        (
            "adaptive_static",
            "static_experiments",
            report["adaptive_vs_static"]["static_experiment_count"],
        ),
        (
            "adaptive_static",
            "adaptive_experiments",
            report["adaptive_vs_static"]["adaptive_experiment_count"],
        ),
        (
            "adaptive_static",
            "experiment_reduction_factor",
            report["adaptive_vs_static"]["experiment_reduction_factor"],
        ),
        (
            "adaptive_static",
            "redundant_static_experiments",
            report["adaptive_vs_static"]["redundant_static_experiments"],
        ),
        (
            "adaptive_static",
            "static_wall_seconds",
            report["adaptive_vs_static"]["static_wall_seconds"],
        ),
        (
            "adaptive_static",
            "adaptive_wall_seconds",
            report["adaptive_vs_static"]["adaptive_wall_seconds"],
        ),
        (
            "adaptive_static",
            "wall_clock_speedup",
            report["adaptive_vs_static"]["wall_clock_speedup"],
        ),
        ("retrieval", "recall_at_1", report["homolog_retrieval"]["recall_at_1"]),
        ("retrieval", "recall_at_5", report["homolog_retrieval"]["recall_at_5"]),
        ("retrieval", "recall_at_10", report["homolog_retrieval"]["recall_at_10"]),
        (
            "variant",
            "substitution_precision",
            report["synthetic_variant_accuracy"]["substitution_precision"],
        ),
        (
            "variant",
            "substitution_recall",
            report["synthetic_variant_accuracy"]["substitution_recall"],
        ),
        ("variant", "indel_precision", report["synthetic_variant_accuracy"]["indel_precision"]),
        ("variant", "indel_recall", report["synthetic_variant_accuracy"]["indel_recall"]),
        ("local_search", "p50_seconds", report["local_sequence_search_latency"]["p50_seconds"]),
        ("local_search", "p95_seconds", report["local_sequence_search_latency"]["p95_seconds"]),
        ("local_search", "cold_seconds", report["local_sequence_search_latency"]["cold_seconds"]),
        ("local_search", "warm_seconds", report["local_sequence_search_latency"]["warm_seconds"]),
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["suite", "metric", "value"])
        writer.writerows(rows)
    adaptive = report["adaptive_vs_static"]
    retrieval = report["homolog_retrieval"]
    variant = report["synthetic_variant_accuracy"]
    local = report["local_sequence_search_latency"]
    retrieval_line = (
        f"| Recall@1 / @5 / @10 | {retrieval['recall_at_1']} / "
        f"{retrieval['recall_at_5']} / {retrieval['recall_at_10']} |\n"
    )
    substitution_line = (
        f"| Variant substitution precision / recall | "
        f"{variant['substitution_precision']} / {variant['substitution_recall']} |\n"
    )
    indel_line = (
        f"| Variant indel precision / recall | {variant['indel_precision']} / "
        f"{variant['indel_recall']} |\n"
    )
    markdown_path.write_text(
        "".join(
            [
                "# Hackathon benchmark summary\n\n",
                f"Stopping criterion: {adaptive['stopping_criterion']}\n\n",
                "| Measure | Result |\n|---|---:|\n",
                f"| Static experiments | {adaptive['static_experiment_count']} |\n",
                f"| Adaptive experiments | {adaptive['adaptive_experiment_count']} |\n",
                f"| Experiment reduction factor | {adaptive['experiment_reduction_factor']}x |\n",
                f"| Redundant static experiments | {adaptive['redundant_static_experiments']} |\n",
                f"| Static decision-segment runtime | {adaptive['static_wall_seconds']} s |\n",
                f"| Adaptive decision-segment runtime | {adaptive['adaptive_wall_seconds']} s |\n",
                f"| Wall-clock speedup (decision segment) | {adaptive['wall_clock_speedup']}x |\n",
                retrieval_line,
                substitution_line,
                indel_line,
                f"| Local sequence-search status | {local['status']} |\n\n",
                f"Local search p50 / p95 / cold / warm (seconds): {local['p50_seconds']} / ",
                f"{local['p95_seconds']} / {local['cold_seconds']} / {local['warm_seconds']}.\n\n",
                "All biological activity results remain simulation-derived predictions; ",
                "no wet-lab efficacy is claimed.\n",
            ]
        ),
        encoding="utf-8",
    )
    return json_path, csv_path, markdown_path


if __name__ == "__main__":
    write_results(run_benchmarks())
