#!/usr/bin/env python3
"""Integration test driving Omnigent's OWN MCP manager against the bundle.

This is the strongest test available on a machine with no harness CLI and no
API key: it parses the agent bundle with Omnigent's parser and then connects,
registers tools and dispatches calls through ``RunnerMcpManager`` -- the same
class Omnigent uses in a live session. The only thing missing is the LLM that
would decide *when* to call the tool.

Run with Omnigent's own interpreter::

    ~/.local/share/uv/tools/omnigent/bin/python \\
        tools/tests/test_omnigent_manager.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[3]

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
    servers = (
        "literature",
        "candidates",
        "runner",
        "critic",
        "knowledge",
        "experiment_planner",
        "result_analysis",
    )
    declarations = [BUNDLE / "tools" / "mcp" / f"{name}.yaml" for name in servers]
    missing = [path for path in declarations if not path.is_file()]
    if missing:
        print(f"error: generated declarations are missing: {missing}.\n  Run: python3 install.py")
        return 1

    print("[1] parse the bundle with Omnigent's parser")
    spec = parse(BUNDLE)
    check("bundle parses", spec.spec_version == 1)
    check("agent is named", spec.name == "bacteriocin-lab", f"got {spec.name}")
    check("AGENTS.md loaded as instructions", bool(spec.instructions))
    check(
        "every agent server declared",
        len(spec.mcp_servers) == len(servers),
        str(len(spec.mcp_servers)),
    )
    check("all use stdio", all(server.transport == "stdio" for server in spec.mcp_servers))
    check(
        "all commands are absolute",
        all(Path(server.command or "").is_absolute() for server in spec.mcp_servers),
    )
    allowlists = {server.name: set(server.tools or []) for server in spec.mcp_servers}
    check(
        "literature allowlist set",
        allowlists.get("literature") == {"literature_evidence"},
        str(allowlists),
    )
    check(
        "candidate allowlist set",
        allowlists.get("candidates") == {"generate_candidates", "describe_agent"},
        str(allowlists),
    )
    check(
        "knowledge allowlist set",
        {"update_research_state", "get_hypothesis_history", "summarize_research_state"}
        <= allowlists.get("knowledge", set()),
        str(allowlists),
    )
    check(
        "planner allowlist set",
        allowlists.get("experiment_planner") == {"plan_experiment", "describe", "get_schema"},
        str(allowlists),
    )
    check(
        "analysis allowlist set",
        allowlists.get("result_analysis") == {"analyze", "get_schema", "describe"},
        str(allowlists),
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
        check("plan_experiment registered", any("plan_experiment" in n for n in names), str(names))
        check("analyze registered", any(n.endswith("analyze") for n in names), str(names))
        check(
            "literature_evidence registered",
            any("literature_evidence" in n for n in names),
            str(names),
        )
        for name in names:
            print(f"       registered: {name}")

        # Tool names may be namespaced by server; find the real call names.
        gen_name = next(n for n in names if "generate_candidates" in n)
        desc_name = next(n for n in names if "describe_agent" in n)
        literature_name = next(n for n in names if "literature_evidence" in n)

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

        print("\n[4b] hand the candidate agent's reply to the knowledge agent through the manager")
        import tempfile

        state_dir = tempfile.mkdtemp(prefix="bacteriocin-state-")
        wanted = ("register_candidates", "summarize_research_state", "verify_state_integrity")
        knowledge = {n: next(x for x in names if x.endswith(n)) for n in wanted}
        registered = tool_payload(
            await manager.call_tool(
                spec,
                knowledge["register_candidates"],
                {"candidate_output": payload, "state_dir": state_dir},
            )
        )
        check(
            "candidates registered from the compact reply",
            registered["status"] == "ok"
            and registered["new_event_types"].get("candidate_registered") == 3,
            str(registered)[:300],
        )
        summary = tool_payload(
            await manager.call_tool(
                spec, knowledge["summarize_research_state"], {"state_dir": state_dir}
            )
        )
        check("state summary lists the hypotheses", len(summary["result"]["hypotheses"]) >= 3)
        check(
            "state says nothing is validated",
            "Nothing here is experimentally validated" in summary["result"]["provenance"],
        )
        verdict = tool_payload(
            await manager.call_tool(
                spec, knowledge["verify_state_integrity"], {"state_dir": state_dir}
            )
        )
        check("history chain intact", verdict["result"]["intact"])

        print("\n[5] call literature_evidence through the manager")
        literature = tool_payload(
            await manager.call_tool(
                spec,
                literature_name,
                {
                    "query_id": "omnigent-manager-test",
                    "question": "What is nisin activity against Listeria monocytogenes?",
                    "bacteriocin": "nisin",
                    "target_organism": "Listeria monocytogenes",
                    "source_documents": [
                        {
                            "source": {
                                "source_id": "doi:10.1000/manager",
                                "title": "Manager fixture",
                            },
                            "text": "Nisin inhibited Listeria monocytogenes in vitro.",
                            "locator": "abstract",
                        }
                    ],
                },
            )
        )
        check("literature record returned", len(literature["evidence"]) == 1)
        check(
            "literature output remains non-decisional",
            literature["decision"]["candidate_decision"] == "not-performed",
        )
        check(
            "author interpretation is not measured data",
            literature["evidence"][0]["measurement"]["data_role"] == "author-interpretation",
        )

        print("\n[6] the schema is self-documenting (the live-run defect)")
        gen_schema = next(
            (
                s_
                for s_ in schemas
                if (s_.get("name") if isinstance(s_, dict) else getattr(s_, "name", "")) == gen_name
            ),
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

        print("\n[7] tool allowlists are enforced")
        expected_count = sum(len(tools) for tools in allowlists.values())
        check(
            "no unexpected tools exposed",
            len(names) == expected_count,
            f"got {len(names)}: {names}",
        )

        print("\n[8] error path through the manager")
        bad = tool_payload(await manager.call_tool(spec, gen_name, {"organism": "   "}))
        check("invalid request does not raise", "candidates" in bad)
        check("candidates empty", bad["candidates"] == [])
        check("reason reported", any("Invalid request" in w for w in bad["warnings"]))

    finally:
        await manager.shutdown()
        print("\n[9] manager shut down cleanly")
        check("shutdown completed", True)

    print(f"\n{'=' * 70}")
    print(f"{len(passed)} passed, {len(failed)} failed")
    for name in failed:
        print(f"  FAILED: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
