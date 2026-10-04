#!/usr/bin/env python3
"""Launcher Omnigent spawns for the deterministic experiment planner.

The planner itself lives in ``bacteriocin_lab.agents.planner`` and is covered by
``bacteriocin_lab/tests/planner``; this file only makes the checkout importable and exposes it
over MCP. Generate the declaration that points here with::

    python3 install.py

Note the naming: this server is ``experiment_planner``. The ``planner`` entry in ``config.yaml``
is a
different thing, a prompt-only LLM sub-agent under ``agents/planner``.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from bacteriocin_lab.agents.planner import TOOL_SPEC, run_agent  # noqa: E402
from bacteriocin_lab.agents.planner.schema import AGENT_NAME  # noqa: E402

# Both MCP SDK majors are supported (1.x FastMCP, 2.x MCPServer); see launchers/critic.py.
try:
    from mcp.server.mcpserver import MCPServer as _ServerClass  # mcp >= 2

    _VERSION_KWARG: dict[str, Any] = {"version": "0.1.0"}
except ModuleNotFoundError:  # pragma: no cover - depends on the interpreter
    from mcp.server.fastmcp import FastMCP as _ServerClass  # mcp 1.x

    _VERSION_KWARG = {}

INSTRUCTIONS = """\
Deterministic experiment planner (active learning) for the bacteriocin-discovery loop.

Call `plan_experiment` with the research objective, the candidates, the hypotheses, every
experiment result so far (`previous_experiments`) and the remaining budget. It returns the ONE
next computational experiment that is expected to teach the most (information gain over the
competing hypotheses, current uncertainty, relevance to the objective, cost), with the reason, the
variables it changed and held constant, and the outcomes it predicts under each hypothesis.

The returned `experiment_spec` is a ready-to-run ExperimentSpec: hand it to the simulator's
`run_experiment`. Planning does not run anything and a predicted outcome is not a result. Pass the
simulator's result back in `previous_experiments` on the next call; the plan will change
because of it.
Same input, same output.

`decision.status` may also be `converged`, `stop_budget_exhausted` or `no_candidates`; read
`why_this_experiment` and `recommended_next_action` instead of assuming a spec is present.
"""

server = _ServerClass(name="experiment_planner", instructions=INSTRUCTIONS, **_VERSION_KWARG)

#: Top-level keys the reader must see first, in case a long reply is truncated downstream.
_LEAD = ("agent", "decision", "confidence", "warnings", "uncertainties", "why_this_experiment")


def _lead(envelope: dict[str, Any]) -> dict[str, Any]:
    """Reorder top-level keys so status, warnings and uncertainty come first (content unchanged)."""
    first = {k: envelope[k] for k in _LEAD if k in envelope}
    return {**first, **{k: v for k, v in envelope.items() if k not in first}}


@server.tool(
    description=(
        "Choose the next computational experiment. Input: research_objective "
        "{target:{species,strain}, desired_behavior:{ph_range,target_cell_density,temperature_c}}, "
        "candidates [{candidate_id, name, confidence, features}], hypotheses "
        "[{hypothesis_id, template, prior_plausibility}], previous_experiments (ExperimentResult "
        "objects, simulator output accepted as-is), budget "
        "{remaining_experiments, compute_budget}, "
        "constraints. Output: decision.status, experiment_spec (feed to the simulator's "
        "run_experiment), variables_changed / variables_held_constant, expected_information_gain "
        "(bits), predicted_possible_outcomes, why_this_experiment, warnings. Proposes only; "
        "never runs the experiment."
    )
)
def plan_experiment(request: dict[str, Any]) -> dict[str, Any]:
    return _lead(run_agent(request or {}))


@server.tool(
    description=(
        "This agent's scientific responsibility, what it does not do, and the JSON schema of its "
        "input."
    )
)
def describe() -> dict[str, Any]:
    return {
        "agent": AGENT_NAME,
        "responsibility": TOOL_SPEC["description"],
        "does_not": [
            "run experiments or simulate anything",
            "interpret results (that is the analysis agent)",
            "generate candidates or hypotheses",
            "claim a predicted outcome as a finding",
        ],
        "input_schema": TOOL_SPEC["input_schema"],
    }


@server.tool(description="JSON Schema of the planner's request.")
def get_schema() -> dict[str, Any]:
    return TOOL_SPEC["input_schema"]


def main() -> None:
    """Serve over stdio, with logging pinned to stderr (stdout is the JSON-RPC channel)."""
    logging.basicConfig(
        stream=sys.stderr,
        level=os.environ.get("BACTERIOCIN_LOG_LEVEL", "WARNING").upper(),
        force=True,
    )
    logging.getLogger(__name__).debug("starting %s", AGENT_NAME)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
