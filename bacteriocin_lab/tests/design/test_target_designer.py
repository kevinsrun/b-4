"""Hard test suite for Target-to-Bacteriocin Computational Design System.

Implements all 24 mandatory hard tests:
TEST 1  — target input normalization
TEST 2  — known candidate retrieval
TEST 3  — known candidate ranking
TEST 4  — natural variant integration
TEST 5  — known candidate stops unnecessary design escalation
TEST 6  — weak known candidate triggers natural search
TEST 7  — weak natural variants trigger computational design
TEST 8  — design mutation count bounded
TEST 9  — designed sequence correctly contains specified mutation
TEST 10 — conserved positions protected when constraints exist
TEST 11 — designed candidate provenance = model-predicted
TEST 12 — natural variant provenance = database-derived
TEST 13 — designed candidate never claims experimental validation
TEST 14 — simulator receives actual sequence
TEST 15 — first simulation changes second design batch
TEST 16 — critic can reject unsupported design
TEST 17 — no-hit BLAST does not become 'novel bacteriocin'
TEST 18 — design budget enforced
TEST 19 — reproducibility with fixed seed
TEST 20 — target conditions influence candidate ranking
TEST 21 — evidence changes ranking
TEST 22 — frontend response serializes cleanly
TEST 23 — no wet-lab/genetic-engineering instructions appear in result
TEST 24 — benchmark runner integration
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from bacteriocin_lab.agents.candidate.knowledge import default_knowledge_source
from bacteriocin_lab.agents.design import (
    MAX_DESIGN_GENERATIONS,
    MAX_MUTATIONS_PER_DESIGN,
    MAX_TOTAL_DESIGNS_PER_RUN,
    ComputationalDesignAgent,
    DesignCritic,
    DesignedCandidate,
    DesignMutation,
    TargetContext,
    compute_candidate_score,
    design_for_target,
    format_sequence_novelty,
    normalize_target,
)
from bacteriocin_lab.agents.design.benchmark import run_target_design_benchmarks
from bacteriocin_lab.agents.simulator import run_experiment


# ---------------------------------------------------------------------------
# TEST 1 — Target input normalization
# ---------------------------------------------------------------------------
def test_1_target_input_normalization() -> None:
    # 1. Standard genus species string
    t1 = normalize_target("Listeria monocytogenes")
    assert t1["organism"] == "Listeria monocytogenes"
    assert t1["gram"] == "positive"
    assert t1["strain"] is None

    # 2. Lowercase with underscore
    t2 = normalize_target("listeria_monocytogenes")
    assert t2["organism"] == "Listeria monocytogenes"
    assert t2["gram"] == "positive"

    # 3. Excess whitespace and uppercase
    t3 = normalize_target("   LISTERIA   MONOCYTOGENES   ")
    assert t3["organism"] == "Listeria monocytogenes"
    assert t3["gram"] == "positive"

    # 4. Embedded strain
    t4 = normalize_target("Listeria monocytogenes EGD-e")
    assert t4["organism"] == "Listeria monocytogenes"
    assert t4["strain"] == "EGD-e"
    assert t4["gram"] == "positive"

    # 5. Dictionary input
    t5 = normalize_target(
        {"organism": "Listeria monocytogenes", "strain": "10403S", "gram": "positive"}
    )
    assert t5["organism"] == "Listeria monocytogenes"
    assert t5["strain"] == "10403S"
    assert t5["gram"] == "positive"

    # 6. Gram-negative genus inference
    t6 = normalize_target("escherichia_coli")
    assert t6["organism"] == "Escherichia coli"
    assert t6["gram"] == "negative"


# ---------------------------------------------------------------------------
# TEST 2 — Known candidate retrieval
# ---------------------------------------------------------------------------
def test_2_known_candidate_retrieval() -> None:
    res = design_for_target("Listeria monocytogenes", seed=42)
    assert len(res.known_candidates) > 0
    candidate_names = [c["name"] for c in res.known_candidates]
    assert "pediocin PA-1" in candidate_names or "nisin A" in candidate_names


# ---------------------------------------------------------------------------
# TEST 3 — Known candidate ranking
# ---------------------------------------------------------------------------
def test_3_known_candidate_ranking() -> None:
    res = design_for_target("Listeria monocytogenes", seed=42)
    assert len(res.known_candidates) >= 2
    # Verify descending sort order by total score
    scores = [c["score"] for c in res.known_candidates]
    assert scores == sorted(scores, reverse=True)

    top_cand = res.known_candidates[0]
    assert "score" in top_cand
    assert "components" in top_cand
    comp = top_cand["components"]
    assert "predicted_activity" in comp
    assert "target_match" in comp
    assert "environmental_robustness" in comp
    assert "evidence_quality" in comp
    assert "uncertainty_penalty" in comp
    # Target-matching candidate should rank above mismatched candidate (e.g. microcin J25)
    microcin = next((c for c in res.known_candidates if "microcin" in c["name"].lower()), None)
    if microcin:
        assert top_cand["score"] > microcin["score"]


# ---------------------------------------------------------------------------
# TEST 4 — Natural variant integration
# ---------------------------------------------------------------------------
def test_4_natural_variant_integration() -> None:
    # Trigger Level 2 natural variant search by requiring higher threshold
    res = design_for_target(
        "Listeria monocytogenes",
        known_threshold=0.95,
        natural_threshold=0.75,
        seed=42,
    )
    assert len(res.natural_variant_candidates) > 0
    for var in res.natural_variant_candidates:
        assert var["provenance"] == "database-derived"
        assert var["experimentally_validated"] is False
        assert "mutation" in var
        assert len(var["sequence"]) > 0
        assert "simulation_metrics" in var


# ---------------------------------------------------------------------------
# TEST 5 — Known candidate stops unnecessary design escalation (CASE A)
# ---------------------------------------------------------------------------
def test_5_known_candidate_stops_unnecessary_design_escalation() -> None:
    # Default threshold (0.80): top known candidate (pediocin PA-1 ~0.87) satisfies criteria
    res = design_for_target(
        "Listeria monocytogenes",
        known_threshold=0.80,
        seed=42,
    )
    assert res.best_current_candidate is not None
    assert res.best_current_candidate["tier"] == "known"
    # No computational designs required
    assert len(res.designed_candidates) == 0


# ---------------------------------------------------------------------------
# TEST 6 — Weak known candidate triggers natural search (CASE B)
# ---------------------------------------------------------------------------
def test_6_weak_known_candidate_triggers_natural_search() -> None:
    # Set known threshold high enough that known candidates don't meet it,
    # but natural threshold low enough that natural variants satisfy it
    res = design_for_target(
        "Listeria monocytogenes",
        known_threshold=0.92,
        natural_threshold=0.80,
        seed=42,
    )
    assert len(res.natural_variant_candidates) > 0
    # Natural variant satisfies criteria; design escalation skipped
    assert len(res.designed_candidates) == 0
    assert any(rec.tier == "natural_variant" for rec in res.recommendations)


# ---------------------------------------------------------------------------
# TEST 7 — Weak natural variants trigger computational design (CASE C)
# ---------------------------------------------------------------------------
def test_7_weak_natural_variants_trigger_computational_design() -> None:
    # Known and natural candidates fail threshold -> Level 3 invoked
    res = design_for_target(
        "Listeria monocytogenes",
        known_threshold=0.95,
        natural_threshold=0.95,
        seed=42,
    )
    assert len(res.designed_candidates) > 0
    assert any(rec.tier == "computational_design" for rec in res.recommendations)


# ---------------------------------------------------------------------------
# TEST 8 — Design mutation count bounded
# ---------------------------------------------------------------------------
def test_8_design_mutation_count_bounded() -> None:
    res = design_for_target(
        "Listeria monocytogenes",
        known_threshold=0.95,
        natural_threshold=0.95,
        seed=42,
    )
    for cand in res.designed_candidates:
        assert 1 <= len(cand.mutations) <= MAX_MUTATIONS_PER_DESIGN


# ---------------------------------------------------------------------------
# TEST 9 — Designed sequence correctly contains specified mutation
# ---------------------------------------------------------------------------
def test_9_designed_sequence_contains_specified_mutation() -> None:
    res = design_for_target(
        "Listeria monocytogenes",
        known_threshold=0.95,
        natural_threshold=0.95,
        seed=42,
    )
    ks = default_knowledge_source()
    rec_map = {r.name.lower().replace(" ", "_").replace("-", "_"): r.sequence for r in ks.records()}

    for cand in res.designed_candidates:
        parent_seq = rec_map.get(cand.parent_candidate_id)
        if not parent_seq:
            continue
        for mut in cand.mutations:
            # 1-indexed position
            pos_0 = mut.position - 1
            assert parent_seq[pos_0] == mut.reference
            assert cand.sequence[pos_0] == mut.alternate


# ---------------------------------------------------------------------------
# TEST 10 — Conserved positions protected when constraints exist
# ---------------------------------------------------------------------------
def test_10_conserved_positions_protected() -> None:
    res = design_for_target(
        "Listeria monocytogenes",
        known_threshold=0.95,
        natural_threshold=0.95,
        seed=42,
    )
    for cand in res.designed_candidates:
        # Cysteines must never be mutated
        for mut in cand.mutations:
            assert mut.reference != "C"
        # If pediocin-derived, the pediocin box YGNGV must remain intact
        if cand.parent_candidate_id == "pediocin_pa_1":
            assert "YGNGV" in cand.sequence


# ---------------------------------------------------------------------------
# TEST 11 — Designed candidate provenance = model-predicted
# ---------------------------------------------------------------------------
def test_11_designed_candidate_provenance_is_model_predicted() -> None:
    res = design_for_target(
        "Listeria monocytogenes",
        known_threshold=0.95,
        natural_threshold=0.95,
        seed=42,
    )
    for cand in res.designed_candidates:
        assert cand.provenance == "model-predicted"


# ---------------------------------------------------------------------------
# TEST 12 — Natural variant provenance = database-derived
# ---------------------------------------------------------------------------
def test_12_natural_variant_provenance_is_database_derived() -> None:
    res = design_for_target(
        "Listeria monocytogenes",
        known_threshold=0.95,
        natural_threshold=0.75,
        seed=42,
    )
    for var in res.natural_variant_candidates:
        assert var["provenance"] == "database-derived"


# ---------------------------------------------------------------------------
# TEST 13 — Designed candidate never claims experimental validation
# ---------------------------------------------------------------------------
def test_13_designed_candidate_never_claims_experimental_validation() -> None:
    res = design_for_target(
        "Listeria monocytogenes",
        known_threshold=0.95,
        natural_threshold=0.95,
        seed=42,
    )
    for cand in res.designed_candidates:
        assert cand.experimentally_validated is False
        # Verify schema enforcement: setting True raises validation error
        with pytest.raises(ValueError):
            DesignedCandidate.model_validate(
                {**cand.model_dump(), "experimentally_validated": True}
            )


# ---------------------------------------------------------------------------
# TEST 14 — Simulator receives actual sequence
# ---------------------------------------------------------------------------
def test_14_simulator_receives_actual_sequence() -> None:
    sequences_passed: list[str] = []
    original_run_experiment = run_experiment

    def spy_run_experiment(spec: Any, **kwargs: Any) -> Any:
        cand = getattr(spec, "candidate", None)
        if cand and cand.sequence:
            sequences_passed.append(cand.sequence)
        return original_run_experiment(spec, **kwargs)

    with patch(
        "bacteriocin_lab.agents.design.agent.run_experiment", side_effect=spy_run_experiment
    ):
        res = design_for_target(
            "Listeria monocytogenes",
            known_threshold=0.95,
            natural_threshold=0.95,
            seed=42,
        )

    assert len(sequences_passed) > 0
    # Verify that sequences passed are non-trivial amino acid strings
    assert all(len(s) >= 20 for s in sequences_passed)
    # Check that designed sequence was among those simulated
    designed_seqs = {c.sequence for c in res.designed_candidates}
    assert any(s in designed_seqs for s in sequences_passed)


# ---------------------------------------------------------------------------
# TEST 15 — First simulation changes second design batch (active search)
# ---------------------------------------------------------------------------
def test_15_first_simulation_changes_second_design_batch() -> None:
    agent = ComputationalDesignAgent(
        seed=42, max_generations=2, designs_per_generation=5, max_total_designs=12
    )
    parent_seq = "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK"
    designs = agent.design_variants(
        parent_candidate_id="nisin_a",
        parent_sequence=parent_seq,
        parent_class="class_i",
        target_organism="Listeria monocytogenes",
    )
    gen1 = [d for d in designs if d.generation == 1]
    gen2 = [d for d in designs if d.generation == 2]

    assert len(gen1) > 0
    assert len(gen2) > 0

    # Best gen1 mutation is used as the anchor in gen2
    gen1_sorted = sorted(gen1, key=lambda c: c.score, reverse=True)
    best_g1_mut = gen1_sorted[0].mutations[0]

    # Every gen2 candidate must incorporate the best gen1 mutation
    for g2 in gen2:
        assert len(g2.mutations) == 2
        assert any(
            m.position == best_g1_mut.position and m.alternate == best_g1_mut.alternate
            for m in g2.mutations
        )


# ---------------------------------------------------------------------------
# TEST 16 — Critic can reject unsupported design
# ---------------------------------------------------------------------------
def test_16_critic_can_reject_unsupported_design() -> None:
    critic = DesignCritic()

    # 1. Experimental validation claim -> REJECT
    with pytest.raises(ValueError):
        DesignedCandidate(
            candidate_id="cand_bad",
            parent_candidate_id="pediocin_pa_1",
            sequence="KYYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC",
            experimentally_validated=True,  # Disallowed
        )

    # 2. Broken Pediocin box -> REJECT
    bad_cand_box = DesignedCandidate(
        candidate_id="cand_bad_box",
        parent_candidate_id="pediocin_pa_1",
        sequence="KAYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC",
        mutations=[
            DesignMutation(
                position=2, reference="Y", alternate="A", origin="conservative_substitution"
            )
        ],
    )
    verdict, notes = critic.review_candidate(
        bad_cand_box,
        parent_class="class_iia",
        parent_sequence="KYYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC",
    )
    assert verdict == "reject"
    assert any("disrupts essential Class IIa pediocin box" in n for n in notes)

    # 3. Disrupted Cysteine -> REJECT
    bad_cand_cys = DesignedCandidate(
        candidate_id="cand_bad_cys",
        parent_candidate_id="pediocin_pa_1",
        sequence="KYYGNGVTAGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC",
        mutations=[
            DesignMutation(
                position=9, reference="C", alternate="A", origin="conservative_substitution"
            )
        ],
    )
    verdict_cys, notes_cys = critic.review_candidate(bad_cand_cys)
    assert verdict_cys == "reject"
    assert any("cysteine" in n.lower() for n in notes_cys)

    # 4. Low simulator confidence -> NEEDS MORE EVIDENCE
    cand_low_conf = DesignedCandidate(
        candidate_id="cand_low_conf",
        parent_candidate_id="pediocin_pa_1",
        sequence="KYYGNGVTCGKRSCSVDWGKATTCIINNGAMAWATGGHQGNHKC",
        mutations=[
            DesignMutation(
                position=12, reference="H", alternate="R", origin="conservative_substitution"
            )
        ],
        uncertainty={"confidence": 0.25},
    )
    verdict_conf, _notes_conf = critic.review_candidate(cand_low_conf)
    assert verdict_conf == "needs_more_evidence"


# ---------------------------------------------------------------------------
# TEST 17 — No-hit BLAST does not become 'novel bacteriocin'
# ---------------------------------------------------------------------------
def test_17_no_hit_blast_does_not_become_novel_bacteriocin() -> None:
    novelty = format_sequence_novelty(database="nr", identity_percent=0.0)
    # Must use qualified phrasing
    assert (
        novelty["novelty_signal"] == "high sequence-novelty signal relative to searched databases"
    )
    # Never claim verified novel bacteriocin solely on no-hit BLAST
    assert "novel bacteriocin" not in novelty["novelty_signal"].lower()
    assert "database" in novelty
    assert "search_parameters" in novelty
    assert "identity_percent" in novelty


# ---------------------------------------------------------------------------
# TEST 18 — Design budget enforced
# ---------------------------------------------------------------------------
def test_18_design_budget_enforced() -> None:
    res = design_for_target(
        "Listeria monocytogenes",
        known_threshold=0.99,
        natural_threshold=0.99,
        max_designed_candidates=8,
        seed=42,
    )
    assert len(res.designed_candidates) <= MAX_TOTAL_DESIGNS_PER_RUN
    assert len(res.designed_candidates) <= 8
    for cand in res.designed_candidates:
        assert cand.generation <= MAX_DESIGN_GENERATIONS


# ---------------------------------------------------------------------------
# TEST 19 — Reproducibility with fixed seed
# ---------------------------------------------------------------------------
def test_19_reproducibility_with_fixed_seed() -> None:
    run1 = design_for_target(
        "Listeria monocytogenes",
        known_threshold=0.95,
        natural_threshold=0.95,
        seed=12345,
    )
    run2 = design_for_target(
        "Listeria monocytogenes",
        known_threshold=0.95,
        natural_threshold=0.95,
        seed=12345,
    )

    assert len(run1.designed_candidates) == len(run2.designed_candidates)
    for c1, c2 in zip(run1.designed_candidates, run2.designed_candidates, strict=True):
        assert c1.candidate_id == c2.candidate_id
        assert c1.sequence == c2.sequence
        assert c1.score == pytest.approx(c2.score)
        assert len(c1.mutations) == len(c2.mutations)


# ---------------------------------------------------------------------------
# TEST 20 — Target conditions influence candidate ranking
# ---------------------------------------------------------------------------
def test_20_target_conditions_influence_ranking() -> None:
    ctx_std = TargetContext(target_cell_density=1e6, ph=6.5)
    ctx_dense = TargetContext(target_cell_density=1e9, ph=6.5)

    res_std = design_for_target("Listeria monocytogenes", context=ctx_std, seed=42)
    res_dense = design_for_target("Listeria monocytogenes", context=ctx_dense, seed=42)

    top_std = res_std.known_candidates[0]
    top_dense = res_dense.known_candidates[0]

    # Scores and environmental robustness components shift under cell density stress
    assert (
        top_std["components"]["environmental_robustness"]
        != top_dense["components"]["environmental_robustness"]
    )
    assert top_std["score"] != top_dense["score"]


# ---------------------------------------------------------------------------
# TEST 21 — Evidence changes ranking
# ---------------------------------------------------------------------------
def test_21_evidence_changes_ranking() -> None:
    score_with_ev, comp_with_ev = compute_candidate_score(
        predicted_inhibition=0.95,
        predicted_log10_reduction=3.0,
        confidence=0.8,
        target_organism="Listeria monocytogenes",
        target_gram="positive",
        candidate_class="class_i",
        known_targets=["Listeria monocytogenes"],
        tier="known",
        has_evidence=True,
        evidence_count=10,
    )

    score_no_ev, comp_no_ev = compute_candidate_score(
        predicted_inhibition=0.95,
        predicted_log10_reduction=3.0,
        confidence=0.8,
        target_organism="Listeria monocytogenes",
        target_gram="positive",
        candidate_class="class_i",
        known_targets=["Listeria monocytogenes"],
        tier="known",
        has_evidence=False,
        evidence_count=0,
    )

    assert comp_with_ev.evidence_quality > comp_no_ev.evidence_quality
    assert score_with_ev > score_no_ev


# ---------------------------------------------------------------------------
# TEST 22 — Frontend response serializes cleanly
# ---------------------------------------------------------------------------
def test_22_frontend_response_serializes_cleanly() -> None:
    res = design_for_target("Listeria monocytogenes", seed=42)
    json_str = res.model_dump_json()
    parsed = json.loads(json_str)

    assert "target" in parsed
    assert "recommendations" in parsed
    assert "best_current_candidate" in parsed
    assert "recommended_next_experiment" in parsed
    assert "future_production_concept" in parsed
    assert len(parsed["recommendations"]) > 0

    first_rec = parsed["recommendations"][0]
    assert "tier" in first_rec
    assert "name" in first_rec
    assert "score" in first_rec
    assert "predicted_inhibition" in first_rec
    assert "confidence" in first_rec


# ---------------------------------------------------------------------------
# TEST 23 — No wet-lab / genetic-engineering instructions appear in result
# ---------------------------------------------------------------------------
def test_23_no_wet_lab_instructions_appear() -> None:
    res = design_for_target(
        "Listeria monocytogenes",
        known_threshold=0.95,
        natural_threshold=0.95,
        seed=42,
    )
    result_dict = res.model_dump()

    forbidden_terms = [
        "crispr",
        "cas9",
        "plasmid",
        "expression vector",
        "transformation protocol",
        "transfection",
        "promoter",
        "cloning workflow",
        "strain engineering",
    ]

    def check_clean(obj: Any, path: str = "") -> None:
        if isinstance(obj, str):
            lower_str = obj.lower()
            for term in forbidden_terms:
                assert term not in lower_str, f"Forbidden term '{term}' found at {path}: '{obj}'"
        elif isinstance(obj, dict):
            for k, v in obj.items():
                check_clean(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                check_clean(item, f"{path}[{idx}]")

    check_clean(result_dict)


# ---------------------------------------------------------------------------
# TEST 24 — Full repository benchmark runner integration
# ---------------------------------------------------------------------------
def test_24_benchmark_runner_integration() -> None:
    report = run_target_design_benchmarks(seed=42)
    assert "known_target_recovery" in report
    assert "natural_variant_ranking" in report
    assert "designed_candidate_improvement" in report
    assert "experiments_needed_to_reach_decision" in report
    assert "adaptive_vs_static_search" in report

    assert report["known_target_recovery"]["score"] >= 0.5
    assert report["natural_variant_ranking"]["valid_provenance"] is True
    assert report["experiments_needed_to_reach_decision"]["decision_reached"] is True
