"""HTTP layer for the BACTERION web UI.

A transport, not a participant. Every endpoint forwards to an existing
specialist -- :func:`bacteriocin_lab.orchestration.run_discovery`, the
simulator's ``run_experiment``, the literature agent, the knowledge agent --
and returns what it returned. Nothing here scores a candidate, predicts a
response, interprets a result or decides what to run next, and no endpoint
invents a field the underlying agent did not emit.

The Python package stays the source of truth; this module only makes it
reachable over HTTP.
"""

from __future__ import annotations

__all__ = ["create_app"]


def __getattr__(name: str):
    # ``fastapi`` is an optional extra, so importing it is deferred until the
    # app is actually requested.
    if name == "create_app":
        from .app import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
