"""Validation of biophysical parameter overrides against directional invariants.

Enforces fail-closed validation: parameter_overrides must satisfy all qualitative
directional invariants checked by SimulationAgent.selftest() before any ExperimentResult
is produced.
"""

from __future__ import annotations

import contextvars
import copy
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from .errors import InvariantViolationError
from .model.parameters import ParameterStore

_IS_VALIDATING: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_IS_VALIDATING", default=False
)

# Increment whenever the meaning of a validation outcome changes independently
# of the simulator model version (for example, when the invariant set changes).
_VALIDATION_REVISION = 1
_VALIDATION_CACHE_MAXSIZE = 256
_ValidationKey = tuple[int, str, str]


@dataclass(frozen=True)
class _ValidationOutcome:
    passed: bool
    n_checks: int
    failed_invariants: tuple[str, ...] = ()
    failed_checks: tuple[tuple[str, str], ...] = ()
    reason: str = ""


_VALIDATION_CACHE: OrderedDict[_ValidationKey, _ValidationOutcome] = OrderedDict()
_VALIDATION_CACHE_LOCK = threading.Lock()


def _cached_outcome(key: _ValidationKey) -> _ValidationOutcome | None:
    with _VALIDATION_CACHE_LOCK:
        outcome = _VALIDATION_CACHE.get(key)
        if outcome is not None:
            _VALIDATION_CACHE.move_to_end(key)
        return outcome


def _store_outcome(key: _ValidationKey, outcome: _ValidationOutcome) -> None:
    with _VALIDATION_CACHE_LOCK:
        _VALIDATION_CACHE[key] = outcome
        _VALIDATION_CACHE.move_to_end(key)
        while len(_VALIDATION_CACHE) > _VALIDATION_CACHE_MAXSIZE:
            _VALIDATION_CACHE.popitem(last=False)


def _clear_validation_cache() -> None:
    """Clear process-local validation outcomes (used by deterministic tests)."""
    with _VALIDATION_CACHE_LOCK:
        _VALIDATION_CACHE.clear()


def _raise_cached_failure(
    outcome: _ValidationOutcome,
    *,
    parameter_overrides: dict[str, Any],
    model_version: str,
    store_hash: str,
) -> None:
    failed_names = list(outcome.failed_invariants)
    failed_details = dict(outcome.failed_checks)
    raise InvariantViolationError(
        f"Parameter overrides violated {len(failed_names)} simulator directional invariant(s): "
        f"{', '.join(failed_names)}",
        failed_invariants=failed_names,
        details={
            "failed_invariants": failed_names,
            "failed_checks": failed_details,
            "parameter_overrides": copy.deepcopy(parameter_overrides),
            "model_version": model_version,
            "store_hash": store_hash,
            "n_checks": outcome.n_checks,
            "n_failed": len(failed_names),
            "reason": outcome.reason,
        },
    )


def validate_parameter_configuration(
    parameter_overrides: dict[str, Any] | None,
    *,
    store: ParameterStore | None = None,
    model_version: str = "bacteriocin-sim",
) -> dict[str, Any]:
    """Validate that candidate parameter_overrides satisfy all directional invariants.

    Parameters:
        parameter_overrides: The replacement priors to check.
        store: Optional ParameterStore already constructed from overrides.
        model_version: The simulator model version string.

    Returns:
        Summary dict of validation status if passed or skipped.

    Raises:
        InvariantViolationError: If ANY directional invariant fails.
    """
    if not parameter_overrides:
        return {"validated": False, "reason": "default_parameters"}

    if _IS_VALIDATING.get():
        # Prevent recursion during selftest execution
        return {"validated": False, "reason": "in_validation"}

    if store is None:
        store = ParameterStore.from_overrides(parameter_overrides)

    store_hash = store.hash()
    cache_key = (_VALIDATION_REVISION, model_version, store_hash)
    cached = _cached_outcome(cache_key)
    if cached is not None:
        if cached.passed:
            return {
                "validated": True,
                "cached": True,
                "store_hash": store_hash,
                "n_checks": cached.n_checks,
            }
        _raise_cached_failure(
            cached,
            parameter_overrides=parameter_overrides,
            model_version=model_version,
            store_hash=store_hash,
        )

    # Run selftest with the candidate parameter_overrides
    from .agent import SimulationBackendAgent

    token = _IS_VALIDATING.set(True)
    try:
        report = SimulationBackendAgent.selftest(parameter_overrides=parameter_overrides)
    finally:
        _IS_VALIDATING.reset(token)

    if report.get("passed"):
        outcome = _ValidationOutcome(
            passed=True,
            n_checks=int(report.get("n_checks", 14)),
        )
        _store_outcome(cache_key, outcome)
        return {
            "validated": True,
            "cached": False,
            "store_hash": store_hash,
            "n_checks": outcome.n_checks,
        }

    # FAIL CLOSED: extract all failed invariants and reject
    failed_checks = [c for c in report.get("checks", []) if not c.get("passed")]
    failed_names = tuple(str(c["check"]) for c in failed_checks)
    failed_details = tuple(
        (str(c["check"]), str(c.get("detail", ""))) for c in failed_checks
    )

    reasons = [f"{key} ({detail})" for key, detail in failed_details]
    reason_str = "; ".join(reasons) if reasons else "qualitative invariants not satisfied"
    outcome = _ValidationOutcome(
        passed=False,
        n_checks=int(report.get("n_checks", 14)),
        failed_invariants=failed_names,
        failed_checks=failed_details,
        reason=reason_str,
    )
    _store_outcome(cache_key, outcome)
    _raise_cached_failure(
        outcome,
        parameter_overrides=parameter_overrides,
        model_version=model_version,
        store_hash=store_hash,
    )
