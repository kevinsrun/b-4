"""Structured error types for the simulation experiment backend.

The backend distinguishes three error classes so that Omnigent can decide
whether to repair a spec, retry against another backend, or abandon a branch:

* :class:`SpecValidationError` -- the ExperimentSpec is unusable as written
  (physically impossible values, malformed payload). Repairable by the planner.
* :class:`BackendUnavailableError` -- the requested experiment backend exists
  in the architecture but cannot execute here (e.g. the wet-lab adapter).
  Not repairable by changing the spec.
* :class:`SimulationError` -- the model itself failed to produce a usable
  prediction (numerical failure). Reportable as an experiment failure.
"""

from __future__ import annotations

from typing import Any


class BacteriocinSimError(Exception):
    """Base class for every error raised by this module."""

    code = "backend_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible representation for the agent output envelope."""
        return {
            "error_code": self.code,
            "error_type": type(self).__name__,
            "message": self.message,
            "details": self.details,
        }


class SpecValidationError(BacteriocinSimError):
    """The ExperimentSpec cannot be simulated as written."""

    code = "spec_validation_error"


class BackendUnavailableError(BacteriocinSimError):
    """A registered backend exists but cannot run experiments in this deployment."""

    code = "backend_unavailable"


class UnknownBackendError(BacteriocinSimError):
    """No adapter is registered under the requested name/assay domain."""

    code = "unknown_backend"


class SimulationError(BacteriocinSimError):
    """The forward model failed numerically."""

    code = "simulation_error"


class InvariantViolationError(BacteriocinSimError):
    """Parameter overrides violate directional biophysical invariants."""

    code = "invariant_violation"

    def __init__(
        self,
        message: str,
        *,
        failed_invariants: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = dict(details or {})
        if failed_invariants is not None:
            merged_details["failed_invariants"] = failed_invariants
        super().__init__(message, details=merged_details)
        self.failed_invariants: list[str] = list(
            failed_invariants or merged_details.get("failed_invariants", [])
        )

