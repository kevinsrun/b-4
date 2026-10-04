# Integration & reliability audit

Baseline: `origin/main` @ `9e69be4`, Python 3.11, fresh venv, `pip install -e ".[dev,mcp]"`.
**538 passed, 1 skipped** in 190 s. Every package imports; no cross-package import cycles.
The suite was green because each agent was tested against its own fixtures. The defects below
live in the seams, which is why nothing caught them.

## Findings

| Sev | Finding | Status |
|---|---|---|
| **P1** | **Real-agent loop dies at iteration 2.** The planner crashes on simulator results (`must be real number, not dict`): the simulator reports `{"value","unit"}` quantities. The only real-agent test ran a single iteration. | Fixed |
| **P2** | **Literature evidence was discarded.** `LiteratureAgentAdapter`'s loop body was `append(...) if False else None`; the orchestrator state had no evidence list at all, so provenance of literature claims could not be preserved. | Fixed |
| **P2** | **Failed simulator runs were stored as results.** A batch with one failing member (`status="failed"`, no measurement) put that member in `state.results`; analysis then read a measurement that was not there. | Fixed |
| **P2** | **Corrupt state was accepted.** An agent could append a record that bypassed validation (empty id, status `PROVEN`, confidence 9.9, dangling references) and it stayed in state. Nothing re-validated after a dispatch. | Fixed |
| **P2** | **Confidence/probability fields unbounded** on `Candidate`, `Hypothesis`, `Finding`, `Review` (accepted -0.1 and 1.5). | Fixed |
| **P2** | **The real critic could not read simulator results**: it validated against the shared contract, logged "skipping unparseable result" and then blamed the claim for a missing citation. | Fixed (`shared/compat.py`) |
| **P2** | Audit log labelled provenance `EvidenceType.SIMULATION` instead of `simulation-derived`. | Fixed |
| **P2** | Simulation-provenance guard keyed on the `backend` string only. | Fixed (also checks the assay domain) |
| **P3** | `max_failures=N>3` never honoured: a retried failing agent tripped the cycle detector / visit cap first and the run reported `stopped` ("cycle") instead of `failed`. | Fixed |
| **P3** | A route to an unknown agent was retried until `max_failures`. A wiring error is not transient. | Fixed (immediate, structured) |
| **P3** | `python -m ...planner` read stdin at import; breaks any tool that imports every module. | Fixed |
| **P3** | No single demo command. | `python -m bacteriocin_lab` |
| **P3** | My own fresh-install test uninstalled the developer's editable install (`pip --prefix` replaces a same-named dist). | Fixed (`--ignore-installed`) + guard |
| **P1-class** | **The loop runs local re-implementations of Analysis, Critic and Knowledge, not the real agents.** | **Open: design decision. TECH_DEBT #1** |
| P2 | Two `ResearchState` types, two event logs; duplicate `ExperimentSpec/Result` definitions. | Open. TECH_DEBT #2, #3 |

## Not changed, on purpose
Public interfaces are unchanged. Additions only: `ResearchState.evidence`, `AgentRegistry.has()`,
`ResearchStateManager.add_evidence()` / `record_experiment_failure()`, `check_state_integrity()`,
`agents/planner/adapters.py`, `shared/compat.py`, `python -m bacteriocin_lab`. Behaviour that changed:
confidence-like fields now reject out-of-range values; a failed run is no longer stored as a result;
a post-dispatch integrity failure reverts the dispatch like any other failure.

## Your 29 tests: where they live
All in `bacteriocin_lab/tests/integration/`, using the real orchestrator with fixture specialists
(`orchestration/fakes`), plus the real agents where the point is the seam.

| # | Test | File |
|---|---|---|
| 1, 2, 3, 27, 28 | clean import, all agents import, schema round-trip, fresh install, demo | `test_integration_packaging.py` |
| 4, 5, 6, 7, 13, 14, 19, 20 | happy path, adaptive loop, result-dependent route, critic rejection, history, provenance, reproducibility, resume | `test_integration_loop.py` |
| 8, 9, 10, 11, 12, 15, 16, 17, 18, 21-26 | invariant failure, exception, malformed output, idempotency, retry, unknown route, missing input, loops, max failures, batch, empty evidence/candidate/experiment, no-mutation-on-failure, validation | `test_integration_failures.py` |
| (seams) | real planner survives iteration 2, critic reads simulator output, evidence recorded, ... | `test_integration_seams.py` |
| 29 | full regression | `pytest` |

Test 20 (resume): supported and tested. Resume re-enters routing at "evidence" (TECH_DEBT #5).
