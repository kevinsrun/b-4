# shared/

Types and helpers every agent agrees on. It depends on pydantic only and must never
import an agent or `orchestration`.

## What is here

* **`schemas.py`** — the persistent scientific state (`ResearchState`), its event log
  entry (`StateEvent`), the records it holds and the value a state operation returns
  (`UpdatedResearchState`). Consumed by `agents/knowledge`.
* **`enums.py`** — the status vocabularies (`HypothesisStatus`, `CandidateStatus`, ...).
* **`config.py`** — repo-wide constants (`SCHEMA_VERSION`).
* **`contract.py`** — the experiment contract: `ExperimentSpec`, `ExperimentResult`,
  `Evidence`, the request/response envelopes. Moved here from the candidate agent so
  that no agent has to import another to speak the contract.
* **`ids.py`** — content-addressed, reproducible ids.

## Known duplication

The contract still exists in three places, and moving files did not reconcile them:
`agents/simulator/schemas.py` (the simulator's concrete models), `shared/contract.py`,
and `orchestration/types.py`. Choosing which optional extensions become canonical
changes validators and tests in every owner, so it is a separate decision recorded in
`docs/agents/simulator-contract.md` and `docs/proposed-contract-changes.md`.
The research state carries specs, results and evidence as plain JSON (`dict`) exactly
as the producing agents emitted them, so it never competes with those models.
