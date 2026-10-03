"""Helpers for building ExperimentResult objects, including failures."""

from __future__ import annotations

import datetime as _dt
import hashlib

from .errors import BacteriocinSimError
from .schemas import (
    EvidenceType,
    ExperimentResult,
    ExperimentSpec,
    Measurement,
    Reproducibility,
)


def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def make_result_id(spec: ExperimentSpec, model_version: str) -> str:
    """Deterministic result ID.

    Derived from the experiment ID, the scientific content hash of the spec
    and the model version, so re-running the same experiment with the same
    model reproduces the same ``result_id`` -- which lets the research state
    deduplicate instead of accumulating near-identical records.
    """
    seed = f"{spec.experiment_id}|{spec.spec_hash()}|{model_version}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"res-{digest}"


def failed_result(
    spec: ExperimentSpec, exc: BacteriocinSimError, *, backend: str
) -> ExperimentResult:
    """A well-formed result describing a failed experiment.

    Failures are first-class results rather than exceptions at the batch level:
    the loop needs to record that an experiment was attempted and why it did
    not produce a measurement.
    """
    return ExperimentResult(
        result_id=make_result_id(spec, f"{backend}:error"),
        experiment_id=spec.experiment_id,
        hypothesis_id=spec.hypothesis_id,
        candidate_id=spec.candidate_id,
        conditions=spec.conditions.to_json_dict(),
        measurement=Measurement(),
        important_factors=[],
        evidence_type=EvidenceType.SIMULATION,
        model_version=f"{backend}:error",
        warnings=[f"experiment failed: {exc.message}"],
        status="failed",
        backend=backend,
        confidence=0.0,
        error=exc.to_dict(),
        reproducibility=Reproducibility(
            deterministic=True, spec_hash=spec.spec_hash(), code_version=None
        ),
        created_at=utc_now_iso(),
    )
