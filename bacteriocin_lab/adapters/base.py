"""The experiment-backend interface: ``run_experiment(ExperimentSpec) -> ExperimentResult``.

Every backend -- the required computational simulator today, a wet-lab bridge
later -- implements this one abstract class. Downstream agents consume
:class:`~bacteriocin_lab.agents.simulator.schemas.ExperimentResult` and never import an adapter
directly, so adding a backend changes no downstream code.

An adapter must:

* be stateless between calls, or expose any state through ``capabilities()``
  so Omnigent can reconstruct it (agent rule 6);
* return a result for every spec it accepts, including on failure
  (``status="failed"`` with an ``error`` block), rather than raising past
  :meth:`run_batch`;
* never emit ``evidence_type="wet-lab-derived"`` unless it genuinely
  executed a physical experiment.
"""

from __future__ import annotations

import abc
from typing import Any

from bacteriocin_lab.agents.simulator.schemas import (
    AssayDomain,
    CandidateSpec,
    ExperimentResult,
    ExperimentSpec,
)


class AdapterCapabilities:
    """Machine-readable description of what a backend can do.

    Omnigent should consult this before planning: it declares which assay
    domains and assay types are executable, which condition variables are
    honoured, and whether the backend is available at all in this deployment.
    """

    def __init__(
        self,
        *,
        name: str,
        available: bool,
        assay_domains: list[str],
        assay_types: list[str],
        supported_conditions: list[str],
        evidence_type: str,
        deterministic: bool,
        model_version: str,
        description: str,
        limitations: list[str] | None = None,
        requires: list[str] | None = None,
    ) -> None:
        self.name = name
        self.available = available
        self.assay_domains = assay_domains
        self.assay_types = assay_types
        self.supported_conditions = supported_conditions
        self.evidence_type = evidence_type
        self.deterministic = deterministic
        self.model_version = model_version
        self.description = description
        self.limitations = limitations or []
        self.requires = requires or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "assay_domains": self.assay_domains,
            "assay_types": self.assay_types,
            "supported_conditions": self.supported_conditions,
            "evidence_type": self.evidence_type,
            "deterministic": self.deterministic,
            "model_version": self.model_version,
            "description": self.description,
            "limitations": self.limitations,
            "requires": self.requires,
        }


class ExperimentAdapter(abc.ABC):
    """Base class for every experiment backend."""

    #: short stable backend name used by the registry and in results
    name: str = "abstract"

    #: assay domains this backend claims
    assay_domains: tuple[AssayDomain, ...] = ()

    @abc.abstractmethod
    def capabilities(self) -> AdapterCapabilities:
        """Describe what this backend can execute."""

    @abc.abstractmethod
    def run(self, spec: ExperimentSpec) -> ExperimentResult:
        """Execute one experiment.

        Raises :class:`~bacteriocin_lab.agents.simulator.errors.SpecValidationError` for an
        unusable spec and
        :class:`~bacteriocin_lab.agents.simulator.errors.BackendUnavailableError` when the
        backend cannot execute here.
        """

    def run_batch(self, specs: list[ExperimentSpec]) -> list[ExperimentResult]:
        """Execute several experiments, isolating per-spec failures.

        One malformed spec must not discard the results of the others -- an
        autonomous loop that loses a whole batch to a single bad field wastes a
        full iteration.
        """
        from bacteriocin_lab.agents.simulator._results import failed_result
        from bacteriocin_lab.agents.simulator.errors import BacteriocinSimError

        out: list[ExperimentResult] = []
        for spec in specs:
            try:
                out.append(self.run(spec))
            except BacteriocinSimError as exc:
                out.append(failed_result(spec, exc, backend=self.name))
            except Exception as exc:  # pragma: no cover - defensive
                from bacteriocin_lab.agents.simulator.errors import SimulationError

                out.append(
                    failed_result(
                        spec,
                        SimulationError(f"unexpected backend failure: {exc}"),
                        backend=self.name,
                    )
                )
        return out

    # ------------------------------------------------------------------
    # optional hooks
    # ------------------------------------------------------------------

    def resolve_candidate(
        self, spec: ExperimentSpec, registry: dict[str, CandidateSpec] | None
    ) -> CandidateSpec | None:
        """Find the candidate's scientific content for a spec.

        Order of preference: inline ``spec.candidate``, then a registry entry
        for ``spec.candidate_id``, then nothing.
        """
        if spec.candidate is not None and (
            spec.candidate.sequence or spec.candidate.bacteriocin_class
        ):
            return spec.candidate
        if registry and spec.candidate_id and spec.candidate_id in registry:
            return registry[spec.candidate_id]
        return spec.candidate
