#!/usr/bin/env python3
"""Drive the literature server over real MCP stdio."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "tools" / "launchers" / "literature.py"
PACKAGE_SRC = REPO / "packages" / "b4_literature" / "src"

passed: list[str] = []
failed: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        passed.append(name)
        print(f"  PASS  {name}")
    else:
        failed.append(name)
        print(f"  FAIL  {name}  {detail}")


def _attr(obj: object, *names: str) -> object:
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    raise AttributeError(f"none of {names} on {type(obj).__name__}")


def payload_of(result) -> dict:
    return json.loads(result.content[0].text)


async def main() -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER)],
        env={"PYTHONPATH": str(PACKAGE_SRC), "BACTERIOCIN_LOG_LEVEL": "WARNING"},
    )
    async with stdio_client(params) as (read, write):  # noqa: SIM117
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            info = _attr(init, "server_info", "serverInfo")
            check("server identity", info.name == "bacteriocin-literature-evidence")

            listing = await session.list_tools()
            names = {tool.name for tool in listing.tools}
            check("bounded tool surface", names == {"literature_evidence"}, str(names))
            tool = listing.tools[0]
            schema = _attr(tool, "input_schema", "inputSchema") or {}
            properties = schema.get("properties") or {}
            check("question is required", "question" in schema.get("required", []))
            check("retrieval controls advertised", "max_results" in properties)
            check("source document input advertised", "source_documents" in properties)
            source_schema = json.dumps(properties["source_documents"])
            check("source document schema is typed", "SourceDocument" in source_schema)
            check("trust warning advertised", "never chooses" in (tool.description or ""))

            payload = payload_of(
                await session.call_tool(
                    "literature_evidence",
                    {
                        "query_id": "protocol-test",
                        "question": "What is nisin activity against Listeria monocytogenes?",
                        "bacteriocin": "nisin",
                        "target_organism": "Listeria monocytogenes",
                        "target_strain": "ATCC 19115",
                        "source_documents": [
                            {
                                "source": {
                                    "source_id": "doi:10.1000/protocol",
                                    "title": "Protocol fixture",
                                    "doi_or_url": "https://doi.org/10.1000/protocol",
                                    "year": 2025,
                                },
                                "text": (
                                    "In a broth microdilution assay, 10^6 CFU/mL "
                                    "Listeria monocytogenes ATCC 19115 in BHI broth was "
                                    "exposed to nisin at 2.5 mg/L for 90 minutes at pH "
                                    "6.5 and 37 °C. The MIC of nisin was 2.5 mg/L."
                                ),
                                "locator": "Results, paragraph 2",
                            }
                        ],
                    },
                )
            )
            check("query identity preserved", payload["query_id"] == "protocol-test")
            check("one measured record extracted", len(payload["evidence"]) == 1)
            evidence = payload["evidence"][0]
            check(
                "literature provenance retained",
                evidence["evidence_type"] == "literature-derived",
            )
            check(
                "measurement remains measured",
                evidence["measurement"]["data_role"] == "measured",
            )
            check(
                "source locator retained",
                evidence["provenance"]["locator"] == "Results, paragraph 2",
            )
            check(
                "missing variables explicit",
                "producer_cell_density" in evidence["missing_variables"],
            )
            check(
                "no candidate decision",
                payload["decision"]["candidate_decision"] == "not-performed",
            )
            check(
                "human or Codex adjudication required",
                payload["recommended_next_action"]["requires_codex_or_human_adjudication"] is True,
            )

    print(f"\n{len(passed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
