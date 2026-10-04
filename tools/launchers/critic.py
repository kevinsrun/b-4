#!/usr/bin/env python3
"""Launcher Omnigent spawns for the scientific critic.

The server itself lives in the package, where it is importable and covered by
``packages/critic_agent/tests``. This file only makes the checkout importable
and hands off, so the thing Omnigent runs is the thing the tests exercise.

Generate the declaration that points here with::

    python3 install.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
for path in (
    REPO / "packages" / "critic_agent" / "src",
    REPO / "packages" / "bacteriocin_discovery" / "src",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from critic_agent import (  # noqa: E402
    AGENT_NAME,
    CriticRequest,
    CriticReview,
    ScientificCriticAgent,
)

# Both MCP SDK majors are supported: Omnigent 0.16 bundles mcp 1.30, where the
# server class is FastMCP; a fresh install resolves 2.x, where it was renamed
# MCPServer. install.py may pick either interpreter.
try:
    from mcp.server.mcpserver import MCPServer as _ServerClass  # mcp >= 2

    _VERSION_KWARG: dict[str, Any] = {"version": "0.1.0"}
except ModuleNotFoundError:  # pragma: no cover - depends on the interpreter
    from mcp.server.fastmcp import FastMCP as _ServerClass  # mcp 1.x

    _VERSION_KWARG = {}

INSTRUCTIONS = """\
Scientific critic for the bacteriocin-discovery loop.

Reviews claims BEFORE the system accepts them into its research state or uses
them to justify a consequential next step. It does not approve by default: a
claim is accepted only when no validation rule objects.

Call `review_claims` with the claims plus the evidence and experiment results
behind them. It returns a status of approve, approve_with_caveats, reject, or
needs_more_evidence, the specific issues found, and which agent should take
the work back (experiment_planner, literature-evidence-agent, or
result_analysis_agent).

A claim that is neither accepted nor rejected is HELD, not approved. Do not
read silence as permission to proceed.
"""

server = _ServerClass(name="critic", instructions=INSTRUCTIONS, **_VERSION_KWARG)
_agent = ScientificCriticAgent()


@server.tool(
    description=(
        "Review claims before the loop accepts them. Checks that the conclusion "
        "follows from the result, that provenance is classified and never described "
        "as experimentally validated when it is simulated, that coverage and controls "
        "are adequate, that claims are not extrapolated outside tested conditions, "
        "that the wording matches the reported uncertainty, and that competing "
        "hypotheses were actually distinguished. Returns a review with a status, "
        "typed issues, accepted/rejected claim IDs and required followups."
    )
)
def review_claims(request: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = CriticRequest.model_validate(request or {})
    except Exception as exc:  # noqa: BLE001 - returned, not raised, like the other backends
        return {
            "error_code": "invalid_request",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
    return _agent.review(parsed).model_dump(mode="json")


@server.tool(
    description=(
        "Review claims and return the common agent envelope (agent, decision, "
        "confidence, uncertainties, artifacts, warnings, recommended_next_action) "
        "instead of the bare review. Use this when the orchestrator wants the "
        "routing recommendation alongside the verdict."
    )
)
def run_agent(envelope: dict[str, Any]) -> dict[str, Any]:
    return _agent.run_envelope(envelope or {}).model_dump(mode="json")


@server.tool(
    description=(
        "This agent's scientific responsibility, what it explicitly does not do, "
        "the agents it can route work back to, and its input/output JSON schemas."
    )
)
def describe() -> dict[str, Any]:
    return _agent.describe()


@server.tool(
    description="JSON Schema for the critic's request or review: 'request' or 'review'."
)
def get_schema(name: str = "request") -> dict[str, Any]:
    models = {"request": CriticRequest, "review": CriticReview}
    model = models.get(name)
    if model is None:
        return {
            "error_code": "unknown_schema",
            "message": f"unknown schema {name!r}",
            "details": {"available": sorted(models)},
        }
    return model.model_json_schema()


def main() -> None:
    """Serve over stdio.

    Logging is pinned to stderr first: on the stdio transport stdout *is* the
    JSON-RPC channel, so one stray print corrupts the stream and surfaces as
    an opaque parse error rather than as the log line that caused it.
    """
    logging.basicConfig(
        stream=sys.stderr,
        level=os.environ.get("BACTERIOCIN_LOG_LEVEL", "WARNING").upper(),
        force=True,
    )
    logging.getLogger(__name__).debug("starting %s", AGENT_NAME)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
