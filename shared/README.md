# shared/

Schemas the agent packages agree on. This is a leaf package (`bacteriocin-shared`,
import `bacteriocin_shared`): it depends on pydantic only and must never import an
agent package.

## What is here

* **`research_state.py`** — the persistent scientific state (`ResearchState`), its
  event log entry (`StateEvent`), the records it holds (candidates, hypotheses,
  experiments, results, findings, relationships, evidence, questions, uncertainties,
  model versions, rankings) and the value a state operation returns
  (`UpdatedResearchState`). Written for, and consumed by, `packages/knowledge_agent`.

## What is deliberately NOT here

The contract types the agents already exchange — `ExperimentSpec`, `ExperimentResult`,
`Evidence`, the request/response envelopes. They currently live in two places:
`packages/bacteriocin_sim/bacteriocin_sim/schemas.py` defines them concretely, and
`packages/bacteriocin_discovery/src/bacteriocin_discovery/contract.py` describes its own
view of the same contract. Each module's docs (`CONTRACT.md`,
`docs/proposed-contract-changes.md`) record proposed changes rather than applying them
unilaterally — the right instinct, and the reason nothing has been moved here.

Promoting one module's schema module into the shared contract is a joint decision
between the two owners, not a mechanical refactor: it fixes which optional extensions
become canonical, and both modules' validators and tests depend on the answer. Adding a
*new* type here (the research state) fixes nothing about the existing ones, which is why
it can happen now. The research state therefore carries specs, results and evidence as
plain JSON (`dict`) exactly as the producing agents emitted them; it never imports their
models and so cannot compete with them.

## Layout

```
shared/
  pyproject.toml                    # name = "bacteriocin-shared"
  bacteriocin_shared/
    __init__.py
    research_state.py
  tests/
```

It is a member of the root uv workspace and is put on the `PYTHONPATH` of every MCP
server that needs it by `install.py`.
