#!/usr/bin/env python3
"""Launcher Omnigent spawns for the Result Analysis agent.

The agent lives in ``bacteriocin_lab.agents.analysis`` and is covered by
``bacteriocin_lab/tests/analysis``; this file only makes the checkout importable and exposes it
over MCP. Generate the declaration that points here with::

    python3 install.py

Note the naming: this server is ``result_analysis``. The ``analysis`` entry in ``config.yaml`` is a
different thing, a prompt-only LLM sub-agent under ``agents/analysis``.
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

from bacteriocin_lab.agents.analysis import (  # noqa: E402
    AGENT_NAME,
    ResultAnalysis,
    ResultAnalysisRequest,
    analyze_result,
)

# Both MCP SDK majors are supported (1.x FastMCP, 2.x MCPServer); see launchers/critic.py.
try:
    from mcp.server.mcpserver import MCPServer as _ServerClass  # mcp >= 2

    _VERSION_KWARG: dict[str, Any] = {"version": "0.1.0"}
except ModuleNotFoundError:  # pragma: no cover - depends on the interpreter
    from mcp.server.fastmcp import FastMCP as _ServerClass  # mcp 1.x

    _VERSION_KWARG = {}

INSTRUCTIONS = """\
Result analysis for the bacteriocin-discovery loop.

Call `analyze_result` with the ExperimentResult just produced, ALL earlier results
(`previous_results`) and, when one is being tested, the hypothesis. It says whether the result
supports, weakens or fails to distinguish that hypothesis, how it compares with earlier
experiments, which variables drove it, what was unexpected and how confident the reading is.

It interprets only. A simulation-derived result is never described as experimentally validated
and every conclusion carries that caveat; repeat it, do not drop it. `inconclusive` is a real
answer, not a failure: it usually means the data cannot separate the outcomes yet.
Same input, same output.
"""

server = _ServerClass(name="result_analysis", instructions=INSTRUCTIONS, **_VERSION_KWARG)

#: Keys the reader must see first, in case a long reply is truncated downstream.
_LEAD = ("agent", "confidence", "warnings", "uncertainties", "decision")


def _lead(envelope: dict[str, Any]) -> dict[str, Any]:
    """Reorder top-level keys so confidence, warnings and uncertainty lead (content unchanged)."""
    first = {k: envelope[k] for k in _LEAD if k in envelope}
    return {**first, **{k: v for k, v in envelope.items() if k not in first}}


@server.tool(
    description=(
        "Interpret one experiment result. Input: result (ExperimentResult), previous_results "
        "(every earlier ExperimentResult; they are what makes comparison possible), optional "
        "hypothesis {hypothesis_id, statement, expected_relationship:{variable,direction}, "
        "predicted_inhibition_fraction, key_conditions}. Output: hypothesis_status "
        "(supported/weakened/inconclusive), drivers, controlled comparisons, unexpected "
        "results, follow-up questions, uncertainties. Interprets only; never validates."
    )
)
def analyze(request: dict[str, Any]) -> dict[str, Any]:
    return _lead(analyze_result(request or {}))


@server.tool(
    description="JSON Schema for the analysis request ('request') or its result ('analysis')."
)
def get_schema(name: str = "request") -> dict[str, Any]:
    models = {"request": ResultAnalysisRequest, "analysis": ResultAnalysis}
    model = models.get(name)
    if model is None:
        return {
            "error_code": "unknown_schema",
            "message": f"unknown schema {name!r}",
            "details": {"available": sorted(models)},
        }
    return model.model_json_schema()


@server.tool(description="This agent's responsibility and what it explicitly does not do.")
def describe() -> dict[str, Any]:
    return {
        "agent": AGENT_NAME,
        "responsibility": (
            "interpret experiment results: does a result support, weaken or fail to distinguish "
            "its hypothesis, how does it compare with earlier results, which variables drove it, "
            "what was unexpected, and how confident is the reading"
        ),
        "does_not": [
            "run experiments",
            "gather literature",
            "generate candidates or hypotheses",
            "describe simulation-derived evidence as experimentally validated",
        ],
    }


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
