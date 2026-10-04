"""TEST 1: Import / Package test.

Fresh package import must succeed through the real package path without
relative-path hacks or sys.path monkey-patching in production code.
"""

from __future__ import annotations


def test_import_orchestration_packages() -> None:
    # 1. Real package imports
    import bacteriocin_lab
    import bacteriocin_lab.orchestration

    assert bacteriocin_lab.__version__ == "0.1.0"
    assert bacteriocin_lab.orchestration.__version__ == "0.1.0"

    # 2. Real core agents and orchestrator symbols
    from bacteriocin_lab.orchestration.registry import AgentRegistry

    registry = AgentRegistry.default()
    assert registry.get("evidence") is not None
    assert registry.get("candidate") is not None
    assert registry.get("planner") is not None
    assert registry.get("simulation") is not None
    assert registry.get("analysis") is not None
    assert registry.get("critic") is not None
    assert registry.get("knowledge") is not None
