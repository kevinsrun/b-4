# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

An autonomous bacteriocin-discovery loop: one Omnigent orchestrator over specialist modules, all in a single installable Python package, `bacteriocin_lab`. [AGENTS.md](AGENTS.md) is the *runtime prompt* for the Omnigent orchestrator (how to run a turn of the loop), not developer docs — edit it only when changing orchestrator behaviour. [README.md](README.md) has the layout and per-module links.

## Commands

```bash
uv sync --all-extras          # editable install + dev/mcp/verify extras
python3 install.py            # generate tools/mcp/*.yaml (machine-specific paths; gitignored)
python3 install.py --check    # verify the declarations are present and current
python3 scripts/run_omnigent.py   # run the orchestrator (not `omnigent run .`; see README)

pytest                                        # all tests (testpaths = bacteriocin_lab/tests)
pytest bacteriocin_lab/tests/candidate/test_scoring.py::test_name   # single test
ruff check bacteriocin_lab                    # lint (line length 100, py311)

# MCP protocol tests are standalone scripts, also run by CI:
python3 bacteriocin_lab/tests/tools/test_literature_protocol.py
python3 bacteriocin_lab/tests/tools/test_runner_protocol.py
python3 bacteriocin_lab/tests/tools/test_candidates_protocol.py

# Web (optional; the loop runs without it). Two processes:
uv sync --extra web && uv run bacterion-api   # API on :8000
cd web && npm install && npm run dev          # UI on :3000, proxies /api to :8000
cd web && npx tsc --noEmit                    # typecheck
```

CI ([.github/workflows/fleet-verify.yml](.github/workflows/fleet-verify.yml), managed by Engineering Fleet — regenerate with `fleet init --ci`, don't hand-edit) runs `install.py` first in every job, then: full `pytest`, `install.py --check`, the three protocol scripts, a full ruff check on the evidence agent/literature launcher/integration tests, and a syntax-only ruff pass (`E9,F63,F7,F82`) on the planner.

Simulator CLI/MCP entry points: `bacteriocin-sim`, `bacteriocin-sim-mcp`; evidence: `b4-literature-evidence`.

## Architecture

**Two kinds of specialist — keep them separate.**
- *Deterministic backends* are MCP servers (pure functions, no model call): literature (`agents/evidence`), candidates (`agents/candidate`), runner (`agents/simulator`), critic, knowledge. Each is spawned through a script in `tools/launchers/` via a declaration in `tools/mcp/*.yaml`. Don't wrap these in an LLM loop — it destroys reproducibility.
- *Reasoning steps* are Omnigent sub-agents: `planner`, `insight`, `analysis`. They are **prompts only** under top-level `agents/<name>/{AGENTS.md,config.yaml}` and are listed in `config.yaml` → `tools.agents`. (The Python `bacteriocin_lab/agents/planner` and `agents/analysis` are the deterministic logic behind them, a different thing from the prompt directories.)

**Why `tools/mcp/*.yaml` is generated:** Omnigent doesn't expand `${VAR}` in `command`/`args`, so `install.py` writes absolute interpreter paths. Only `*.yaml.example` is committed. After adding or changing an MCP server, update `install.py` and the `.example` file, and rerun it. Both mcp SDK majors (1.x `FastMCP`, 2.x `MCPServer`) must keep working.

**Package layering** (`bacteriocin_lab/`):
- `shared/` — schemas, contract (`ExperimentSpec`/`ExperimentResult`/`Evidence`), enums, ids. Depends on pydantic only; **must never import an agent or `orchestration`**.
- `agents/<name>/` — each specialist is self-contained; agents should not import each other (shared types live in `shared/` for exactly this reason).
- `adapters/` — experiment backends (simulation, wet-lab stub).
- `orchestration/` — the in-Python workflow engine (`workflow.py`, `routing.py`, `loop_guards.py`, `state.py`, `registry.py`), `agent_adapters/` wrapping each real specialist, and `fakes/` fixture agents for dependency injection in tests. `AgentRegistry.default()` wires real agents; tests inject fakes.
- `agents/knowledge` — the research state: an append-only event log (`events.py`, `reducer.py`, `store.py`) with hash-verifiable history; `policy.py` encodes the rules (inconclusive leaves a hypothesis untouched, failed attempt ≠ negative finding, nothing is validated unless `wet-lab-derived`). State persists under `artifacts/` (gitignored; `BACTERIOCIN_STATE_DIR` overrides).

**Web layer** (optional, added on top of the above):
- `bacteriocin_lab/api/` — FastAPI. Every handler forwards to one existing entry point (`run_discovery`, `run_experiment(s)`, `generate_candidates`, the literature agent, `knowledge_call`) and serialises the reply. **It must not compute a scientific value or invent a field.** Only read-only knowledge operations are exposed; writing to the research state belongs to the loop. Runs execute on a worker thread and are observed by wrapping each registry agent in a proxy (`api/observe.py`) that reports dispatches without touching the engine.
- `web/` — Next.js 15 + TS + Tailwind v4. Holds no scientific data: sequences come from `/api/reference-bacteriocins` (the candidate agent's knowledge source), not from a local copy. Every figure carries a provenance tag (`components/provenance.tsx`) — literature-derived / proposal / simulation-derived — and these are never merged.
- When adding an endpoint that takes a `candidate_registry`, coerce it to `CandidateSpec` (the adapter needs models, not dicts), and pass sequences: without them the simulator falls back to a generic prior and the result is not specific to the candidate named.

**Known duplication:** the experiment contract exists in three places — `agents/simulator/schemas.py`, `shared/contract.py`, and `orchestration/types.py`. This is deliberate for now (see [bacteriocin_lab/shared/README.md](bacteriocin_lab/shared/README.md), [docs/agents/simulator-contract.md](docs/agents/simulator-contract.md), [docs/proposed-contract-changes.md](docs/proposed-contract-changes.md)). When changing a contract field, check all three and their tests.

## Provenance invariants (enforce in code, tests and prose)

Three claim types must never be merged: literature agent → *literature-derived evidence*; candidate agent → *proposals* (never evidence of activity); simulator → *simulation-derived predictions* (hypotheses, never observations). The simulator schema rejects `wet-lab-derived` provenance and `validated_experimentally=True`; don't loosen that. If you install `parameter_overrides`, run the simulator `selftest` (14 directional biology invariants) afterwards.

## Other notes

- Per-module READMEs under `bacteriocin_lab/agents/*/README.md` hold detail for simulator, candidate, evidence, planner, knowledge, critic.
- [docs/agent-teams-reference.md](docs/agent-teams-reference.md) — read before planning or spawning agent teams.
- Ruff per-file ignores: E501/RUF001 relaxed in `agents/evidence` and E501 in `orchestration`.
