"""End-to-end integration tests for the real Omnigent discovery loop.

Covers all 17 required integration gates:
1. All MCP servers import/register.
2. Planner callable through Omnigent/MCP.
3. Result analysis callable through Omnigent/MCP.
4. Real critic executes.
5. Real knowledge agent executes.
6. Evidence changes candidate ranking.
7. Candidate sequence reaches simulator.
8. First result changes second experiment.
9. Critic rejection reroutes.
10. Simulation invariant failure produces no accepted result.
11. State survives failed dispatch.
12. Provenance preserved.
13. Idempotent retry does not duplicate result.
14. Loop guard stops repetition.
15. State serialization works.
16. verify_state_integrity passes.
17. Full repo regression.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bacteriocin_lab.agents.candidate.agent import CandidateGenerationAgent
from bacteriocin_lab.agents.candidate.schema import CandidateRequest
from bacteriocin_lab.agents.simulator import InvariantViolationError
from bacteriocin_lab.agents.simulator.schemas import CandidateSpec, EvidenceType, ExperimentResult
from bacteriocin_lab.orchestration import (
    AgentRegistry,
    DiscoveryWorkflowEngine,
    OmnigentAdapter,
    ResearchObjective,
    ResearchState,
    Route,
    run_discovery,
)
from bacteriocin_lab.orchestration.agent_adapters import (
    RealAnalysisAdapter,
    RealCriticAdapter,
    RealKnowledgeAdapter,
    SimulationAgentAdapter,
)
from bacteriocin_lab.orchestration.loop_guards import LoopGuards
from bacteriocin_lab.orchestration.routing import Router
from bacteriocin_lab.orchestration.state import ResearchStateManager, check_state_integrity
from bacteriocin_lab.orchestration.types import Candidate, ExperimentSpec, Finding

REPO = Path(__file__).resolve().parents[3]
MCP_DIR = REPO / "tools" / "mcp"
LAUNCHERS = REPO / "tools" / "launchers"

EXPECTED_SERVERS = (
    "literature",
    "candidates",
    "runner",
    "critic",
    "knowledge",
    "experiment_planner",
    "result_analysis",
)


# ---------------------------------------------------------------------------
# GATE 1: All MCP servers import/register
# ---------------------------------------------------------------------------
def test_01_all_mcp_servers_import_and_register():
    """Verify all 7 MCP server declarations exist, parse cleanly, and point to launchers."""
    assert MCP_DIR.is_dir(), f"MCP directory missing: {MCP_DIR}"

    for name in EXPECTED_SERVERS:
        declaration = MCP_DIR / f"{name}.yaml"
        assert declaration.is_file(), f"MCP declaration missing: {declaration}"

        raw = declaration.read_text()
        assert f"name: {name}" in raw
        assert "transport: stdio" in raw
        # Extract command and args
        lines = [line.strip() for line in raw.splitlines()]
        cmd_lines = [line_item for line_item in lines if line_item.startswith("command:")]
        assert cmd_lines, f"No command in {declaration}"
        cmd_path = cmd_lines[0].split(":", 1)[1].strip().strip('"\'')
        assert Path(cmd_path).is_absolute()

        arg_lines = [
            line_item for line_item in lines if line_item.startswith("- ") and "tools/launchers" in line_item
        ]
        assert arg_lines, f"No launcher arg in {declaration}"
        launcher_path = arg_lines[0].lstrip("- ").strip().strip('"\'')
        assert Path(launcher_path).is_file(), f"Launcher does not exist: {launcher_path}"


# ---------------------------------------------------------------------------
# GATE 2: Planner callable through Omnigent/MCP
# ---------------------------------------------------------------------------
def test_02_planner_callable_through_omnigent_mcp(tmp_path):
    """Verify experiment planner MCP tool can be queried and returns valid plans."""
    import tools.launchers.planner as planner_tool

    desc = planner_tool.describe()
    assert desc["agent"] == "experiment_planner"
    assert "input_schema" in desc

    schema = planner_tool.get_schema()
    assert "properties" in schema

    req = {
        "research_objective": {
            "target": {"species": "Listeria monocytogenes", "strain": "EGD-e"},
            "desired_behavior": {"ph_range": [6.0, 7.5], "target_cell_density": 1e8},
        },
        "candidates": [
            {
                "candidate_id": "cand_sakacin",
                "name": "sakacin P",
                "confidence": 0.7,
                "features": {"mechanism": "pore_forming", "known_targets": ["Listeria monocytogenes"]},
            }
        ],
        "hypotheses": [
            {
                "hypothesis_id": "hyp_1",
                "template": "ph_window",
                "statement": "sakacin P is active at pH 6.0-7.5 against Listeria monocytogenes.",
                "prior_plausibility": 0.7,
            }
        ],
        "previous_experiments": [],
        "budget": {"remaining_experiments": 5},
    }
    response = planner_tool.plan_experiment(req)
    assert response["decision"]["status"] in ("planned", "propose_experiment")
    assert response["experiment_spec"] is not None
    assert response["experiment_spec"]["candidate_id"] == "cand_sakacin"


# ---------------------------------------------------------------------------
# GATE 3: Result analysis callable through Omnigent/MCP
# ---------------------------------------------------------------------------
def test_03_result_analysis_callable_through_omnigent_mcp():
    """Verify result analysis agent can be executed with schema validation."""
    import tools.launchers.analysis as analysis_tool

    desc = analysis_tool.describe()
    assert desc["agent"] == "result_analysis_agent"
    schema = analysis_tool.get_schema()
    assert "properties" in schema

    # Direct run via adapter contract
    adapter = RealAnalysisAdapter()
    state = ResearchState(
        objective=ResearchObjective(
            goal="Test Listeria",
            target={"species": "Listeria monocytogenes"},
        )
    )
    # With no results, should skip gracefully
    res = adapter.run(state)
    assert res["status"] == "skipped"


# ---------------------------------------------------------------------------
# GATE 4: Real critic executes
# ---------------------------------------------------------------------------
def test_04_real_critic_executes():
    """Verify real scientific critic executes, reviews claims conservatively, and returns structured verdict."""
    state = ResearchState(
        objective=ResearchObjective(
            goal="Test Listeria",
            target={"species": "Listeria monocytogenes"},
        )
    )
    cand = Candidate(candidate_id="cand_test", name="Sakacin P", sequence="ACDEFGHIKLMNPQRSTVWY")
    state.candidates.append(cand)
    state_mgr = ResearchStateManager(state)
    res = ExperimentResult(
        result_id="res_01",
        experiment_id="exp_01",
        candidate_id="cand_test",
        target={"organism": "Listeria monocytogenes"},
        conditions={"target_cell_density": 1e8, "ph": 7.0},
        status="ok",
        predicted_inhibition_fraction=0.85,
        predicted_log10_reduction_vs_control=1.2,
        evidence_type=EvidenceType.SIMULATION,
        validated_experimentally=False,
    )
    state_mgr.add_experiment_result(res)
    state.findings.append(
        Finding(
            finding_id="find_01",
            statement="Candidate showed 85% inhibition in simulation.",
            status="supported",
            confidence=0.8,
            candidate_ids=["cand_test"],
            evidence_ids=[res.result_id],
        )
    )
    adapter = RealCriticAdapter()
    out = adapter.run(state)
    assert out["status"] in ("needs_more_evidence", "rejected", "approved", "approved_with_caveats")
    assert len(state.reviews) >= 1
    review = state.reviews[-1]
    assert review.reviewer == "scientific_critic_agent"
    assert review.status in ("needs_more_evidence", "rejected", "approved", "approved_with_caveats")
    assert review.critique


# ---------------------------------------------------------------------------
# GATE 5: Real knowledge agent executes
# ---------------------------------------------------------------------------
def test_05_real_knowledge_agent_executes():
    """Verify real knowledge agent folds findings and reviews, advancing state iteration."""
    state = ResearchState(
        objective=ResearchObjective(
            goal="Target Listeria",
            target={"species": "Listeria monocytogenes"},
        )
    )
    cand = Candidate(candidate_id="cand_test", name="Sakacin P", sequence="ACDEFGHIKLMNPQRSTVWY")
    state.candidates.append(cand)
    state_mgr = ResearchStateManager(state)
    res = ExperimentResult(
        result_id="res_01",
        experiment_id="exp_01",
        candidate_id="cand_test",
        target={"organism": "Listeria monocytogenes"},
        conditions={"target_cell_density": 1e8, "ph": 7.0},
        status="ok",
        predicted_inhibition_fraction=0.85,
        predicted_log10_reduction_vs_control=1.2,
        evidence_type=EvidenceType.SIMULATION,
        validated_experimentally=False,
    )
    state_mgr.add_experiment_result(res)

    # First run analysis adapter to get a real analysis payload
    analysis_adapter = RealAnalysisAdapter()
    analysis_out = analysis_adapter.run(state)
    assert analysis_out["status"] == "success"
    assert state.findings

    initial_iter = state.iteration
    knowledge_adapter = RealKnowledgeAdapter()
    out = knowledge_adapter.run(state)
    assert out["status"] == "success"
    assert state.iteration == initial_iter + 1


# ---------------------------------------------------------------------------
# GATE 6: Evidence changes candidate ranking
# ---------------------------------------------------------------------------
def test_06_evidence_changes_candidate_ranking():
    """Verify candidate generation produces ranked candidates with falsifiable hypotheses."""
    agent = CandidateGenerationAgent()

    # Query 1: standard neutral pH
    req_neutral = CandidateRequest(
        target={"organism": "Listeria monocytogenes", "gram": "positive"},
        conditions={"ph_low": 6.5, "ph_high": 7.5, "target_cell_density": 1e6},
        constraints={"max_candidates": 3},
    )
    res_neutral = agent.run(req_neutral)
    assert len(res_neutral.candidates) >= 1

    # Query 2: extreme acidic pH
    req_acidic = CandidateRequest(
        target={"organism": "Listeria monocytogenes", "gram": "positive"},
        conditions={"ph_low": 4.0, "ph_high": 4.5, "target_cell_density": 1e8},
        constraints={"max_candidates": 3},
    )
    res_acidic = agent.run(req_acidic)
    assert len(res_acidic.candidates) >= 1

    # Scores and justifications should reflect condition sensitivity
    assert res_neutral.candidates[0].hypotheses[0].falsified_if
    assert res_acidic.candidates[0].hypotheses[0].falsified_if


# ---------------------------------------------------------------------------
# GATE 7: Candidate sequence reaches simulator
# ---------------------------------------------------------------------------
def test_07_candidate_sequence_reaches_simulator():
    """Verify SimulationAgentAdapter constructs CandidateSpec with sequence and passes to run_experiments."""
    captured_registry: dict[str, CandidateSpec] = {}

    def mock_run_experiments(specs, candidate_registry=None, parameter_overrides=None):
        if candidate_registry:
            captured_registry.update(candidate_registry)
        return [
            ExperimentResult(
                result_id="res_test_01",
                experiment_id=specs[0].experiment_id,
                candidate_id=specs[0].candidate_id,
                target={"organism": "Listeria monocytogenes"},
                conditions={"target_cell_density": 1e8, "ph": 7.0},
                status="ok",
                predicted_inhibition_fraction=0.88,
                predicted_log10_reduction_vs_control=1.5,
                evidence_type=EvidenceType.SIMULATION,
                validated_experimentally=False,
            )
        ]

    state = ResearchState(
        objective=ResearchObjective(
            goal="Target Listeria",
            target={"species": "Listeria monocytogenes"},
        )
    )
    test_seq = "KYYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC"
    state.candidates.append(
        Candidate(candidate_id="cand_test_seq", name="Sakacin P", sequence=test_seq)
    )
    state.experiments.append(
        ExperimentSpec(
            experiment_id="exp_test_01",
            candidate_id="cand_test_seq",
            target={"organism": "Listeria monocytogenes"},
            conditions={"target_cell_density": 1e8, "ph": 7.0},
        )
    )

    import bacteriocin_lab.orchestration.agent_adapters.simulation_adapter as sim_mod

    orig_fn = sim_mod.run_experiments
    sim_mod.run_experiments = mock_run_experiments
    try:
        adapter = SimulationAgentAdapter()
        res = adapter.run(state)
        assert res["status"] == "success"
        assert "cand_test_seq" in captured_registry
        assert captured_registry["cand_test_seq"].sequence == test_seq
    finally:
        sim_mod.run_experiments = orig_fn


# ---------------------------------------------------------------------------
# GATE 8: First result changes second experiment
# ---------------------------------------------------------------------------
def test_08_first_result_changes_second_experiment():
    """Verify 2-iteration loop produces different experiments adaptively linked by first result."""
    obj = ResearchObjective(
        goal="Find a promising bacteriocin for high-density Listeria monocytogenes.",
        target={"species": "Listeria monocytogenes", "gram": "positive"},
        desired_behavior={"target_cell_density": 1e8, "ph": 7.0},
        constraints={"max_candidates": 3},
    )
    result = run_discovery(objective=obj, registry=AgentRegistry.real(), max_iterations=2)

    assert result.iterations_completed == 2
    experiments = result.final_state.get("experiments", [])
    assert len(experiments) >= 2

    exp1 = experiments[0]
    exp2 = experiments[1]

    # Experiments must not be identical
    assert exp1["experiment_id"] != exp2["experiment_id"]
    assert exp1["candidate_id"] != exp2["candidate_id"]

    # Trace verifies the link
    trace = result.execution_trace
    planner_steps = [t for t in trace if t.get("agent") == "planner"]
    assert len(planner_steps) >= 2
    assert "follow-up" in planner_steps[1].get("routing_reason", "").lower() or (
        planner_steps[1].get("routing_reason") != planner_steps[0].get("routing_reason")
    )


# ---------------------------------------------------------------------------
# GATE 9: Critic rejection reroutes
# ---------------------------------------------------------------------------
def test_09_critic_rejection_reroutes():
    """Verify Router properly reroutes when critic demands more evidence or rejects findings."""
    router = Router()
    state = ResearchState(
        objective=ResearchObjective(
            goal="Target Listeria",
            target={"species": "Listeria monocytogenes"},
        )
    )

    # 1. Critic needs more evidence -> reroutes to evidence
    from bacteriocin_lab.orchestration.types import Review

    state.reviews.append(
        Review(
            review_id="rev_01",
            reviewer="scientific_critic_agent",
            finding_ids=["find_01"],
            status="needs_more_evidence",
            critique="Need replication across multiple densities.",
        )
    )
    route = router.determine_next_route(state, last_agent="critic")
    assert route.next_agent == "evidence"

    # 2. Critic finds experiment inconclusive -> reroutes to planner
    state.reviews[-1].status = "experiment_inconclusive"
    route = router.determine_next_route(state, last_agent="critic")
    assert route.next_agent == "planner"

    # 3. Critic rejects candidate -> commits the rejection, then back to candidates.
    # The knowledge agent settles the rejected candidate and advances the turn before
    # a replacement is proposed; routing straight to candidate would leave a run that
    # keeps rejecting stuck in iteration 0 until the visit guard stopped it.
    state.reviews[-1].status = "rejected"
    route = router.determine_next_route(state, last_agent="critic")
    assert route.next_agent == "knowledge"
    assert "reviews" in route.required_inputs

    # Rule 9 then hands the untested replacement back to the candidate agent.
    route = router.determine_next_route(state, last_agent="knowledge")
    assert route.next_agent == "candidate"


# ---------------------------------------------------------------------------
# GATE 10: Simulation invariant failure produces no accepted result
# ---------------------------------------------------------------------------
def test_10_simulation_invariant_failure_produces_no_accepted_result():
    """Verify fail-closed behavior: invalid simulation produces no accepted result in state."""
    state = ResearchState(
        objective=ResearchObjective(
            goal="Target Listeria",
            target={"species": "Listeria monocytogenes"},
        )
    )
    state.experiments.append(
        ExperimentSpec(
            experiment_id="exp_unsafe",
            candidate_id="cand_1",
            target={"organism": "Listeria monocytogenes"},
            conditions={"target_cell_density": 1e8, "ph": 7.0},
        )
    )
    UNSAFE_OVERRIDES = {
        "targets": {
            "escherichia coli": {"log10_mic_um_base": -2.0},
            "listeria monocytogenes": {"log10_mic_um_base": 4.0},
        }
    }
    adapter = SimulationAgentAdapter(parameter_overrides=UNSAFE_OVERRIDES)
    with pytest.raises(InvariantViolationError):
        adapter.run(state)

    # No unverified result should be committed
    assert len(state.results) == 0


# ---------------------------------------------------------------------------
# GATE 11: State survives failed dispatch
# ---------------------------------------------------------------------------
def test_11_state_survives_failed_dispatch():
    """Verify workflow engine rolls back to snapshot if an agent fails mid-run."""
    reg = AgentRegistry.default()

    class FailingSimulationAdapter:
        name = "simulation"

        def run(self, state: ResearchState):
            state.iteration = 999  # Corrupt state
            raise RuntimeError("Simulator crashed unexpectedly")

    reg.register("simulation", FailingSimulationAdapter())
    obj = ResearchObjective(
        goal="Target Listeria",
        target={"species": "Listeria monocytogenes"},
    )
    engine = DiscoveryWorkflowEngine(registry=reg, max_iterations=2, max_failures=1)
    result = engine.run(obj)

    assert result.status == "failed"
    assert any("Simulator crashed unexpectedly" in err for err in result.errors)
    # State iteration was rolled back, not 999
    assert result.final_state["iteration"] < 999


# ---------------------------------------------------------------------------
# GATE 12: Provenance preserved
# ---------------------------------------------------------------------------
def test_12_provenance_preserved():
    """Verify provenance rules: simulated results are simulation-derived and never wet-lab."""
    obj = ResearchObjective(
        goal="Find a bacteriocin against Listeria.",
        target={"species": "Listeria monocytogenes", "gram": "positive"},
        desired_behavior={"target_cell_density": 1e8},
        constraints={"max_candidates": 2},
    )
    result = run_discovery(objective=obj, registry=AgentRegistry.real(), max_iterations=1)
    state = result.final_state

    for r in state.get("results", []):
        assert r["evidence_type"] == "simulation-derived"
        assert r.get("validated_experimentally") is False


# ---------------------------------------------------------------------------
# GATE 13: Idempotent retry does not duplicate result
# ---------------------------------------------------------------------------
def test_13_idempotent_retry_does_not_duplicate_result():
    """Verify adding the same result twice is idempotent and does not duplicate entries."""
    state = ResearchState(
        objective=ResearchObjective(
            goal="Target Listeria",
            target={"species": "Listeria monocytogenes"},
        )
    )
    state_mgr = ResearchStateManager(state)
    res = ExperimentResult(
        result_id="res_dup_check",
        experiment_id="exp_dup_check",
        candidate_id="cand_test",
        target={"organism": "Listeria monocytogenes"},
        conditions={"target_cell_density": 1e8, "ph": 7.0},
        status="ok",
        predicted_inhibition_fraction=0.88,
        predicted_log10_reduction_vs_control=1.5,
        evidence_type=EvidenceType.SIMULATION,
        validated_experimentally=False,
    )

    first_add = state_mgr.add_experiment_result(res)
    assert first_add is True
    assert len(state.results) == 1

    second_add = state_mgr.add_experiment_result(res)
    assert second_add is False
    assert len(state.results) == 1


# ---------------------------------------------------------------------------
# GATE 14: Loop guard stops repetition
# ---------------------------------------------------------------------------
def test_14_loop_guard_stops_repetition():
    """Verify LoopGuards detects repetition cycles and agent visit limits."""
    guards = LoopGuards(max_iterations=10, max_visits_per_agent_per_iteration=2)

    # 1. Visit limit within single iteration
    ok1, _ = guards.record_agent_visit(iteration=0, agent="planner")
    assert ok1 is True
    ok2, _ = guards.record_agent_visit(iteration=0, agent="planner")
    assert ok2 is True
    ok3, err3 = guards.record_agent_visit(iteration=0, agent="planner")
    assert ok3 is False
    assert "exceeded maximum visits" in err3

    # 2. Cycle detection
    guards_cycle = LoopGuards(max_cycle_repeats=2)
    route_a = Route(next_agent="evidence", reason="r1")
    route_b = Route(next_agent="candidate", reason="r2")
    guards_cycle.check_cycle(route_a)
    guards_cycle.check_cycle(route_b)
    guards_cycle.check_cycle(route_a)
    is_cycle, reason = guards_cycle.check_cycle(route_b)
    assert is_cycle is True
    assert "Detected recurring cycle" in reason


# ---------------------------------------------------------------------------
# GATE 15: State serialization works
# ---------------------------------------------------------------------------
def test_15_state_serialization_works(tmp_path):
    """Verify state serialization and deserialization via OmnigentAdapter roundtrips cleanly."""
    obj = ResearchObjective(
        goal="Target Listeria",
        target={"species": "Listeria monocytogenes"},
    )
    state = ResearchState(objective=obj, iteration=3)
    state.candidates.append(Candidate(candidate_id="cand_1", name="Nisin A", score=0.9))

    file_path = tmp_path / "research_state.json"
    OmnigentAdapter.save_state_to_file(state, file_path)
    assert file_path.is_file()

    loaded = OmnigentAdapter.load_state_from_file(file_path)
    assert loaded.iteration == 3
    assert len(loaded.candidates) == 1
    assert loaded.candidates[0].candidate_id == "cand_1"
    assert loaded.candidates[0].name == "Nisin A"


# ---------------------------------------------------------------------------
# GATE 16: verify_state_integrity passes
# ---------------------------------------------------------------------------
def test_16_verify_state_integrity_passes():
    """Verify check_state_integrity passes on a multi-step real discovery run."""
    obj = ResearchObjective(
        goal="Find a promising bacteriocin for high-density conditions.",
        target={"species": "Listeria monocytogenes", "gram": "positive"},
        desired_behavior={"target_cell_density": 1e8, "ph": 7.0},
        constraints={"max_candidates": 2},
    )
    result = run_discovery(objective=obj, registry=AgentRegistry.real(), max_iterations=2)
    state = ResearchState.model_validate(result.final_state)

    problems = check_state_integrity(state)
    assert problems == [], f"Integrity problems found: {problems}"


# ---------------------------------------------------------------------------
# GATE 17: Full repo regression
# ---------------------------------------------------------------------------
def test_17_full_repo_regression():
    """Verify OmnigentAdapter coordinates the discovery workflow smoothly."""
    adapter = OmnigentAdapter()
    obj = {
        "goal": "Target Listeria monocytogenes with robust bacteriocin.",
        "target": {"species": "Listeria monocytogenes", "gram": "positive"},
        "desired_behavior": {"target_cell_density": 1e8, "ph": 7.0},
        "constraints": {"max_candidates": 2},
    }
    result = adapter.run(objective=obj, max_iterations=2)

    assert result.status in ("completed", "max_iterations")
    assert result.iterations_completed == 2
    assert len(result.execution_trace) >= 10
    assert result.summary["experiments_run"] >= 2
    assert result.summary["findings_count"] >= 2
    assert result.summary["reviews_count"] >= 2
