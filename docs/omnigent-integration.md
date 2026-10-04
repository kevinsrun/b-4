# Omnigent integration notes

Written for: whoever wires this agent into the Omnigent orchestration layer.

The agent is a pure function of its request plus an injected knowledge source.
It holds no state between calls, starts no background work, and never calls
another agent. You own the loop; it answers one question.

---

## 1. Registering the tool

```python
from bacteriocin_lab.agents.candidate import generate_candidates

# JSON in, JSON out. Never raises on bad input.
omnigent.register_tool(
    name="generate_candidates",
    fn=generate_candidates,
    description=(
        "Propose a ranked, diverse set of bacteriocin candidates worth testing next, "
        "each with a falsifiable hypothesis. Proposals only -- never evidence of activity."
    ),
)
```

To inject a production knowledge source, bind it once:

```python
from functools import partial
from bacteriocin_lab.agents.candidate import CandidateGenerationAgent

agent = CandidateGenerationAgent(knowledge_source=BactibaseSource(...))
omnigent.register_tool(name="generate_candidates", fn=agent.run_envelope)
```

Construct the agent **once** and reuse it. `JsonFileKnowledgeSource` caches
records on first read, so a fresh agent per call re-parses the dataset.

### Request shape

Minimum viable request — only `target.organism` is required:

```json
{ "target": { "organism": "Listeria monocytogenes" } }
```

A realistic one:

```json
{
  "research_objective": { "goal": "..." },
  "target": { "organism": "Listeria monocytogenes", "strain": "EGD-e", "gram": "positive" },
  "desired_behavior": {
    "high_inhibition": true,
    "ph_range": [6.0, 7.5],
    "target_cell_density": 100000000,
    "temperature_c": 37,
    "assay_domain": "simulated_in_vitro"
  },
  "constraints": { "max_candidates": 5, "diversity_weight": 0.3 },
  "previous_results": [ /* ExperimentResult objects */ ],
  "competing_hypotheses": [ /* see section 3 */ ],
  "evidence": [ /* Evidence objects */ ]
}
```

**Always pass `gram`.** Without it the envelope-accessibility reasoning is
skipped entirely, and a Gram-negative-specific candidate can rank highly against
a Gram-positive target on information gain alone.

---

## 2. Closing the loop

The contract requires that a result can change the next decision. Two fields do
that, and the agent is only as good as what you feed back.

### `previous_results` — feed back every result

Pass the `ExperimentResult` objects as they come out of the simulation adapter.
The agent reads `candidate_id` from each one and drops the novelty of anything
already tested to zero, which pushes the next iteration onto new ground.

```python
request["previous_results"] = research_state.all_results  # not just the last one
```

Passing only the most recent result makes the agent re-propose things tested
three iterations ago.

### `exclude_candidate_ids` — retire what is settled

Novelty decay is a soft signal. When a candidate is genuinely finished —
confirmed, refuted, or ruled out on other grounds — exclude it outright:

```python
request["constraints"]["exclude_candidate_ids"] = research_state.settled_candidate_ids
```

Exclusions appear in `decision.rejected` with a reason, so the audit trail
survives.

---

## 3. Getting real value out of hypothesis discrimination

This component scores **0 for every candidate** unless you pass
`competing_hypotheses` with machine-readable discriminating features. On a cold
start that is correct and the agent reports it as a `data-gap` uncertainty. But
if you never populate it, you are running the agent with 10% of its weight
permanently inert.

A usable hypothesis needs `discriminating_feature` (any numeric field on
`PeptideFeatures`) and `favourable_range`:

```json
"competing_hypotheses": [
  {
    "hypothesis_id": "hyp_charge_driven",
    "statement": "Activity is limited by electrostatic association with the anionic envelope.",
    "discriminating_feature": "net_charge",
    "favourable_range": [3.0, 12.0],
    "status": "open"
  },
  {
    "hypothesis_id": "hyp_insertion_driven",
    "statement": "Activity is limited by membrane insertion; net charge is largely irrelevant.",
    "discriminating_feature": "net_charge",
    "favourable_range": [-5.0, 1.0],
    "status": "open"
  }
]
```

Available features: `net_charge`, `charge_density`, `gravy`,
`hydrophobic_fraction`, `aromatic_fraction`, `sequence_length`,
`molecular_weight`, `cysteine_count`, `max_disulfide_bonds`. Numeric fields in a
candidate's `known_stability` also resolve.

Set `status` to `supported` or `contradicted` once an experiment settles a
hypothesis; closed hypotheses are ignored. **The analysis agent should write
these back** — that is the mechanism by which the loop narrows rather than
wanders.

---

## 4. Handing candidates to the experiment planner

`recommended_next_action.payload_hint` carries what the planner needs:

```json
{
  "candidate_ids": ["cand_..."],
  "hypothesis_ids": ["hyp_..."],
  "target": { "organism": "...", "strain": "...", "gram": "positive" },
  "suggested_sweeps": ["bacteriocin_concentration", "target_cell_density", "ph"],
  "assay_domain": "simulated_in_vitro"
}
```

Two things to carry across:

**Translate `target.organism` to `target.species`.** The contract uses both names
for the same field — see [proposed-contract-changes.md](proposed-contract-changes.md#1-targetorganism-vs-targetspecies-naming-conflict).
Until that is resolved the planner must map it, or the species silently becomes
`None`.

**Honour the sweep.** Each hypothesis carries
`predicted_inhibition_fraction` and a `falsified_if` clause written against *a
concentration range*, not a single value. A single-point experiment cannot
falsify it, so the loop learns nothing. Build the `ExperimentSpec` set as a
sweep.

---

## 5. Reading the output safely

### Never treat this output as a finding

Every emitted `Evidence` is `evidence_type: "inferred-hypothesis"`, every
candidate is `validation_status: "unvalidated"`, and every
`predicted_inhibition_fraction` is a **heuristic prior**, not a measurement.

Guard on it rather than trusting convention:

```python
from bacteriocin_lab.shared.contract import Evidence

for item in (Evidence.model_validate(e) for e in response["evidence"]):
    assert not item.is_experimentally_validated
```

If the analysis agent ever reads these priors as observations, the system will
confirm its own guesses. Keep them in separate stores.

### `confidence` means "worth testing", not "likely active"

Both `envelope.confidence` and each candidate's `confidence` mix in
`information_gain`. A candidate can score *high* precisely because its outcome is
uncertain. Do not threshold on it as a potency estimate.

### Surface the warnings

`warnings` carries unverified sequences, post-translational-modification caveats
and computationally modified candidates. These are the cases where a
confident-looking number is not trustworthy. Log them; do not swallow them.

### Act on high-severity uncertainties

`uncertainties[].severity == "high"` is worth routing on. The two that fire in
practice:

- **missing `target_cell_density`** → the planner must sweep density, since
  inhibition is dose-per-cell dependent and otherwise unpredictable
- **heuristic promise scores** → always present; clears only when
  `score_promise` is replaced with a model fitted to accumulated results

---

## 6. Tuning

```json
"constraints": {
  "max_candidates": 5,
  "diversity_weight": 0.3,
  "min_total_score": 0.0,
  "scoring_weights": {
    "promise": 0.35, "information_gain": 0.20, "novelty": 0.15,
    "condition_fit": 0.15, "hypothesis_discrimination": 0.10, "uncertainty": 0.05
  }
}
```

Weights are normalised, so only ratios matter. Suggested campaign arc:

| Phase | Shift | Why |
|---|---|---|
| Early / broad | `information_gain` ↑, `novelty` ↑, `diversity_weight` → 0.4-0.5 | Map the space; avoid anchoring on one family |
| Mid / hypothesis-driven | `hypothesis_discrimination` ↑ to 0.3+ | Settle open questions rather than accumulate points |
| Late / optimisation | `promise` ↑, `condition_fit` ↑, `diversity_weight` → 0.1 | Refine the leading family under realistic conditions |

`diversity_weight = 0` is a plain score sort. Raise it when the returned set
keeps clustering in one class.

---

## 7. Reproducibility

Identical input gives byte-identical output, and IDs are content-addressed
BLAKE2b digests — so the same peptide from two sources collapses to one
`candidate_id`, and IDs are stable across processes and machines.

For a reproducible campaign record, store per call:

- the full request payload (`artifacts.run_id` is its content hash)
- `artifacts.knowledge_source` and the dataset version behind it
- `model_version` (currently `candidate-generation/0.1.0`)
- `artifacts.scoring_weights` as normalised

`MODEL_VERSION` is bumped on any change that can alter output for identical
input. Treat results produced under different `model_version` values as
non-comparable.

---

## 8. Boundaries

What this agent will not do, by design:

- **No simulation or potency prediction.** `predicted_inhibition_fraction` is a
  prior shrunk toward 0.5; sharpening it is the simulation agent's job.
- **No orchestration.** `recommended_next_action` is advisory. The agent never
  invokes another agent.
- **No de novo sequence generation.** Only conservative variants of
  characterised parents, and only when explicitly enabled.
- **No `research_state` reads.** It derives everything from `previous_results`,
  `evidence` and `competing_hypotheses`, so another agent's interpretation of the
  state object cannot break it. Pass results explicitly.
- **No wet-lab claims, ever.** Structurally prevented at the schema level.

---

## 9. Checklist before running a campaign

- [ ] Verify the seed sequences, or inject a real knowledge source
      (`scripts/verify_seed_sequences.py`)
- [ ] Pass `target.gram` on every request
- [ ] Feed back **all** `previous_results`, not just the latest
- [ ] Have the analysis agent write `competing_hypotheses` with
      `discriminating_feature` and `favourable_range`
- [ ] Mark settled hypotheses `supported`/`contradicted`
- [ ] Translate `organism` → `species` for the experiment planner
- [ ] Build concentration **and** density sweeps, not single points
- [ ] Keep inferred priors in a separate store from simulation results
- [ ] Log `warnings` and route on high-severity uncertainties
- [ ] Record `model_version` with every stored result
