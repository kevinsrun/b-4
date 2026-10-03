# bacteriocin-sim

The **computational simulation experiment backend** for the Omnigent
autonomous bacteriocin-discovery lab.

One job: given a bacteriocin, a target organism and a set of biological
conditions, predict the antimicrobial response as a continuous,
uncertainty-quantified value — and say how much it actually knows.

```
run_experiment(ExperimentSpec) -> ExperimentResult
```

It does not gather evidence, form hypotheses, design candidates, or choose what
to run next. See [CONTRACT.md](CONTRACT.md) for conformance against the shared
system contract and for proposed (not unilaterally applied) schema extensions.

> Every output of this module is **simulation-derived**. It is a hypothesis to
> be tested, never an experimental observation. The schema refuses to let a
> result claim otherwise.

## Install

```bash
uv venv && uv pip install -e ".[dev]"     # or: pip install -e ".[dev]"
```

Only runtime dependency: `pydantic>=2.7`.

## Use

### From Python

```python
from bacteriocin_sim import run_experiment

result = run_experiment({
    "experiment_id": "exp-0001",
    "hypothesis_id": "hyp-0001",
    "candidate_id": "cand-nisin-a",
    "candidate": {
        "sequence": "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK",
        "bacteriocin_class": "class_I_lantibiotic",
    },
    "target": {"species": "Listeria monocytogenes", "strain": "EGD-e"},
    "conditions": {
        "bacteriocin_concentration": {"value": 1.0, "unit": "uM"},
        "target_cell_density": {"value": 1e6, "unit": "cfu_per_ml"},
        "ph": 6.5,
        "temperature_c": 30.0,
        "medium": "bhi",
        "ionic_conditions": {"nacl_mm": 85.0, "mgcl2_mm": 1.0},
        "incubation_time": 8.0,
        "growth_phase": "exponential",
        "assay_domain": "simulated_in_vitro",
        "assay_type": "microtiter_growth_inhibition",
    },
})

print(result.measurement.predicted_inhibition_fraction)   # 0.9997
print(result.measurement.predicted_mic_um)                # 0.52
print(result.measurement.ci95_inhibition_fraction)        # [0.0125, 1.0]
print(result.important_factors[0].factor)                 # incubation_time_h
```

### Through the agent envelope

```python
from bacteriocin_sim import run_agent

output = run_agent({
    "research_objective": {...}, "research_state": {...},
    "constraints": {"max_experiments": 8},
    "experiment_specs": [spec_a, spec_b],
    "candidate_registry": {"cand-nisin-a": {"sequence": "ITSIS..."}},
})
```

Returns the common output shape: `agent`, `decision`, `evidence`, `confidence`,
`uncertainties`, `artifacts`, `warnings`, `recommended_next_action`.

A malformed spec inside the envelope becomes one `status="failed"` result; it
never sinks the batch.

### From the CLI

```bash
python -m bacteriocin_sim capabilities
python -m bacteriocin_sim schema experiment_spec
python -m bacteriocin_sim run   --spec examples/spec_nisin_listeria.json
python -m bacteriocin_sim run   --spec examples/spec_pediocin_resistance.json
python -m bacteriocin_sim agent --input examples/agent_envelope.json
python -m bacteriocin_sim sweep --spec examples/spec_nisin_listeria.json \
    --factor bacteriocin_concentration --values 0.05,0.1,0.25,0.5,1,2,5 --unit uM
python -m bacteriocin_sim selftest
```

### As an MCP server

This module is a *tool*, not an agent: it holds no conversation, runs no
model and takes no decision. So it is exposed to an orchestrator over MCP
rather than registered as an agent in its own right.

```bash
uv pip install -e ".[mcp]"
python3 ../../install.py                 # from the repo root: python3 install.py
omnigent run ../..                       # the lab bundle lives at the repo root
```

Tools: `capabilities` · `get_schema` · `run_experiment` · `run_experiments` ·
`run_agent` · `describe` · `selftest`. A `BacteriocinSimError` comes back as
its structured payload rather than as a protocol error, so the caller keeps
the distinction between a bad spec, an unavailable backend and a numerical
failure.

Both MCP SDK majors are supported: Omnigent 0.16 bundles mcp 1.30 (`FastMCP`),
a fresh install resolves 2.x (`MCPServer`).

The server is a transport and nothing else. `tests/test_mcp_server.py` asserts
a result obtained through MCP is byte-identical to the same result from the
direct API, and
the repo-root `README.md` and `tools/`
covers the wiring, the agent bundle, and why the generated declaration is not
committed.

## What the model actually computes

### 1. Potency — additive on the log10 MIC scale

```
log10 MIC_eff = curated organism prior
              + structural-class offset
              - cationicity term          (tanh-saturating, charge at the assay pH)
              - amphipathicity term       (Eisenberg hydrophobic moment)
              + length-mismatch term
              + receptor term             (missing Man-PTS / lipid II / OM receptor)
              + outer-membrane term       (Gram-negative LPS, relieved by EDTA)
              + resistance term           (named determinants, capped)
              + electrostatic term        (ionic screening, divalent competition)
```

log10 MIC is the scale on which susceptibility is reported and on which these
effects are roughly additive. Continuous descriptor terms are `tanh`-bounded
and the additive penalties are capped, so extrapolation degrades gracefully
rather than producing unphysical MICs.

Net charge is computed from the sequence at the *experiment's* pH via
Henderson–Hasselbalch — so pH acts on the peptide and on the organism
independently, as it does in reality.

### 2. Availability — the inoculum effect, from a mass balance

Target cells carry a finite number of peptide-binding sites, so free peptide
follows a Langmuir balance:

```
C_total = C_free + B_total · C_free / (Kd + C_free)
```

At 1e6 sites/cell this is negligible at 1e5 CFU/mL and reaches the
sub-micromolar range near 1e9 CFU/mL — which is why apparent potency depends on
inoculum. No ad-hoc density fudge factor is involved. Medium binding (casein,
fat, plastic) and protease activity scale availability and decay.

### 3. Kinetics — a coupled ODE, integrated to the readout

```
dP/dt  = -k_deg·P + in-situ production from producer cells
dNs/dt =  mu(N)·Ns - k_max·theta·phase·Ns
dNr/dt =  mu(N)·Nr - k_max·theta·phase·rho·Nr
theta  =  Hill(C_free, MIC_eff, h)
mu(N)  =  mu_max · f_T · f_pH · richness · (1 - N/Nmax)
```

integrated with fixed-step RK4 (step count a pure function of incubation time),
alongside an untreated control — because the reported observables are relative
to a control, exactly as a real growth-inhibition assay is.

This is an ODE rather than a static dose–response curve because peptide decay,
target regrowth and peptide titration are coupled *in time*. That coupling is
what makes incubation time a genuinely informative variable: the model
reproduces kill-then-regrowth, so a 6 h and a 24 h readout of identical
conditions are different measurements. A static Hill curve cannot do that, and
a result that cannot change with the readout time cannot change the loop's next
decision.

Growth and susceptibility use Rosso cardinal-parameter models for temperature
and pH, so an organism outside its growth range stops growing instead of
extrapolating nonsense — and the result says so in its warnings.

### 4. Uncertainty — accumulated from named sources

Variance is summed in quadrature on the **logit scale of the inhibition
fraction**, where the model's own error is roughly homoscedastic. Named
sources include model form, the organism's MIC prior, an unknown organism, a
missing candidate sequence, an uncertain structural class, each imputed
condition, each excursion outside the validated domain, poorly-constrained
medium properties, kill/regrowth-boundary timing, in-situ production rate, and
strain-level variation.

The MIC-prior contribution is propagated by **re-running the forward model**
with the dose shifted by ±1σ decades — a secant over the real uncertainty
range, not a local derivative. That matters: these priors span more than a
decade, and a prediction that looks locally flat can be far off its plateau one
sigma away. A local derivative would report false precision for exactly the
saturated predictions most at risk of being wrong.

The result is a model that knows where it is ignorant. Across a dose sweep,
confidence is *lowest at the MIC transition* and recovers well above it:

| dose (µM) | inhibition | 95% interval | confidence |
|---|---|---|---|
| 0.05 | 0.021 | [0.000, 0.884] | 0.251 |
| 0.25 | 0.531 | [0.000, 1.000] | 0.162 |
| 1.00 | 0.9997 | [0.013, 1.000] | 0.136 |
| 5.00 | 1.000 | [1.000, 1.000] | 0.382 |

### 5. Sensitivity — what to vary next

Every condition is perturbed and the model re-run, reporting
`d logit(inhibition)` per **natural step**: per decade for ratio-scale factors
(dose, cell density, time, salt), per a stated absolute step for interval-scale
factors (pH, temperature) — because `d/d ln(°C)` is meaningless on a scale with
an arbitrary zero. One logit unit is ≈ 0.43 log10 of survival.

Each factor is tagged with whether it was **provided or imputed**. An imputed
factor with high sensitivity is the single most useful thing this backend can
report: it means the prediction describes an assumed default rather than a
defined experiment, and `recommended_next_action` says exactly that.

## Scientific caveats

The structure of the model is defensible; **the numbers are coarse,
uncalibrated literature priors**, and nothing here has been fitted to a
specific dataset. Known limitations are declared in
`capabilities()["limitations"]` and include: post-translational modifications
are invisible to a primary-sequence model (so lantibiotic class inference is
weak); two-peptide class IIb systems are modelled as a single peptide; no
synergy between bacteriocins; no spatial structure, so agar-diffusion zone
diameters are extrapolated from a well-mixed result; strain variation enters
only through explicitly supplied resistance factors.

All priors live in one content-hashed `ParameterStore` with a deep-merge
override layer:

```python
run_experiment(spec, parameter_overrides={
    "targets": {"listeria monocytogenes": {"log10_mic_um_base": 0.3,
                                           "sigma_log10_mic": 0.2}}
})
```

Overriding changes the predictions *and* the `parameter_set_hash` stamped into
every result, so no result is ever ambiguous about which parameter set produced
it. This is the seam the knowledge-update step of the loop is meant to use.

## Reproducibility

No RNG anywhere in the forward model. Identical input yields byte-identical
output, and `result_id` / `evidence_id` are deterministic content hashes — so
re-running an experiment updates the research state instead of duplicating it.
Each result carries `spec_hash`, `parameter_set_hash` and `code_version`.

## Tests

```bash
python -m pytest tests -q          # 133 tests (18 need the [mcp] extra; skipped without it)
python -m bacteriocin_sim selftest # 14 scientific invariants
```

The invariants are *directional* checks — statements true of bacteriocin
biology that must therefore be true of any usable model of it. A failure means
the model is giving scientifically wrong answers regardless of how confident it
looks:

* dose–response is monotone, and zero dose gives zero inhibition
* raising the inoculum raises apparent resistance
* Gram-negatives are less susceptible, and EDTA relieves the barrier
* class IIa peptides need the mannose-PTS receptor (Listeria ≫ *S. aureus*)
* resistance determinants and divalent cations reduce activity
* stationary cells are more tolerant than exponential ones
* peptide-binding media (milk) reduce activity
* incubation time changes the readout
* uncertainty grows when inputs are unknown
* results are deterministic, and never claim experimental validation

## Layout

```
bacteriocin_sim/
  schemas.py          ExperimentSpec / ExperimentResult / agent envelopes
  api.py              run_experiment, run_experiments
  agent.py            Omnigent-callable agent wrapper
  registry.py         backend registration and assay-domain routing
  errors.py           SpecValidation / BackendUnavailable / Simulation
  cli.py              run · sweep · agent · schema · capabilities · selftest
  mcp_server.py       the same surface over MCP (optional [mcp] extra)
  selftest.py         the scientific invariants
  adapters/
    base.py           ExperimentAdapter: the one interface both backends share
    simulation.py     the required computational backend
    wet_lab.py        declared, unavailable, same interface
  model/
    peptide.py        sequence-derived descriptors (pure functions)
    parameters.py     curated priors, hashable, overridable
    environment.py    units, defaults, lookups, cardinal models, Langmuir
    potency.py        structure-activity log10 MIC model
    kinetics.py       coupled peptide/population ODEs
    uncertainty.py    variance budget and sensitivity analysis

```
