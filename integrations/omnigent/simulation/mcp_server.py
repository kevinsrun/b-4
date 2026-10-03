#!/usr/bin/env python3
"""Launcher Omnigent spawns for the simulation experiment backend.

Omnigent's MCP declaration names a ``command`` and ``args`` that are literal
absolute paths, so it needs a script at a fixed location. The server itself
lives in :mod:`bacteriocin_sim.mcp_server` -- inside the package, where it is
importable and unit-tested by ``tests/test_mcp_server.py``. This file only
makes the repository importable and hands off, so that the thing Omnigent runs
and the thing the tests exercise are the same code.

Generate the declaration that points here with::

    python3 integrations/omnigent/simulation/install.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# The declaration sets PYTHONPATH, but a developer running this script by hand
# has no reason to. Prepending keeps both paths working.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bacteriocin_sim.mcp_server import main  # noqa: E402

if __name__ == "__main__":
    main()
