"""update_state: what the state believes, why, and that no belief is ever silently overwritten."""

from __future__ import annotations

import pytest

from bacteriocin_lab.agents.knowledge import (
    StateInputError,
    StatePolicy,
    get_candidate_history,
    get_hypothesis_history,
    get_open_questions,
    initialize_state,
    register_candidates,
    summarize_current_state,
    update_state,
)
from bacteriocin_lab.tests.knowledge.knowledge_helpers import (
    analysis,
    candidate_envelope,
    clock,
    finding,
    result,
    spec,
    uncertainty,
)

H = "hyp_cand_a"


def start(*candidates: str):
    u = initialize_state({"goal": "inhibit Listeria"}, clock=clock)
    return register_candidates(
        u.state, candidate_envelope(*(candidates or ("cand_a",))), clock=clock
    ).state


def step(state, n: int, status: str, **kw):
    """One loop turn: analysis for experiment exp_<n>."""
    eid = f"exp_{n}"
    return update_state(
        state,
        analysis(eid, status, **kw),
        result=result(f"res_{eid}", eid),
        spec=spec(eid),
        clock=clock,
    )


# ---- the required behaviour: history is preserved ------------------------------------------------


def test_supported_then_weakened_preserves_both_states_chronologically():
    s1 = step(start(), 1, "supported", strength="moderate")
    s2 = step(s1.state, 2, "weakened", strength="moderate")
    hyp = s2.state.hypotheses[H]
    assert hyp.status == "weakened"
    assert [(c.previous_status, c.new_status) for c in hyp.status_history] == [
        (None, "open"),
        ("open", "supported"),
        ("supported", "weakened"),
    ]
    assert [c.iteration for c in hyp.status_history] == sorted(
        c.iteration for c in hyp.status_history
    )
    last = hyp.status_history[-1]
    assert (
        last.triggered_by[:1] == ["experiment:exp_2"]
        and "finding:find_exp_2" in last.triggered_by
        and "result:res_exp_2" in last.triggered_by
    )


def test_the_transition_event_has_the_documented_shape():
    s1 = step(start(), 1, "supported")
    s2 = step(s1.state, 2, "weakened")
    (t,) = s2.hypothesis_transitions
    assert t["event"] == "hypothesis_update" and t["hypothesis_id"] == H
    assert (t["previous_status"], t["new_status"]) == ("supported", "weakened")
    assert t["iteration"] == 2 and set(t["triggered_by"]) >= {
        "experiment:exp_2",
        "finding:find_exp_2",
    }


def test_nothing_in_a_past_status_entry_changes_when_a_later_one_is_added():
    s1 = step(start(), 1, "supported")
    before = [c.model_dump() for c in s1.state.hypotheses[H].status_history]
    s2 = step(s1.state, 2, "weakened")
    assert [c.model_dump() for c in s2.state.hypotheses[H].status_history[: len(before)]] == before


def test_iteration_advances_once_per_analysis_and_events_carry_their_turn():
    s1 = step(start(), 1, "supported")
    assert s1.state.iteration == 2
    s2 = step(s1.state, 2, "weakened")
    assert s2.state.iteration == 3
    assert {e.iteration for e in s1.new_events} == {1} and {e.iteration for e in s2.new_events} == {
        2
    }
    batch = update_state(
        s2.state,
        analysis("exp_3", "supported"),
        result=result("res_exp_3", "exp_3"),
        spec=spec("exp_3"),
        advance_iteration=False,
        clock=clock,
    )
    assert batch.state.iteration == 3  # a batch of results can share one turn


# ---- inconclusive, rejection, contested -------------------------------------------------------------


def test_inconclusive_leaves_the_hypothesis_untouched_but_is_recorded():
    s1 = step(start(), 1, "supported")
    s2 = step(s1.state, 2, "inconclusive", strength="none")
    hyp = s2.state.hypotheses[H]
    assert hyp.status == "supported" and s2.hypothesis_transitions == []
    assert hyp.n_inconclusive == 1 and hyp.observations[-1]["analysis_status"] == "inconclusive"
    timeline = get_hypothesis_history(s2.state, H)["timeline"]
    assert any(t["type"] == "observation" and t["changed_status"] == "untouched" for t in timeline)


def test_strong_weakening_rejects_the_hypothesis_and_then_the_candidate():
    s = step(step(start(), 1, "supported").state, 2, "weakened", strength="strong")
    assert (
        s.state.hypotheses[H].status == "rejected"
        and "strong" in s.state.hypotheses[H].status_history[-1].reason
    )
    assert s.state.candidates["cand_a"].status == "rejected"
    (ct,) = s.candidate_transitions
    assert ct["new_status"] == "rejected" and "all 1 of its hypotheses are rejected" in ct["reason"]
    summary = summarize_current_state(s.state)
    assert [h["hypothesis_id"] for h in summary["rejected_hypotheses"]] == [H] and summary[
        "rejected_hypotheses"
    ][0]["triggered_by"]
    assert [c["candidate_id"] for c in summary["rejected_candidates"]] == ["cand_a"]


def test_two_consecutive_moderate_weakenings_reject():
    s = step(start(), 1, "weakened", strength="moderate")
    assert s.state.hypotheses[H].status == "weakened"
    s = step(s.state, 2, "weakened", strength="moderate")
    assert (
        s.state.hypotheses[H].status == "rejected"
        and "consecutive" in s.state.hypotheses[H].status_history[-1].reason
    )


def test_a_rejected_hypothesis_can_be_reopened_and_its_candidate_returns_to_test():
    s = step(step(start(), 1, "supported").state, 2, "weakened", strength="strong")
    s = step(s.state, 3, "supported", strength="strong")
    hyp = s.state.hypotheses[H]
    assert hyp.status == "supported" and [c.new_status for c in hyp.status_history][-3:] == [
        "supported",
        "rejected",
        "supported",
    ]
    assert "reopened" in hyp.status_history[-1].reason
    assert s.state.candidates["cand_a"].status == "under_test"


def test_a_candidate_with_a_surviving_hypothesis_is_not_rejected():
    u = register_candidates(
        initialize_state({"g": 1}, clock=clock).state, candidate_envelope("cand_a"), clock=clock
    ).state
    extra = {
        "decision": {
            "candidates": [
                {
                    "candidate_id": "cand_a",
                    "rank": 1,
                    "hypotheses": [
                        {"hypothesis_id": "hyp_second", "statement": "s", "candidate_id": "cand_a"}
                    ],
                }
            ]
        }
    }
    u = register_candidates(u, extra, clock=clock).state
    s = step(u, 1, "weakened", strength="strong")
    assert (
        s.state.hypotheses[H].status == "rejected"
        and s.state.candidates["cand_a"].status == "under_test"
    )


def test_policy_is_configurable_and_recorded_in_the_reason():
    lenient = StatePolicy(reject_on_strong_weakening=False, reject_after_consecutive_weakened=5)
    s = update_state(
        start(),
        analysis("exp_1", "weakened", strength="strong"),
        result=result("r", "exp_1"),
        spec=spec("exp_1"),
        policy=lenient,
        clock=clock,
    )
    assert s.state.hypotheses[H].status == "weakened"


def test_alternate_analysis_vocabularies_are_read_with_a_warning():
    s = step(start(), 1, "contradicted", strength="moderate")
    assert s.state.hypotheses[H].status == "weakened" and any(
        "read as 'weakened'" in w for w in s.warnings
    )
    with pytest.raises(StateInputError, match="hypothesis_status"):
        step(start(), 1, "banana")


def test_contested_means_the_latest_two_decisive_results_disagree():
    s = step(start(), 1, "supported")
    assert not s.state.hypotheses[H].contested
    s = step(s.state, 2, "weakened")
    assert s.state.hypotheses[H].contested
    assert any(
        q["kind"] == "contested_hypothesis" and q["derived"] for q in get_open_questions(s.state)
    )
    s = step(s.state, 3, "weakened")
    assert not s.state.hypotheses[H].contested  # agreement settles it again


# ---- relationships -----------------------------------------------------------------------------------


def test_only_controlled_findings_become_known_relationships_and_changes_are_kept():
    s = step(
        start(),
        1,
        "supported",
        findings=[
            finding("target_cell_density", "negative"),
            finding("ph", "positive", controlled=False),
        ],
    )
    assert set(s.state.relationships) == {"cand_a::target_cell_density"}
    s = step(
        s.state, 2, "supported", findings=[finding("target_cell_density", "negative", effect=-0.3)]
    )
    rel = s.state.relationships["cand_a::target_cell_density"]
    assert (
        rel.relationship == "negative"
        and rel.n_confirming == 2
        and rel.effect_size == -0.3
        and len(rel.history) == 1
    )

    s = step(
        s.state, 3, "weakened", findings=[finding("target_cell_density", "positive", effect=0.2)]
    )
    rel = s.state.relationships["cand_a::target_cell_density"]
    assert rel.relationship == "positive" and [
        (c.previous_status, c.new_status) for c in rel.history
    ] == [(None, "negative"), ("negative", "positive")]
    assert [c["variable"] for c in s.relationship_changes] == ["target_cell_density"]
    assert any(q["kind"] == "relationship_reversal" for q in get_open_questions(s.state))


def test_an_unresolved_finding_never_replaces_a_known_relationship():
    s = step(start(), 1, "supported", findings=[finding("ph", "negative")])
    s = step(s.state, 2, "inconclusive", findings=[finding("ph", "unresolved", effect=None)])
    rel = s.state.relationships["cand_a::ph"]
    assert rel.relationship == "negative" and rel.n_unresolved == 1


# ---- uncertainties and questions ---------------------------------------------------------------------


def test_uncertainty_is_observed_resolved_when_no_longer_reported_and_can_return():
    a, b = (
        uncertainty("two points: shape unknown", "epistemic"),
        uncertainty("no uncertainty reported", "data-gap", "high"),
    )
    s = step(start(), 1, "supported", uncertainties=[a, b])
    assert {u.status for u in s.state.uncertainties.values()} == {"active"}
    s = step(s.state, 2, "supported", uncertainties=[a])
    by_desc = {u.description: u for u in s.state.uncertainties.values()}
    assert (
        by_desc["two points: shape unknown"].status == "active"
        and by_desc["two points: shape unknown"].occurrences == 2
    )
    gone = by_desc["no uncertainty reported"]
    assert gone.status == "resolved" and [c.new_status for c in gone.history] == [
        "active",
        "resolved",
    ]
    s = step(s.state, 3, "supported", uncertainties=[a, b])
    assert by_desc and s.state.uncertainties[gone.uncertainty_id].status == "active"
    assert [c.new_status for c in s.state.uncertainties[gone.uncertainty_id].history] == [
        "active",
        "resolved",
        "active",
    ]


def test_digits_do_not_make_two_uncertainties_different():
    s = step(start(), 1, "supported", uncertainties=[uncertainty("sigma 0.25 was used")])
    s = step(s.state, 2, "supported", uncertainties=[uncertainty("sigma 0.31 was used")])
    assert (
        len(s.state.uncertainties) == 1
        and next(iter(s.state.uncertainties.values())).occurrences == 2
    )


def test_followups_are_deduplicated_and_resolve_variable_questions_close_automatically():
    sug = [
        {
            "vary": "target_cell_density",
            "reason": "no controlled comparison",
            "suggested_values": [1e4, 1e8],
        }
    ]
    s = step(
        start(),
        1,
        "inconclusive",
        followups=["Re-run at 1e4 CFU/mL changing only density.", "Does it hold in a wet lab?"],
        suggested=sug,
    )
    s = step(
        s.state,
        2,
        "inconclusive",
        followups=["Re-run at 1e8 CFU/mL changing only density.", "Does it hold in a wet lab?"],
        suggested=sug,
    )
    open_q = [q for q in get_open_questions(s.state, include_derived=False)]
    assert (
        sum(q["kind"] == "followup" for q in open_q) == 2
    )  # wording that differs only by numbers is one question
    assert sum(q["kind"] == "resolve_variable" for q in open_q) == 1
    s = step(s.state, 3, "supported", findings=[finding("target_cell_density", "negative")])
    q = next(q for q in s.state.questions.values() if q.kind == "resolve_variable")
    assert q.status == "closed" and "negative" in q.close_reason and q.closed_by


def test_derived_questions_name_untested_hypotheses():
    state = start("cand_a", "cand_b")
    qs = get_open_questions(state)
    assert {q["question_id"] for q in qs} == {
        "derived:untested:hyp_cand_a",
        "derived:untested:hyp_cand_b",
    }
    s = step(state, 1, "supported")
    assert "derived:untested:hyp_cand_a" not in {
        q["question_id"] for q in get_open_questions(s.state)
    }


def test_unexpected_results_become_open_questions():
    s = step(
        start(),
        1,
        "supported",
        unexpected=[
            {
                "kind": "contradicts_prior_trend",
                "description": "trend reversed",
                "severity": "high",
                "refs": ["res_x"],
            }
        ],
    )
    assert any(
        q.kind == "unexpected_result" and "trend reversed" in q.text
        for q in s.state.questions.values()
    )


# ---- failures, gaps, idempotence, provenance -----------------------------------------------------------


def test_a_failed_attempt_is_not_a_negative_finding():
    state = step(start(), 1, "supported").state
    s = update_state(
        state, analysis("exp_2", "inconclusive", failed=True), spec=spec("exp_2"), clock=clock
    )
    assert s.state.experiments["exp_2"].status == "failed" and "res_exp_2" not in s.state.results
    assert s.state.hypotheses[H].status == "supported" and s.hypothesis_transitions == []
    assert s.state.hypotheses[H].n_weakening == 0 and s.state.hypotheses[H].n_inconclusive == 0
    assert any(q.kind == "failed_experiment" for q in s.state.questions.values())


def test_resubmitting_the_same_analysis_changes_nothing_at_all():
    s1 = step(start(), 1, "supported")
    again = step(s1.state, 1, "supported")
    assert (
        again.new_events == [] and again.state == s1.state
    )  # no events, no counters, no iteration
    assert any("already recorded" in w for w in again.warnings)


def test_unregistered_candidate_hypothesis_and_experiment_are_created_implicitly_with_warnings():
    s = update_state(None, analysis("exp_7", "supported", candidate_id="cand_z"), clock=clock)
    assert (
        s.state.candidates["cand_z"].implicit
        and s.state.hypotheses["hyp_cand_z"].implicit
        and s.state.experiments["exp_7"].implicit
    )
    joined = " ".join(s.warnings)
    assert "not registered" in joined and "never planned" in joined and "was not supplied" in joined
    assert s.state.results["res_exp_7"].result_supplied is False


def test_missing_required_ids_are_a_clear_input_error():
    with pytest.raises(StateInputError, match="experiment_id, result_id and candidate_id"):
        update_state(None, {"decision": {"hypothesis_status": "supported"}}, clock=clock)
    with pytest.raises(StateInputError):
        update_state(None, "not an object", clock=clock)  # type: ignore[arg-type]


def test_a_candidate_cannot_be_recorded_as_validated_without_wet_lab_evidence():
    env = candidate_envelope("cand_a")
    env["decision"]["candidates"][0]["validation_status"] = "experimentally-validated"
    u = register_candidates(initialize_state({"g": 1}, clock=clock).state, env, clock=clock)
    assert u.state.candidates["cand_a"].validation_status == "unvalidated" and any(
        "experimentally-validated" in w for w in u.warnings
    )


def test_summary_never_claims_validation_for_simulation_results():
    s = step(start(), 1, "supported")
    prov = summarize_current_state(s.state)["provenance"]
    assert "simulation-derived" in prov and "Nothing here is experimentally validated" in prov
    wet = update_state(
        s.state,
        analysis("exp_2", "supported"),
        result=result("res_w", "exp_2", evidence_type="wet-lab-derived"),
        spec=spec("exp_2"),
        clock=clock,
    )
    assert "wet-lab-derived" in summarize_current_state(wet.state)["provenance"]


def test_evidence_is_recorded_once_and_linked_to_the_hypothesis():
    ev = [
        {
            "evidence_id": "ev_1",
            "evidence_type": "inferred-hypothesis",
            "claim": "claim",
            "subject_ids": [H],
            "derived_from_evidence_type": "simulation-derived",
        }
    ]
    s = step(start(), 1, "supported", evidence=ev)
    assert (
        s.state.evidence["ev_1"].derived_from_evidence_type == "simulation-derived"
        and "ev_1" in s.state.hypotheses[H].evidence_ids
    )
    s = step(s.state, 2, "supported", evidence=ev)
    assert len(s.state.evidence) == 1


def test_model_versions_are_tracked_and_a_mix_is_flagged():
    s = update_state(
        start(),
        analysis("exp_1", "supported"),
        result=result("r1", "exp_1", model_version="sim/1.0"),
        spec=spec("exp_1"),
        clock=clock,
    )
    s = update_state(
        s.state,
        analysis("exp_2", "supported"),
        result=result("r2", "exp_2", model_version="sim/2.0"),
        spec=spec("exp_2"),
        clock=clock,
    )
    summary = summarize_current_state(s.state)
    assert (
        summary["model_versions"] == ["sim/1.0", "sim/2.0"]
        and "2 different model versions" in summary["model_version_warning"]
    )
    assert set(s.state.model_versions) >= {
        "sim/1.0",
        "sim/2.0",
        "result-analysis/0.1.0",
        "candidate-generation/0.1.0",
    }


def test_candidate_history_tells_the_story_in_order():
    s = step(step(start(), 1, "supported").state, 2, "weakened", strength="strong")
    h = get_candidate_history(s.state, "cand_a")
    kinds = [t["type"] for t in h["timeline"]]
    assert {"status_change", "ranked", "hypothesis_status_change", "result"} <= set(kinds)
    assert [t["iteration"] for t in h["timeline"]] == sorted(t["iteration"] for t in h["timeline"])
    assert h["candidate"]["status"] == "rejected" and [
        e["experiment_id"] for e in h["experiments"]
    ] == ["exp_1", "exp_2"]
