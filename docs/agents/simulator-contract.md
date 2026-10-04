# Contract compliance and proposed extensions

This module implements the **simulation experiment backend** of the Omnigent
bacteriocin-discovery system. This document records exactly how it sits against
the shared system contract, and — importantly — lists the schema changes it
would *like*, without having applied any of them unilaterally.

## 1. What this module is, and is not

| | |
|---|---|
| **Scientific responsibility** | Given a bacteriocin, a target organism and a set of biological conditions, predict the antimicrobial response as a continuous, uncertainty-quantified value. |
| **Agent name** | `simulation_experiment_backend` |
| **Evidence class produced** | `simulation-derived`, always |
| **Does not** | gather evidence · form hypotheses · design or select candidates · choose the next experiment (it only *recommends*) · hold state across calls · orchestrate anything |

## 2. Shared-contract conformance

### Agent design rules

| Rule | How it is met |
|---|---|
| 1. One scientific responsibility | Execute experiments. Nothing else. |
| 2. Tool-callable interface | `run_experiment`, `run_experiments`, `run_agent`, plus a CLI (`python -m bacteriocin_lab.agents.simulator`). |
| 3. Structured JSON I/O | Pydantic v2 models throughout; `model_json_schema()` exported via `bacteriocin-sim schema`. |
| 4. Explicit uncertainty | `measurement.uncertainty`, `ci95_inhibition_fraction`, `sigma_logit_inhibition`, a per-source `uncertainty_components` breakdown, and a scalar `confidence`. |
| 5. Evidence provenance | `parameter_provenance` names the origin of every model input; `uncertainty_components` names every variance source. |
| 6. No hidden state | Adapters and the agent are stateless; the parameter set is content-hashed into every result. |
| 7. Persistent IDs | `experiment_id`, `hypothesis_id`, `candidate_id` pass through; `result_id` and `evidence_id` are **deterministic hashes** so re-running an experiment does not duplicate the research state. |
| 8. Distinguish evidence classes | `EvidenceType` enum covers all six classes; this backend emits only `simulation-derived`, and labels curated priors `database-derived` and descriptors `model-predicted` inside the provenance block. |
| 9. Never claim validation | Enforced in the schema: `ExperimentResult` **rejects** `evidence_type="wet-lab-derived"` and **rejects** `validated_experimentally=True`. Every result also carries an explicit caveat warning. |
| 10. Independently callable | No orchestrator import; no dependency on any other agent. |
| 11. Modular | Downstream agents read `ExperimentResult` only. The mechanism trace is additive and ignorable. |
| 12. Validation and error handling | Field validators plus three error classes (`SpecValidationError`, `BackendUnavailableError`, `SimulationError`). Batch execution isolates per-spec failures into `status="failed"` results. |
| 13. Reproducible | Fully deterministic; no RNG anywhere in the forward model. `reproducibility` carries `spec_hash`, `parameter_set_hash`, `code_version`. |
| 14. Stable interface | Every contract field is present with its contract name; extensions are optional; unknown incoming keys are preserved, not dropped. |

### Experiment interface

`run_experiment(ExperimentSpec) -> ExperimentResult` is implemented, with
backend routing driven by `conditions.assay_domain`:

| `assay_domain` | backend |
|---|---|
| `simulated_in_vitro`, `simulated_in_vivo_like` | `simulation` (available) |
| `wet_lab_in_vitro`, `wet_lab_in_vivo` | `wet_lab` (declared, `available=False`) |

`WetLabAdapter` already implements the full `ExperimentAdapter` interface and
reports its unavailability through `capabilities()`. The seam exists today, so
connecting a laboratory is an adapter implementation rather than a refactor,
and **no downstream agent changes**.

### Condition variables honoured

Every variable named in the shared contract is modelled, not merely accepted:

bacteriocin identity · sequence · structural/physicochemical properties ·
target species · target strain · bacteriocin concentration · target cell
density · producer cell density · growth phase · pH · temperature · medium ·
ionic conditions · incubation time · assay type · in-vitro context · simulated
in-vivo-like context · known resistance/susceptibility factors.

**Cell density is a first-class variable**, as required. It enters through a
Langmuir mass balance: target cells carry a finite number of peptide-binding
sites, so a high inoculum titrates free peptide out of solution. The model
reproduces a ~5-fold rise in apparent IC50 from 1e4 to 1e9 CFU/mL without any
ad-hoc term. Density is also unit-carrying (`cfu_per_ml`, `cells_per_ml`,
`od600`, `log10_cfu_per_ml`) because a silent OD-for-CFU error is nine orders
of magnitude.

## 3. Proposed contract extensions — NOT applied unilaterally

Each item below is implemented as an **optional, additive** field: a producer
that knows only the shared contract still validates, and every contract field
keeps its name, nesting and default. Nothing existing has been renamed,
removed or re-typed. These are proposals for the shared schema.

### 3.1 `ExperimentSpec.candidate` — the only one that is near-essential

**Problem.** The shared `ExperimentSpec` identifies the molecule under test by
`candidate_id` alone. A forward model cannot predict activity from an opaque
identifier: it needs at minimum the sequence, ideally the structural class.

**Current workaround (no schema change required of anyone).** The backend looks
for the candidate's content in three places, in order:

1. `spec.candidate` (optional inline block);
2. a `candidate_registry: {candidate_id: CandidateSpec}` passed alongside the
   specs — this requires **no spec change at all** and is the recommended
   integration;
3. nothing — in which case the simulation still runs on a generic
   small-bacteriocin prior, flags `no_candidate_sequence` as a dominant
   uncertainty source, warns that *the result is not specific to the named
   candidate*, and recommends `resolve_candidate_sequences` as the next action.

**Proposal.** Either standardise the optional `candidate` block, or standardise
a shared candidate store that any agent can resolve `candidate_id` against. The
second is cleaner and keeps `ExperimentSpec` small. This is a decision for
whoever owns the candidate-design module, not for this one.

### 3.2 Units on quantities

**Proposal.** Allow `bacteriocin_concentration`, `target_cell_density` and
`producer_cell_density` to be `{"value": float, "unit": str}` as well as a bare
number. Bare numbers remain valid and are interpreted with a documented default
unit **plus a warning**.

**Rationale.** These three fields are the ones where an unstated unit changes
the answer by orders of magnitude. Activity units (`iu_per_ml`, `au_per_ml`)
are deliberately **refused** rather than silently converted, since they are
assay-defined and not reducible to molarity.

### 3.3 `Target.resistance_factors`

**Proposal.** A list of `{name, effect, magnitude_log10_mic?, evidence_type,
evidence_id?}`. The contract already names "known resistance/susceptibility
factors" as a context variable but gives no field for them.

**Rationale.** Resistance determinants are the single largest source of
strain-level variation (`nsr` ≈ +1.5 log10 MIC; Man-PTS loss ≈ +2.2 for class
IIa). Carrying `evidence_id` keeps the provenance chain intact back to the
literature agent. Supplying a magnitude is optional — the backend substitutes a
curated value and records the imputation.

### 3.4 Additive result fields

`Measurement` keeps all four contract fields and adds, all nullable:
`primary_metric`, `ci95_inhibition_fraction`, `sigma_logit_inhibition`,
`uncertainty_log10_reduction`, `predicted_log10_reduction_vs_control`,
`predicted_log10_change_from_inoculum`, `predicted_mic_um`,
`predicted_zone_diameter_mm`, `free_peptide_concentration_um`,
`kill_rate_per_h`, `dose_over_mic`.

**Rationale.** The contract asks for continuous values rather than
active/inactive labels. `predicted_inhibition_fraction` alone cannot carry a
continuous signal once it saturates at ~1.0, which happens for most
above-MIC conditions. `predicted_log10_reduction_vs_control` stays informative
there, and `predicted_mic_um` is the quantity the literature actually reports,
making simulation and literature evidence directly comparable.

`ExperimentResult` adds: `status`, `hypothesis_id`, `backend`, `assay_domain`,
`assay_type`, `confidence`, `validated_experimentally` (always `False`, and
schema-enforced), `uncertainty_components`, `parameter_provenance`,
`mechanism_trace`, `reproducibility`, `error`, `created_at`.

`ImportantFactor` is given a structure rather than being a bare string list:
`{factor, sensitivity, direction, value, unit, source, rationale}`. The `unit`
and `source` fields are what make it actionable — `source="imputed_default"` on
a high-sensitivity factor tells the planner that the prediction describes an
assumed default rather than a defined experiment.

### 3.5 `conditions.assay_type` and `incubation_time_unit`

**Proposal.** `assay_type` (MIC broth microdilution / microtiter growth
inhibition / time-kill / agar well diffusion / spot-on-lawn) and an explicit
`incubation_time_unit`.

**Rationale.** The contract lists "assay type" as a context variable but has no
field for it, and the assay determines *which observable is the primary one*.
A time-kill and a growth-inhibition assay on identical conditions are not the
same measurement. `incubation_time` without a unit is ambiguous between hours
and minutes.

### 3.6 For a future wet-lab adapter

When the wet-lab backend is implemented it will need scheduling metadata
(plate, well, operator, instrument, run date) on the spec, and empirical
replicate statistics on the result. Both should be added the same additive way,
and documented here rather than applied unilaterally.

## 4. Things this module deliberately does not do

* **It does not calibrate itself.** All priors are coarse, uncalibrated
  literature estimates. They live in one hashable `ParameterStore` that accepts
  a deep-merged override layer, so the knowledge-update step of the loop can
  install refitted values without touching model code — and every result records
  which parameter set produced it.
* **It does not decide.** `recommended_next_action` is a recommendation derived
  from its own sensitivity and uncertainty output. The planner and Omnigent are
  free to ignore it.
* **It does not dress up a guess.** When the candidate, the organism or the
  conditions are unknown, it still returns a result — with the uncertainty that
  honesty requires, a named reason, and a warning that says so.
