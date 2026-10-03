"""Public experiment interface: ``run_experiment(ExperimentSpec) -> ExperimentResult``.

This is the function the rest of the system calls. It accepts either a model
object or a plain dict (so an LLM-driven planner can pass JSON straight
through), routes to a backend, and returns a validated result.
"""

from __future__ import annotations

from typing import Any

from ._results import failed_result
from .errors import BacteriocinSimError, SpecValidationError
from .registry import backend_for_domain, get_adapter
from .schemas import CandidateSpec, ExperimentResult, ExperimentSpec


def coerce_spec(spec: ExperimentSpec | dict[str, Any]) -> ExperimentSpec:
    """Validate a spec given as a model or a JSON-compatible dict."""
    if isinstance(spec, ExperimentSpec):
        return spec
    if not isinstance(spec, dict):
        raise SpecValidationError(
            f"ExperimentSpec must be a dict or ExperimentSpec, got {type(spec).__name__}"
        )
    try:
        return ExperimentSpec.model_validate(spec)
    except Exception as exc:
        raise SpecValidationError(
            f"invalid ExperimentSpec: {exc}", details={"received_keys": sorted(spec)}
        ) from exc


def run_experiment(
    spec: ExperimentSpec | dict[str, Any],
    *,
    backend: str | None = None,
    candidate_registry: dict[str, CandidateSpec] | None = None,
    parameter_overrides: dict[str, Any] | None = None,
) -> ExperimentResult:
    """Execute one experiment on the appropriate backend.

    ``backend`` overrides the routing that would otherwise be derived from
    ``spec.conditions.assay_domain``. Raises
    :class:`~bacteriocin_sim.errors.BacteriocinSimError` subclasses; use
    :func:`run_experiments` for failure-isolating batch execution.
    """
    validated = coerce_spec(spec)
    name = backend or backend_for_domain(validated.conditions.assay_domain)
    adapter = get_adapter(
        name,
        candidate_registry=candidate_registry,
        parameter_overrides=parameter_overrides,
    )
    return adapter.run(validated)


def run_experiments(
    specs: list[ExperimentSpec | dict[str, Any]],
    *,
    backend: str | None = None,
    candidate_registry: dict[str, CandidateSpec] | None = None,
    parameter_overrides: dict[str, Any] | None = None,
) -> list[ExperimentResult]:
    """Execute many experiments, isolating per-spec failures.

    Specs are grouped by backend so that each adapter is constructed once, and
    a failure in one spec yields a ``status="failed"`` result rather than
    aborting the batch.
    """
    groups: dict[str, list[ExperimentSpec]] = {}
    order: list[tuple[str, int]] = []
    failures: dict[int, ExperimentResult] = {}

    for index, raw in enumerate(specs):
        try:
            validated = coerce_spec(raw)
            name = backend or backend_for_domain(validated.conditions.assay_domain)
        except BacteriocinSimError as exc:
            placeholder = _placeholder_spec(raw, index)
            failures[index] = failed_result(placeholder, exc, backend=backend or "unrouted")
            order.append(("__failed__", index))
            continue
        groups.setdefault(name, []).append(validated)
        order.append((name, len(groups[name]) - 1))

    results: dict[str, list[ExperimentResult]] = {}
    for name, grouped in groups.items():
        adapter = get_adapter(
            name,
            candidate_registry=candidate_registry,
            parameter_overrides=parameter_overrides,
        )
        results[name] = adapter.run_batch(grouped)

    out: list[ExperimentResult] = []
    for index, (name, position) in enumerate(order):
        if name == "__failed__":
            out.append(failures[position])
        else:
            out.append(results[name][position])
    return out


def _placeholder_spec(raw: Any, index: int) -> ExperimentSpec:
    """Build a minimal valid spec so an invalid input still yields a result."""
    experiment_id = None
    if isinstance(raw, dict):
        experiment_id = raw.get("experiment_id")
    return ExperimentSpec(
        experiment_id=str(experiment_id or f"invalid-spec-{index}"),
        candidate_id=raw.get("candidate_id") if isinstance(raw, dict) else None,
    )
