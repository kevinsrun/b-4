from __future__ import annotations

import csv
import json
import logging
import math
import statistics
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

from bacteriocin_lab.agents.evidence.ncbi.blast import (
    clear_blast_cache,
    is_executable_available,
    normalize_protein_sequence,
)
from bacteriocin_lab.agents.evidence.ncbi.config import NCBIConfig
from bacteriocin_lab.agents.evidence.ncbi.local_blast import resolve_local_db

logger = logging.getLogger("benchmarks.latency")

BENCHMARK_DIR = Path(__file__).resolve().parent.parent
SEEDS_FILE = BENCHMARK_DIR / "seeds" / "bacteriocins.csv"
FIXTURES_FILE = BENCHMARK_DIR / "fixtures" / "homolog_search_fixtures.json"


def load_seed_queries(limit: int = 15) -> list[dict[str, str]]:
    queries: list[dict[str, str]] = []
    if not SEEDS_FILE.exists():
        return queries
    with SEEDS_FILE.open(mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or row.get("candidate_id") or "").strip()
            seq = (row.get("reference_sequence") or row.get("sequence") or "").strip()
            if name and seq:
                queries.append({"name": name, "sequence": seq})
            if len(queries) >= limit:
                break
    return queries


def compute_latency_stats(durations_ms: list[float]) -> dict[str, float]:
    """Compute distribution statistics for a list of duration measurements in milliseconds."""
    if not durations_ms:
        return {
            "count": 0,
            "min_ms": 0.0,
            "max_ms": 0.0,
            "mean_ms": 0.0,
            "median_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
        }

    s = sorted(durations_ms)
    n = len(s)
    mean_val = statistics.mean(s)
    med_val = statistics.median(s)

    # 95th percentile with linear interpolation
    k = (n - 1) * 0.95
    f = math.floor(k)
    c = math.ceil(k)
    p95_val = s[f] if f == c else s[f] + (k - f) * (s[c] - s[f])

    return {
        "count": n,
        "min_ms": round(s[0], 3),
        "max_ms": round(s[-1], 3),
        "mean_ms": round(mean_val, 3),
        "median_ms": round(med_val, 3),
        "p50_ms": round(med_val, 3),
        "p95_ms": round(p95_val, 3),
    }


def run_latency_benchmark(
    offline: bool = True,
    num_queries: int = 15,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute search latency and caching performance benchmark.

    Measures:
    - Cold-cache query latency (hashing, input validation, execution/mock dispatch)
    - Warm-cache query latency (in-memory hash hit)
    - Statistical distribution: min, max, mean, median (p50), p95
    - Measured warm-vs-cold cache speedup factor
    - Local vs remote backend availability detection

    Args:
        offline: If True, uses deterministic fixture dispatch to avoid external network calls.
        num_queries: Number of seed sequences to evaluate (10-20).

    Returns:
        tuple (summary_metrics_dict, detailed_csv_rows)
    """
    queries = load_seed_queries(limit=num_queries)
    cfg = NCBIConfig()

    local_exe_found = is_executable_available(cfg.blastp_executable)
    local_db_path = resolve_local_db("swissprot", cfg)
    local_available = local_exe_found and (local_db_path is not None)

    # Load fixture data for offline mode
    fixture_data: dict[str, list[dict[str, Any]]] = {}
    if FIXTURES_FILE.exists():
        with FIXTURES_FILE.open(mode="r", encoding="utf-8") as f:
            fixture_data = json.load(f)

    # Import blastp and mocked dispatch
    from bacteriocin_lab.agents.evidence.ncbi import blast as blast_module

    cold_durations: list[float] = []
    warm_durations: list[float] = []
    csv_rows: list[dict[str, Any]] = []

    # Reset cache before cold pass
    clear_blast_cache()

    def mock_remote_blastp(
        self: Any, sequence: str, database: str = "swissprot", **kwargs: Any
    ) -> dict[str, Any]:
        cid = kwargs.get("candidate_id") or "query"
        hits = fixture_data.get(cid, [])
        return {
            "candidate_id": cid,
            "query_id": "query",
            "database": database,
            "status": "complete",
            "hits": hits,
            "duration_ms": 12.5,
            "backend_used": "remote_fixture",
            "provenance": "database-derived",
        }

    # Execute Cold-Cache Pass
    patcher = (
        patch.object(blast_module.RemoteNcbiBlastBackend, "blastp", mock_remote_blastp)
        if offline
        else None
    )

    if patcher:
        patcher.start()

    try:
        for q in queries:
            name = q["name"]
            seq = q["sequence"]
            norm_seq = normalize_protein_sequence(seq)

            # Cold pass
            start_cold = time.perf_counter()
            res_cold = blast_module.blastp(
                sequence=norm_seq,
                database="swissprot",
                candidate_id=name,
                backend="auto",
                use_cache=True,
            )
            cold_ms = (time.perf_counter() - start_cold) * 1000.0
            cold_durations.append(cold_ms)

            csv_rows.append(
                {
                    "benchmark": "latency_search",
                    "item_id": name,
                    "cache_state": "cold",
                    "seq_len": len(norm_seq),
                    "duration_ms": round(cold_ms, 3),
                    "backend_used": res_cold.get("backend_used", "auto"),
                    "hit_count": len(res_cold.get("hits", [])),
                }
            )

        # Execute Warm-Cache Pass
        for q in queries:
            name = q["name"]
            seq = q["sequence"]
            norm_seq = normalize_protein_sequence(seq)

            start_warm = time.perf_counter()
            res_warm = blast_module.blastp(
                sequence=norm_seq,
                database="swissprot",
                candidate_id=name,
                backend="auto",
                use_cache=True,
            )
            warm_ms = (time.perf_counter() - start_warm) * 1000.0
            warm_durations.append(warm_ms)

            csv_rows.append(
                {
                    "benchmark": "latency_search",
                    "item_id": name,
                    "cache_state": "warm",
                    "seq_len": len(norm_seq),
                    "duration_ms": round(warm_ms, 3),
                    "backend_used": res_warm.get("backend_used", "cached"),
                    "hit_count": len(res_warm.get("hits", [])),
                }
            )
    finally:
        if patcher:
            patcher.stop()

    cold_stats = compute_latency_stats(cold_durations)
    warm_stats = compute_latency_stats(warm_durations)

    # Measured speedup factor
    med_cold = max(cold_stats["median_ms"], 0.001)
    med_warm = max(warm_stats["median_ms"], 0.0001)
    speedup = round(med_cold / med_warm, 2)

    summary = {
        "queries_evaluated": len(queries),
        "execution_mode": "offline_fixture" if offline else "live_network",
        "local_blastp_executable_available": local_exe_found,
        "local_database_available": local_available,
        "cold_cache_latency_ms": cold_stats,
        "warm_cache_latency_ms": warm_stats,
        "measured_cache_speedup_factor": speedup,
        "provenance": "database-derived",
    }

    return summary, csv_rows
