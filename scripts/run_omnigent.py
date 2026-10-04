#!/usr/bin/env python3
"""Run the B-4 agent through a minimal, symlink-free Omnigent bundle.

Omnigent 0.16 archives every file below an agent directory and rejects links
when unpacking it. A normal uv environment contains ``.venv/bin/python``
symlinks, so passing the repository root directly cannot work after ``uv
sync``. The MCP servers still need to run from the real checkout, where their
generated declarations use absolute paths.

This launcher stages only the declarative agent surface and forwards all CLI
arguments to ``omnigent run``. It never copies the virtualenv, Git data,
packages, credentials, or research artifacts.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REQUIRED_DECLARATIONS = (
    "literature.yaml",
    "candidates.yaml",
    "experiment_planner.yaml",
    "runner.yaml",
    "result_analysis.yaml",
    "critic.yaml",
    "knowledge.yaml",
)


def _stage_bundle(destination: Path) -> None:
    shutil.copy2(REPO / "config.yaml", destination / "config.yaml")
    shutil.copy2(REPO / "AGENTS.md", destination / "AGENTS.md")
    shutil.copytree(REPO / "agents", destination / "agents")

    mcp_destination = destination / "tools" / "mcp"
    mcp_destination.mkdir(parents=True)
    missing: list[str] = []
    for filename in REQUIRED_DECLARATIONS:
        source = REPO / "tools" / "mcp" / filename
        if not source.is_file():
            missing.append(filename)
            continue
        shutil.copy2(source, mcp_destination / filename)

    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            f"generated MCP declarations missing: {joined}; run `python3 install.py` first"
        )


def main(argv: list[str] | None = None) -> int:
    omnigent = shutil.which("omnigent")
    if omnigent is None:
        print("error: omnigent executable not found", file=sys.stderr)
        return 127

    try:
        with tempfile.TemporaryDirectory(prefix="b4-omnigent-") as temporary:
            bundle = Path(temporary) / "agent"
            bundle.mkdir()
            _stage_bundle(bundle)
            completed = subprocess.run(
                [omnigent, "run", str(bundle), *(argv if argv is not None else sys.argv[1:])],
                check=False,
            )
            return completed.returncode
    except (OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
