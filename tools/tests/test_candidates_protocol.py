#!/usr/bin/env python3
"""Protocol-level test: drive the MCP server as a real stdio client.

This spawns ``mcp_server.py`` as a subprocess and speaks MCP over stdio exactly
as Omnigent's ``mcp_manager`` does -- initialize, tools/list, tools/call. It
proves wire compatibility without depending on Omnigent's config loader, an
API key, or a model.

Run with an interpreter that has the ``mcp`` SDK::

    ~/.local/share/uv/tools/omnigent/bin/python \\
        integrations/omnigent/test_mcp_protocol.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "tools" / "launchers" / "candidates.py"
PACKAGE_SRC = REPO / "packages" / "bacteriocin_discovery" / "src"


def _attr(obj: object, *names: str) -> object:
    """Read the first attribute that exists.

    The MCP SDK renamed its result fields between majors: 1.x exposes
    ``serverInfo`` / ``protocolVersion``, 2.x the snake_case spellings. The
    server supports both SDKs, so this client has to as well.
    """
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    raise AttributeError(f"none of {names} on {type(obj).__name__}")

# Flat arguments, matching the tool's advertised schema. The nested-dict form
# was replaced after a live run showed the model guessing parameter names.
LISTERIA_ARGS = {
    "organism": "Listeria monocytogenes",
    "strain": "EGD-e",
    "gram": "positive",
    "max_candidates": 3,
    "ph_low": 6.0,
    "ph_high": 7.5,
    "temperature_c": 37,
    "target_cell_density": 100000000,
    "diversity_weight": 0.3,
}

passed: list[str] = []
failed: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        passed.append(name)
        print(f"  PASS  {name}")
    else:
        failed.append(name)
        print(f"  FAIL  {name}  {detail}")


def payload_of(result) -> dict:
    """Extract the JSON payload from a tools/call result."""
    text = result.content[0].text
    return json.loads(text)


async def main() -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER)],
        env={"PYTHONPATH": str(PACKAGE_SRC), "BACTERIOCIN_LOG_LEVEL": "WARNING"},
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            print("\n[1] initialize")
            init = await session.initialize()
            check("handshake completes", init is not None)
            info = _attr(init, "server_info", "serverInfo")
            check(
                "server identifies itself",
                info.name == "bacteriocin-candidate-generation",
                f"got {info.name!r}",
            )
            print(f"       server: {info.name} v{info.version}")
            print(f"       protocol: {_attr(init, 'protocol_version', 'protocolVersion')}")

            print("\n[2] tools/list")
            listing = await session.list_tools()
            names = {t.name for t in listing.tools}
            check("generate_candidates exposed", "generate_candidates" in names, f"got {names}")
            check("describe_agent exposed", "describe_agent" in names, f"got {names}")
            for tool in listing.tools:
                schema = _attr(tool, "input_schema", "inputSchema") or {}
                print(f"       {tool.name}  props={list((schema.get('properties') or {}).keys())}")
            disclaimer = next(
                (t.description for t in listing.tools if t.name == "generate_candidates"), ""
            )
            check(
                "tool description carries the no-validation disclaimer",
                "never claims a candidate is active" in (disclaimer or ""),
            )

            print("\n[3] tools/call describe_agent")
            described = payload_of(await session.call_tool("describe_agent", {}))
            check(
                "reports agent identity",
                described.get("agent") == "candidate_generation_agent",
                f"got {described.get('agent')}",
            )
            check("reports model_version", bool(described.get("model_version")))
            check("declares what it will not do", bool(described.get("will_not")))
            print(f"       knowledge_source: {described.get('knowledge_source')}")

            print("\n[4] tools/call generate_candidates -- Gram-positive target")
            result = payload_of(
                await session.call_tool("generate_candidates", LISTERIA_ARGS)
            )
            candidates = result["candidates"]
            check(
                "max_candidates is honoured",
                result["returned_count"] == 3,
                f"asked 3, got {result['returned_count']}",
            )
            check(
                "all candidates unvalidated (contract rule 9)",
                all(c["validation_status"] == "unvalidated" for c in candidates),
            )
            check(
                "every candidate has a falsification clause",
                all(c["falsified_if"] for c in candidates),
            )
            check(
                "recommends the experiment planner",
                result["recommended_next_action"]["agent"] == "experiment_planner",
            )
            check("provenance disclaimer is the first field", "PROPOSALS, NOT FINDINGS" in result["PROVENANCE"])
            check("warnings survive compaction", len(result["warnings"]) >= 1)
            check(
                "priors are labelled as priors",
                all("predicted_inhibition_fraction_PRIOR" in c for c in candidates),
            )
            check("full envelope written to disk", bool(result["full_envelope_path"]))
            check(
                "response is small enough to survive truncation",
                len(json.dumps(result)) < 15000,
                f"{len(json.dumps(result))} bytes",
            )
            for candidate in candidates:
                print(
                    f"       #{candidate['rank']} {candidate['name']}  "
                    f"total={candidate['score_total']:.3f}  "
                    f"driver={candidate['rank_driven_by']}"
                )
            print(f"       response size: {len(json.dumps(result))} bytes")

            print("\n[5] tools/call generate_candidates -- Gram-negative target")
            gram_negative = payload_of(
                await session.call_tool(
                    "generate_candidates",
                    {
                        "organism": "Escherichia coli",
                        "gram": "negative",
                        "ph_low": 6.5,
                        "ph_high": 7.5,
                        "target_cell_density": 1e6,
                        "max_candidates": 2,
                        "diversity_weight": 0.0,
                    },
                )
            )
            top = gram_negative["candidates"][0]
            check(
                "promotes a Gram-negative-active candidate",
                top["name"] == "microcin J25",
                f"got {top['name']}",
            )
            print(f"       top: {top['name']}  promise={top['score_components']['promise']:.2f}")

            print("\n[6] tools/call generate_candidates -- invalid request")
            bad = payload_of(
                await session.call_tool(
                    "generate_candidates", {"organism": "   "}
                )
            )
            check("no exception across the tool boundary", "candidates" in bad)
            check("candidates empty", bad["candidates"] == [])
            check(
                "explains the failure",
                any("Invalid request" in w for w in bad["warnings"]),
            )

            print("\n[7] loop closure -- feeding a result back changes the ranking")
            tested_id = candidates[0]["candidate_id"]
            second = payload_of(
                await session.call_tool(
                    "generate_candidates",
                    {
                        **LISTERIA_ARGS,
                        "diversity_weight": 0.0,
                        "previous_results": [
                            {
                                "result_id": "res_mcp_1",
                                "experiment_id": "exp_mcp_1",
                                "candidate_id": tested_id,
                                "measurement": {"predicted_inhibition_fraction": 0.85},
                                "evidence_type": "simulation-derived",
                            }
                        ],
                    },
                )
            )
            before_novelty = candidates[0]["score_components"]["novelty"]
            after = {c["candidate_id"]: c for c in second["candidates"]}.get(tested_id)
            check(
                "tested candidate loses novelty or drops out",
                after is None or after["score_components"]["novelty"] < before_novelty,
                f"novelty {before_novelty} -> "
                f"{after['score_components']['novelty'] if after else 'dropped'}",
            )
            if after:
                print(
                    f"       {after['name']}: novelty {before_novelty:.2f} -> "
                    f"{after['score_components']['novelty']:.2f}"
                )

            print("\n[8] determinism across calls")
            again = payload_of(
                await session.call_tool("generate_candidates", LISTERIA_ARGS)
            )
            # full_envelope_path is content-addressed on the request, so it is
            # stable too; comparing the whole payload is the strict check.
            check("identical arguments give identical output", again == result)

    print(f"\n{'=' * 70}")
    print(f"{len(passed)} passed, {len(failed)} failed")
    if failed:
        for name in failed:
            print(f"  FAILED: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
