# Proposed changes to the shared system contract

Written for: the Omnigent orchestration owner and the other specialist-agent implementers.

The shared contract was implemented as given, in
[`src/bacteriocin_discovery/contract.py`](../src/bacteriocin_discovery/contract.py).
Nothing below has been changed unilaterally. Each item is a request, with the
workaround currently in place so the module runs without it.

---

## 1. `target.organism` vs `target.species` (naming conflict)

**Severity: low, but it will cause bugs.**

The contract's input example for this agent uses:

```json
"target": { "organism": "...", "strain": "..." }
```

while the shared `ExperimentSpec` uses:

```json
"target": { "species": "...", "strain": "..." }
```

Two names for the same field across one system invites silent `None` reads when
an agent passes a target through. Nothing errors; a species just goes missing.

**Current workaround:** `CandidateTarget.organism` matches this agent's example,
and the agent emits `target` into `recommended_next_action.payload_hint` using
its own field names. The experiment planner has to translate.

**Request:** standardise on `species` everywhere, since that is the taxonomically
precise term and it is what the required `ExperimentSpec` already uses. If
`organism` is preferred, change `ExperimentSpec` instead. Either resolution is
fine; having both is not.

---

## 2. `conditions` has no units

**Severity: high. This one can produce wrong science rather than a crash.**

`ExperimentSpec.conditions` specifies:

```json
"bacteriocin_concentration": null,
"target_cell_density": null,
"incubation_time": null
```

with no units. Bacteriocin concentrations appear in the literature as nM, µg/mL,
IU/mL, AU/mL and MIC multiples, and these differ by orders of magnitude. Cell
density appears as CFU/mL and as OD600, which are not interconvertible without a
strain-specific calibration. Incubation time appears in minutes and hours.

A unitless `50.0` is not interpretable, and two agents that assume different
units will silently disagree. Because the result metric is dose-dependent, that
disagreement corrupts the dose-response relationship the whole system exists to
learn.

**Current workaround:** `ExperimentConditions` in this module adds optional
`concentration_unit`, `target_cell_density_unit` and `incubation_time_unit`
fields. These are additive and safe for agents that ignore them, but they are
*optional*, so they do not actually prevent the failure.

**Request:** make unit fields required alongside each quantity, or mandate
canonical units in the contract (suggest: nM for concentration, CFU/mL for
density, hours for time) and state that explicitly.

---

## 3. `ExperimentResult.measurement` has three overlapping activity fields

**Severity: medium.**

```json
"predicted_inhibition_fraction": null,
"predicted_survival_fraction": null,
"predicted_activity": null
```

`inhibition_fraction` and `survival_fraction` are usually complements, but the
contract does not say so, nor which is authoritative when both are set and they
do not sum to 1. `predicted_activity` is undefined in scale and direction.

Any agent learning from accumulated results has to guess which field to read.

**Request:** either declare `predicted_inhibition_fraction` the single canonical
readout with the others derived, or state the invariant
(`survival = 1 - inhibition`) and define `predicted_activity`'s units and
direction.

---

## 4. No `confidence` on `ExperimentResult`

**Severity: medium.**

`measurement.uncertainty` exists but is unconstrained and un-described. For a
simulation backend, the useful quantity is usually an interval or a standard
deviation, not a scalar.

Agent design rule 4 requires every agent to return explicit uncertainty, so a
result from the simulation adapter should carry it in a defined form.

**Request:** specify `uncertainty` as a standard deviation on the same scale as
the measurement, or replace it with an explicit interval
(`{"low": 0.3, "high": 0.7, "kind": "95%-ci"}`).

---

## 5. Evidence has no defined shape

**Severity: medium.**

The common envelope carries `"evidence": []` but never defines an evidence
object, while design rules 5, 7 and 8 require preserved provenance, persistent
`evidence_id`s, and clean separation of literature / database / model /
simulation / inferred / wet-lab provenance. Those obligations cannot be met
against an undefined item.

**Current workaround:** `contract.Evidence` defines `evidence_id`,
`evidence_type`, `claim`, `source`, `confidence`, `subject_ids` and
`retrieved_at`, with `extra="allow"` so other agents can add fields. This agent
also reads an optional `candidate` payload off an evidence item as the handoff
convention from a literature-mining agent.

**Request:** promote something like this `Evidence` model into the shared
contract, so every agent reads and writes the same provenance record. Also
please confirm or replace the `evidence.candidate` handoff convention.

---

## 6. `uncertainties` is typed as a list of strings by example

**Severity: low.**

The output example implies `"uncertainties": []` holds strings. Strings are not
machine-actionable: the orchestrator cannot tell a high-severity data gap that
should trigger more evidence gathering from a routine caveat.

**Current workaround:** `contract.Uncertainty` provides `kind`, `description`,
`affects` and `severity`, and `AgentResponseEnvelope.uncertainties` accepts
`str | Uncertainty` so plain strings from other agents still validate.

**Request:** adopt the structured form, keeping the string union for
compatibility.

---

## 7. `assay_domain` vocabulary is not enumerated

**Severity: low.**

`"assay_domain": "simulated_in_vitro"` appears as a default without the set of
permitted values. Since a future wet-lab adapter must deliver results through
the same `ExperimentResult`, this field is how an analysis agent tells a
simulated observation from a real one — which makes it load-bearing for design
rule 9.

**Current workaround:** this module defines
`AssayDomain = Literal["simulated_in_vitro", "simulated_in_vivo_like", "in_vitro", "in_vivo"]`.

**Request:** fix the vocabulary in the shared contract, and state that
`evidence_type` must agree with it (an `in_vitro` assay_domain cannot carry
`evidence_type: "simulation-derived"`).

---

## 8. Nothing structurally prevents a validation claim

**Severity: high, and it is the rule most worth hardening.**

Rule 9 says no agent may present simulated or predicted results as
experimentally validated, but the contract has no field that carries validation
state, so the rule is only convention. An agent that writes
`"evidence_type": "wet-lab-derived"` onto a simulated result breaks the
scientific integrity of the whole system, and nothing catches it.

**Current workaround:** `CandidateProposal.validation_status` is validated to
reject `"experimentally-validated"` from this agent, and
`contract.EXPERIMENTALLY_VALIDATED_EVIDENCE` plus the
`is_experimentally_validated` properties give downstream agents one place to
check rather than string-matching.

**Request:** add `validation_status` to the shared contract, and have Omnigent
enforce at the tool boundary that only the wet-lab adapter may emit
`wet-lab-derived` or `experimentally-validated`. A rule this important should be
structural, not advisory.

---

## 9. No defined shape for `research_state`

**Severity: medium.**

`research_state` is `{}` in the envelope, but the loop depends on it: step 7 is
"update the research state" and step 8 is "decide what experiment to run next".
Every agent currently has to invent its own reading of it, which makes the state
unshareable in practice.

**Current workaround:** this agent does not read `research_state` at all. It
derives everything it needs from `previous_results`, `evidence` and
`competing_hypotheses`, so it cannot be broken by another agent's
interpretation. The cost is that it cannot use accumulated knowledge that lives
only in the state object.

**Request:** define a minimal shared shape — at least
`tested_candidate_ids`, `open_hypotheses`, `refuted_hypotheses` and
`iteration` — so agents can read each other's contributions.
