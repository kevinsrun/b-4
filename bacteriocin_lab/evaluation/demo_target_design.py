"""Deterministic demo scenario for Target-to-Bacteriocin Computational Design.

Demonstrates:
Target: Listeria monocytogenes
Context: high cell density (1e8 CFU/mL)
Workflow:
1. Search evidence & knowledge base
2. Rank known bacteriocins
3. Check sequence homologs & natural variants
4. Evaluate known & natural candidates against high-density target
5. Propose bounded computational sequence hypotheses
6. Simulate candidate sequences under target conditions
7. Pass candidate through scientific critic review
8. Recommend top candidate with explicit score breakdown
9. Propose concrete computational follow-up experiment
"""

from __future__ import annotations

import sys

from bacteriocin_lab.agents.design import (
    DesiredProperties,
    TargetContext,
    design_for_target,
)


def run_target_design_demo() -> int:
    """Execute the canonical target-to-bacteriocin design demo."""
    print("=" * 75)
    print(" B-4 AUTONOMOUS BACTERIOCIN DISCOVERY LAB - TARGET DESIGN SYSTEM")
    print("=" * 75)

    target_organism = "Listeria monocytogenes"
    context = TargetContext(
        target_cell_density=1e8,
        ph=6.5,
        temperature_c=37.0,
        incubation_hours=24.0,
        bacteriocin_concentration=5.0,
    )
    desired = DesiredProperties(
        high_density_activity=True,
        broad_activity=False,
        prefer_known_bacteriocins=True,
    )

    print("\nUser Query: 'What bacterium do you want to target?'")
    print(f"Selected Target: {target_organism}")
    density_str = f"{context.target_cell_density:.1e}"
    print(f"Assay Context: high cell density ({density_str} CFU/mL), pH {context.ph}\n")

    print("SYSTEM EXECUTION:")
    print("  [1] Normalizing target input and determining Gram status...")
    print("  [2] Searching literature evidence & known bacteriocin records...")
    print("  [3] Simulating known candidates against target under specified conditions...")
    print("  [4] Evaluating known candidates: checking tolerance to high cell density...")
    print("  [5] Checking sequence homologs and natural sequence variation...")
    print("  [6] Simulating natural variants with actual amino-acid sequences...")
    print("  [7] Escalating to bounded computational sequence design (Generations 1..3)...")
    print("  [8] Simulating prospective designs and submitting to Scientific Critic...")
    print("  [9] Synthesizing multi-tier recommendation and next experiment proposal...\n")

    # Run design with seed for deterministic reproducibility
    # Using thresholds that exercise the full escalation flow under high cell density
    result = design_for_target(
        target_organism=target_organism,
        context=context,
        desired_properties=desired,
        known_threshold=0.92,
        natural_threshold=0.88,
        seed=42,
    )

    print("-" * 75)
    print("DESIGN SYSTEM RESULTS")
    print("-" * 75)
    print(f"Target: {result.target['organism']} (Gram: {result.target['gram']})")
    ev_count = result.evidence_summary["literature_candidates_screened"]
    print(f"Evidence Screened: {ev_count} known bacteriocins")
    print(f"Natural Variants Identified: {result.evidence_summary['natural_variants_identified']}")
    des_count = result.evidence_summary["computational_designs_generated"]
    print(f"Computational Designs Evaluated: {des_count}\n")

    print("Candidate Recommendations (Frontend Structured Items):")
    for r in result.recommendations:
        mut_str = f" [mutations: {', '.join(r.mutations)}]" if r.mutations else ""
        print(
            f"  * [{r.tier.upper()}] {r.name}: score={r.score:.4f}, "
            f"pred_inh={r.predicted_inhibition:.3f}, conf={r.confidence}{mut_str}"
        )

    best = result.best_current_candidate
    if best:
        print(f"\nRecommended Candidate: {best['name']} ({best['tier']})")
        print(f"  Sequence: {best['sequence']}")
        print(f"  Total Score: {best['score']:.4f}")
        print(f"  Provenance: {best.get('provenance', 'model-predicted')}")
        print(f"  Experimentally Validated: {best.get('experimentally_validated', False)}")
        if "critic_verdict" in best:
            print(f"  Scientific Critic Verdict: {best['critic_verdict']}")

    rec_exp = result.recommended_next_experiment
    if rec_exp:
        print("\nRecommended Next Computational Experiment:")
        print(f"  Type: {rec_exp.get('experiment_type')}")
        print(f"  Candidate ID: {rec_exp.get('candidate_id')}")
        print(f"  Purpose: {rec_exp.get('purpose')}")
        print(f"  Concentrations: {rec_exp.get('suggested_concentrations_um')} uM")

    print("\nBiological Safety & Limitations:")
    for note in result.future_production_concept.notes:
        print(f"  * {note}")

    print("\n" + "=" * 75)
    print(" DEMO COMPLETED SUCCESSFULLY")
    print("=" * 75)
    return 0


if __name__ == "__main__":
    sys.exit(run_target_design_demo())
