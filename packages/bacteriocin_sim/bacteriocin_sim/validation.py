"""Validation of biophysical parameter overrides against directional invariants.

Enforces fail-closed validation: parameter_overrides must satisfy all qualitative
directional invariants checked by SimulationAgent.selftest() before any ExperimentResult
is produced.
"""

from __future__ import annotations

import contextvars
from typing import Any

from .errors import InvariantViolationError
from .model.parameters import ParameterStore

_IS_VALIDATING: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_IS_VALIDATING", default=False
)
_VALIDATED_HASHES: set[str] = set()

# Pre-populate default parameter store hash so un-overridden models incur zero validation overhead
try:
    _DEFAULT_STORE_HASH = ParameterStore().hash()
    _VALIDATED_HASHES.add(_DEFAULT_STORE_HASH)
except Exception:  # pragma: no cover - defensive
    _DEFAULT_STORE_HASH = ""


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
    if store_hash in _VALIDATED_HASHES:
        return {"validated": True, "cached": True, "store_hash": store_hash}

    # Run selftest with the candidate parameter_overrides
    from .agent import SimulationBackendAgent

    token = _IS_VALIDATING.set(True)
    try:
        report = SimulationBackendAgent.selftest(parameter_overrides=parameter_overrides)
    finally:
        _IS_VALIDATING.reset(token)

    if report.get("passed"):
        _VALIDATED_HASHES.add(store_hash)
        return {
            "validated": True,
            "cached": False,
            "store_hash": store_hash,
            "n_checks": report.get("n_checks", 14),
        }

    # FAIL CLOSED: extract all failed invariants and reject
    failed_checks = [c for c in report.get("checks", []) if not c.get("passed")]
    failed_names = [str(c["check"]) for c in failed_checks]
    failed_details = {str(c["check"]): str(c.get("detail", "")) for c in failed_checks}

    reasons = [f"{k} ({v})" for k, v in failed_details.items()]
    reason_str = "; ".join(reasons) if reasons else "qualitative invariants not satisfied"

    raise InvariantViolationError(
        f"Parameter overrides violated {len(failed_names)} simulator directional invariant(s): "
        f"{', '.join(failed_names)}",
        failed_invariants=failed_names,
        details={
            "failed_invariants": failed_names,
            "failed_checks": failed_details,
            "parameter_overrides": parameter_overrides,
            "model_version": model_version,
            "store_hash": store_hash,
            "n_checks": report.get("n_checks", 14),
            "n_failed": len(failed_names),
            "reason": reason_str,
        },
    )
