"""The model's qualitative invariants, run through pytest.

Each invariant in ``bacteriocin_sim.selftest`` becomes its own test so a
failure names the specific piece of biology the model got wrong.
"""

from __future__ import annotations

import pytest

from bacteriocin_sim.selftest import CHECKS


@pytest.mark.parametrize("name", sorted(CHECKS))
def test_invariant(name: str) -> None:
    passed, detail = CHECKS[name]()
    assert passed, f"{name}: {detail}"
