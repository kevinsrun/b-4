# shared/

The contract types both packages agree on: `ExperimentSpec`,
`ExperimentResult`, `Measurement`, `EvidenceType` and friends — the formats
agents pass to each other.

**This directory is intentionally empty of code right now.**

Those types currently live in two places:
`packages/bacteriocin_sim/bacteriocin_sim/schemas.py` defines them concretely,
and `packages/bacteriocin_discovery/src/bacteriocin_discovery/contract.py`
describes its own view of the same contract. Each module's docs
(`CONTRACT.md`, `docs/proposed-contract-changes.md`) record proposed changes
rather than applying them unilaterally — which is the right instinct, and the
reason nothing has been moved here yet.

Promoting one module's schema module into the shared contract is a joint
decision between the two owners, not a mechanical refactor: it fixes which
optional extensions become canonical, and both modules' validators and tests
depend on the answer. Doing it as part of a layout change would smuggle a
scientific decision into a directory move.

## When it happens

Create `shared/bacteriocin_shared/` as a real importable package — not a
loose `schemas.py`. Every MCP server runs as its own subprocess and receives
`shared/` on its `PYTHONPATH`, so it has to be importable:

```
shared/
  pyproject.toml                    # name = "bacteriocin-shared"
  bacteriocin_shared/
    __init__.py
    schemas.py
```

Then add it to the workspace members in the root `pyproject.toml`, depend on
it from both packages, and extend each generated declaration's `PYTHONPATH`
in `install.py` to include it.
