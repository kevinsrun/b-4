"""MCP server exposing the simulation backend as callable tools.

This is a *transport*, not a layer of logic. Every tool here is a thin
adapter over the public API in :mod:`bacteriocin_sim.api` and
:mod:`bacteriocin_sim.agent`; no scientific decision is taken in this file,
and nothing here may change a prediction. If a behaviour matters, it belongs
in the model, not in the server that serves it.

Why MCP rather than an agent config: this module is a tool, not an agent. It
holds no conversation, runs no model and takes no decision -- it answers
``run_experiment(spec) -> result`` deterministically. The orchestrator that
*does* reason (plan experiments, read results, choose the next move) declares
this server in its own ``tools/mcp/`` directory and calls these tools.

Error convention: a :class:`~bacteriocin_sim.errors.BacteriocinSimError` is
returned as its ``to_dict()`` payload rather than raised. This matches the
module's existing stance that a failed experiment is a *result* the loop
should record, not an exception that destroys the turn -- and it keeps the
distinction between the three error classes legible to the caller, which an
MCP protocol error would flatten.

Run it with::

    python -m bacteriocin_sim.mcp_server

Requires the optional ``mcp`` extra::

    uv pip install -e ".[mcp]"
"""

from __future__ import annotations

from typing import Any

from . import __version__
from .agent import SimulationBackendAgent
from .agent import run_agent as _run_agent
from .api import run_experiment as _run_experiment
from .api import run_experiments as _run_experiments
from .errors import BacteriocinSimError
from .registry import describe_backends
from .schemas import AgentInput, AgentOutput, ExperimentResult, ExperimentSpec
from .selftest import run_selftest

try:
    from mcp.server.mcpserver import MCPServer
except ModuleNotFoundError as exc:  # pragma: no cover - depends on the extra
    raise ModuleNotFoundError(
        "the MCP server needs the optional 'mcp' extra: "
        'uv pip install -e ".[mcp]"'
    ) from exc

#: The schemas a caller can request by name, mirroring the ``schema`` CLI
#: subcommand so the two interfaces never disagree about what exists.
_SCHEMAS: dict[str, type] = {
    "experiment_spec": ExperimentSpec,
    "experiment_result": ExperimentResult,
    "agent_input": AgentInput,
    "agent_output": AgentOutput,
}

INSTRUCTIONS = """\
Computational simulation backend for bacteriocin (antimicrobial peptide)
activity experiments.

Given a peptide, a target organism and a set of biological conditions, it
predicts the antimicrobial response as a continuous, uncertainty-quantified
value, and reports which conditions the prediction is most sensitive to.

Call `get_schema("experiment_spec")` before building your first spec.

Three things to know when reading a result:

1. Every output is simulation-derived. It is a hypothesis to be tested, never
   an experimental observation, and the schema refuses to let a result claim
   otherwise.
2. The numbers come from coarse, uncalibrated literature priors. The structure
   of the model is defensible; the calibration is not. Treat `confidence` and
   `uncertainty_components` as part of the answer, not as decoration.
3. `important_factors` tags each condition `provided` or `imputed_default`.
   A high-sensitivity *imputed* factor means the prediction describes an
   assumed default rather than the experiment you think you specified --
   that is the most actionable thing this backend reports.
"""

server = MCPServer(
    name="bacteriocin-sim",
    version=__version__,
    instructions=INSTRUCTIONS,
)


def _guard(fn, *args: Any, **kwargs: Any) -> Any:
    """Run a backend call, returning structured errors instead of raising."""
    try:
        return fn(*args, **kwargs)
    except BacteriocinSimError as exc:
        return exc.to_dict()
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "error_code": "unexpected_error",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "details": {},
        }


@server.tool(
    description=(
        "Describe this backend: module version, registered experiment backends, "
        "the assay domains and types each can execute, the condition variables "
        "honoured, and the model's declared limitations. Call this before "
        "planning experiments."
    )
)
def capabilities() -> dict[str, Any]:
    return {
        "module": "bacteriocin_sim",
        "version": __version__,
        "backends": describe_backends(),
    }


@server.tool(
    description=(
        "Return the JSON Schema for one of: experiment_spec, experiment_result, "
        "agent_input, agent_output. Pass 'all' for every schema."
    )
)
def get_schema(name: str = "experiment_spec") -> dict[str, Any]:
    if name == "all":
        return {k: v.model_json_schema() for k, v in _SCHEMAS.items()}
    model = _SCHEMAS.get(name)
    if model is None:
        return {
            "error_code": "unknown_schema",
            "message": f"unknown schema {name!r}",
            "details": {"available": sorted(_SCHEMAS) + ["all"]},
        }
    return model.model_json_schema()


@server.tool(
    description=(
        "Execute one experiment and return a full ExperimentResult: the "
        "predicted measurement, a ranked sensitivity analysis, the uncertainty "
        "budget by named source, parameter provenance, and a mechanism trace. "
        "`spec` must match the experiment_spec schema. Optionally supply "
        "`candidate_registry` mapping candidate_id to a candidate block (the "
        "recommended way to resolve a bare candidate_id), and "
        "`parameter_overrides` to deep-merge replacement priors -- overrides "
        "change the predictions and the parameter_set_hash stamped into the "
        "result."
    )
)
def run_experiment(
    spec: dict[str, Any],
    backend: str | None = None,
    candidate_registry: dict[str, Any] | None = None,
    parameter_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = _guard(
        _run_experiment,
        spec,
        backend=backend,
        candidate_registry=candidate_registry,
        parameter_overrides=parameter_overrides,
    )
    return result.to_json_dict() if isinstance(result, ExperimentResult) else result


@server.tool(
    description=(
        "Execute many experiments in one call, isolating per-spec failures: a "
        "malformed spec becomes one result with status='failed' and an error "
        "block rather than sinking the batch. Results are returned in input "
        "order. Prefer this over repeated run_experiment calls -- it builds "
        "each backend once."
    )
)
def run_experiments(
    specs: list[dict[str, Any]],
    backend: str | None = None,
    candidate_registry: dict[str, Any] | None = None,
    parameter_overrides: dict[str, Any] | None = None,
) -> list[dict[str, Any]] | dict[str, Any]:
    results = _guard(
        _run_experiments,
        specs,
        backend=backend,
        candidate_registry=candidate_registry,
        parameter_overrides=parameter_overrides,
    )
    if isinstance(results, list):
        return [r.to_json_dict() for r in results]
    return results


@server.tool(
    description=(
        "Run the full agent envelope: executes every spec in `envelope"
        ".experiment_specs` and returns the common output shape (agent, "
        "decision, evidence, confidence, uncertainties, artifacts, warnings, "
        "recommended_next_action). Use this instead of run_experiments when "
        "you want the backend's own read on what to do next -- "
        "recommended_next_action names the single change that would most "
        "reduce uncertainty, such as supplying a missing candidate sequence or "
        "pinning down an influential condition that was left to a default."
    )
)
def run_agent(envelope: dict[str, Any]) -> dict[str, Any]:
    output = _guard(_run_agent, envelope)
    return output.to_json_dict() if isinstance(output, AgentOutput) else output


@server.tool(
    description=(
        "Self-description for capability negotiation: this agent's scientific "
        "responsibility, what it explicitly does not do, and its input/output "
        "JSON schemas."
    )
)
def describe() -> dict[str, Any]:
    return SimulationBackendAgent().describe()


@server.tool(
    description=(
        "Run the model's scientific invariants -- directional checks that must "
        "hold of any usable model of bacteriocin biology (dose-response is "
        "monotone, raising the inoculum raises apparent resistance, EDTA "
        "relieves the Gram-negative barrier, and so on). A failure means the "
        "model is giving scientifically wrong answers regardless of how "
        "confident its output looks. Use it to verify a parameter override "
        "has not broken the model."
    )
)
def selftest() -> dict[str, Any]:
    return run_selftest()


def main() -> None:
    """Serve over stdio. This is the entry point the agent config spawns."""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
