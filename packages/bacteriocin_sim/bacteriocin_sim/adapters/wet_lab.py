"""Wet-lab adapter placeholder.

This adapter exists so that the architecture's second backend is a *declared,
discoverable* seam rather than a future refactor. It implements the full
:class:`~bacteriocin_sim.adapters.base.ExperimentAdapter` interface, reports
``available=False``, and refuses to run.

Nothing downstream needs to change when a real implementation lands: it will
return the same :class:`~bacteriocin_sim.schemas.ExperimentResult`, differing
only in ``evidence_type="wet-lab-derived"`` and in carrying real measurement
uncertainty instead of model uncertainty.

Design notes for whoever implements it:

* ``evidence_type`` becomes ``wet-lab-derived``; the schema deliberately
  forbids the *simulation* backend from ever using that value.
* ``measurement.uncertainty`` should then be empirical (replicate SD), and
  ``important_factors`` should come from the design of the physical experiment
  rather than from model sensitivity analysis.
* ``reproducibility.deterministic`` must be ``False``.
* Specs will need scheduling metadata (plate/well, operator, instrument) --
  add them as additive optional fields and document the proposal, exactly as
  the candidate block is documented in ``CONTRACT.md``.
"""

from __future__ import annotations

from ..errors import BackendUnavailableError
from ..schemas import AssayDomain, ExperimentResult, ExperimentSpec
from .base import AdapterCapabilities, ExperimentAdapter


class WetLabAdapter(ExperimentAdapter):
    """Declared-but-unavailable physical experiment backend."""

    name = "wet_lab"
    assay_domains = (AssayDomain.WET_LAB_IN_VITRO, AssayDomain.WET_LAB_IN_VIVO)

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name=self.name,
            available=False,
            assay_domains=[d.value for d in self.assay_domains],
            assay_types=[],
            supported_conditions=[],
            evidence_type="wet-lab-derived",
            deterministic=False,
            model_version="not-implemented",
            description=(
                "Placeholder for a future physical-experiment bridge. Present so that "
                "backend routing, capability negotiation and result provenance are "
                "already backend-agnostic."
            ),
            limitations=[
                "no physical laboratory is connected to this deployment",
                "the system is designed to operate fully without wet-lab data",
            ],
            requires=["a laboratory execution service", "an assay scheduling interface"],
        )

    def run(self, spec: ExperimentSpec) -> ExperimentResult:
        raise BackendUnavailableError(
            "the wet-lab backend is not implemented in this deployment; route the "
            "experiment to the simulation backend by setting "
            "conditions.assay_domain='simulated_in_vitro'",
            details={
                "experiment_id": spec.experiment_id,
                "requested_assay_domain": (
                    spec.conditions.assay_domain.value
                    if hasattr(spec.conditions.assay_domain, "value")
                    else str(spec.conditions.assay_domain)
                ),
                "available_backends": ["simulation"],
            },
        )
