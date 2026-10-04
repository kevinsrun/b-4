# Tech debt

Issues that matter but were out of scope for the integration/reliability pass (see
`docs/integration-audit.md` for what was fixed). Ordered by severity. None of these stops the system
installing, running or passing its tests; item 1 is the one to decide on before relying on the loop's
*scientific* conclusions.

## CRITICAL

### 1. The autonomous loop does not run the real Analysis, Critic or Knowledge agents
- **Issue.** `AgentRegistry.default()` wires the real evidence, candidate, planner and simulator
  agents, but `analysis`, `critic` and `knowledge` are the orchestration layer's own classes
  (`orchestration/agent_adapters/{analysis,critic,knowledge}_agent.py`). They re-implement the
  scientific responsibility of `bacteriocin_lab.agents.analysis|critic|knowledge` with hard-coded
  thresholds (e.g. inhibition >= 0.70 "supported", <= 0.40 "contradicted"). The real agents are
  exercised only by their own suites and by pairwise tests.
- **Why it matters.** The Critic is the safety/review agent. In the loop that actually runs, nothing
  consults it, and the real Analysis agent's hypothesis-aware, uncertainty-aware reading is bypassed.
  The classes even share names (`ResultAnalysisAgent`, `ScientificCriticAgent`, `KnowledgeAgent`),
  which makes the gap easy to miss.
- **Why it was not swapped in.** It is a policy change, not a thin adapter: the real critic's verdicts
  (`approve | approve_with_caveats | reject | needs_more_evidence`) do not match the orchestrator's
  `Review.status` vocabulary (`approved | needs_more_evidence | experiment_inconclusive |
  analysis_unsupported | rejected`); the real analysis needs hypotheses carrying numeric predictions
  or an `expected_relationship`, which `orchestration.types.Hypothesis` does not keep; and routing would
  change (the real critic asks for >= 2 results per claim, so it will send the loop back far more often).
- **Current mitigation.** Provenance is enforced in the state manager independent of any agent (never
  wet-lab from simulation, failed runs never stored as results, references and ids re-validated after
  every dispatch, unsafe simulator overrides fail closed). The real critic now *can* read simulator
  results (`shared/compat.py`), so wiring it in is no longer blocked by a data-shape bug.
- **Recommended fix.** Add `RealAnalysisAdapter` / `RealCriticAdapter` mapping the real envelopes onto
  `Finding` / `Review` (including an explicit verdict map), have the candidate adapter keep
  `predicted_inhibition_fraction` / `key_conditions` on `Hypothesis`, expose `AgentRegistry.real()`, and
  run the existing orchestration tests against both registries before making it the default.

## HIGH

### 2. Two research-state implementations
- `orchestration.types.ResearchState` (what the workflow mutates) and `shared.ResearchState` (what the
  Knowledge agent persists, with a hash-chained event log and integrity verification) are unrelated
  classes. The orchestrator's `scientific_history` is not the Knowledge agent's event log.
- **Mitigation.** Both round-trip through JSON and are tested; history is append-only in each.
- **Fix.** Make the workflow persist through `KnowledgeAgent` (item 1 is the natural moment).

### 3. Duplicate experiment schemas
- `ExperimentSpec` / `ExperimentResult` exist in `shared/contract.py` and `agents/simulator/schemas.py`
  (plus the planner's plain dicts). They differ in representation (floats vs `{value, unit}`; strings
  vs structured `important_factors`). `shared/compat.py` bridges the critic's boundary and
  `agents/planner/adapters.py` the planner's; the analysis agent has its own adapter.
- **Fix.** Pick one canonical result type and delete the bridges; a joint owners' decision.

### 4. Literature evidence never influences candidates
- The literature adapter calls the agent with `retrieval: {"enabled": False}`, so the default loop
  retrieves nothing, and `CandidateAgentAdapter` never passes `state.evidence` to the candidate agent
  (which itself only reads candidate pools from evidence carrying a `candidate` block).
- Evidence *is* now recorded in state with its provenance (it was silently discarded before).
- **Fix.** Map literature records to candidate-pool entries; decide where retrieval is enabled.

## MEDIUM

### 5. Resume restarts routing at "evidence"
`run_discovery(initial_state=...)` preserves ids, history and results and does not redo settled
candidates, but routing re-enters at the cold-start step rather than where the run stopped. Steps are
idempotent so nothing is duplicated; it costs extra calls. The router has no persisted position.

### 6. The planner runs partly blind on real candidates
Hypotheses reach the planner without a `template`, so it treats them as null-like and warns; its
candidate features are only partially mapped (`planner/adapters.py`). It plans, but with less
information than it could use. The simulator will also run a candidate that has no sequence on a
class-default prior (documented simulator behaviour), so such a result is not about that peptide.

### 7. Slow simulator tests
Full suite ~3 min; `test_override_validation.py::test_7_no_silent_fallback` alone ~117 s. Each unsafe
override re-runs the full invariant self-test (~7 s) because only *passing* configurations are cached.

### 8. Errors are strings
`DiscoveryResult.errors` and `ExecutionTraceItem.error` are free text. Consumers must parse prose to
tell "unknown agent" from "invariant violation". Add `error_type` / `retryable`.

### 9. Result identity policy is implicit
Results are keyed by `result_id`; resubmitting the same id is a no-op; distinct ids for one experiment
are kept as replicates (needed for wet-lab data). Safe retries therefore depend on content-derived ids
(true for the simulator; not enforced for other producers). Documented in `tests/integration`.

## LOW

10. `evaluation/examples/planner/run_planning_loop.py` mutates `sys.path` (example script only).
11. `.DS_Store` is tracked in git; add it to `.gitignore` and remove it.
12. The planner package keeps `typing.List/Optional` style (~300 findings under the repo ruff config);
    CI enforces only `E9,F63,F7,F82` there.
13. `tests/tools/test_omnigent_manager.py` needs the external `omnigent` package and was not run in the
    pip-only verification environment.
14. `orchestration/workflow.py` has a pre-existing unused `# noqa: BLE001`.
15. `tests/planner/test_planner.py::test_consumes_candidate_agent_output` skips itself: it imports the
    old standalone `candidate_agent` package, which no longer exists after the single-package restructure.
    It is the suite's one skip (pre-existing). It should be rewritten against `bacteriocin_lab.agents.candidate`.
