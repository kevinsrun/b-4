# Experiment Planner - Omnigent integration notes

**Register:** `experiment_planner.TOOL_SPEC` (name `experiment_planner`), call `experiment_planner.run_agent(payload)`.
Stateless: Omnigent owns the loop state and passes everything back each call.

## Loop wiring
```
candidate_generation_design -> candidates, hypotheses
        |
        v
experiment_planner(candidates, hypotheses, previous_experiments, budget)   <---------+
        | decision.status == "propose_experiment"                                    |
        v                                                                            |
simulation_runner: run_experiment(ExperimentSpec) -> ExperimentResult  --append to previous_experiments
        | (future) wet_lab_adapter.run(...) returns the same ExperimentResult shape
        v
result analysis / research-state update (hypothesis status) -> next planner call
```
On each iteration Omnigent should: append every returned `ExperimentResult` to `previous_experiments`, decrement
`budget.remaining_experiments` (and `compute_budget` by `artifacts.budget_after.estimated_cost_of_proposal`), and pass
updated `hypotheses` (a hypothesis with `status: "rejected"` is excluded). Handle `decision.status`:
`propose_experiment` (run `experiment_spec`, or all of `batch`), `stop_budget_exhausted`, `converged`
(go to reporting / new hypotheses), `no_candidates` (call candidate generation), `error` (see `warnings`).

## Inputs consumed
* `candidates`: `candidate_id`, optional `name`, `confidence`, `features.{mechanism, known_targets,
  net_charge_at_target_ph, stability.ph_activity_window}` - exactly what `candidate_generation_design` emits; all optional except the ID.
* `hypotheses`: `hypothesis_id`, `template`, `prior_plausibility`, optional `suggested_test.{vary, levels}` (used to add test levels).
* `previous_experiments`: ExperimentResult objects: `candidate_id`, `conditions`, `measurement.predicted_inhibition_fraction`
  (or survival fraction / activity), `measurement.uncertainty`, `evidence_type` (`wet-lab-derived` gets higher weight).
  Missing condition values are assumed to equal reference conditions (a warning is emitted).

## Contract notes
* **Reproducibility:** `artifacts.input_digest_sha256` + `model_version`; `experiment_id = exp_<hash(candidate, conditions, #prior experiments, target)>`.
* **Evidence typing:** the planner reports consumed results in `evidence` with their own `evidence_type`; it never upgrades
  simulation/model output to validated, and labels expected results `simulation-derived`.
* `hyp_null_no_context_effect` is an internal baseline hypothesis ID that may appear as `hypothesis_id` or in the posterior list.

## Proposed contract changes (NOT applied; shared schemas untouched)
1. **ExperimentSpec shape mismatch.** The shared contract nests variables under `conditions`; the planner task statement shows
   them flat in `experiment_spec`. The planner returns the shared shape in `experiment_spec` and the flat one in
   `experiment_spec_flat`. Please confirm one canonical shape.
2. Define units for `bacteriocin_concentration` and `incubation_time` (planner assumes relative units and hours).
3. Add `Hypothesis` as a shared entity with `template` / `status` / `prior_plausibility`, and a registry of templates with
   prediction models so the planner and analysis agent agree on what each hypothesis predicts.
4. Add `hypothesis_id` to ExperimentResult (the planner reads it if present, but does not depend on it).
