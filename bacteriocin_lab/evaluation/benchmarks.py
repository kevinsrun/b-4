"""Benchmarks: the simulator's directional-biology invariants as a runnable gate.

These are directional checks (more dose never inhibits less, Gram-negative targets resist
Gram-positive-specific peptides, ...), not calibration against measured data.
"""

from __future__ import annotations

import sys
from typing import Any

from bacteriocin_lab.agents.simulator.selftest import run_selftest


def run_invariant_benchmark(parameter_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the simulator selftest, optionally under refitted priors, and return its report."""
    return run_selftest(parameter_overrides)


if __name__ == "__main__":
    report = run_invariant_benchmark()
    print(f"{report['n_checks']} invariants, {report['n_failed']} failed")
    sys.exit(0 if report["passed"] else 1)
