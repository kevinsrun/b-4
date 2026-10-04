"""Target-to-Bacteriocin Computational Design Pipeline.

Orchestrates hierarchical candidate selection and sequence optimization:
LEVEL 1 — Known Bacteriocins
LEVEL 2 — Natural Variants (homolog discovery)
LEVEL 3 — Computational Sequence Designs (bounded, conservative hypotheses)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from bacteriocin_lab.agents.candidate.knowledge import (
    KnowledgeSource,
    default_knowledge_source,
)
from bacteriocin_lab.agents.simulator import (
    CandidateSpec,
    Conditions,
    ExperimentSpec,
    Target,
    run_experiment,
)
from bacteriocin_lab.agents.variant import (
    FixtureAlignmentBackend,
    VariantDiscoveryAgent,
    mutate_sequence,
)

from .agent import ComputationalDesignAgent
from .config import (
    DEFAULT_KNOWN_THRESHOLD,
    DEFAULT_NATURAL_THRESHOLD,
    MAX_DESIGN_GENERATIONS,
    MAX_DESIGNS_PER_GENERATION,
    MAX_MUTATIONS_PER_DESIGN,
    MAX_TOTAL_DESIGNS_PER_RUN,
)
from .models import (
    DesignedCandidate,
    DesiredProperties,
    FutureProductionConcept,
    RecommendationItem,
    TargetContext,
    TargetDesignResult,
)
from .scoring import compute_candidate_score

logger = logging.getLogger(__name__)

GRAM_POSITIVE_GENERA = {
    "listeria",
    "staphylococcus",
    "enterococcus",
    "bacillus",
    "clostridium",
    "streptococcus",
    "lactobacillus",
    "lactococcus",
    "micrococcus",
    "corynebacterium",
}

GRAM_NEGATIVE_GENERA = {
    "escherichia",
    "salmonella",
    "pseudomonas",
    "klebsiella",
    "acinetobacter",
    "campylobacter",
    "vibrio",
    "helicobacter",
    "enterobacter",
    "shigella",
}

# Curated natural homologs for deterministic offline replay
CURATED_HOMOLOGS: dict[str, list[dict[str, Any]]] = {
    "nisin A": [
        {
            "accession": "P29559",
            "sequence": "ITSISLCTPGCKTGALMGCNMKTATCHCSINVSK",
            "title": "Nisin Z (H27N)",
        },
        {
            "accession": "Q846A7",
            "sequence": "ITSISLCTPGCKTGALMGCNMKTATCHCSIRVSK",
            "title": "Nisin variant (H27R)",
        },
    ],
    "pediocin PA-1": [
        {
            "accession": "P36495",
            "sequence": "KYYGNGVTCGKNSCSVDWGKATTCIINNGAMAWATGGHQGNHKC",
            "title": "Pediocin Ach (H12N)",
        },
        {
            "accession": "Q48641",
            "sequence": "KYYGNGVTCGKHSCSVDWGKATTCIINNGAMSWATGGHQGNHKC",
            "title": "Pediocin homolog (A32S)",
        },
    ],
}


def normalize_target(
    target_organism: str | dict[str, Any], target_strain: str | None = None
) -> dict[str, Any]:
    """Normalize target organism name, parse strain if embedded, and infer Gram status."""
    if isinstance(target_organism, dict):
        org = target_organism.get("organism") or target_organism.get("species") or ""
        strain = target_organism.get("strain") or target_strain
        gram = target_organism.get("gram")
    else:
        org = str(target_organism)
        strain = target_strain
        gram = None

    # Replace underscores and collapse whitespace
    clean_org = re.sub(r"[_\s]+", " ", org).strip()

    # If strain wasn't provided explicitly, check if embedded in organism name
    # e.g. 'Listeria monocytogenes EGD-e'
    parts = clean_org.split()
    if len(parts) >= 3 and not strain:
        # Genus + species + strain
        clean_org = f"{parts[0]} {parts[1]}"
        strain = " ".join(parts[2:])
    elif len(parts) >= 2:
        # Standard genus species
        clean_org = f"{parts[0].capitalize()} {parts[1].lower()}"
    elif len(parts) == 1:
        clean_org = parts[0].capitalize()

    # Infer Gram status if not explicitly passed
    if not gram and parts:
        genus = parts[0].lower()
        if genus in GRAM_POSITIVE_GENERA:
            gram = "positive"
        elif genus in GRAM_NEGATIVE_GENERA:
            gram = "negative"
        else:
            gram = "positive"  # Default assumption for standard bacteriocin targets

    return {
        "organism": clean_org,
        "strain": strain,
        "gram": gram,
    }


def format_sequence_novelty(
    database: str = "nr",
    identity_percent: float = 0.0,
    coverage_percent: float | None = None,
    closest_hit: str | None = None,
) -> dict[str, Any]:
    """Format BLAST sequence novelty signal without uncalibrated biological claims."""
    return {
        "novelty_signal": "high sequence-novelty signal relative to searched databases",
        "database": database,
        "closest_hit": closest_hit,
        "identity_percent": identity_percent,
        "coverage_percent": coverage_percent,
        "search_parameters": {"program": "blastp", "matrix": "BLOSUM62"},
        "note": (
            "Absence of close homolog matches represents sequence novelty relative to searched "
            "databases only; it does NOT constitute proof of biological activity or validation."
        ),
    }


def design_for_target(
    target_organism: str | dict[str, Any],
    target_strain: str | None = None,
    context: TargetContext | dict[str, Any] | None = None,
    desired_properties: DesiredProperties | dict[str, Any] | None = None,
    max_known_candidates: int = 10,
    max_natural_variants: int = 10,
    max_designed_candidates: int = 10,
    seed: int | None = None,
    known_threshold: float = DEFAULT_KNOWN_THRESHOLD,
    natural_threshold: float = DEFAULT_NATURAL_THRESHOLD,
    knowledge_source: KnowledgeSource | None = None,
    homolog_data: dict[str, list[dict[str, Any]]] | None = None,
    alignment_backend: Any | None = None,
) -> TargetDesignResult:
    """Execute target-to-bacteriocin design with hierarchical escalation."""
    # 1. Normalize input parameters
    target_info = normalize_target(target_organism, target_strain)
    org_name = target_info["organism"]
    gram_status = target_info["gram"]

    if isinstance(context, dict):
        ctx = TargetContext(**context)
    elif isinstance(context, TargetContext):
        ctx = context
    else:
        ctx = TargetContext()

    if isinstance(desired_properties, dict):
        props = DesiredProperties(**desired_properties)
    elif isinstance(desired_properties, DesiredProperties):
        props = desired_properties
    else:
        props = DesiredProperties()

    ks = knowledge_source or default_knowledge_source()
    curated_homolog_map = homolog_data or CURATED_HOMOLOGS

    known_evaluated: list[dict[str, Any]] = []
    natural_evaluated: list[dict[str, Any]] = []
    designed_evaluated: list[DesignedCandidate] = []
    recommendation_items: list[RecommendationItem] = []

    # ------------------------------------------------------------------
    # LEVEL 1: KNOWN BACTERIOCINS
    # ------------------------------------------------------------------
    known_records = list(ks.records())

    for rec in known_records:
        if not rec.sequence:
            continue

        cid = rec.name.lower().replace(" ", "_").replace("-", "_")
        spec = ExperimentSpec(
            experiment_id=f"exp_{cid}",
            hypothesis_id=f"hyp_{cid}",
            candidate_id=cid,
            target=Target(species=org_name, gram=gram_status or "positive"),
            conditions=Conditions(
                assay_type="growth_inhibition",
                ph=ctx.ph,
                temperature_c=ctx.temperature_c,
                target_cell_density=ctx.target_cell_density,
                bacteriocin_concentration=ctx.bacteriocin_concentration,
            ),
            candidate=CandidateSpec(
                candidate_id=cid,
                name=rec.name,
                sequence=rec.sequence,
                bacteriocin_class=rec.bacteriocin_class,
            ),
        )

        sim_res = run_experiment(spec)
        pred_inh = getattr(sim_res.measurement, "predicted_inhibition_fraction", 0.5)
        pred_log10 = getattr(sim_res.measurement, "predicted_log10_reduction_vs_control", 1.0)
        confidence = getattr(sim_res, "confidence", 0.5)

        total_score, score_components = compute_candidate_score(
            predicted_inhibition=pred_inh,
            predicted_log10_reduction=pred_log10,
            confidence=confidence,
            target_organism=org_name,
            target_gram=gram_status,
            candidate_class=rec.bacteriocin_class,
            known_targets=rec.known_targets,
            tier="known",
            has_evidence=True,
            evidence_count=len(rec.known_targets or []) * 2 + 5,
            target_cell_density=ctx.target_cell_density,
        )

        cand_data = {
            "candidate_id": cid,
            "name": rec.name,
            "sequence": rec.sequence,
            "bacteriocin_class": rec.bacteriocin_class,
            "tier": "known",
            "score": total_score,
            "components": score_components.to_dict(),
            "provenance": "literature-derived",
            "experimentally_validated": bool(rec.sequence_verified),
            "evidence_count": len(rec.known_targets or []) * 2 + 5,
            "known_targets": rec.known_targets or [],
            "simulation_metrics": {
                "predicted_inhibition": round(pred_inh, 5),
                "predicted_log10_reduction": round(pred_log10, 4),
                "predicted_mic_um": round(getattr(sim_res.measurement, "predicted_mic_um", 1.0), 4),
                "confidence": confidence,
            },
        }
        known_evaluated.append(cand_data)

    known_evaluated.sort(key=lambda c: c["score"], reverse=True)
    top_known = known_evaluated[0] if known_evaluated else None

    # Check Level 1 stopping condition (CASE A: known candidate works well)
    known_satisfies = (
        top_known is not None
        and top_known["score"] >= known_threshold
        and props.prefer_known_bacteriocins
    )

    if top_known:
        recommendation_items.append(
            RecommendationItem(
                tier="known",
                name=top_known["name"],
                score=top_known["score"],
                predicted_inhibition=top_known["simulation_metrics"]["predicted_inhibition"],
                confidence="high"
                if top_known["simulation_metrics"]["confidence"] >= 0.5
                else "moderate",
                evidence_count=top_known.get("evidence_count", 5),
                experimentally_validated=top_known["experimentally_validated"],
                candidate_id=top_known["candidate_id"],
            )
        )

    # ------------------------------------------------------------------
    # LEVEL 2: NATURAL VARIANTS
    # ------------------------------------------------------------------
    top_natural = None
    if not known_satisfies and top_known:
        parent_name = top_known["name"]
        parent_seq = top_known["sequence"]
        parent_cid = top_known["candidate_id"]
        parent_cls = top_known["bacteriocin_class"]

        homologs = curated_homolog_map.get(parent_name, [])
        if homologs:
            variant_agent = VariantDiscoveryAgent(
                alignment_backend=alignment_backend or FixtureAlignmentBackend()
            )
            discovery_res = variant_agent.discover(
                candidate_id=parent_cid,
                sequence=parent_seq,
                homologs=homologs,
                max_variants=max_natural_variants,
            )

            for var in discovery_res.variants:
                mutated_seq = mutate_sequence(parent_seq, var)
                var_cid = f"{parent_cid}_{var.protein_change}"

                spec = ExperimentSpec(
                    experiment_id=f"exp_{var_cid}",
                    hypothesis_id=f"hyp_{var_cid}",
                    candidate_id=var_cid,
                    target=Target(species=org_name, gram=gram_status or "positive"),
                    conditions=Conditions(
                        assay_type="growth_inhibition",
                        ph=ctx.ph,
                        temperature_c=ctx.temperature_c,
                        target_cell_density=ctx.target_cell_density,
                        bacteriocin_concentration=ctx.bacteriocin_concentration,
                    ),
                    candidate=CandidateSpec(
                        candidate_id=var_cid,
                        name=f"{parent_name} {var.protein_change}",
                        sequence=mutated_seq,
                        bacteriocin_class=parent_cls,
                    ),
                )

                sim_res = run_experiment(spec)
                pred_inh = getattr(sim_res.measurement, "predicted_inhibition_fraction", 0.5)
                pred_log10 = getattr(
                    sim_res.measurement, "predicted_log10_reduction_vs_control", 1.0
                )
                confidence = getattr(sim_res, "confidence", 0.5)

                total_score, score_components = compute_candidate_score(
                    predicted_inhibition=pred_inh,
                    predicted_log10_reduction=pred_log10,
                    confidence=confidence,
                    target_organism=org_name,
                    target_gram=gram_status,
                    candidate_class=parent_cls,
                    known_targets=top_known.get("known_targets", []),
                    tier="natural_variant",
                    has_evidence=True,
                    evidence_count=len(var.source_accessions),
                    has_homolog_support=True,
                    target_cell_density=ctx.target_cell_density,
                )

                nat_cand = {
                    "candidate_id": var_cid,
                    "parent_candidate_id": parent_cid,
                    "name": f"{parent_name} {var.protein_change}",
                    "sequence": mutated_seq,
                    "source": "natural_variant",
                    "mutation": var.protein_change,
                    "protein_position": var.protein_position,
                    "reference_aa": var.reference_aa,
                    "alternate_aa": var.alternate_aa,
                    "observed_accessions": var.source_accessions,
                    "tier": "natural_variant",
                    "score": total_score,
                    "components": score_components.to_dict(),
                    "provenance": "database-derived",
                    "experimentally_validated": False,
                    "simulation_metrics": {
                        "predicted_inhibition": round(pred_inh, 5),
                        "predicted_log10_reduction": round(pred_log10, 4),
                        "predicted_mic_um": round(
                            getattr(sim_res.measurement, "predicted_mic_um", 1.0), 4
                        ),
                        "confidence": confidence,
                    },
                }
                natural_evaluated.append(nat_cand)

            natural_evaluated.sort(key=lambda c: c["score"], reverse=True)
            top_natural = natural_evaluated[0] if natural_evaluated else None

            if top_natural:
                recommendation_items.append(
                    RecommendationItem(
                        tier="natural_variant",
                        name=top_natural["name"],
                        score=top_natural["score"],
                        predicted_inhibition=top_natural["simulation_metrics"][
                            "predicted_inhibition"
                        ],
                        confidence="moderate",
                        evidence_count=len(top_natural.get("observed_accessions", [])),
                        experimentally_validated=False,
                        candidate_id=top_natural["candidate_id"],
                        mutations=[top_natural["mutation"]],
                    )
                )

    # Check Level 2 stopping condition (CASE B: natural variant satisfies criteria)
    natural_satisfies = top_natural is not None and top_natural["score"] >= natural_threshold

    # ------------------------------------------------------------------
    # LEVEL 3: COMPUTATIONAL DESIGN
    # ------------------------------------------------------------------
    if not known_satisfies and not natural_satisfies and top_known:
        # CASE C: Escalate to computational sequence design
        parent_cid = top_known["candidate_id"]
        parent_seq = top_known["sequence"]
        parent_cls = top_known["bacteriocin_class"]

        designer = ComputationalDesignAgent(
            seed=seed,
            max_generations=MAX_DESIGN_GENERATIONS,
            designs_per_generation=min(max_designed_candidates, MAX_DESIGNS_PER_GENERATION),
            max_total_designs=MAX_TOTAL_DESIGNS_PER_RUN,
            max_mutations_per_design=MAX_MUTATIONS_PER_DESIGN,
        )

        designed_candidates = designer.design_variants(
            parent_candidate_id=parent_cid,
            parent_sequence=parent_seq,
            parent_class=parent_cls,
            target_organism=org_name,
            target_gram=gram_status,
            context=ctx,
            desired_properties=props,
        )
        designed_evaluated.extend(designed_candidates)

        if designed_evaluated:
            top_designed = designed_evaluated[0]
            recommendation_items.append(
                RecommendationItem(
                    tier="computational_design",
                    name=f"Design {top_designed.candidate_id}",
                    score=top_designed.score,
                    predicted_inhibition=top_designed.simulation_metrics.get(
                        "predicted_inhibition", 0.5
                    ),
                    confidence="moderate",
                    experimentally_validated=False,
                    candidate_id=top_designed.candidate_id,
                    mutations=[
                        f"{m.reference}{m.position}{m.alternate}" for m in top_designed.mutations
                    ],
                )
            )

    # Determine best overall candidate
    all_candidates: list[dict[str, Any]] = []
    for k in known_evaluated:
        all_candidates.append(k)
    for n in natural_evaluated:
        all_candidates.append(n)
    for d in designed_evaluated:
        all_candidates.append(
            {
                "candidate_id": d.candidate_id,
                "name": f"Design {d.candidate_id}",
                "sequence": d.sequence,
                "tier": "computational_design",
                "score": d.score,
                "provenance": d.provenance,
                "experimentally_validated": d.experimentally_validated,
                "simulation_metrics": d.simulation_metrics,
                "critic_verdict": d.critic_verdict,
                "mutations": [f"{m.reference}{m.position}{m.alternate}" for m in d.mutations],
            }
        )

    all_candidates.sort(key=lambda c: c["score"], reverse=True)
    best_candidate = all_candidates[0] if all_candidates else None

    # Determine recommended next experiment
    rec_exp: dict[str, Any] = {}
    if best_candidate:
        cand_id = best_candidate["candidate_id"]
        pred_mic = best_candidate.get("simulation_metrics", {}).get("predicted_mic_um", 1.0)
        rec_exp = {
            "experiment_type": "concentration_sweep_simulation",
            "candidate_id": cand_id,
            "target": target_info,
            "purpose": (
                f"Computational dose-response sweep across 0.25x to 4x predicted MIC "
                f"({pred_mic:.2f} uM) under {ctx.ph:.1f} pH and "
                f"{ctx.target_cell_density:.1e} CFU/mL to refine inhibition curve."
            ),
            "suggested_concentrations_um": [
                round(pred_mic * factor, 3) for factor in [0.25, 0.5, 1.0, 2.0, 4.0]
            ],
            "recommended_assay": "growth_inhibition",
        }

    # Safety: Non-operational future production concept
    future_concept = FutureProductionConcept(
        status="requires_specialist_review",
        candidate_peptide=best_candidate["sequence"] if best_candidate else "",
        producer_compatibility="possible"
        if top_known and "lactic" in top_known.get("name", "").lower()
        else "unknown",
        notes=[
            "Organism engineering and recombinant expression are out of scope.",
            "Candidate peptide requires specialist biosafety and wet-lab experimental "
            "review before expression testing.",
            "This is a non-operational future-validation concept only.",
        ],
    )

    limitations = [
        "All predictions are simulation-derived hypotheses and have not been validated in a lab.",
        "Simulator uses coarse, uncalibrated priors; predicted MIC may vary from experiments.",
        "Candidate sequence proposals explore computational space and do not guarantee efficacy.",
    ]

    uncertainties = [
        f"Cell density scaling sensitivity at {ctx.target_cell_density:.1e} CFU/mL.",
        "Peptide degradation and stability kinetics in real target matrices.",
    ]

    return TargetDesignResult(
        target=target_info,
        known_candidates=known_evaluated[:max_known_candidates],
        natural_variant_candidates=natural_evaluated[:max_natural_variants],
        designed_candidates=designed_evaluated[:max_designed_candidates],
        best_current_candidate=best_candidate,
        evidence_summary={
            "literature_candidates_screened": len(known_evaluated),
            "natural_variants_identified": len(natural_evaluated),
            "computational_designs_generated": len(designed_evaluated),
        },
        uncertainties=uncertainties,
        recommended_next_experiment=rec_exp,
        limitations=limitations,
        provenance={
            "agent": "target_to_bacteriocin_designer",
            "model_version": "designer/0.1.0",
            "simulator_backend": "standard",
            "seed": seed,
        },
        recommendations=recommendation_items,
        future_production_concept=future_concept,
    )
