"""The Omnigent-callable interface: JSON in, contract envelope out, never raises."""

from __future__ import annotations

import json

import pytest

from bacteriocin_lab.agents.knowledge import (
    AGENT_NAME,
    MODEL_VERSION,
    OPERATIONS,
    KnowledgeAgent,
    knowledge_call,
)
from bacteriocin_lab.shared.contract import AgentResponseEnvelope
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


@pytest.fixture
def agent(tmp_path):
    return KnowledgeAgent(state_dir=tmp_path / "state", clock=clock)


def call(agent, **payload):
    env = agent.run_envelope(payload)
    AgentResponseEnvelope.model_validate(
        env.model_dump()
    )  # always a valid shared-contract envelope
    return env


def seed(agent):
    call(agent, operation="initialize_state", objective={"goal": "g"})
    call(agent, operation="register_candidates", candidate_output=candidate_envelope("cand_a"))
    call(agent, operation="record_experiment_plan", plan=spec("exp_1"))


def test_a_full_loop_through_the_interface_persists_and_accumulates(agent, tmp_path):
    seed(agent)
    env = call(
        agent,
        operation="update_state",
        analysis_result=analysis(
            "exp_1",
            "supported",
            findings=[finding("ph", "negative")],
            uncertainties=[uncertainty("shape unknown", "epistemic", "high")],
        ),
        result=result("res_exp_1", "exp_1"),
    )
    d = env.decision
    assert env.agent == AGENT_NAME and env.model_version == MODEL_VERSION and env.confidence == 1.0
    assert d["status"] == "ok" and d["persisted"] is True and d["iteration"] == 2
    assert d["new_event_count"] == len(d["new_events"]) and all(
        "event_hash" not in e for e in d["new_events"]
    )
    assert (
        env.artifacts["state_dir"].endswith("state")
        and (tmp_path / "state" / "events.jsonl").is_file()
    )
    assert [u.description for u in env.uncertainties] == [
        "shape unknown"
    ]  # what is still uncertain travels with every reply
    nxt = env.recommended_next_action
    assert nxt.agent == "experiment_planner" and nxt.payload_hint["hypothesis_statuses"] == {
        H: "supported"
    }

    again = call(agent, operation="summarize_current_state")
    assert (
        again.decision["result"]["counts"]["results"] == 1
        and again.decision["result"]["iteration"] == 2
    )


def test_the_documented_transition_is_visible_in_the_reply(agent):
    seed(agent)
    call(
        agent,
        operation="update_state",
        analysis_result=analysis("exp_1", "supported"),
        result=result("res_exp_1", "exp_1"),
    )
    call(agent, operation="record_experiment_plan", plan=spec("exp_2"))
    env = call(
        agent,
        operation="update_state",
        analysis_result=analysis("exp_2", "weakened"),
        result=result("res_exp_2", "exp_2"),
    )
    (t,) = env.decision["hypothesis_transitions"]
    assert (
        t["previous_status"] == "supported"
        and t["new_status"] == "weakened"
        and t["iteration"] == 2
    )
    assert set(t["triggered_by"]) >= {"experiment:exp_2", "finding:find_exp_2"}


def test_every_query_operation(agent):
    seed(agent)
    call(
        agent,
        operation="update_state",
        analysis_result=analysis("exp_1", "supported", followups=["why?"]),
        result=result("res_exp_1", "exp_1"),
    )
    assert (
        call(agent, operation="get_candidate_history", candidate_id="cand_a").decision["result"][
            "candidate"
        ]["status"]
        == "under_test"
    )
    assert (
        call(agent, operation="get_hypothesis_history", hypothesis_id=H).decision["result"][
            "hypothesis"
        ]["status"]
        == "supported"
    )
    assert (
        call(agent, operation="get_experiment_history").decision["result"][0]["experiment_id"]
        == "exp_1"
    )
    assert (
        call(agent, operation="get_experiment_history", candidate_id="nobody").decision["result"]
        == []
    )
    assert any(
        q["text"] == "why?" for q in call(agent, operation="get_open_questions").decision["result"]
    )
    assert call(agent, operation="verify_integrity").decision["result"]["intact"] is True
    past = call(agent, operation="state_at_iteration", iteration=1)
    assert (
        past.decision["result"]["iteration"] == 2
        and past.artifacts["state"]["hypotheses"][H]["status"] == "supported"
    )  # state once turn 1 closed


def test_manual_curation_operations(agent):
    seed(agent)
    env = call(
        agent,
        operation="reject_candidate",
        candidate_id="cand_a",
        reason="off-target toxicity concern",
    )
    assert env.decision["candidate_transitions"][0]["new_status"] == "rejected"
    call(
        agent,
        operation="update_state",
        analysis_result=analysis("exp_1", "inconclusive", followups=["a question"]),
        result=result("r", "exp_1"),
    )
    qid = next(
        q["question_id"]
        for q in call(agent, operation="get_open_questions").decision["result"]
        if q["text"] == "a question"
    )
    call(agent, operation="close_question", question_id=qid, reason="answered offline")
    assert all(
        q["text"] != "a question"
        for q in call(agent, operation="get_open_questions").decision["result"]
    )


def test_pure_mode_returns_the_state_and_writes_nothing(tmp_path):
    pure = KnowledgeAgent(clock=clock)
    first = call(
        pure, operation="register_candidates", candidate_output=candidate_envelope("cand_a")
    )
    assert first.decision["persisted"] is False and any(
        "Not persisted" in w for w in first.warnings
    )
    state = first.artifacts["updated_state"]
    second = call(
        pure,
        operation="update_state",
        previous_state=state,
        analysis_result=analysis("exp_1", "supported"),
        result=result("r", "exp_1"),
        spec=spec("exp_1"),
    )
    assert second.artifacts["updated_state"]["hypotheses"][H]["status"] == "supported"
    assert (
        call(
            pure,
            operation="summarize_current_state",
            previous_state=second.artifacts["updated_state"],
        ).decision["result"]["counts"]["results"]
        == 1
    )
    assert not list(tmp_path.iterdir())


def test_state_dir_env_var_is_honoured(tmp_path, monkeypatch):
    monkeypatch.setenv("BACTERIOCIN_STATE_DIR", str(tmp_path / "env_state"))
    env = call(KnowledgeAgent(clock=clock), operation="initialize_state", objective={"goal": "g"})
    assert env.decision["persisted"] and (tmp_path / "env_state" / "events.jsonl").is_file()


def test_errors_are_structured_never_raised(agent):
    assert call(agent, operation="nope").decision["status"] == "error"
    assert (
        call(agent, operation="update_state").decision["status"] == "error"
    )  # missing analysis_result
    bad = call(
        agent,
        operation="update_state",
        analysis_result={"decision": {"hypothesis_status": "supported"}},
    )
    assert (
        bad.decision["status"] == "error"
        and bad.confidence == 0.0
        and bad.uncertainties[0].kind == "data-gap"
    )
    seed(agent)
    assert (
        call(agent, operation="get_candidate_history", candidate_id="ghost").decision["status"]
        == "not_found"
    )
    assert (
        call(agent, operation="get_hypothesis_history", hypothesis_id="ghost").decision["status"]
        == "not_found"
    )
    assert (
        KnowledgeAgent(clock=clock)
        .run_envelope({"operation": "get_open_questions"})
        .decision["status"]
        == "error"
    )  # no state source
    for junk in (None, [], "x", 5, {"operation": 3}):
        assert knowledge_call(junk)["decision"]["status"] == "error"  # type: ignore[arg-type]


def test_a_stale_write_is_reported_as_a_conflict(agent):
    seed(agent)
    env = call(
        agent,
        operation="update_state",
        analysis_result=analysis("exp_1", "supported"),
        result=result("r", "exp_1"),
        expected_event_count=1,
    )
    assert (
        env.decision["status"] == "conflict" and "moved since it was read" in env.decision["error"]
    )


def test_tampering_is_surfaced_as_an_integrity_error(agent, tmp_path):
    seed(agent)
    path = tmp_path / "state" / "events.jsonl"
    lines = path.read_text().splitlines()
    ev = json.loads(lines[0])
    ev["objective"] = {"goal": "rewritten"}
    lines[0] = json.dumps(ev)
    path.write_text("\n".join(lines) + "\n")
    verdict = call(agent, operation="verify_integrity")
    assert verdict.decision["status"] == "integrity_error" and verdict.confidence == 0.0
    assert verdict.decision["result"]["intact"] is False and any(
        "edited" in p for p in verdict.decision["result"]["problems"]
    )  # the diagnosis, not a bare error
    assert verdict.uncertainties[0].severity == "high"
    assert call(agent, operation="get_open_questions").decision["status"] == "integrity_error"


def test_verify_integrity_diagnoses_an_unreadable_log_instead_of_failing(agent, tmp_path):
    seed(agent)
    path = tmp_path / "state" / "events.jsonl"
    path.write_text(path.read_text() + "this is not json\n")
    verdict = call(agent, operation="verify_integrity")
    assert verdict.decision["status"] == "integrity_error" and any(
        "not a valid event" in p for p in verdict.decision["result"]["problems"]
    )


def test_module_level_entry_point_matches_the_class(tmp_path, monkeypatch):
    monkeypatch.setenv("BACTERIOCIN_STATE_DIR", str(tmp_path / "s"))
    import bacteriocin_lab.agents.knowledge.agent as mod

    monkeypatch.setattr(mod, "_DEFAULT", None)
    out = knowledge_call({"operation": "initialize_state", "objective": {"goal": "g"}})
    assert out["agent"] == AGENT_NAME and out["decision"]["status"] == "ok" and json.dumps(out)
    assert set(OPERATIONS) >= {
        "update_state",
        "get_candidate_history",
        "get_hypothesis_history",
        "get_experiment_history",
        "get_open_questions",
        "summarize_current_state",
    }


def test_replies_are_deterministic_given_a_fixed_clock(tmp_path):
    def run(d):
        a = KnowledgeAgent(state_dir=d, clock=clock)
        seed(a)
        return call(
            a,
            operation="update_state",
            analysis_result=analysis("exp_1", "supported"),
            result=result("r", "exp_1"),
        )

    a, b = run(tmp_path / "a"), run(tmp_path / "b")
    assert (
        a.decision == b.decision
        and a.artifacts["last_event_hash"] == b.artifacts["last_event_hash"]
    )  # same history, same hash chain
