# Experiment Planner / Active Learning Agent

Decides **which computational experiment to run next**. Pure Python 3.9+, standard library only, stateless and
deterministic (same request -> byte-identical JSON). It plans experiments; it does not run them, and anything it
expects back is `simulation-derived`, never validation.

```python
from bacteriocin_lab.agents.planner import run_agent, TOOL_SPEC
out = run_agent({"research_objective": {"target": {"species": "Listeria monocytogenes", "strain": "ATCC 19115"},
                                        "desired_behavior": {"ph_range": [6.0, 7.5], "target_cell_density": 1e8}},
                 "candidates": [...], "hypotheses": [...],      # e.g. straight from candidate_agent output
                 "previous_experiments": [...],                   # ExperimentResult objects
                 "budget": {"remaining_experiments": 20, "compute_budget": None}})
```
CLI `python -m bacteriocin_lab.agents.planner request.json` · loop demo `python -m bacteriocin_lab.evaluation.examples.planner.run_planning_loop [n_steps]` ·
tests `python -m unittest discover -s tests`.

## How it chooses

```
experiment_score = uncertainty x relevance x (discrimination + 0.15*uncertainty [+0.05 baseline bonus]) / cost
```
* **uncertainty** - 1 minus kernel coverage of the candidate's explored condition space (pH, log density, log
  concentration, temperature, incubation time, medium, domain). Repeating a point scores ~0; wet-lab data covers fully.
* **discrimination** - mutual information (bits) between "which hypothesis is true" and the outcome, normalised by
  log2(#hypotheses). Each hypothesis carries an executable prediction model (below); posteriors are recomputed from
  `previous_experiments` on every call, so **results steer the next choice**. A built-in `null` hypothesis
  ("no context effect") is always included so one real hypothesis can still be tested against nothing happening.
* **relevance** - candidate priority (from its `confidence`) x closeness of the conditions to the objective
  (soft penalties, floor 0.25, so off-range discriminating tests like pH 4.5 remain possible).
* **cost** - relative: physiological assay 3x, incubation sqrt(t/24h), +0.5 producer cells, +0.25 ionic conditions.
  Respects `budget.compute_budget`; `remaining_experiments` caps the batch.
* Proposals are **one-variable-at-a-time** perturbations of reference conditions (objective-derived; override with
  `constraints.reference_conditions`), so `variables_changed` / `variables_held_constant` are interpretable.
  An untested candidate's reference point gets a small baseline bonus (anchors its activity level).

Hypothesis models (matched on `template`, as emitted by `candidate_agent`): `ph_window` (activity drops outside the
candidate's pH window), `inoculum_effect` (drop with density above 1e6, steeper for pore-formers), `cationic_charge`,
`receptor_specificity` (condition-independent, candidate-level predictions). Factor models fit a per-candidate
activity ceiling from its data, shrunk toward a prior. Likelihood noise = measurement noise (floor 0.12, wet-lab x0.6)
combined with a 0.15 model-error term so crude models cannot drive posteriors to certainty. Hypotheses with an unknown
template get a warning and are treated as null-like (the planner cannot discriminate them).

Stop states: `stop_budget_exhausted`, `converged` (best MI < `min_expected_information_gain` and coverage > 65%),
`no_candidates` (-> asks `candidate_generation_design`), `error` (invalid input; never raises).

## Output
Task-specified fields (`experiment_id, hypothesis_id, candidate_id, experiment_spec, variables_changed,
variables_held_constant, expected_information_gain` [bits], `predicted_possible_outcomes` [bands of per-hypothesis
predictions with posterior-if-observed], `why_this_experiment, confidence, recommended_next_action`) plus the common
envelope (`agent, decision, evidence, uncertainties, artifacts, warnings`), `batch` (when `batch_size>1`, picks are
diversified by virtual coverage), and `artifacts.hypothesis_posterior / top_alternatives / budget_after / input_digest`.
`experiment_spec` follows the **shared ExperimentSpec** (nested `conditions`) so it can go straight into
`run_experiment`; `experiment_spec_flat` is the flat shape written in the task statement (see integration notes).
`confidence` = confidence the experiment is informative, not a prediction of the outcome.

## Limitations (read before trusting it)
* The surrogate hypothesis models are hand-written heuristics, **not mechanistic simulators**; "information gain" is
  relative to them. Weights/constants (0.15 explore weight, kernel scales, model error, relevance decay) are untuned.
* Per-candidate ceilings can be confounded with conditions when the reference point already sits in a suppressive
  regime (e.g. reference density 1e8): one point cannot separate low activity from an inoculum effect. The loop example
  shows this resolving only as more conditions are sampled.
* One-variable-at-a-time designs miss interactions (pH x density etc.). Concentration units are relative unless set.
* Hypotheses are scored independently of candidate-level cross effects; the posterior is a pseudo-Bayesian
  approximation (profile-fitted amplitudes, Gaussian noise), not a full Bayesian model comparison.
* `examples/toy_simulator.py` is a toy with invented ground truth, for demonstrating the loop only.
