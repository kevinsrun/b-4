"""bacteriocin_sim -- the computational simulation experiment backend.

One scientific responsibility: given an
:class:`~bacteriocin_lab.agents.simulator.schemas.ExperimentSpec` describing a bacteriocin, a
target organism and a set of biological conditions, predict the antimicrobial
response as a continuous, uncertainty-quantified
:class:`~bacteriocin_lab.agents.simulator.schemas.ExperimentResult`.

This module does **not** gather evidence, form hypotheses, design candidates,
choose the next experiment, or orchestrate anything. It executes experiments
and reports what it predicted, how confident it is, and which variables
mattered.

Typical use by Omnigent::

    from bacteriocin_lab.agents.simulator import run_experiment

    result = run_experiment({
        "experiment_id": "exp-0001",
        "candidate_id": "cand-nisin-a",
        "candidate": {"sequence": "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK"},
        "target": {"species": "Listeria monocytogenes"},
        "conditions": {
            "bacteriocin_concentration": {"value": 2.0, "unit": "uM"},
            "target_cell_density": {"value": 1e6, "unit": "cfu_per_ml"},
            "ph": 6.5, "temperature_c": 30.0, "medium": "bhi",
            "incubation_time": 18.0, "growth_phase": "exponential",
            "assay_domain": "simulated_in_vitro",
        },
    })

or, through the agent envelope::

    from bacteriocin_lab.agents.simulator import run_agent
    output = run_agent({"experiment_specs": [spec, ...]})
"""

from __future__ import annotations

__version__ = "0.1.0"

# The adapters live in ``bacteriocin_lab.adapters`` and import this package's schemas,
# so they are resolved on first access to keep the import graph acyclic.
_ADAPTER_EXPORTS = ("AdapterCapabilities", "ExperimentAdapter", "SimulationAdapter", "WetLabAdapter")


def __getattr__(name: str):
    if name in _ADAPTER_EXPORTS:
        from bacteriocin_lab import adapters

        return getattr(adapters, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


from .agent import SimulationAgent, SimulationBackendAgent, run_agent  # noqa: E402
from .api import coerce_spec, run_experiment, run_experiments  # noqa: E402
from .errors import (  # noqa: E402
    BackendUnavailableError,
    BacteriocinSimError,
    InvariantViolationError,
    SimulationError,
    SpecValidationError,
    UnknownBackendError,
)
from .registry import (  # noqa: E402
    available_backends,
    backend_for_domain,
    describe_backends,
    get_adapter,
    register_adapter,
)
from .schemas import (  # noqa: E402
    AGENT_NAME,
    AgentInput,
    AgentOutput,
    AssayDomain,
    AssayType,
    BacteriocinClass,
    CandidateSpec,
    Conditions,
    EvidenceRecord,
    EvidenceType,
    ExperimentResult,
    ExperimentSpec,
    GrowthPhase,
    Measurement,
    Target,
)

__all__ = [
    "AGENT_NAME",
    "AdapterCapabilities",
    "AgentInput",
    "AgentOutput",
    "AssayDomain",
    "AssayType",
    "BacteriocinClass",
    "BackendUnavailableError",
    "BacteriocinSimError",
    "CandidateSpec",
    "Conditions",
    "EvidenceRecord",
    "EvidenceType",
    "ExperimentAdapter",
    "ExperimentResult",
    "ExperimentSpec",
    "GrowthPhase",
    "InvariantViolationError",
    "Measurement",
    "SimulationAdapter",
    "SimulationAgent",
    "SimulationBackendAgent",
    "SimulationError",
    "SpecValidationError",
    "Target",
    "UnknownBackendError",
    "WetLabAdapter",
    "__version__",
    "available_backends",
    "backend_for_domain",
    "coerce_spec",
    "describe_backends",
    "get_adapter",
    "register_adapter",
    "run_agent",
    "run_experiment",
    "run_experiments",
]
