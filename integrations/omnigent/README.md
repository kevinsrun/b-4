# Omnigent integration

Exposes the Candidate Generation & Design Agent to Omnigent as an MCP tool.

Tested against **Omnigent 0.16.0**, MCP SDK 1.30.0, protocol `2025-11-25`.

## What Omnigent actually is here

Worth stating plainly, because it differs from the system contract's premise.
The contract describes Omnigent as the orchestration layer of a bacteriocin
lab. The installed Omnigent 0.16.0 is a **general multi-agent orchestrator for
coding harnesses** (Claude Code, Codex, Devin, Goose, …). It has no built-in
notion of bacteriocins, experiments, or a scientific loop.

What it does have is the right shape to host this agent:

- **agent bundles** — a directory with `config.yaml`, `AGENTS.md`, `tools/`
- **MCP servers** per bundle, stdio or HTTP
- **sub-agents**, so the other specialist agents can be added as siblings

So the integration is: the specialist agent becomes an MCP tool, and an
Omnigent agent bundle calls it. That bundle plays the orchestration role the
contract assigns to Omnigent.

## Layout

```
integrations/omnigent/
  install.py                  Generates the MCP declaration with absolute paths
  mcp_server.py               MCP server wrapping generate_candidates
  test_mcp_protocol.py        Protocol test: hand-rolled MCP stdio client
  test_omnigent_manager.py    Integration test: Omnigent's own RunnerMcpManager
  agent/
    config.yaml               Agent spec (spec_version 1)
    AGENTS.md                 Orchestration-role instructions
    tools/mcp/bacteriocin.yaml.example   Placeholder, committed
    tools/mcp/bacteriocin.yaml           GENERATED, gitignored
```

**Run `install.py` before anything else on a fresh clone.** The real
`bacteriocin.yaml` is not committed: it holds absolute paths for one machine,
so checking it in would both break on every other machine and publish a home
directory. The tests exit with instructions if it is missing.

## Setup

```bash
python3 integrations/omnigent/install.py
```

This picks an interpreter that can import both `mcp` and `pydantic`, then writes
`agent/tools/mcp/bacteriocin.yaml`. Re-run it after moving the repository or
changing interpreter; `--check` verifies without writing.

### Why a generator rather than a checked-in YAML

Omnigent expands `${VAR}` in an MCP server's `env` block but **not** in
`command` or `args` — its parser documents those as literals. So the
interpreter and script paths cannot be environment variables; they have to be
written out as absolutes. The generator keeps that reproducible instead of
hard-coding one machine's paths.

Two traps this avoids, both found by testing rather than reading:

1. **Never `resolve()` the interpreter path.** A virtualenv's `bin/python` is a
   symlink to a base interpreter. Resolving it yields a path that runs *without*
   the venv's `site-packages`, so `import mcp` fails even though the symlink
   works. The generator verifies the candidate and returns the **unresolved**
   path.
2. **Keep logs off stdout.** stdio *is* the MCP channel, so a stray `print`
   corrupts the JSON-RPC stream. The server logs to stderr only, and the
   protocol test asserts stderr stays clean.

## Run it

```bash
export PATH="$HOME/.local/bin:$PATH"
omnigent run integrations/omnigent/agent --harness <harness> \
  -p "Propose 3 candidates against Listeria monocytogenes (Gram-positive) at pH 6.0-7.5, 1e8 CFU/mL."
```

A live run needs a configured harness — a CLI installed *and* a credential.
`omnigent config list` shows both; a credential listed without its CLI installed
still fails at runner launch with `harness '<name>' is not configured on host`.
Run `omnigent setup` to fix that.

Verified end to end against the `claude` harness: the agent calls
`describe_agent`, then `generate_candidates`, and reports the ranked candidates
with warnings quoted verbatim. See [Two defects a live run
found](#two-defects-a-live-run-found) for what that run changed.

## Tests

```bash
OMNI_PY=~/.local/share/uv/tools/omnigent/bin/python

$OMNI_PY integrations/omnigent/test_mcp_protocol.py      # 23 checks
$OMNI_PY integrations/omnigent/test_omnigent_manager.py  # 27 checks
$OMNI_PY integrations/omnigent/mcp_server.py --selftest  # no transport
```

`test_mcp_protocol.py` drives the server as an MCP stdio client: initialize,
tools/list, tools/call, error paths, loop closure, determinism.

`test_omnigent_manager.py` is the stronger one — it parses the bundle with
Omnigent's parser and dispatches through `RunnerMcpManager`, the same class a
live session uses. It covers connection, tool registration, the allowlist,
calls, the error path and clean shutdown.

## Two defects a live run found

Both were mine, and neither showed up in the offline tests. They are recorded
here because the fixes look like arbitrary style choices otherwise.

### 1. The input schema never reached the model

The tool originally took one `request: dict` parameter. That advertises the
JSON Schema `{"type": "object", "additionalProperties": true}` — which tells a
model nothing about the fields inside. A 150-line `REQUEST_SCHEMA` was attached
as `__mcp_input_schema__`, which is **not** a FastMCP hook, so it was dead code.

In the live run Claude guessed `n_candidates: 3`, the agent ignored the unknown
key, and the whole 7-candidate pool came back. No error — just a silently wrong
answer, which is the worst failure mode available.

Fixed by replacing the nested dict with **23 flat, annotated parameters**, so
`max_candidates` is advertised and there is nothing to guess. `request_override`
remains as the escape hatch for contract fields the signature does not expose.
`test_omnigent_manager.py` now asserts the parameters are actually advertised.

### 2. The response was truncated past the warnings

The full envelope is ~25 KB for five candidates. The orchestrator truncated a
56 KB reply at ~2 KB and lost the provenance warnings, the high-severity
uncertainty, and most of the candidate list — exactly the content that stops a
proposal being restated as a finding.

Fixed by returning a **compact payload, warnings first**. Field order is load
bearing: `PROVENANCE` and `warnings` lead, so truncation cannot eat them.
Candidates are reduced to identity, the score split, the hypothesis and the
falsification clause — ~7.6 KB for three. The full envelope is written to
`BACTERIOCIN_ARTIFACT_DIR` and its path returned, so nothing is lost;
`include_full_envelope=true` inlines it for callers that can take the size.

### Smaller things the same run surfaced

- **`rank_driven_by` reported `novelty` for everything.** It took the largest
  raw component, but novelty is 1.00 for every candidate on a cold start. It now
  reports the largest *weighted contribution*, so promise at 35% beats novelty
  at 15% and the field actually distinguishes candidates.
- **`target_cell_density="1e8"` was rejected.** A model writes cell densities in
  scientific notation. Numeric strings (and thousands separators) are now
  coerced, which removes a wasted round trip.

## Tools exposed

Omnigent namespaces tools by server, so the model sees:

| Tool | Purpose |
|---|---|
| `bacteriocin__generate_candidates` | Propose ranked candidates. Takes one `request` object. |
| `bacteriocin__describe_agent` | Identity, scoring objectives, and what the agent refuses to do. |

`generate_candidates` takes flat arguments — `organism` (the only required
one), `gram`, `max_candidates`, `ph_low`/`ph_high`, `target_cell_density`,
`competing_hypotheses`, `previous_results` and so on. It returns the compact
payload described above.

## Guarding the provenance rule across the boundary

An orchestrating LLM is the most likely thing to restate a proposal as a
finding, so the disclaimer is repeated at every layer it will encounter:

- the **tool description** states the agent never claims a candidate is active
- the **text digest** opens with "These are proposals, not findings"
- **`AGENTS.md`** tells the orchestrator not to write "candidate X inhibits Y",
  and to report high-severity uncertainties verbatim
- the **envelope** carries `validation_status: "unvalidated"` and
  `evidence_type: "inferred-hypothesis"` on everything

`AGENTS.md` also warns against re-calling the tool hoping for different output —
it is deterministic, so changing the result means changing the request.

## Configuration

| Variable | Effect |
|---|---|
| `PYTHONPATH` | Must include this repo's `src`. Set by the generator. |
| `BACTERIOCIN_KNOWLEDGE_PATH` | Curated dataset JSON, replacing the unverified seed. Missing file fails at startup rather than silently falling back. |
| `BACTERIOCIN_LOG_LEVEL` | Server log level on stderr. Default `INFO`; the bundle sets `WARNING`. |
| `BACTERIOCIN_ARTIFACT_DIR` | Where full envelopes are written. Defaults to a `bacteriocin-runs` directory under the system temp dir. |

Point `BACTERIOCIN_KNOWLEDGE_PATH` at real curated data before any real
campaign — the shipped seed sequences are unverified. See the root README.

## Adding the rest of the loop

The other specialist agents become sibling MCP servers in the same bundle: drop
a `tools/mcp/<name>.yaml` per agent. Omnigent discovers every `.yaml` in that
directory. `agents/` holds sub-agents if you want one orchestrator per loop
stage instead of a single lead.

When the experiment planner is added, remember it must translate
`target.organism` → `target.species`; the contract uses both names for the same
field. See [../../docs/proposed-contract-changes.md](../../docs/proposed-contract-changes.md).
