from __future__ import annotations

import csv
import json
import logging
import time
from pathlib import Path
from typing import Any

from bacteriocin_lab.agents.variant.agent import VariantDiscoveryAgent
from bacteriocin_lab.agents.variant.alignment import AutoAlignmentBackend, FixtureAlignmentBackend

logger = logging.getLogger("benchmarks.natural")

BENCHMARK_DIR = Path(__file__).resolve().parent.parent
SEEDS_FILE = BENCHMARK_DIR / "seeds" / "bacteriocins.csv"
NATURAL_HOMOLOGS_FILE = BENCHMARK_DIR / "fixtures" / "natural_homologs.json"

DISCLAIMER = (
    "Scientifically grounded disclaimer: Natural variants identified from homolog alignment "
    "do NOT have proven functional activity or wet-lab validation. Identified variants reflect "
    "naturally occurring sequence divergence among homologous proteins and serve as prioritized "
    "candidates for downstream simulated screening."
)

TARGET_SEEDS = [
    "nisin_a",
    "pediocin_pa1",
    "sakacin_p",
    "subtilin",
    "microcin_j25",
]


def load_target_sequences(seeds_path: Path = SEEDS_FILE) -> dict[str, str]:
    """Load query sequences for the 5 target bacteriocins from seeds/bacteriocins.csv."""
    targets: dict[str, str] = {}
    if not seeds_path.exists():
        return targets
    with seeds_path.open(mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = (row.get("name") or row.get("candidate_id") or "").strip()
            seq = (row.get("reference_sequence") or row.get("sequence") or "").strip().upper()
            if cid in TARGET_SEEDS:
                targets[cid] = seq
    return targets


def load_natural_homologs(
    fixtures_path: Path = NATURAL_HOMOLOGS_FILE,
) -> dict[str, list[dict[str, Any]]]:
    if not fixtures_path.exists():
        return {}
    with fixtures_path.open(mode="r", encoding="utf-8") as f:
        return json.load(f)


def run_natural_variant_benchmark() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute natural variant discovery pipeline throughput and reproducibility benchmark.

    Evaluates:
    - 5 real bacteriocins (Nisin A, Pediocin PA-1, Sakacin P, Subtilin, Microcin J25)
    - Homolog retrieval count, alignment count, unique variant count
    - Pipeline runtime (latency in milliseconds)
    - Deterministic reproducibility (two consecutive passes yield identical variants)
    - Explicit non-validation disclaimer

    Returns:
        tuple (summary_metrics_dict, detailed_csv_rows)
    """
    target_seqs = load_target_sequences()
    homologs_map = load_natural_homologs()

    auto_aligner = AutoAlignmentBackend()
    aligner = auto_aligner if auto_aligner.is_available() else FixtureAlignmentBackend()
    agent = VariantDiscoveryAgent(alignment_backend=aligner)

    per_target_results: list[dict[str, Any]] = []
    csv_rows: list[dict[str, Any]] = []
    all_reproducible = True
    total_variants_found = 0
    latencies_ms: list[float] = []

    for target_id in TARGET_SEEDS:
        seq = target_seqs.get(target_id)
        if not seq:
            logger.warning("Missing seed sequence for target %s", target_id)
            continue

        homologs = homologs_map.get(target_id, [])

        # Pass 1: measure runtime and outcome
        start_t = time.perf_counter()
        res1 = agent.discover(candidate_id=target_id, sequence=seq, homologs=homologs)
        duration_ms = (time.perf_counter() - start_t) * 1000.0
        latencies_ms.append(duration_ms)

        # Pass 2: verify reproducibility
        res2 = agent.discover(candidate_id=target_id, sequence=seq, homologs=homologs)
        variants1 = [v.protein_change for v in res1.variants]
        variants2 = [v.protein_change for v in res2.variants]
        is_reproducible = variants1 == variants2
        if not is_reproducible:
            all_reproducible = False

        total_variants_found += len(res1.variants)

        target_summary = {
            "candidate_id": target_id,
            "sequence_length": len(seq),
            "homologs_retrieved": res1.homolog_count,
            "homologs_aligned": res1.aligned_homolog_count,
            "unique_variants_found": len(res1.variants),
            "variants": [
                {
                    "change": v.protein_change,
                    "type": v.variant_type,
                    "frequency": v.frequency,
                    "hypothesis": v.functional_effect.hypothesis,
                }
                for v in res1.variants
            ],
            "latency_ms": round(duration_ms, 2),
            "reproducible": is_reproducible,
        }
        per_target_results.append(target_summary)

        # CSV row per target summary
        csv_rows.append(
            {
                "benchmark": "natural_variant_throughput",
                "item_id": target_id,
                "seq_len": len(seq),
                "homologs_retrieved": res1.homolog_count,
                "homologs_aligned": res1.aligned_homolog_count,
                "variants_discovered": len(res1.variants),
                "latency_ms": round(duration_ms, 2),
                "reproducible": is_reproducible,
                "top_variant": res1.variants[0].protein_change if res1.variants else "none",
            }
        )

        # Also write rows for individual variants found
        for v in res1.variants:
            csv_rows.append(
                {
                    "benchmark": "natural_variant_detail",
                    "item_id": f"{target_id}:{v.protein_change}",
                    "seq_len": len(seq),
                    "homologs_retrieved": res1.homolog_count,
                    "homologs_aligned": res1.aligned_homolog_count,
                    "variants_discovered": 1,
                    "latency_ms": round(duration_ms, 2),
                    "reproducible": is_reproducible,
                    "top_variant": v.protein_change,
                }
            )

    mean_latency = sum(latencies_ms) / max(len(latencies_ms), 1)
    summary = {
        "targets_evaluated": len(per_target_results),
        "total_variants_discovered": total_variants_found,
        "mean_latency_ms": round(mean_latency, 2),
        "all_reproducible": all_reproducible,
        "provenance": "database-derived",
        "scientific_disclaimer": DISCLAIMER,
        "targets": per_target_results,
    }

    return summary, csv_rows
