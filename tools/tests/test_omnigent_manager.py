#!/usr/bin/env python3
"""Integration test driving Omnigent's OWN MCP manager against the bundle.

This is the strongest test available on a machine with no harness CLI and no
API key: it parses the agent bundle with Omnigent's parser and then connects,
registers tools and dispatches calls through ``RunnerMcpManager`` -- the same
class Omnigent uses in a live session. The only thing missing is the LLM that
would decide *when* to call the tool.

Run with Omnigent's own interpreter::

    ~/.local/share/uv/tools/omnigent/bin/python \\
        integrations/omnigent/test_omnigent_manager.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent / "agent"

passed: list[str] = []
failed: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        passed.append(name)
        print(f"  PASS  {name}")
    else:
        failed.append(name)
        print(f"  FAIL  {name}  {detail}")


def tool_payload(result) -> dict:
    """Pull the JSON payload out of whatever shape the manager returns."""
    # The manager normalises MCP content blocks; handle the common shapes.
    content = getattr(result, "content", result)
    if isinstance(content, list) and content:
        block = content[0]
        text = getattr(block, "text", None) or (
            block.get("text") if isinstance(block, dict) else None
        )
    else:
        text = getattr(content, "text", None) or (
            content if isinstance(content, str) else json.dumps(content)
        )
    return json.loads(text)


async def main() -> int:
    from omnigent.runner.mcp_manager import RunnerMcpManager
    from omnigent.spec import parse

    # The MCP declaration is generated, not checked in: it holds machine-specific
    # absolute paths because Omnigent treats `command`/`args` as literals.
    declaration = BUNDLE / "tools" / "mcp" / "bacteriocin.yaml"
    if not declaration.is_file():
        print(
            f"error: {declaration} is missing.\n"
            "  Run: python3 integrations/omnigent/install.py"
        )
        return 1

    print("[1] parse the bundle with Omnigent's parser")
    spec = parse(BUNDLE)
    check("bundle parses", spec.spec_version == 1)
    check("agent is named", spec.name == "bacteriocin-discovery-lead", f"got {spec.name}")
    check("AGENTS.md loaded as instructions", bool(spec.instructions))
    check("one MCP server declared", len(spec.mcp_servers) == 1)
    server = spec.mcp_servers[0]
    check("stdio transport", server.transport == "stdio")
    check("command is absolute", Path(server.command or "").is_absolute(), server.command or "")
    check(
        "tool allowlist set",
        set(server.tools or []) == {"generate_candidates", "describe_agent"},
        str(server.tools),
    )
    print(f"       instructions: {len(spec.instructions or '')} chars")

    manager = RunnerMcpManager()
    try:
        print("\n[2] connect and discover schemas through RunnerMcpManager")
        result = await manager.schemas_for(spec)
        schemas = result.schemas if hasattr(result, "schemas") else result
        names = []
        for schema in schemas:
            name = schema.get("name") if isinstance(schema, dict) else getattr(schema, "name", None)
            if name:
                names.append(name)
        check("manager connected and registered tools", bool(names), f"got {names}")
        check(
            "generate_candidates registered",
            any("generate_candidates" in n for n in names),
            str(names),
        )
        check("describe_agent registered", any("describe_agent" in n for n in names), str(names))
        for name in names:
            print(f"       registered: {name}")

        # Tool names may be namespaced by server; find the real call names.
        gen_name = next(n for n in names if "generate_candidates" in n)
        desc_name = next(n for n in names if "describe_agent" in n)

        print("\n[3] call describe_agent through the manager")
        described = tool_payload(await manager.call_tool(spec, desc_name, {}))
        check(
            "identity returned",
            described.get("agent") == "candidate_generation_agent",
            str(described.get("agent")),
        )
        check("refusals declared", bool(described.get("will_not")))
        print(f"       model_version: {described.get('model_version')}")
        print(f"       knowledge_source: {described.get('knowledge_source')}")

        print("\n[4] call generate_candidates through the manager")
        payload = tool_payload(
            await manager.call_tool(
                spec,
                gen_name,
                {
                    "organism": "Listeria monocytogenes",
                    "strain": "EGD-e",
                    "gram": "positive",
                    "max_candidates": 3,
                    "ph_low": 6.0,
                    "ph_high": 7.5,
                    "temperature_c": 37,
                    "target_cell_density": 100000000,
                    "diversity_weight": 0.3,
                },
            )
        )
        candidates = payload["candidates"]
        check(
            "max_candidates honoured through the manager",
            payload["returned_count"] == 3,
            f"asked 3, got {payload['returned_count']}",
        )
        check(
            "contract rule 9: all unvalidated",
            all(c["validation_status"] == "unvalidated" for c in candidates),
        )
        check(
            "each has a falsification clause",
            all(c["falsified_if"] for c in candidates),
        )
        check(
            "routes to experiment_planner",
            payload["recommended_next_action"]["agent"] == "experiment_planner",
        )
        check("provenance disclaimer present", "PROPOSALS, NOT FINDINGS" in payload["PROVENANCE"])
        check("warnings survive the manager hop", len(payload["warnings"]) >= 1)
        check(
            "response small enough for a model turn",
            len(json.dumps(payload)) < 15000,
            f"{len(json.dumps(payload))} bytes",
        )
        for candidate in candidates:
            print(
                f"       #{candidate['rank']} {candidate['name']}  "
                f"total={candidate['score_total']:.3f}  driver={candidate['rank_driven_by']}"
            )
        print(f"       response size: {len(json.dumps(payload))} bytes")

        print("\n[5] the schema is self-documenting (the live-run defect)")
        gen_schema = next(
            (s_ for s_ in schemas
             if (s_.get("name") if isinstance(s_, dict) else getattr(s_, "name", "")) == gen_name),
            None,
        )
        # Omnigent normalises MCP schemas into OpenAI function-calling shape, so
        # the JSON Schema lives under "parameters" rather than "inputSchema".
        props: dict = {}
        if isinstance(gen_schema, dict):
            props = (gen_schema.get("parameters") or {}).get("properties") or {}
        check(
            "max_candidates is an advertised parameter",
            "max_candidates" in props,
            f"advertised: {sorted(props)[:8]}",
        )
        check("organism is advertised", "organism" in props, f"advertised: {sorted(props)[:8]}")
        check("gram is advertised", "gram" in props)
        print(f"       {len(props)} parameters advertised to the model")

        print("\n[6] tool allowlist is enforced")
        # `mcp_server.py` registers only these two, and the YAML allowlist names
        # the same two, so nothing outside the list should be callable.
        check("no unexpected tools exposed", len(names) == 2, f"got {len(names)}: {names}")

        print("\n[7] error path through the manager")
        bad = tool_payload(await manager.call_tool(spec, gen_name, {"organism": "   "}))
        check("invalid request does not raise", "candidates" in bad)
        check("candidates empty", bad["candidates"] == [])
        check("reason reported", any("Invalid request" in w for w in bad["warnings"]))

    finally:
        await manager.shutdown()
        print("\n[8] manager shut down cleanly")
        check("shutdown completed", True)

    print(f"\n{'=' * 70}")
    print(f"{len(passed)} passed, {len(failed)} failed")
    for name in failed:
        print(f"  FAILED: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
