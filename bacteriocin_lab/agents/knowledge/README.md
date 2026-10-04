# Knowledge / Research-State Agent

The persistent scientific state of the B-4 discovery programme. It can reconstruct **what the
system believed, why it believed it, which experiments produced which results, what evidence was
used, which hypotheses survived, which candidates were rejected, and what is still uncertain.**

It is a structured state manager, not a memory chatbot: deterministic, no model, no free text
stored as belief. It records what the other agents concluded; it never does science and never
invents evidence.

```
candidate agent ──┐
experiment planner ├──► knowledge agent ──► ResearchState ──► "what next?" ──► planner / orchestrator
simulator ─────────┤        (events)           (projection)
result analysis ───┘
```

## The one rule: history is never overwritten

The authoritative record is an **append-only, hash-chained event log**. `ResearchState` is a pure
function of it. So:

* a hypothesis that goes `supported → weakened` keeps **both** statuses, in order, with the
  experiment and finding that triggered the change (`status_history`);
* any past turn can be rebuilt from the log alone (`state_at_iteration`, `state_at_event`);
* editing, deleting or reordering a past event changes every later hash and is detected;
* `state.json` is derived and never trusted: lose it and nothing is lost; edit it and the log wins.

```json
{"iteration": 2, "event": "hypothesis_update", "hypothesis_id": "hyp_a",
 "previous_status": "supported", "new_status": "weakened",
 "triggered_by": ["experiment:exp_2", "result:res_2", "finding:find_2"],
 "evidence_strength": "moderate", "reason": "weakened by moderate evidence"}
```

## What it tracks

| | |
|---|---|
| objective | every revision, never replaced |
| candidate registry | status history (`proposed → under_test → rejected`), rank history per iteration, hypotheses, experiments |
| hypothesis registry | status history, every observation (including inconclusive ones), counts, `contested`, evidence basis |
| experiment and result history | the spec and the result exactly as the producing agents emitted them |
| structured findings | the analysis's verdict, evidence strength, relationships, unexpected results, drivers |
| known variable-response relationships | per `(candidate, variable)`, with every change; only **controlled** findings count |
| evidence provenance | evidence type preserved verbatim; linked to hypotheses |
| rejected hypotheses / candidates | with the reason and the events that caused them |
| open questions | stored (from analyses) plus derived (untested or contested hypotheses, unresolved variables) |
| uncertainties | observed, **resolved** when a later analysis of the same scope stops reporting them, reactivated if they return |
| model versions | per component; a warning when results come from more than one |
| iteration number | one per closed loop turn |

## How a belief changes (the policy, `StatePolicy`)

* **inconclusive** analysis: the hypothesis is **untouched** (recorded as an observation).
* **supported**: status becomes `supported` (a `rejected` hypothesis is reopened).
* **weakened**: `weakened`, or `rejected` if the evidence was `strong` or the last two decisive
  results both weakened it.
* A candidate is `rejected` when **all** its hypotheses are rejected, and returns to `under_test`
  if one is reopened.
* **contested** = the two most recent decisive results disagree; agreement settles it again.
* A **failed attempt** (no measurement) is recorded as a failed experiment and an open question,
  never as a negative finding.
* Nothing becomes "validated": candidate status refuses `experimentally-validated` without a
  wet-lab-derived result, and the summary states the provenance of every result.
* Re-submitting an analysis already recorded changes **nothing** (no events, no counters).

All thresholds live in `StatePolicy` and each transition records its reason.

## Using it

```python
from bacteriocin_lab.agents.knowledge import JsonFileStateStore, ResearchStateManager, update_state

# persisted: the state lives in <dir>/events.jsonl (+ a derived state.json)
mgr = ResearchStateManager(JsonFileStateStore("artifacts/research_state"))
mgr.initialize({"goal": "does target density reduce inhibition?"})
mgr.register_candidates(candidate_agent_envelope)
mgr.record_experiment_plan(spec)
updated = mgr.update_state(analysis_envelope, result=experiment_result)
updated.hypothesis_transitions  # [{"previous_status": "supported", "new_status": "weakened", ...}]

mgr.get_candidate_history("cand_a")
mgr.get_hypothesis_history("hyp_a")
mgr.get_experiment_history()
mgr.get_open_questions()
mgr.summarize_current_state()
mgr.state_at_iteration(3)
mgr.verify_integrity()

# pure: no store, nothing written
updated = update_state(previous_state, analysis_envelope, result=experiment_result)
```

`update_state(previous_state, analysis_result, ...)` accepts the Result Analysis Agent's envelope
(or just its `decision`). Reasoning sub-agents may use looser JSON: it needs only `experiment_id`,
`result_id`, `candidate_id` and `hypothesis_status`; `contradicted` is read as `weakened` and
`untouched` as `inconclusive`, with a warning.

### From Omnigent

`knowledge_call(payload)` is JSON in, `AgentResponseEnvelope` out (the shared contract, imported
from `bacteriocin_lab.shared.contract`), and never raises. `payload["operation"]` is one of
`initialize_state`, `register_candidates`, `record_experiment_plan`, `register_evidence`,
`update_state`, `reject_candidate`, `close_question`, `get_candidate_history`,
`get_hypothesis_history`, `get_experiment_history`, `get_open_questions`,
`summarize_current_state`, `state_at_iteration`, `verify_integrity`. Pass `state_dir` (or set
`BACTERIOCIN_STATE_DIR`) to persist, or `previous_state` for pure mode.

The MCP server is `tools/launchers/knowledge.py` (declared by `python3 install.py`); its tools are
flat and annotated, replies are compact with the provenance disclaimer and warnings first, and
large inputs can be passed by path (the candidates launcher already returns `full_envelope_path`).
Orchestrator instructions are in the repository `AGENTS.md`.

### Concurrency and failure

Writers are serialised with a file lock and an optimistic check: pass `expected_event_count` and a
write is refused (`StateConflict`) if the log moved since you read it. An operation either commits
all of its events or none. Errors come back as structured envelopes (`error`, `conflict`,
`not_found`, `integrity_error`), never exceptions; `verify_integrity` diagnoses a damaged log
rather than failing on it.

## Layout

```
shared/schemas.py   the schemas (ResearchState, StateEvent, records, UpdatedResearchState)
agents/knowledge/
  events.py     hash-chained log: seal, verify_chain
  reducer.py    pure projection; validates every event against the current state
  session.py    sequences, seals and applies events for one operation
  ingest.py     candidate / plan / evidence / analysis -> events (all policy lives here)
  manager.py    pure operations + ResearchStateManager over a store
  store.py      StateStore, JsonFileStateStore (MVP), InMemoryStateStore
  queries.py    histories, open questions, summary
  agent.py      knowledge_call / KnowledgeAgent (the Omnigent interface)
  policy.py     StatePolicy
```

## Limits (honest)

* The status policy is a transparent heuristic over the analysis's verdict and evidence strength;
  it does not re-weigh the underlying data. "Weakened" means the analysis said so, not that the
  hypothesis is false, and the history keeps that distinction.
* Beliefs here are about what **simulations and models** showed; the state records provenance but
  cannot make a simulation a measurement.
* JSON/local persistence only. The file lock is POSIX; the log is rebuilt by replay on every load
  (fine for hundreds of events; a database or snapshotting would be the next step, behind the same
  `StateStore` interface).
* Open-question auto-closing is rule-based (a decisive controlled finding closes the matching
  "isolate this variable" question); free-text follow-ups stay open until closed explicitly.
* The shared contract types still live in two places (see `shared/README.md`); this package carries
  specs, results and evidence as plain JSON so it cannot compete with either.
