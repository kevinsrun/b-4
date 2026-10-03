#!/usr/bin/env python3
"""Protocol test: drive the launcher Omnigent actually spawns, over real stdio.

``tests/test_mcp_server.py`` calls the tool functions directly, which proves
the backend is wired correctly but says nothing about the transport. This test
covers the part only a subprocess can: that the generated declaration points
at an interpreter that can import the server, that the launcher's path setup
works from an unrelated cwd, and that a real MCP client can initialize,
enumerate the tools and get a scientifically correct answer back over
JSON-RPC.

Run it directly (no pytest needed -- ``testpaths`` does not collect this
directory)::

    python3 integrations/omnigent/simulation/test_mcp_protocol.py

Run ``install.py`` first; this exits with instructions if the declaration is
missing or stale.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

sys.path.insert(0, str(REPO))
import install  # noqa: E402  (repo-root module, not a package)

DECLARATION = REPO / "tools" / "mcp" / "runner.yaml"
LAUNCHER = REPO / "tools" / "launchers" / "runner.py"
PACKAGE = REPO / "packages" / "bacteriocin_sim"
SPEC = json.loads((PACKAGE / "examples" / "spec_nisin_listeria.json").read_text())

EXPECTED_TOOLS = {
    "capabilities",
    "describe",
    "get_schema",
    "run_agent",
    "run_experiments",
    "run_experiment",
    "selftest",
}

_FAILURES: list[str] = []


def _attr(obj: object, *names: str) -> object:
    """Read the first attribute that exists.

    The MCP SDK renamed its result fields between majors: 1.x exposes
    ``serverInfo`` / ``structuredContent``, 2.x ``server_info`` /
    ``structured_content``. The server supports both SDKs, so this client has
    to as well, or the test would only ever exercise one of them.
    """
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    raise AttributeError(f"none of {names} on {type(obj).__name__}")


def _payload(result: object) -> dict:
    """Tool result as a dict, whichever SDK major produced it."""
    structured = _attr(result, "structured_content", "structuredContent")
    if structured:
        return structured  # type: ignore[return-value]
    return json.loads(result.content[0].text)  # type: ignore[attr-defined]


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' -- ' + detail) if detail else ''}")
    if not ok:
        _FAILURES.append(label)


def check_declaration() -> None:
    print("declaration")
    if not DECLARATION.is_file():
        raise SystemExit(
            f"error: {DECLARATION} is missing.\n"
            "  run: python3 install.py"
        )
    text = DECLARATION.read_text()
    check("names the launcher by absolute path", str(LAUNCHER) in text)
    check("sets PYTHONPATH to the package", f'PYTHONPATH: "{PACKAGE}"' in text)
    check("keeps logs off stdout", "BACTERIOCIN_LOG_LEVEL" in text)
    # A ${VAR} left in command/args would be passed through literally by
    # Omnigent and the spawn would fail with a confusing ENOENT. Only the
    # directives matter -- the header comment legitimately mentions ${VAR}
    # while explaining why these paths are written out.
    directives = [
        line
        for line in text.split("env:", 1)[0].splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    check(
        "no unexpanded ${VAR} in command/args",
        not any("${" in line for line in directives),
    )


async def check_protocol() -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    python = install.find_python(None)
    print(f"\nprotocol (interpreter: {python})")

    params = StdioServerParameters(
        command=str(python),
        args=[str(LAUNCHER)],
        env={"PYTHONPATH": str(PACKAGE), "BACTERIOCIN_LOG_LEVEL": "WARNING"},
        # Deliberately not the repo: proves the launcher's own path setup works
        # rather than the cwd quietly making the import succeed.
        cwd=str(Path.home()),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            server_name = _attr(_attr(init, "server_info", "serverInfo"), "name")
            check("initialize", server_name == "bacteriocin-sim",
                  f"server={server_name}")

            listed = await session.list_tools()
            names = {t.name for t in listed.tools}
            check("declared tool surface", names == EXPECTED_TOOLS,
                  f"{len(names)} tools")
            check("every tool documented", all(t.description for t in listed.tools))

            res = await session.call_tool("run_experiment", {"spec": SPEC})
            result = _payload(res)
            m = result["measurement"]
            check("run_experiment succeeds", result["status"] == "ok")
            check("provenance is simulation-derived",
                  result["evidence_type"] == "simulation-derived")
            check("never claims validation",
                  result["validated_experimentally"] is False)
            check("carries a continuous prediction",
                  isinstance(m["predicted_inhibition_fraction"], float))
            check("carries an MIC", m["predicted_mic_um"] > 0,
                  f"MIC={m['predicted_mic_um']} uM")
            check("quantifies its uncertainty",
                  len(result["uncertainty_components"]) > 0,
                  f"{len(result['uncertainty_components'])} named sources")
            check("ranks the factors", len(result["important_factors"]) > 0,
                  f"top={result['important_factors'][0]['factor']}")

            # Determinism must survive the transport, not just the API.
            again = await session.call_tool("run_experiment", {"spec": SPEC})
            repeat = _payload(again)
            for payload in (result, repeat):
                payload.pop("created_at", None)
            check("deterministic across calls", result == repeat)

            bad = await session.call_tool("run_experiment", {"spec": {"nope": 1}})
            err = _payload(bad)
            check("a bad spec returns a structured error",
                  err.get("error_code") == "spec_validation_error")

            st = await session.call_tool("selftest", {})
            report = _payload(st)
            check("scientific invariants hold", report["passed"] is True,
                  f"{report['n_checks']} checks")


def main() -> int:
    check_declaration()
    asyncio.run(check_protocol())
    print()
    if _FAILURES:
        print(f"{len(_FAILURES)} check(s) failed: {', '.join(_FAILURES)}")
        return 1
    print("all protocol checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
