#!/usr/bin/env python3
"""Protocol-level test: drive the knowledge MCP server as a real stdio client.

Spawns ``tools/launchers/knowledge.py`` as a subprocess and speaks MCP over stdio exactly as
Omnigent's ``mcp_manager`` does. It also spawns the candidates launcher and hands the knowledge
server that agent's saved envelope **by path**, the real cross-server handoff.

Run with an interpreter that has the ``mcp`` SDK::

    ~/.local/share/uv/tools/omnigent/bin/python tools/tests/test_knowledge_protocol.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
KNOWLEDGE = REPO / "tools" / "launchers" / "knowledge.py"
CANDIDATES = REPO / "tools" / "launchers" / "candidates.py"
KNOWLEDGE_PATH = ":".join(
    str(REPO / p)
    for p in ("packages/knowledge_agent/src", "shared", "packages/bacteriocin_discovery/src")
)

passed: list[str] = []
failed: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (passed if condition else failed).append(name)
    print(f"  {'PASS' if condition else 'FAIL'}  {name}  {'' if condition else detail}")


def payload_of(result) -> dict:
    return json.loads(result.content[0].text)


def _attr(obj: object, *names: str) -> object:
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    raise AttributeError(f"none of {names} on {type(obj).__name__}")


def analysis(
    n: int, status: str, candidate_id: str, hypothesis_id: str, strength: str = "moderate"
) -> dict:
    return {
        "decision": {
            "finding_id": f"find_{n}",
            "experiment_id": f"exp_{n}",
            "result_id": f"res_{n}",
            "candidate_id": candidate_id,
            "hypothesis_id": hypothesis_id,
            "hypothesis_status": status,
            "evidence_strength": strength,
            "findings": [
                {
                    "variable": "target_cell_density",
                    "relationship": "negative" if status == "supported" else "positive",
                    "controlled": True,
                    "effect_size": -0.2,
                }
            ],
            "recommended_followup_questions": [
                "Does this simulated relationship hold in a wet-lab assay?"
            ],
        }
    }


async def main() -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    state_dir = tempfile.mkdtemp(prefix="bacteriocin-state-")
    artifact_dir = tempfile.mkdtemp(prefix="bacteriocin-artifacts-")
    k_params = StdioServerParameters(
        command=sys.executable,
        args=[str(KNOWLEDGE)],
        env={"PYTHONPATH": KNOWLEDGE_PATH, "BACTERIOCIN_LOG_LEVEL": "WARNING"},
    )
    c_params = StdioServerParameters(
        command=sys.executable,
        args=[str(CANDIDATES)],
        env={
            "PYTHONPATH": str(REPO / "packages/bacteriocin_discovery/src"),
            "BACTERIOCIN_LOG_LEVEL": "WARNING",
            "BACTERIOCIN_ARTIFACT_DIR": artifact_dir,
        },
    )

    async with (
        stdio_client(c_params) as (cr, cw),
        ClientSession(cr, cw) as cands,
        stdio_client(k_params) as (kr, kw),
        ClientSession(kr, kw) as know,
    ):
        print("[1] initialize")
        init = await know.initialize()
        await cands.initialize()
        info = _attr(init, "server_info", "serverInfo")
        check(
            "server identifies itself", info.name == "bacteriocin-knowledge", f"got {info.name!r}"
        )

        print("\n[2] tools/list")
        listing = await know.list_tools()
        names = {t.name for t in listing.tools}
        expected = {
            "initialize_research_state",
            "register_candidates",
            "record_experiment_plan",
            "register_evidence",
            "update_research_state",
            "reject_candidate",
            "close_open_question",
            "get_candidate_history",
            "get_hypothesis_history",
            "get_experiment_history",
            "get_open_questions",
            "summarize_research_state",
            "get_state_at_iteration",
            "verify_state_integrity",
        }
        check("all fourteen tools exposed", names == expected, f"got {sorted(names ^ expected)}")
        desc = next(t.description for t in listing.tools if t.name == "update_research_state")
        check("tool description states the append-only rule", "never overwrites history" in desc)
        check("tool description states the inconclusive rule", "INCONCLUSIVE" in desc)
        schema = (
            _attr(
                next(t for t in listing.tools if t.name == "update_research_state"),
                "input_schema",
                "inputSchema",
            )
            or {}
        )
        check(
            "update_research_state advertises flat parameters",
            {
                "analysis_result",
                "result",
                "spec",
                "hypothesis",
                "advance_iteration",
                "expected_event_count",
            }
            <= set(schema.get("properties", {})),
        )

        print("\n[3] a real cross-server handoff: candidates -> knowledge, by path")
        proposed = payload_of(
            await cands.call_tool(
                "generate_candidates",
                {
                    "organism": "Listeria monocytogenes",
                    "gram": "positive",
                    "max_candidates": 2,
                    "target_cell_density": 1e8,
                },
            )
        )
        check(
            "candidate agent saved its full envelope",
            bool(proposed["full_envelope_path"]) and Path(proposed["full_envelope_path"]).is_file(),
        )
        await know.call_tool(
            "initialize_research_state",
            {"objective": {"goal": "density effect on inhibition"}, "state_dir": state_dir},
        )
        reg = payload_of(
            await know.call_tool(
                "register_candidates",
                {"candidate_output_path": proposed["full_envelope_path"], "state_dir": state_dir},
            )
        )
        check(
            "candidates registered from the saved envelope",
            reg["status"] == "ok" and reg["new_event_types"].get("candidate_registered") == 2,
            str(reg)[:300],
        )
        check(
            "provenance disclaimer is the first field",
            next(iter(reg)) == "PROVENANCE" and "NOT" in reg["PROVENANCE"],
        )
        top = proposed["candidates"][0]
        cid, hid = top["candidate_id"], top["hypothesis_ids"][0]
        compact = payload_of(
            await know.call_tool(
                "get_candidate_history", {"candidate_id": cid, "state_dir": state_dir}
            )
        )
        check(
            "candidate history is queryable",
            compact["result"]["candidate"]["status"] == "proposed"
            and compact["result"]["hypotheses"],
        )
        compact_reg = payload_of(
            await know.call_tool(
                "register_candidates", {"candidate_output": proposed, "state_dir": state_dir}
            )
        )
        check(
            "registering the compact reply again is a no-op for candidates",
            not compact_reg["new_event_types"].get("candidate_registered"),
        )

        print("\n[4] supported, then weakened: both states survive")
        await know.call_tool(
            "record_experiment_plan",
            {
                "plan": {"experiment_id": "exp_1", "candidate_id": cid, "hypothesis_id": hid},
                "state_dir": state_dir,
            },
        )
        r1 = payload_of(
            await know.call_tool(
                "update_research_state",
                {"analysis_result": analysis(1, "supported", cid, hid), "state_dir": state_dir},
            )
        )
        check(
            "first update moves the hypothesis to supported",
            [t["new_status"] for t in r1["hypothesis_transitions"]] == ["supported"],
        )
        r2 = payload_of(
            await know.call_tool(
                "update_research_state",
                {"analysis_result": analysis(2, "weakened", cid, hid), "state_dir": state_dir},
            )
        )
        (t,) = r2["hypothesis_transitions"]
        check(
            "second update records supported -> weakened",
            (t["previous_status"], t["new_status"]) == ("supported", "weakened"),
        )
        check(
            "transition names what triggered it",
            "experiment:exp_2" in t["triggered_by"] and "finding:find_2" in t["triggered_by"],
        )
        check(
            "response is small enough to survive truncation",
            len(json.dumps(r2)) < 12000,
            f"{len(json.dumps(r2))} bytes",
        )
        history = payload_of(
            await know.call_tool(
                "get_hypothesis_history", {"hypothesis_id": hid, "state_dir": state_dir}
            )
        )
        chain = [
            (c["from"], c["to"])
            for c in history["result"]["timeline"]
            if c["type"] == "status_change"
        ]
        check(
            "hypothesis history keeps every status",
            chain == [(None, "open"), ("open", "supported"), ("supported", "weakened")],
            str(chain),
        )

        print("\n[5] questions, summary, reconstruction")
        questions = payload_of(await know.call_tool("get_open_questions", {"state_dir": state_dir}))
        check(
            "open questions include the relationship reversal",
            any("changed from" in q["text"] for q in questions["result"]),
            str([q["text"] for q in questions["result"]]),
        )
        summary = payload_of(
            await know.call_tool("summarize_research_state", {"state_dir": state_dir})
        )
        check(
            "summary says nothing is validated",
            "Nothing here is experimentally validated" in summary["result"]["provenance"]
            or "none" in summary["result"]["provenance"],
        )
        past = payload_of(
            await know.call_tool("get_state_at_iteration", {"iteration": 1, "state_dir": state_dir})
        )
        check(
            "the state after turn 1 is reconstructed from the log",
            [h["status"] for h in past["result"]["hypotheses"] if h["hypothesis_id"] == hid]
            == ["supported"],
        )
        check(
            "integrity verifies",
            payload_of(await know.call_tool("verify_state_integrity", {"state_dir": state_dir}))[
                "result"
            ]["intact"],
        )
        check("the log is on disk", (Path(state_dir) / "events.jsonl").is_file())

        print("\n[6] errors are structured, never exceptions")
        missing = payload_of(
            await know.call_tool(
                "get_candidate_history", {"candidate_id": "ghost", "state_dir": state_dir}
            )
        )
        check("unknown candidate is reported as not_found", missing["status"] == "not_found")
        bad = payload_of(
            await know.call_tool(
                "update_research_state",
                {
                    "analysis_result": {"decision": {"hypothesis_status": "supported"}},
                    "state_dir": state_dir,
                },
            )
        )
        check("invalid analysis is an error envelope", bad["status"] == "error" and bad["warnings"])
        stale = payload_of(
            await know.call_tool(
                "update_research_state",
                {
                    "analysis_result": analysis(9, "supported", cid, hid),
                    "expected_event_count": 1,
                    "state_dir": state_dir,
                },
            )
        )
        check("a stale write is a conflict", stale["status"] == "conflict")
        nopath = payload_of(
            await know.call_tool(
                "register_candidates",
                {"candidate_output_path": "/nonexistent.json", "state_dir": state_dir},
            )
        )
        check("a bad path is reported, not raised", nopath["status"] == "error")

        print("\n[7] tampering is detected")
        events = Path(state_dir) / "events.jsonl"
        lines = events.read_text().splitlines()
        first = json.loads(lines[0])
        first["objective"] = {"goal": "quietly rewritten"}
        lines[0] = json.dumps(first)
        events.write_text("\n".join(lines) + "\n")
        verdict = payload_of(
            await know.call_tool("verify_state_integrity", {"state_dir": state_dir})
        )
        check(
            "verify_state_integrity reports the edit",
            verdict["status"] == "integrity_error" and not verdict["result"]["intact"],
        )

    print(f"\n{'=' * 70}\n{len(passed)} passed, {len(failed)} failed")
    for name in failed:
        print(f"  FAILED: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
