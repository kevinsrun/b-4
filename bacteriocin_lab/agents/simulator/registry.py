"""Backend registry and routing.

Keeping the mapping of *name / assay domain* -> *adapter* in one place is what
makes the ``simulation_adapter.run(...)`` / ``wet_lab_adapter.run(...)`` split
in the shared architecture a configuration detail rather than a code change.
Omnigent calls :func:`run_experiment`; which backend executes is decided here
from the spec's ``assay_domain`` or an explicit override.
"""

from __future__ import annotations

from typing import Any, Callable

from bacteriocin_lab.adapters.base import ExperimentAdapter
from bacteriocin_lab.adapters.simulation import SimulationAdapter
from bacteriocin_lab.adapters.wetlab import WetLabAdapter

from .errors import UnknownBackendError
from .schemas import AssayDomain

AdapterFactory = Callable[..., ExperimentAdapter]

_FACTORIES: dict[str, AdapterFactory] = {}
_DOMAIN_ROUTES: dict[str, str] = {}


def register_adapter(
    name: str, factory: AdapterFactory, *, assay_domains: list[str] | None = None
) -> None:
    """Register a backend under ``name``, optionally claiming assay domains."""
    _FACTORIES[name] = factory
    for domain in assay_domains or []:
        _DOMAIN_ROUTES[domain] = name


def get_adapter(name: str, **kwargs: Any) -> ExperimentAdapter:
    """Instantiate a registered backend.

    ``kwargs`` are passed to the factory, so a caller can supply
    ``parameter_overrides`` or a ``candidate_registry`` without the registry
    knowing what those mean.
    """
    factory = _FACTORIES.get(name)
    if factory is None:
        raise UnknownBackendError(
            f"no experiment backend registered as {name!r}",
            details={"available_backends": sorted(_FACTORIES)},
        )
    try:
        return factory(**kwargs)
    except TypeError:
        # a backend that does not accept these options gets a bare instance
        return factory()


def backend_for_domain(assay_domain: str | AssayDomain) -> str:
    """Which backend claims this assay domain."""
    value = (
        assay_domain.value if isinstance(assay_domain, AssayDomain) else str(assay_domain)
    )
    name = _DOMAIN_ROUTES.get(value)
    if name is None:
        raise UnknownBackendError(
            f"no backend is registered for assay_domain={value!r}",
            details={"routed_domains": sorted(_DOMAIN_ROUTES)},
        )
    return name


def available_backends() -> list[str]:
    return sorted(_FACTORIES)


def describe_backends(**kwargs: Any) -> dict[str, Any]:
    """Capability report for every registered backend."""
    out: dict[str, Any] = {}
    for name in sorted(_FACTORIES):
        try:
            out[name] = get_adapter(name, **kwargs).capabilities().to_dict()
        except Exception as exc:  # pragma: no cover - defensive
            out[name] = {"name": name, "available": False, "error": str(exc)}
    return out


register_adapter(
    "simulation",
    SimulationAdapter,
    assay_domains=[
        AssayDomain.SIMULATED_IN_VITRO.value,
        AssayDomain.SIMULATED_IN_VIVO_LIKE.value,
    ],
)
register_adapter(
    "wet_lab",
    WetLabAdapter,
    assay_domains=[
        AssayDomain.WET_LAB_IN_VITRO.value,
        AssayDomain.WET_LAB_IN_VIVO.value,
    ],
)
