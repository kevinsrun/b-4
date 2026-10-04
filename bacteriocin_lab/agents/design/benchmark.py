"""Benchmark suite for target-to-bacteriocin design pipeline.

Measures:
1. Known-target recovery rate
2. Natural-variant ranking quality
3. Designed candidate improvement under simulator
   (with uncertainty, evidence quality, modifications, critic verdict)
4. Experiments/designs needed to reach decision
5. Adaptive vs static sequence search efficiency
"""

from __future__ import annotations

import logging
from typing import Any

from .agent import ComputationalDesignAgent
from .models import DesiredProperties, TargetContext
from .pipeline import design_for_target

logger = logging.getLogger(__name__)


def run_target_design_benchmarks(seed: int = 42) -> dict[str, Any]:
    """Execute all 5 target design benchmarks and return structured report."""
    results: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 1. Known-target recovery
    # ------------------------------------------------------------------
    targets_to_test = [
        {
            "species": "Listeria monocytogenes",
            "expected_genus": "Listeria",
            "expected_top": ["pediocin PA-1", "nisin A"],
        },
        {
            "species": "Escherichia coli",
            "expected_genus": "Escherichia",
            "expected_top": ["microcin J25"],
        },
    ]

    recovery_hits = 0
    recovery_details = []
    for t in targets_to_test:
        res = design_for_target(t["species"], seed=seed)
        top_name = res.best_current_candidate["name"] if res.best_current_candidate else ""
        hit = any(exp.lower() in top_name.lower() for exp in t["expected_top"])
        if hit:
            recovery_hits += 1
        recovery_details.append(
            {
                "target": t["species"],
                "top_candidate": top_name,
                "recovered": hit,
            }
        )

    results["known_target_recovery"] = {
        "score": recovery_hits / len(targets_to_test),
        "total_targets_tested": len(targets_to_test),
        "details": recovery_details,
    }

    # ------------------------------------------------------------------
    # 2. Natural-variant ranking
    # ------------------------------------------------------------------
    # Check that natural variants retain database-derived provenance and rank reasonably
    nat_res = design_for_target(
        "Listeria monocytogenes",
        known_threshold=0.95,
        natural_threshold=0.75,
        seed=seed,
    )
    nat_vars = nat_res.natural_variant_candidates
    valid_provenance = all(v.get("provenance") == "database-derived" for v in nat_vars)
    has_accessions = all(len(v.get("observed_accessions", [])) > 0 for v in nat_vars)

    results["natural_variant_ranking"] = {
        "variants_discovered": len(nat_vars),
        "valid_provenance": valid_provenance,
        "has_accessions": has_accessions,
        "top_variant": nat_vars[0]["name"] if nat_vars else None,
        "top_variant_score": nat_vars[0]["score"] if nat_vars else 0.0,
    }

    # ------------------------------------------------------------------
    # 3. Designed candidate improvement under simulator
    # ------------------------------------------------------------------
    # Test under high cell density (1e8)
    high_density_ctx = TargetContext(target_cell_density=1e8, ph=6.5)
    des_res = design_for_target(
        "Listeria monocytogenes",
        context=high_density_ctx,
        desired_properties=DesiredProperties(high_density_activity=True),
        known_threshold=0.99,
        natural_threshold=0.99,
        seed=seed,
    )

    designed = des_res.designed_candidates
    top_des = designed[0] if designed else None

    results["designed_candidate_improvement"] = {
        "candidate_id": top_des.candidate_id if top_des else None,
        "score": top_des.score if top_des else 0.0,
        "predicted_inhibition": top_des.simulation_metrics.get("predicted_inhibition", 0.0)
        if top_des
        else 0.0,
        "predicted_log10_reduction": top_des.simulation_metrics.get(
            "predicted_log10_reduction", 0.0
        )
        if top_des
        else 0.0,
        "uncertainty": top_des.uncertainty if top_des else {},
        "evidence_quality": top_des.components.get("evidence_quality", 0.0) if top_des else 0.0,
        "number_of_modifications": len(top_des.mutations) if top_des else 0,
        "critic_verdict": top_des.critic_verdict if top_des else "none",
    }

    # ------------------------------------------------------------------
    # 4. Experiments / designs needed to reach decision
    # ------------------------------------------------------------------
    total_designs = len(designed)
    results["experiments_needed_to_reach_decision"] = {
        "designs_evaluated": total_designs,
        "generations_completed": max([c.generation for c in designed], default=0),
        "decision_reached": top_des is not None,
        "recommended_tier": des_res.recommendations[0].tier if des_res.recommendations else None,
    }

    # ------------------------------------------------------------------
    # 5. Adaptive vs static sequence search
    # ------------------------------------------------------------------
    # Compare multi-generation adaptive agent with a single static generation
    adaptive_agent = ComputationalDesignAgent(
        seed=seed, max_generations=2, designs_per_generation=5, max_total_designs=10
    )
    static_agent = ComputationalDesignAgent(
        seed=seed, max_generations=1, designs_per_generation=10, max_total_designs=10
    )

    parent_seq = "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK"
    adapt_designs = adaptive_agent.design_variants(
        parent_candidate_id="nisin_a",
        parent_sequence=parent_seq,
        parent_class="class_i",
        target_organism="Listeria monocytogenes",
        context=high_density_ctx,
    )

    static_designs = static_agent.design_variants(
        parent_candidate_id="nisin_a",
        parent_sequence=parent_seq,
        parent_class="class_i",
        target_organism="Listeria monocytogenes",
        context=high_density_ctx,
    )

    best_adapt_score = adapt_designs[0].score if adapt_designs else 0.0
    best_static_score = static_designs[0].score if static_designs else 0.0

    results["adaptive_vs_static_search"] = {
        "adaptive_best_score": best_adapt_score,
        "static_best_score": best_static_score,
        "adaptive_advantage": round(best_adapt_score - best_static_score, 4),
        "adaptive_generations": max([c.generation for c in adapt_designs], default=1),
        "static_generations": 1,
    }

    return results
