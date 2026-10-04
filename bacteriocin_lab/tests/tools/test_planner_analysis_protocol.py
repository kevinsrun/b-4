"""Protocol tests for the ``experiment_planner`` and ``result_analysis`` MCP servers.

Each test spawns the launcher Omnigent would spawn and speaks MCP over real stdio from an unrelated
working directory, so it covers what in-process tests cannot: that the launcher imports, that the
declared tool surface is what the server really exposes, and that a real client gets a correct
answer.

Collected by pytest (unlike the older protocol scripts). Skipped only when the optional ``mcp`` SDK
is not installed; ``pip install -e ".[mcp]"`` provides it.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="the MCP SDK is an optional extra: pip install -e '.[mcp]'")

import install
from bacteriocin_lab.agents.simulator import run_experiment
from bacteriocin_lab.agents.simulator.selftest import spec as sim_spec

REPO = Path(__file__).resolve().parents[3]
LAUNCHERS = REPO / "tools" / "launchers"


def _attr(obj, *names):
    """Read the first attribute present (the MCP SDK renamed fields between 1.x and 2.x)."""
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    raise AttributeError(f"none of {names} on {type(obj).__name__}")


def _payload(result) -> dict:
    structured = _attr(result, "structured_content", "structuredContent")
    return structured if structured else json.loads(result.content[0].text)


def session_run(launcher: str, work, calls):
    """Spawn ``launcher``, run ``calls(session)`` and return its result."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(LAUNCHERS / launcher)],
        env={"PYTHONPATH": str(REPO), "BACTERIOCIN_LOG_LEVEL": "WARNING"},
        cwd=str(work),  # deliberately not the repo
    )

    async def go():
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            return await calls(session)

    return asyncio.run(go())


def planner_request(previous=()) -> dict:
    return {
        "research_objective": {
            "target": {"species": "Listeria monocytogenes", "strain": "ATCC 19115"},
            "desired_behavior": {"ph_range": [6.0, 7.5], "target_cell_density": 1e8},
        },
        "candidates": [
            {
                "candidate_id": "cand_a",
                "name": "A",
                "confidence": 0.6,
                "features": {"mechanism": "pore", "known_targets": ["Listeria monocytogenes"]},
            },
            {"candidate_id": "cand_b", "name": "B", "confidence": 0.5, "features": {}},
        ],
        "hypotheses": [
            {"hypothesis_id": "h_ph", "template": "ph_window", "prior_plausibility": 0.6}
        ],
        "previous_experiments": list(previous),
        "budget": {"remaining_experiments": 5},
    }


def test_planner_server_exposes_its_declared_tools_and_plans(tmp_path):
    async def calls(s):
        tools = {t.name: t for t in (await s.list_tools()).tools}
        plan = _payload(await s.call_tool("plan_experiment", {"request": planner_request()}))
        again = _payload(await s.call_tool("plan_experiment", {"request": planner_request()}))
        bad = _payload(await s.call_tool("plan_experiment", {"request": {"nonsense": 1}}))
        return tools, plan, again, bad

    tools, plan, again, bad = session_run("planner.py", tmp_path, calls)

    assert set(tools) == {"plan_experiment", "describe", "get_schema"}
    assert all(t.description for t in tools.values())
    assert plan["decision"]["status"] == "propose_experiment"
    assert plan["experiment_spec"]["candidate_id"] in {"cand_a", "cand_b"}
    assert plan["experiment_spec"]["conditions"]["assay_domain"] == "simulated_in_vitro"
    assert plan["decision"]["evidence_type_of_expected_result"] == "simulation-derived"
    assert list(plan)[:2] == ["agent", "decision"], "status must lead so truncation cannot hide it"
    assert plan == again, "planning must be deterministic across calls"
    # A malformed request is a structured error, not a crashed server.
    assert bad["decision"]["status"] == "error" and bad["warnings"]


def test_planner_server_accepts_real_simulator_output(tmp_path):
    """Simulator quantities ({"value","unit"}) must not break the planner (regression)."""
    result = run_experiment(sim_spec()).to_json_dict()
    req = planner_request([dict(result, candidate_id="cand_a")])

    async def calls(s):
        return _payload(await s.call_tool("plan_experiment", {"request": req}))

    out = session_run("planner.py", tmp_path, calls)
    assert out["decision"]["status"] == "propose_experiment", out["warnings"]
    assert out["artifacts"]["candidate_experiment_counts"]["cand_a"] == 1


def test_analysis_server_interprets_a_real_result_without_validating_it(tmp_path):
    result = run_experiment(sim_spec()).to_json_dict()

    async def calls(s):
        tools = {t.name for t in (await s.list_tools()).tools}
        out = _payload(
            await s.call_tool("analyze", {"request": {"result": result, "previous_results": []}})
        )
        bad = _payload(await s.call_tool("analyze", {"request": {"nonsense": 1}}))
        schema = _payload(await s.call_tool("get_schema", {"name": "request"}))
        return tools, out, bad, schema

    tools, out, bad, schema = session_run("analysis.py", tmp_path, calls)

    assert tools == {"analyze", "get_schema", "describe"}
    decision = out["decision"]
    assert (
        decision["result_id"] == result["result_id"]
        and decision["candidate_id"] == result["candidate_id"]
    )
    assert decision["source_evidence_type"] == "simulation-derived"
    assert "NOT experimentally validated" in decision["provenance_note"]
    assert decision["hypothesis_status"] in {"supported", "weakened", "inconclusive"}
    assert list(out)[:3] == ["agent", "confidence", "warnings"], "caveats must lead the reply"
    assert out["uncertainties"], "uncertainty must be reported"
    assert bad["decision"].get("status") != "ok" or bad["warnings"]  # structured, not a crash
    assert "properties" in schema


def test_every_declared_tool_exists_on_its_server_and_nothing_is_undeclared(tmp_path):
    """install.py's tool allowlist is what the model sees: drift in either direction is a bug."""
    problems = []
    for server in install.SERVERS:

        async def calls(s):
            return {t.name for t in (await s.list_tools()).tools}

        live = session_run(server.launcher.name, tmp_path, calls)
        declared = set(server.tools)
        if declared - live:
            problems.append(f"{server.name}: declared but not served: {sorted(declared - live)}")
        if live - declared:
            problems.append(
                f"{server.name}: served but hidden from the model: {sorted(live - declared)}"
            )
    assert not problems, "\n".join(problems)


def test_install_declares_every_agent_launcher():
    names = {s.name for s in install.SERVERS}
    assert {
        "literature",
        "candidates",
        "runner",
        "critic",
        "knowledge",
        "experiment_planner",
        "result_analysis",
    } <= names
    for server in install.SERVERS:
        assert server.launcher.is_file(), server.launcher
        example = REPO / "tools" / "mcp" / f"{server.name}.yaml.example"
        assert example.is_file(), f"missing committed placeholder {example.name}"
