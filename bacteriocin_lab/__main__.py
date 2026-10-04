"""``python -m bacteriocin_lab`` runs the deterministic end-to-end discovery demo.

Fixture agents, no network, no API keys: it exercises the real orchestrator, router, state manager
and loop guards. For real-agent behaviour see ``bacteriocin_lab.orchestration.registry``.
"""

from __future__ import annotations

import sys

from bacteriocin_lab.evaluation.demo_scenarios import run_demo

if __name__ == "__main__":
    sys.exit(run_demo())
