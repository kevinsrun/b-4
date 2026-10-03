# Omnigent integration — simulation experiment backend

Exposes the computational simulation backend (`bacteriocin_sim`) to Omnigent
as an MCP tool.

Tested against **Omnigent 0.16.0**, MCP SDK **1.30.0 and 2.3.0**.

This follows the pattern established by the candidate agent's integration at
`integrations/omnigent/` — generated declaration, committed example, logs off
stdout, read-only orchestrator. See [Consolidating the
bundles](#consolidating-the-bundles) for the one open question.

## Why MCP rather than an agent

`bacteriocin_sim` is a tool, not an agent. It holds no conversation, runs no
model and takes no decision — it answers `run_experiment(spec) -> result`
deterministically. Omnigent's unit of registration is an LLM loop (harness +
instructions + tools), so the backend becomes an MCP tool and an agent bundle
calls it. The bundle plays the orchestration role.

## Layout

```
integrations/omnigent/simulation/
  install.py               Generates the MCP declaration with absolute paths
  mcp_server.py            Launcher Omnigent spawns; server lives in the package
  test_mcp_protocol.py     Protocol test: real stdio client against the launcher
  agent/
    config.yaml            Agent spec (spec_version 1)
    AGENTS.md              Orchestration-role instructions
    tools/mcp/bacteriocin-sim.yaml.example   Placeholder, committed
    tools/mcp/bacteriocin-sim.yaml           GENERATED, gitignored
```

The server implementation is `bacteriocin_sim/mcp_server.py`, inside the
package rather than here, so the code Omnigent runs is the same code
`tests/test_mcp_server.py` unit-tests. This file is only a launcher.

**Run `install.py` before anything else on a fresh clone.** The real
`bacteriocin-sim.yaml` is not committed: it holds absolute paths for one
machine, so checking it in would both break on every other machine and publish
a home directory. `install.py --check` exits non-zero with instructions if it
is missing or stale.

## Setup

```bash
uv pip install -e ".[mcp]"
python3 integrations/omnigent/simulation/install.py
omnigent run integrations/omnigent/simulation/agent
```

Verify the wiring end to end:

```bash
python3 integrations/omnigent/simulation/test_mcp_protocol.py
```

That spawns the launcher as a subprocess from an unrelated working directory,
initializes a real MCP session, and checks the surface, determinism, the
structured error path and the 14 scientific invariants.

## Tools exposed

| tool | purpose |
|---|---|
| `capabilities` | registered backends, assay domains, declared limitations |
| `get_schema` | JSON Schema for spec / result / agent envelopes |
| `run_experiment` | one experiment → one full result |
| `run_experiments` | a batch, isolating per-spec failures |
| `run_agent` | the full envelope, including `recommended_next_action` |
| `describe` | self-description for capability negotiation |
| `selftest` | the 14 directional biology invariants |

The declaration carries an explicit `tools:` allow-list, so a tool cannot
start reaching the model merely because the server registered it.

A `BacteriocinSimError` is returned as its structured payload rather than
raised, so the caller keeps the distinction between a bad spec, an unavailable
backend and a numerical failure — an MCP protocol error would flatten all
three.

## Notes for whoever maintains this

**Both MCP SDK majors are supported deliberately.** Omnigent 0.16 bundles
mcp 1.30, where the server class is `FastMCP`; a fresh install resolves 2.x,
where it was renamed `MCPServer`. `install.py` may legitimately pick either
interpreter, so the server detects which is present. The protocol test is
likewise agnostic — 1.x returns `serverInfo` / `structuredContent`, 2.x the
snake_case spellings.

**Do not print to stdout from anything the server imports.** On the stdio
transport stdout *is* the JSON-RPC channel; one stray `print` corrupts the
stream and surfaces as an opaque parse error rather than as the log line that
caused it. `main()` pins logging to stderr, and `BACTERIOCIN_LOG_LEVEL` in the
declaration keeps it quiet.

**`install.py` does not resolve symlinks on the interpreter.** A virtualenv's
`bin/python` is a symlink to a base interpreter, and resolving it yields a path
that runs *without* the venv's site-packages — so the resolved path fails to
import `mcp` even though the symlink works.

**The orchestrator bundle is read-only on purpose.** `config.yaml` declares no
`os_env`, so the agent gets no filesystem or shell tools. It reads the
backend's output; letting a model edit the repository invites it to "fix" an
inconvenient scientific result. It also pins no harness or model, so the
bundle stays portable across whatever credential `omnigent config` holds.

## Consolidating the bundles

Right now this directory ships its own bundle (`bacteriocin-sim-lead`) so the
backend is independently runnable. The candidate agent ships another
(`bacteriocin-discovery-lead`). The real loop wants **one** orchestrator
holding both tools — it designs candidates and then tests them, and splitting
that across two agents means neither can close the loop.

That consolidation is a decision for the two module owners together, not
something to apply unilaterally, so it is written down here rather than done.
The mechanical part is small:

```bash
python3 integrations/omnigent/simulation/install.py \
    --bundle integrations/omnigent/agent
```

`--bundle` writes the declaration into the shared bundle's `tools/mcp/`
instead of this one. The remaining work is editorial: merge this directory's
`AGENTS.md` guidance into the shared bundle's, under a section naming when to
call the generator versus the simulator, and extend the shared `.gitignore`
entry to cover the second generated declaration. The two declarations have
distinct `name:` values (`bacteriocin` and `bacteriocin-sim`), so they already
coexist without collision.
