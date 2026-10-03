# Candidate Generation & Design Agent

One specialist module of an Omnigent-orchestrated autonomous bacteriocin-discovery
system. Given a scientific objective, evidence, open hypotheses, constraints and
previous results, it proposes a **ranked, diverse set of bacteriocin candidates
worth testing next**, each with a falsifiable hypothesis and explicit provenance.

It proposes. It does not simulate, does not predict potency, and never claims a
candidate works.

```
evidence ─┐
           ├─→ [candidate_generation_agent] ─→ ranked candidates + hypotheses ─→ experiment_planner
hypotheses ┘                                                                          │
     ▲                                                                                ▼
     └──────────────── research state ←── analysis ←── simulation ←────────────────────┘
```

## Install and run

Requires Python 3.11+ and Pydantic 2.

```bash
pip install -e ".[dev]"
pytest                                        # 168 tests
python3 examples/generate_candidates.py       # five worked scenarios
```

## Quick use

```python
from bacteriocin_discovery.candidate_agent import generate_candidates

response = generate_candidates({
    "target": {"organism": "Listeria monocytogenes", "strain": "EGD-e", "gram": "positive"},
    "desired_behavior": {
        "high_inhibition": True,
        "ph_range": [6.0, 7.5],
        "target_cell_density": 100_000_000,
        "temperature_c": 37,
    },
    "constraints": {"max_candidates": 5},
})
```

`response` is an `AgentResponseEnvelope` dict. It is always well-formed, including
on invalid input — see [Error handling](#error-handling).

## What the ranking actually optimises

This is the part worth reading. A candidate-selection agent that sorts by
predicted potency produces a **degenerate discovery loop**: it proposes the same
well-characterised family every iteration, each experiment confirms what was
already believed, and the research state stops moving.

So the score has six components, each in `[0, 1]`, combined under configurable
weights:

| Component | Default weight | What it measures |
|---|---|---|
| `promise` | 35% | Predicted biological usefulness against this target |
| `information_gain` | 20% | Expected reduction in uncertainty if tested |
| `novelty` | 15% | Dissimilarity to what has already been tested |
| `condition_fit` | 15% | Known stability vs. the requested assay conditions |
| `hypothesis_discrimination` | 10% | Power to separate competing open hypotheses |
| `uncertainty` | 5% | How little is known about this candidate |

Roughly half the weight sits on exploratory terms. Two mechanisms do the real
work:

**Information gain peaks on uncertain outcomes, not likely successes.** Treating
`promise` as a rough probability of a positive result, the term uses normalised
binary entropy `4p(1-p)`, which maximises at `p = 0.5`. A candidate that is
near-certainly active teaches almost nothing, and neither does one that is
near-certainly inactive. The most informative experiment is the one whose
outcome is genuinely in doubt.

**Hypothesis discrimination rewards candidates that split the hypotheses.** For
each open hypothesis naming a `discriminating_feature` and a `favourable_range`,
the agent checks whether the candidate falls inside it. A candidate that
satisfies some hypotheses and violates others is maximally decisive: whichever
way the experiment goes, some hypotheses lose. A candidate all hypotheses agree
on cannot separate them, however promising it looks.

Both terms are deliberately *non-monotonic in predicted strength*. That is the
point.

### Diversity: redundancy is about mechanism, not sequence

Ranking is not a sort. It is greedy maximal-marginal-relevance selection, because
the value of a *set* of experiments is not the sum of its members' values — ten
near-identical class IIa peptides answer close to one question.

An empirical finding shaped this. Two class IIa bacteriocins that both dock onto
Man-PTS (pediocin PA-1 and leucocin A) share only **~9% of their 3-mers** —
barely more than an unrelated lasso peptide at 0% — yet testing both answers
nearly the same scientific question. Raw sequence similarity badly understates
experimental redundancy.

So `experimental_redundancy` takes the strongest of three signals: k-mer
similarity, shared bacteriocin class, and shared receptor. `diversity_weight`
then trades score for coverage so the returned set spans families rather than
collapsing onto one.

## Scientific caveats that are enforced in code

These are the places where a plausible-looking number would have been wrong, and
the agent says so rather than reporting it quietly.

**Post-translational modification.** Class I lantibiotics (nisin), lasso
peptides and circular bacteriocins carry modifications that primary-sequence
formulas cannot see. Nisin A's unmodified sequence computes **3498 Da** against
a mature mass of **~3354 Da** — the eight dehydrations that form its thioether
rings each remove ~18 Da. `compute_features` attaches a caveat for these classes
instead of reporting a confident mass. There is a test asserting exactly this gap.

**Cell density is a real variable.** Bacteriocin activity is dose-*per-cell*
dependent, so the same concentration can clear a dilute culture and fail against
a dense one. A missing `target_cell_density` is reported as a **high-severity**
uncertainty, high density penalises candidates recorded as adsorbing or being
sequestered, and the recommendation to the planner always asks for a
concentration sweep rather than a single value.

**Envelope accessibility cuts both ways.** A Gram-negative target with no
recorded outer-membrane uptake route is penalised. The reverse is penalised
harder: a candidate whose uptake depends on an outer-membrane transporter (FhuA,
TonB, BtuB) against a Gram-positive target is not merely less effective — the
machinery is absent. Without this, microcin J25 ranked #2 against *Listeria*
purely on information gain.

**Species matching is conservative.** `Listeria monocytogenes` matches
`Listeria spp.` but *not* `Listeria innocua`. Bacteriocin spectra are frequently
species- and strain-specific, so genus-level inference would manufacture
evidence.

**Sequence verification.** The shipped seed dataset is marked
`"sequence_verified": false` on **every** record, because its sequences were
transcribed from secondary knowledge rather than fetched from a primary
database. One wrong residue silently corrupts mass, charge, GRAVY and every
derived score. Unverified sequences raise uncertainty, produce an output warning,
and appear as a failure mode on the candidate. Run:

```bash
pip install httpx
PYTHONPATH=src python3 scripts/verify_seed_sequences.py --write
```

**Do not treat the seed data as publication-grade until this passes.**

## Contract compliance

| Rule | How it is met |
|---|---|
| 1. One responsibility | Proposes candidates and hypotheses. No simulation, no orchestration. |
| 2. Tool-callable | `generate_candidates(payload) -> dict`. |
| 3. Structured JSON I/O | Pydantic models throughout; `model_dump(mode="json")` round-trips. |
| 4. Explicit uncertainty | Per-candidate `confidence`, six-way `ScoreBreakdown`, structured `uncertainties` with severity. |
| 5. Provenance preserved | `evidence_ids` on every candidate; emitted `Evidence` per proposal. |
| 6. No hidden state | Knowledge source is **injected**, named in `artifacts.knowledge_source`. The agent holds no mutable state between calls. |
| 7. Persistent IDs | `cand_`/`hyp_`/`ev_`/`run_` prefixes over BLAKE2b content hashes. |
| 8. Provenance types distinguished | Curated fields vs. `features.computed` (model-predicted) vs. hypotheses (inferred). |
| 9. Never claims validation | `validation_status` **rejects** `experimentally-validated` at the schema level. All emitted evidence is `inferred-hypothesis`. |
| 10. Independently callable | No dependency on any other agent. |
| 11. Modular | Downstream agents see only contract types. |
| 12. Validation and errors | Invalid input returns a well-formed envelope, never an exception. |
| 13. Reproducible | Content-addressed IDs, deterministic scoring, tie-breaks on `candidate_id`. Tested. |
| 14. Stable interface | Contract implemented as given; nine requested changes documented, not applied. |

Rule 9 is the one worth noting: it is enforced *structurally*. A
`CandidateProposal` cannot be constructed with
`validation_status="experimentally-validated"` — it raises `ValidationError`.

## Error handling

Nothing in the discovery loop should stop because one record is malformed.

| Failure | Behaviour |
|---|---|
| Invalid request | Well-formed envelope, `confidence=0`, reason in `warnings`. No exception. |
| Knowledge source unreachable | Warning; proceeds with caller-supplied candidates. |
| Non-standard residue in a sequence | That record enters `rejected` with a reason; the run continues. |
| Malformed `candidate_pool` entry | Same — per-record rejection. |
| Empty candidate pool | Recommends `evidence_gathering_agent` instead of the planner. |
| Malformed `previous_results` entry | Skipped silently; a bad result record must not stall the loop. |

Ambiguity codes (`X`, `B`, `Z`, `J`) are **rejected, not guessed** — substituting
a residue would corrupt every downstream calculation.

Everything dropped appears in `rejected` with a reason, so a run is auditable.

## Layout

```
src/bacteriocin_discovery/
  contract.py              Shared system contract (not ours to change)
  ids.py                   Content-addressed persistent IDs
  candidate_agent/
    agent.py               Orchestration and the tool interface
    schema.py              Candidate/request/response models
    features.py            Deterministic physicochemistry
    scoring.py             Six-component scoring, MMR selection
    hypotheses.py          Falsifiable hypothesis generation
    design.py              Conservative variants (stretch goal)
    knowledge.py           Pluggable knowledge sources
  data/seed_bacteriocins.json   Example dataset (unverified)
docs/
  omnigent-integration.md       How to wire this in
  proposed-contract-changes.md  Nine requested contract changes
```

## Inverse design (stretch goal)

Off by default; enable with `constraints.allow_sequence_modification`.

Scope is deliberately narrow. There is **no de novo generation** — emitting
plausible novel sequences without a trained generative model would manufacture
false confidence. Instead it proposes small, reversible variants of
well-characterised parents, and never alters conserved motifs (the YGNGV
pediocin box), cysteines (disulfide topology is load-bearing), prolines (turn
geometry) or the termini.

Variants come in **pairs** that bracket the parent's net charge — one raised, one
lowered. The pair is the useful unit: together they test whether activity tracks
charge at all, whereas a single variant cannot distinguish "charge matters" from
"this substitution happened to help".

Parents are chosen by how well characterised they are, not by predicted potency,
because a variant is only interpretable against a known baseline.

Every variant is `origin="modified"`, `sequence_verified=False`, carries its
substitutions in standard notation (`Q13K`), states its design intent, and
triggers an explicit warning.

## Extending

**Plug in a real database** — implement the `KnowledgeSource` protocol
(`source_name`, `records()`) and pass it to `CandidateGenerationAgent`. BACTIBASE
and BAGEL4 both fit.

**Replace the heuristics with a learned model.** The `promise` score is hand-set
physicochemistry and reported spectra, not a fitted model, and the agent reports
this as a high-severity `model-limitation` on every run. Once the loop has
accumulated simulation results, `score_promise` is the function to replace; the
six-component structure and everything downstream stay unchanged.

**Retune the objectives** — pass `constraints.scoring_weights`. The exploration
and exploitation terms are separately addressable, and `ScoreBreakdown` keeps the
components so a reviewer who disagrees with the weighting can recombine them
without re-running anything.

## Tests

168 tests. The ones that matter most defend behaviour rather than output shape:

- information gain peaks at `p = 0.5` and is symmetric about it
- a candidate satisfying *some* hypotheses beats one satisfying *all*
- diversity selection prefers a different family over a higher-scoring near-duplicate
- feeding back a result demotes the candidate that was tested
- `validation_status="experimentally-validated"` raises
- identical input gives byte-identical output
- the same peptide from two sources collapses to one candidate
- nisin's unmodified mass exceeds its mature mass by ~8 dehydrations
