# Result Analysis Agent

Written for: engineers wiring the agent into Omnigent, and implementers of the Experiment Planner and Knowledge Agent that consume its output.

It interprets one `ExperimentResult`: does it support, weaken, or fail to distinguish the hypothesis it tested; how does it compare with earlier experiments; which variables drove it; what was unexpected; how sure is that reading. It does not run experiments, does not choose the next one, and does not write the knowledge base. Source: [`src/bacteriocin_discovery/result_analysis_agent/`](../src/bacteriocin_discovery/result_analysis_agent/).

## Calling it

```python
from bacteriocin_lab.agents.analysis import analyze_result

response = analyze_result({
    "result": {...},                      # ExperimentResult just produced
    "previous_results": [...],            # ALL earlier ExperimentResult objects
    "hypothesis": {                       # or a candidate-agent TestableHypothesis, unchanged
        "hypothesis_id": "hyp_...",
        "expected_relationship": {"variable": "target_cell_density", "direction": "negative"},
    },
})
```

JSON in, `AgentResponseEnvelope`-shaped JSON out; it never raises. Invalid input returns a well-formed envelope with `confidence = 0` and a `data-gap` uncertainty. Other optional inputs: `spec`, `candidate`, `research_state` (its `hypotheses` and `results` are used when not passed explicitly), `evidence`.

Omnigent exposure: `analyze_result` is the callable (JSON in, envelope out). This package ships no MCP server; the wiring lives in `tools/launchers/`, following the existing pattern: a launcher in `tools/launchers/`, a declaration in `tools/mcp/`, and the role instructions in `agents/analysis/`. The reference design for such a server (flat, annotated parameters; compact response with the provenance disclaimer and warnings first; full envelope written to a file) is the one `tools/launchers/candidates.py` already uses.

## Output (`decision`)

```json
{
  "finding_id": "find_...", "experiment_id": "...", "result_id": "...", "candidate_id": "...",
  "hypothesis_id": "...", "hypothesis_status": "supported | weakened | inconclusive",
  "evidence_strength": "none | weak | moderate | strong",
  "findings": [{"variable": "target_cell_density", "relationship": "negative",
                "effect_size": -0.215, "interpretation": "Higher target cell density is associated with reduced predicted inhibition ...",
                "delta_inhibition": -0.43, "z_score": -10.1, "n_points": 2, "controlled": true}],
  "unexpected_results": [], "drivers": [], "confidence": 0.73,
  "uncertainties": [], "recommended_followup_questions": [],
  "source_evidence_type": "simulation-derived", "provenance_note": "..."
}
```

Extras beyond the requested shape: `evidence_strength`, `status_basis`, `prediction_source`, `drivers`, `observed`, `source_evidence_type`, `provenance_note`. `uncertainties` are the contract's structured `Uncertainty` objects.

Envelope: `evidence` holds the interpretations as `inferred-hypothesis` evidence (each tagged with `derived_from_evidence_type`); `artifacts` holds `comparisons`, `confidence_breakdown`, `knowledge_update` (for the Knowledge Agent) and `planner_hints` (for the Experiment Planner: resolved/unresolved variables, `reopen_hypothesis_ids`, `suggested_experiments`, follow-up questions); `recommended_next_action` is `experiment_planner` with `also_notify: ["knowledge_agent"]`.

## How it decides

**Comparison against previous experiments.** Only *controlled series* count: the current result plus prior results for the same candidate (and assay domain) in which a single variable differs and everything else (all numeric conditions, medium, growth phase, assay type, ionic conditions) is identical. Anything else is confounded and is reported as a data gap, never as a finding. Results in different units are excluded. Concentration and densities are analysed on a log10 axis, so `effect_size` is the change in inhibition fraction per log10 unit (per unit for pH, temperature, time).

**Relationship.** For two points: `positive`/`negative` only if the change is at least 0.05 in inhibition fraction **and** at least 2 combined standard uncertainties; a change under 0.05 is `none`; a larger change inside the noise is `unresolved`. For three or more points: a sign reversal among meaningful steps is `non_monotonic`, and a last step under 25% of the largest flags a `plateau`. A result with no reported uncertainty is analysed with an assumed 0.05, and that is recorded as an uncertainty.

**Hypothesis verdict**, first available form wins:

1. `expected_relationship` — tested against the controlled series (match → `supported`, opposite or absent effect → `weakened`, noise/non-monotonic/no series → `inconclusive`).
2. `predicted_inhibition_fraction` — z against the observation uncertainty combined with a tolerance (default 0.15).
3. `predicted_direction` `inhibition` / `no-effect` — fixed thresholds, uncertainty-aware.
4. A keyword reading of `statement` — only when unambiguous, always labelled `statement-keyword-heuristic`, never `strong`.

A result outside the hypothesis's `key_conditions` is `inconclusive`. A hypothesis is never `supported` just because nothing contradicted it.

**Unexpected results**: trend reversal against earlier controlled results (high), prediction mismatch, non-monotonic response, inhibition/survival that do not sum to 1 (high), and producer `important_factors` that disagree with the controlled analysis.

**Confidence** (in the reading, not in biology): `0.35 + evidence strength (0–0.25) + controlled comparison on the hypothesis variable (0.15) + other controlled series (≤0.10) − measurement uncertainty (≤0.20) − high-severity unexpected results (≤0.20) − heuristic prediction (0.05)`, floor 0.05, **cap 0.85** unless the result is wet-lab-derived (cap 0.95). The breakdown is in `artifacts.confidence_breakdown`.

## Contract rules it enforces

* Rule 8/9 — every interpretation is tagged with the source evidence type; non-wet-lab results are described as "predicted", never "measured". A guard (`claims_experimental_validation`) scans every generated string and **fails closed** (zero-confidence envelope) if a draft would claim validation of a non-wet-lab result; negations such as "NOT experimentally validated" pass.
* It never emits `wet-lab-derived` evidence, even when analysing wet-lab input.
* Reproducible: IDs are content-addressed (`finding_id` includes `model_version`), output is a pure function of the request.

## Simulator compatibility

`bacteriocin_sim` returns the contract fields plus extensions, and its shape differs from the shared contract in three places. `adapters.py` handles them at the boundary, losslessly (richer detail is kept as extra keys), and passes contract-shaped input through unchanged:

* quantities in `conditions` are `{"value", "unit"}` objects -> flattened to the contract's float plus `*_unit` field;
* `important_factors` are objects -> names kept as the contract's strings, full objects kept in `important_factor_details` (used for drivers and for `imputed_default` sources);
* `status: "failed"` -> reported as a **failed attempt**, not a negative finding: zero confidence, an `inconclusive` verdict whose basis says so, no comparison. Failed prior attempts are excluded from comparisons.

Two further behaviours follow from the simulator's documentation:

* `measurement.uncertainty` is a standard deviation of the *fraction* and collapses toward 0 or 1 as inhibition saturates, even when the model is very unsure. When `ci95_inhibition_fraction` is present and implies a wider spread, that sigma is used and the substitution is reported as an uncertainty. The real fixture shows why: inhibition 0.9997 with reported uncertainty 0.0019, but a 95% interval of 0.01-1.0.
* At the ceiling or floor the agent points to `predicted_log10_reduction_vs_control`; it surfaces `imputed_fields`, and the largest `uncertainty_components` source, as uncertainties.

Results that state a `target` (the simulator puts it in `conditions`) are only compared when species and strain match; this closes, for simulator results, the target gap noted below.

## Contract gaps noticed

Recorded here rather than edited into the shared contract, in the spirit of `docs/proposed-contract-changes.md` (outside this package):

1. `ExperimentResult` carries no target in the contract; comparison is per candidate unless the result states one (as the simulator's does).
2. `important_factors` is a list of strings in the contract and a list of objects in the simulator; the contract has no direction, size or method.
3. Hypothesis status vocabularies differ: `CompetingHypothesis.status` is `open | supported | contradicted`; this agent returns `supported | weakened | inconclusive` plus an evidence strength (`weakened` + `strong` ~ `contradicted`).
4. The contract has no replicate count or seed on results, so replication cannot raise confidence.

## Known limits

* Categorical conditions (medium, growth phase) must match for a comparison to be controlled but are not themselves analysed as variables.
* Cross-target comparison is only checked when results state their target (simulator results do); otherwise comparison is per candidate.
* Two-point relationships say nothing about shape; the agent states this as an uncertainty and asks for an intermediate point.
* Thresholds (`MIN_EFFECT = 0.05`, `Z = 2`, tolerance 0.15, confidence weights) are heuristics, defined as named constants and tested, not fitted to data.
