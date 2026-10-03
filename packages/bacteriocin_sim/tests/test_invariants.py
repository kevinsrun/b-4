"""The model's qualitative invariants, run through pytest.

Each invariant in ``bacteriocin_sim.selftest`` becomes its own test so a
failure names the specific piece of biology the model got wrong.

Invariants listed in ``KNOWN_FAILURES`` are open defects in the *model*, not
wrong tests, so they are ``xfail`` rather than deleted or weakened. ``strict``
is deliberate: if someone repairs the model, the xpass fails the suite and
says the entry should be retired. A known failure that quietly starts passing
is how a fixed bug gets re-introduced later.
"""

from __future__ import annotations

import pytest

from bacteriocin_sim.selftest import CHECKS, KNOWN_FAILURES, run_selftest


@pytest.mark.parametrize("name", sorted(CHECKS))
def test_invariant(name: str, request: pytest.FixtureRequest) -> None:
    if name in KNOWN_FAILURES:
        request.applymarker(
            pytest.mark.xfail(strict=True, reason=KNOWN_FAILURES[name])
        )
    passed, detail = CHECKS[name]()
    assert passed, f"{name}: {detail}"


def test_report_separates_known_failures_from_real_ones() -> None:
    """A known failure must not fail the run, and must stay visible."""
    report = run_selftest()
    assert report["n_failed"] == 0, [
        c for c in report["checks"] if c["status"] == "fail"
    ]
    assert report["passed"] is True
    for entry in report["checks"]:
        assert entry["status"] in {
            "pass",
            "fail",
            "known_failure",
            "unexpectedly_fixed",
        }
        if entry["status"] == "known_failure":
            assert entry["known_failure_reason"]


def test_every_known_failure_is_still_failing() -> None:
    """Guards the registry against going stale.

    An entry that no longer reproduces means the model was fixed and nobody
    retired the entry -- which would then mask a genuine regression of the
    same invariant later.
    """
    report = run_selftest()
    fixed = [c["check"] for c in report["checks"] if c["status"] == "unexpectedly_fixed"]
    assert not fixed, (
        f"these invariants now pass and should be removed from KNOWN_FAILURES: {fixed}"
    )
