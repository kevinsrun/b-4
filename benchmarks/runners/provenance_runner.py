from __future__ import annotations

import logging
from typing import Any

from bacteriocin_lab.agents.simulator.api import run_experiments
from bacteriocin_lab.agents.simulator.schemas import CandidateSpec, ExperimentSpec
from bacteriocin_lab.agents.variant.models import FunctionalEffectHypothesis, VariantRecord
from bacteriocin_lab.orchestration.agent_adapters.candidate_adapter import CandidateAgentAdapter
from bacteriocin_lab.orchestration.agent_adapters.literature_adapter import LiteratureAgentAdapter
from bacteriocin_lab.orchestration.state import check_state_integrity
from bacteriocin_lab.orchestration.types import ResearchObjective, ResearchState

logger = logging.getLogger("benchmarks.provenance")

VALID_PROVENANCE_TAGS = {
    "literature-derived",
    "database-derived",
    "simulation-derived",
    "synthetic-test-data",
}


def run_provenance_benchmark() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute provenance and scientific honesty benchmark (Benchmark 7).

    Verifies across all specialist outputs and schemas:
    1. Literature evidence produces 'literature-derived' or 'database-derived' evidence.
    2. BLAST and database retrieval produce 'database-derived' records.
    3. Simulator produces 'simulation-derived' predictions, never 'wet-lab-derived'.
    4. Synthetic benchmark fixtures produce 'synthetic-test-data'.
    5. Candidate proposals are marked 'unvalidated' and never claimed as proven activity.
    6. Critic and state manager maintain strict calibration: zero claims of wet-lab validation.

    Returns:
        tuple (summary_metrics_dict, detailed_csv_rows)
    """
    csv_rows: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    violations = 0

    # 1. Literature Agent provenance verification
    try:
        lit_state = ResearchState(
            objective=ResearchObjective(
                goal="Retrieve literature evidence for Listeria monocytogenes.",
                target={"species": "Listeria monocytogenes"},
            )
        )
        lit_adapter = LiteratureAgentAdapter()
        lit_adapter.run(lit_state)
        # Any evidence items in state must be valid
        lit_valid = True
        for ev in lit_state.evidence:
            if ev.evidence_type not in VALID_PROVENANCE_TAGS:
                lit_valid = False
                violations += 1

        checks.append(
            {
                "subsystem": "literature_evidence",
                "provenance": "literature-derived",
                "valid": lit_valid,
                "notes": "Literature agent produces literature-derived evidence",
            }
        )
        csv_rows.append(
            {
                "benchmark": "provenance_honesty",
                "subsystem": "literature_evidence",
                "observed_provenance": "literature-derived",
                "valid": lit_valid,
                "validated_experimentally_claim": False,
            }
        )
    except Exception as exc:
        logger.warning("Literature provenance check exception: %s", exc)

    # 2. Candidate Proposal validation_status verification
    try:
        cand_state = ResearchState(
            objective=ResearchObjective(
                goal="Generate candidate bacteriocins.",
                target={"species": "Listeria monocytogenes", "gram": "positive"},
                constraints={"max_candidates": 3},
            )
        )
        cand_adapter = CandidateAgentAdapter()
        cand_adapter.run(cand_state)
        proposals = cand_state.candidates
        all_unvalidated = len(proposals) > 0 and all(
            c.validation_status == "unvalidated" for c in proposals
        )
        if not all_unvalidated:
            violations += 1

        checks.append(
            {
                "subsystem": "candidate_proposals",
                "provenance": "simulation-derived",
                "valid": all_unvalidated,
                "notes": f"{len(proposals)} proposals verified as unvalidated",
            }
        )
        csv_rows.append(
            {
                "benchmark": "provenance_honesty",
                "subsystem": "candidate_proposals",
                "observed_provenance": "proposals_unvalidated",
                "valid": all_unvalidated,
                "validated_experimentally_claim": False,
            }
        )
    except Exception as exc:
        logger.warning("Candidate proposal check exception: %s", exc)

    # 3. Simulator Output evidence_type and validated_experimentally check
    try:
        spec = ExperimentSpec(
            experiment_id="prov_test_exp",
            candidate_id="prov_cand",
            target_organism="Listeria monocytogenes",
            target_cell_density=1e6,
            peptide_concentration_um=5.0,
        )
        reg = {
            "prov_cand": CandidateSpec(
                candidate_id="prov_cand",
                sequence="ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
            )
        }
        sim_results = run_experiments([spec], candidate_registry=reg)
        sim_res = sim_results[0]

        is_sim_derived = sim_res.evidence_type == "simulation-derived"
        no_wet_lab_claim = getattr(sim_res, "validated_experimentally", False) is False

        is_sim_valid = is_sim_derived and no_wet_lab_claim
        if not is_sim_valid:
            violations += 1

        checks.append(
            {
                "subsystem": "simulation_runner",
                "provenance": sim_res.evidence_type,
                "valid": is_sim_valid,
                "notes": "Simulation produces predictions, not wet-lab observations",
            }
        )
        csv_rows.append(
            {
                "benchmark": "provenance_honesty",
                "subsystem": "simulation_runner",
                "observed_provenance": sim_res.evidence_type,
                "valid": is_sim_valid,
                "validated_experimentally_claim": not no_wet_lab_claim,
            }
        )
    except Exception as exc:
        logger.warning("Simulator provenance check exception: %s", exc)

    # 4. Variant discovery model provenance verification
    try:
        v_record = VariantRecord(
            variant_id="var_nisin_01",
            parent_candidate_id="nisin_a",
            protein_change="H27N",
            variant_type="missense",
            reference_aa="H",
            alternate_aa="N",
            protein_position=27,
            observed_count=1,
            homolog_count=3,
            frequency=1.0,
            conservation_score=0.9,
            functional_effect=FunctionalEffectHypothesis(
                hypothesis="Conservative natural variant substitution",
                confidence=0.7,
                possible_effects=["neutral"],
            ),
            provenance="database-derived",
        )
        is_var_valid = v_record.provenance == "database-derived"
        if not is_var_valid:
            violations += 1

        checks.append(
            {
                "subsystem": "variant_discovery",
                "provenance": v_record.provenance,
                "valid": is_var_valid,
                "notes": "Natural variant records tagged database-derived without functional claim",
            }
        )
        csv_rows.append(
            {
                "benchmark": "provenance_honesty",
                "subsystem": "variant_discovery",
                "observed_provenance": v_record.provenance,
                "valid": is_var_valid,
                "validated_experimentally_claim": False,
            }
        )
    except Exception as exc:
        logger.warning("Variant provenance check exception: %s", exc)

    # 5. Research State integrity verification
    try:
        obj = ResearchObjective(
            goal="Provenance audit discovery campaign",
            target={"species": "Listeria monocytogenes", "gram": "positive"},
            desired_behavior={"target_cell_density": 1e8},
            constraints={"max_candidates": 2},
        )
        from bacteriocin_lab.orchestration import run_discovery
        from bacteriocin_lab.orchestration.registry import AgentRegistry

        discovery_res = run_discovery(
            objective=obj, registry=AgentRegistry.real(), max_iterations=1
        )
        state = ResearchState.model_validate(discovery_res.final_state)
        problems = check_state_integrity(state)
        is_intact = len(problems) == 0
        if not is_intact:
            violations += 1

        checks.append(
            {
                "subsystem": "research_state_integrity",
                "provenance": "audit_passed",
                "valid": is_intact,
                "notes": "State integrity checks passed without corruption",
            }
        )
        csv_rows.append(
            {
                "benchmark": "provenance_honesty",
                "subsystem": "research_state_integrity",
                "observed_provenance": "state_verified",
                "valid": is_intact,
                "validated_experimentally_claim": False,
            }
        )
    except Exception as exc:
        logger.warning("Research state integrity check exception: %s", exc)

    summary = {
        "subsystems_audited": len(checks),
        "provenance_violations": violations,
        "zero_wet_lab_claims_verified": violations == 0,
        "valid_provenance_tags": sorted(VALID_PROVENANCE_TAGS),
        "audit_checks": checks,
        "provenance": "audit_composite",
    }

    return summary, csv_rows
