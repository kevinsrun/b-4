from __future__ import annotations

import logging
import time
from typing import Any

from bacteriocin_lab.agents.simulator.api import run_experiments
from bacteriocin_lab.agents.simulator.schemas import CandidateSpec, ExperimentSpec
from bacteriocin_lab.orchestration import ResearchObjective, run_discovery
from bacteriocin_lab.orchestration.registry import AgentRegistry

logger = logging.getLogger("benchmarks.adaptive")

STATIC_CANDIDATES = [
    ("nisin_a", "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK"),
    ("pediocin_pa1", "KYYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC"),
    ("sakacin_p", "KYYGNGVHCGKHSCTVDWGTAIGNIGNNAAANWATGGNAGWNK"),
    ("subtilin", "WKSESLCTPGCVTGALQTCFLQTLTCNCKISK"),
    ("microcin_j25", "GGAGHVPEYFVGIGTPISFYG"),
]

STATIC_DENSITIES = [1e6, 1e7, 1e8]
STATIC_DOSES = [1.0, 5.0, 20.0]


def run_adaptive_efficiency_benchmark() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute autonomous loop efficiency benchmark (Benchmark 5).

    Compares:
    1. Static Screening Baseline: Full factorial grid of 5 candidates x 3 densities x 3 doses
       (45 total experiments).
    2. Adaptive Omnigent Strategy: Closed-loop hypothesis-driven discovery running 2 iterations.

    Measures:
    - Experiment count comparison (static vs adaptive)
    - Experiment reduction factor (static_experiments / adaptive_experiments)
    - Wall-clock runtime and speedup factor
    - Scientific discovery output

    Returns:
        tuple (summary_metrics_dict, detailed_csv_rows)
    """
    csv_rows: list[dict[str, Any]] = []

    # 1. Run Static Screening Grid Baseline
    static_specs: list[ExperimentSpec] = []
    cand_reg = {
        cid: CandidateSpec(candidate_id=cid, sequence=seq) for cid, seq in STATIC_CANDIDATES
    }

    for cid, _ in STATIC_CANDIDATES:
        for dens in STATIC_DENSITIES:
            for dose in STATIC_DOSES:
                static_specs.append(
                    ExperimentSpec(
                        experiment_id=f"static_{cid}_{int(dens)}_{int(dose)}",
                        candidate_id=cid,
                        target_organism="Listeria monocytogenes",
                        target_cell_density=dens,
                        peptide_concentration_um=dose,
                        ph=7.0,
                        temperature_c=37.0,
                        incubation_time_h=16.0,
                        assay_type="broth_microdilution",
                    )
                )

    start_static = time.perf_counter()
    static_results = run_experiments(static_specs, candidate_registry=cand_reg)
    static_duration_ms = (time.perf_counter() - start_static) * 1000.0

    csv_rows.append(
        {
            "benchmark": "loop_efficiency",
            "strategy": "static_screening_grid",
            "experiment_count": len(static_results),
            "duration_ms": round(static_duration_ms, 2),
            "iterations": 1,
            "reduction_factor": 1.0,
            "wall_clock_speedup": 1.0,
            "provenance": "simulation-derived",
        }
    )

    # 2. Run Adaptive Omnigent Discovery Loop
    obj = ResearchObjective(
        goal="Find a bacteriocin active against Listeria monocytogenes under high cell density.",
        target={"species": "Listeria monocytogenes", "gram": "positive"},
        desired_behavior={"target_cell_density": 1e8},
        constraints={"max_candidates": 3},
    )

    start_adaptive = time.perf_counter()
    discovery_res = run_discovery(
        objective=obj,
        registry=AgentRegistry.real(),
        max_iterations=2,
    )
    adaptive_duration_ms = (time.perf_counter() - start_adaptive) * 1000.0

    adaptive_exp_count = len(discovery_res.final_state.get("experiments", []))
    reduction_factor = round(len(static_results) / max(adaptive_exp_count, 1), 2)
    speedup = round(static_duration_ms / max(adaptive_duration_ms, 0.001), 2)

    csv_rows.append(
        {
            "benchmark": "loop_efficiency",
            "strategy": "adaptive_omnigent_loop",
            "experiment_count": adaptive_exp_count,
            "duration_ms": round(adaptive_duration_ms, 2),
            "iterations": discovery_res.iterations_completed,
            "reduction_factor": reduction_factor,
            "wall_clock_speedup": speedup,
            "provenance": "simulation-derived",
        }
    )

    summary = {
        "static_screening_experiments": len(static_results),
        "static_screening_duration_ms": round(static_duration_ms, 2),
        "adaptive_loop_experiments": adaptive_exp_count,
        "adaptive_loop_duration_ms": round(adaptive_duration_ms, 2),
        "experiment_reduction_factor": reduction_factor,
        "wall_clock_speedup": speedup,
        "loop_status": discovery_res.status,
        "findings_count": len(discovery_res.final_state.get("findings", [])),
        "provenance": "simulation-derived",
    }

    return summary, csv_rows


def run_decision_adaptivity_benchmark() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute decision adaptivity benchmark (Benchmark 6).

    Evaluates:
    - Sequential turn adaptation: Trial A evaluates Candidate 1 in turn 1,
      then selects a DIFFERENT candidate or adapted condition for turn 2.
    - Objective-driven candidate selection: Gram-positive vs Gram-negative targets
      drive completely divergent initial candidate selections.
    - Verified adaptivity conditions.

    Returns:
        tuple (summary_metrics_dict, detailed_csv_rows)
    """
    csv_rows: list[dict[str, Any]] = []

    # Run Campaign 1: Gram-positive Listeria monocytogenes
    obj_listeria = ResearchObjective(
        goal="Discover a bacteriocin active against Listeria monocytogenes.",
        target={"species": "Listeria monocytogenes", "gram": "positive"},
        desired_behavior={"target_cell_density": 1e8},
        constraints={"max_candidates": 3},
    )
    res_listeria = run_discovery(
        objective=obj_listeria,
        registry=AgentRegistry.real(),
        max_iterations=2,
    )
    exps_listeria = res_listeria.final_state.get("experiments", [])

    # Run Campaign 2: Gram-negative Escherichia coli
    obj_ecoli = ResearchObjective(
        goal="Discover a bacteriocin active against Escherichia coli.",
        target={"species": "Escherichia coli", "gram": "negative"},
        desired_behavior={"target_cell_density": 1e7},
        constraints={"max_candidates": 3},
    )
    res_ecoli = run_discovery(
        objective=obj_ecoli,
        registry=AgentRegistry.real(),
        max_iterations=2,
    )
    exps_ecoli = res_ecoli.final_state.get("experiments", [])

    # Verification checks
    within_campaign_adaptive = False
    if len(exps_listeria) >= 2:
        e1 = exps_listeria[0]
        e2 = exps_listeria[1]
        within_campaign_adaptive = (
            e1["experiment_id"] != e2["experiment_id"] and e1["candidate_id"] != e2["candidate_id"]
        )

    cross_target_adaptive = False
    if exps_listeria and exps_ecoli:
        cross_target_adaptive = (
            exps_listeria[0]["candidate_id"] != exps_ecoli[0]["candidate_id"]
            or exps_listeria[0]["conditions"] != exps_ecoli[0]["conditions"]
        )

    all_adaptive = within_campaign_adaptive and cross_target_adaptive

    csv_rows.append(
        {
            "benchmark": "decision_adaptivity",
            "campaign": "listeria_monocytogenes",
            "turn_1_candidate": exps_listeria[0]["candidate_id"] if exps_listeria else "none",
            "turn_2_candidate": exps_listeria[1]["candidate_id"]
            if len(exps_listeria) > 1
            else "none",
            "turn_1_density": exps_listeria[0]["conditions"].get("target_cell_density")
            if exps_listeria
            else None,
            "within_campaign_adapted": within_campaign_adaptive,
        }
    )

    csv_rows.append(
        {
            "benchmark": "decision_adaptivity",
            "campaign": "escherichia_coli",
            "turn_1_candidate": exps_ecoli[0]["candidate_id"] if exps_ecoli else "none",
            "turn_2_candidate": exps_ecoli[1]["candidate_id"] if len(exps_ecoli) > 1 else "none",
            "turn_1_density": exps_ecoli[0]["conditions"].get("target_cell_density")
            if exps_ecoli
            else None,
            "within_campaign_adapted": len(exps_ecoli) >= 2
            and exps_ecoli[0]["candidate_id"] != exps_ecoli[1]["candidate_id"],
        }
    )

    summary = {
        "listeria_campaign_experiments": len(exps_listeria),
        "ecoli_campaign_experiments": len(exps_ecoli),
        "within_campaign_adaptation_verified": within_campaign_adaptive,
        "cross_target_adaptation_verified": cross_target_adaptive,
        "overall_adaptivity_verified": all_adaptive,
        "provenance": "simulation-derived",
    }

    return summary, csv_rows
