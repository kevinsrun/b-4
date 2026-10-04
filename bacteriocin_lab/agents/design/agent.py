"""Computational design agent for bacteriocin sequence optimization."""

from __future__ import annotations

import logging
import random
from typing import Any

from bacteriocin_lab.agents.simulator import (
    CandidateSpec,
    Conditions,
    ExperimentSpec,
    Target,
    run_experiment,
)

from .config import (
    MAX_DESIGN_GENERATIONS,
    MAX_DESIGNS_PER_GENERATION,
    MAX_MUTATIONS_PER_DESIGN,
    MAX_TOTAL_DESIGNS_PER_RUN,
)
from .critic import DesignCritic
from .models import (
    DesignedCandidate,
    DesignMutation,
    DesignRationale,
    DesiredProperties,
    TargetContext,
)
from .scoring import compute_candidate_score

logger = logging.getLogger(__name__)

# Conservative amino-acid substitution groups (physicochemically similar)
CONSERVATIVE_PAIRS: dict[str, list[str]] = {
    "K": ["R"],
    "R": ["K"],
    "D": ["E"],
    "E": ["D"],
    "S": ["T", "A"],
    "T": ["S"],
    "N": ["Q"],
    "Q": ["N"],
    "I": ["L", "V"],
    "L": ["I", "V"],
    "V": ["I", "L", "A"],
    "A": ["V", "S"],
    "F": ["Y"],
    "Y": ["F"],
    "H": ["R", "K"],  # Protonated at acidic/neutral pH; can enhance cationic interaction
}


class ComputationalDesignAgent:
    """Agent that designs prospective bacteriocin sequence hypotheses via iterative optimization."""

    def __init__(
        self,
        critic: DesignCritic | None = None,
        seed: int | None = None,
        max_generations: int = MAX_DESIGN_GENERATIONS,
        designs_per_generation: int = MAX_DESIGNS_PER_GENERATION,
        max_total_designs: int = MAX_TOTAL_DESIGNS_PER_RUN,
        max_mutations_per_design: int = MAX_MUTATIONS_PER_DESIGN,
    ) -> None:
        self.critic = critic or DesignCritic()
        self.seed = seed
        self.max_generations = max_generations
        self.designs_per_generation = designs_per_generation
        self.max_total_designs = max_total_designs
        self.max_mutations_per_design = max_mutations_per_design
        self._rng = random.Random(seed)

    def _find_protected_positions(
        self,
        sequence: str,
        parent_class: str | None = None,
        user_conserved: list[int] | None = None,
    ) -> set[int]:
        """Find 1-indexed positions in sequence that must NOT be mutated."""
        protected: set[int] = set()

        # 1. Protect all Cysteines (structural disulfide / lanthionine bridges)
        for i, aa in enumerate(sequence, start=1):
            if aa == "C":
                protected.add(i)

        # 2. Protect Class IIa Pediocin Box (YGNGV / KYYGNGV)
        if parent_class == "class_iia" or "YGNGV" in sequence:
            motif = "KYYGNGV" if "KYYGNGV" in sequence else "YGNGV"
            idx = sequence.find(motif)
            if idx != -1:
                for pos in range(idx + 1, idx + 1 + len(motif)):
                    protected.add(pos)

        # 3. User-supplied or alignment-identified conserved positions
        if user_conserved:
            for pos in user_conserved:
                protected.add(pos)

        return protected

    def _apply_mutations(self, sequence: str, mutations: list[DesignMutation]) -> str:
        """Apply a list of mutations to an amino acid sequence."""
        seq_chars = list(sequence)
        for mut in mutations:
            idx = mut.position - 1
            if 0 <= idx < len(seq_chars):
                seq_chars[idx] = mut.alternate
        return "".join(seq_chars)

    def _simulate_and_evaluate(
        self,
        candidate_id: str,
        sequence: str,
        parent_candidate_id: str,
        mutations: list[DesignMutation],
        generation: int,
        target_organism: str,
        target_gram: str | None,
        parent_class: str,
        context: TargetContext,
        desired_properties: DesiredProperties,
        parent_sequence: str,
    ) -> DesignedCandidate:
        """Run simulation with actual candidate sequence and evaluate score and critique."""
        spec = ExperimentSpec(
            experiment_id=f"exp_{candidate_id}",
            hypothesis_id=f"hyp_{candidate_id}",
            candidate_id=candidate_id,
            target=Target(species=target_organism, gram=target_gram or "positive"),
            conditions=Conditions(
                assay_type="growth_inhibition",
                ph=context.ph,
                temperature_c=context.temperature_c,
                target_cell_density=context.target_cell_density,
                bacteriocin_concentration=context.bacteriocin_concentration,
            ),
            candidate=CandidateSpec(
                candidate_id=candidate_id,
                name=candidate_id,
                sequence=sequence,
                bacteriocin_class=parent_class,
            ),
        )

        sim_res = run_experiment(spec)
        pred_inh = getattr(sim_res.measurement, "predicted_inhibition_fraction", 0.5)
        pred_log10 = getattr(sim_res.measurement, "predicted_log10_reduction_vs_control", 1.0)
        confidence = getattr(sim_res, "confidence", 0.5)

        has_homolog_sup = any(m.origin == "natural_homolog" for m in mutations)
        is_conservative = all(
            m.origin in ("natural_homolog", "conservative_substitution") for m in mutations
        )

        total_score, components = compute_candidate_score(
            predicted_inhibition=pred_inh,
            predicted_log10_reduction=pred_log10,
            confidence=confidence,
            target_organism=target_organism,
            target_gram=target_gram,
            candidate_class=parent_class,
            known_targets=[target_organism],
            tier="computational_design",
            has_evidence=False,
            evidence_count=0,
            has_homolog_support=has_homolog_sup,
            target_cell_density=context.target_cell_density,
            has_motif_penalty=False,
            is_conservative=is_conservative,
        )

        rationale = DesignRationale(
            status="hypothesis",
            evidence_ids=[],
            natural_variant_support=[f"{m.reference}{m.position}{m.alternate}" for m in mutations],
            expected_properties=[
                f"predicted inhibition {pred_inh:.3f}",
                f"log10 reduction {pred_log10:.2f}",
                f"optimized for cell density {context.target_cell_density:.1e}",
            ],
        )

        cand = DesignedCandidate(
            candidate_id=candidate_id,
            parent_candidate_id=parent_candidate_id,
            sequence=sequence,
            mutations=mutations,
            design_class="conservative_variant",
            rationale=rationale,
            provenance="model-predicted",
            experimentally_validated=False,
            uncertainty={
                "confidence": confidence,
                "components": [c.source for c in getattr(sim_res, "uncertainty_components", [])],
            },
            score=total_score,
            components=components.to_dict(),
            generation=generation,
            simulation_metrics={
                "predicted_inhibition": round(pred_inh, 5),
                "predicted_log10_reduction": round(pred_log10, 4),
                "predicted_mic_um": round(getattr(sim_res.measurement, "predicted_mic_um", 1.0), 4),
            },
        )

        # Scientific critic gate
        verdict, notes = self.critic.review_candidate(
            cand, parent_class=parent_class, parent_sequence=parent_sequence
        )
        cand.critic_verdict = verdict
        cand.critic_notes = notes

        return cand

    def design_variants(
        self,
        parent_candidate_id: str,
        parent_sequence: str,
        parent_class: str,
        target_organism: str,
        target_gram: str | None = None,
        context: TargetContext | None = None,
        desired_properties: DesiredProperties | None = None,
        homolog_variants: list[Any] | None = None,
        conserved_positions: list[int] | None = None,
    ) -> list[DesignedCandidate]:
        """Propose and iteratively optimize bounded computational designs."""
        ctx = context or TargetContext()
        props = desired_properties or DesiredProperties()
        protected = self._find_protected_positions(
            parent_sequence, parent_class, conserved_positions
        )

        available_positions = [
            i for i, aa in enumerate(parent_sequence, start=1) if i not in protected
        ]
        if not available_positions:
            return []

        all_designed: list[DesignedCandidate] = []
        design_counter = 1

        # ------------------------------------------------------------------
        # GENERATION 1: Initial single-point conservative substitutions
        # ------------------------------------------------------------------
        gen1_mutation_pool: list[DesignMutation] = []

        # 1. Homolog-derived mutations if available
        if homolog_variants:
            for hv in homolog_variants:
                pos = getattr(hv, "protein_position", None)
                ref = getattr(hv, "reference_aa", None)
                alt = getattr(hv, "alternate_aa", None)
                if pos and ref and alt and pos not in protected:
                    accessions = getattr(hv, "source_accessions", [])
                    gen1_mutation_pool.append(
                        DesignMutation(
                            position=pos,
                            reference=ref,
                            alternate=alt,
                            origin="natural_homolog",
                            supporting_accessions=accessions,
                            rationale="Observed in natural homolog alignment",
                        )
                    )

        # 2. Conservative substitutions from amino acid groups
        # If high density activity is requested, prioritize basic substitutions (K, R)
        sorted_positions = list(available_positions)
        if self.seed is not None:
            self._rng.shuffle(sorted_positions)

        for pos in sorted_positions:
            ref_aa = parent_sequence[pos - 1]
            alts = CONSERVATIVE_PAIRS.get(ref_aa, [])
            for alt_aa in alts:
                gen1_mutation_pool.append(
                    DesignMutation(
                        position=pos,
                        reference=ref_aa,
                        alternate=alt_aa,
                        origin="conservative_substitution",
                        rationale=f"Conservative substitution {ref_aa}->{alt_aa}",
                    )
                )

        # Deduplicate pool while preserving order
        seen_muts: set[tuple[int, str, str]] = set()
        unique_pool: list[DesignMutation] = []
        for m in gen1_mutation_pool:
            key = (m.position, m.reference, m.alternate)
            if key not in seen_muts:
                seen_muts.add(key)
                unique_pool.append(m)

        # Limit to designs_per_generation
        gen1_selected = unique_pool[: self.designs_per_generation]
        gen1_candidates: list[DesignedCandidate] = []

        for mut in gen1_selected:
            if len(all_designed) >= self.max_total_designs:
                break
            cand_id = f"design_{parent_candidate_id}_g1_{design_counter:03d}"
            design_counter += 1
            seq = self._apply_mutations(parent_sequence, [mut])
            cand = self._simulate_and_evaluate(
                candidate_id=cand_id,
                sequence=seq,
                parent_candidate_id=parent_candidate_id,
                mutations=[mut],
                generation=1,
                target_organism=target_organism,
                target_gram=target_gram,
                parent_class=parent_class,
                context=ctx,
                desired_properties=props,
                parent_sequence=parent_sequence,
            )
            gen1_candidates.append(cand)
            all_designed.append(cand)

        if (
            not gen1_candidates
            or self.max_generations < 2
            or len(all_designed) >= self.max_total_designs
        ):
            all_designed.sort(key=lambda c: c.score, reverse=True)
            return all_designed

        # ------------------------------------------------------------------
        # GENERATION 2: Active optimization building on best Gen 1 result
        # ------------------------------------------------------------------
        # Sort Gen 1 by score to find top performer
        gen1_candidates.sort(key=lambda c: c.score, reverse=True)
        best_g1 = gen1_candidates[0]
        best_g1_mut = best_g1.mutations[0]

        gen2_candidates: list[DesignedCandidate] = []
        # Find secondary positions for 2-point mutations combining with best_g1_mut
        sec_positions = [p for p in available_positions if p != best_g1_mut.position]
        if self.seed is not None:
            self._rng.shuffle(sec_positions)

        for pos in sec_positions:
            if (
                len(all_designed) >= self.max_total_designs
                or len(gen2_candidates) >= self.designs_per_generation
            ):
                break
            ref_aa = parent_sequence[pos - 1]
            alts = CONSERVATIVE_PAIRS.get(ref_aa, [])
            if not alts:
                continue
            alt_aa = alts[0]
            anchor_str = f"{best_g1_mut.reference}{best_g1_mut.position}{best_g1_mut.alternate}"
            sec_mut = DesignMutation(
                position=pos,
                reference=ref_aa,
                alternate=alt_aa,
                origin="conservative_substitution",
                rationale=f"Secondary refinement combining with {anchor_str}",
            )
            combined_muts = [best_g1_mut, sec_mut]
            cand_id = f"design_{parent_candidate_id}_g2_{design_counter:03d}"
            design_counter += 1
            seq = self._apply_mutations(parent_sequence, combined_muts)
            cand = self._simulate_and_evaluate(
                candidate_id=cand_id,
                sequence=seq,
                parent_candidate_id=parent_candidate_id,
                mutations=combined_muts,
                generation=2,
                target_organism=target_organism,
                target_gram=target_gram,
                parent_class=parent_class,
                context=ctx,
                desired_properties=props,
                parent_sequence=parent_sequence,
            )
            gen2_candidates.append(cand)
            all_designed.append(cand)

        # ------------------------------------------------------------------
        # GENERATION 3: 3-point bounded mutations if budget and generations allow
        # ------------------------------------------------------------------
        if (
            gen2_candidates
            and self.max_generations >= 3
            and len(all_designed) < self.max_total_designs
        ):
            gen2_candidates.sort(key=lambda c: c.score, reverse=True)
            best_g2 = gen2_candidates[0]
            used_positions = {m.position for m in best_g2.mutations}
            ter_positions = [p for p in available_positions if p not in used_positions]
            if self.seed is not None:
                self._rng.shuffle(ter_positions)

            gen3_candidates: list[DesignedCandidate] = []
            for pos in ter_positions:
                if (
                    len(all_designed) >= self.max_total_designs
                    or len(gen3_candidates) >= self.designs_per_generation
                ):
                    break
                ref_aa = parent_sequence[pos - 1]
                alts = CONSERVATIVE_PAIRS.get(ref_aa, [])
                if not alts:
                    continue
                alt_aa = alts[0]
                ter_mut = DesignMutation(
                    position=pos,
                    reference=ref_aa,
                    alternate=alt_aa,
                    origin="conservative_substitution",
                    rationale="Tertiary bounded refinement",
                )
                three_muts = [*best_g2.mutations, ter_mut]
                cand_id = f"design_{parent_candidate_id}_g3_{design_counter:03d}"
                design_counter += 1
                seq = self._apply_mutations(parent_sequence, three_muts)
                cand = self._simulate_and_evaluate(
                    candidate_id=cand_id,
                    sequence=seq,
                    parent_candidate_id=parent_candidate_id,
                    mutations=three_muts,
                    generation=3,
                    target_organism=target_organism,
                    target_gram=target_gram,
                    parent_class=parent_class,
                    context=ctx,
                    desired_properties=props,
                    parent_sequence=parent_sequence,
                )
                gen3_candidates.append(cand)
                all_designed.append(cand)

        all_designed.sort(key=lambda c: c.score, reverse=True)
        return all_designed
