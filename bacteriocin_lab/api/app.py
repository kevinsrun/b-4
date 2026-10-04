"""The HTTP surface. Each handler forwards to a specialist and returns its output.

Two rules hold throughout:

* **No science here.** A handler validates its request, calls one existing
  entry point, and serialises the reply. It does not compute a score, a
  prediction, a confidence or a next step.
* **No invented fields.** What an agent did not emit is absent, not defaulted.
  Where this layer adds anything of its own -- a provenance label, a run id --
  it is named so the client can tell it apart.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from bacteriocin_lab.agents.candidate import AGENT_NAME as CANDIDATE_AGENT
from bacteriocin_lab.agents.candidate import MODEL_VERSION as CANDIDATE_VERSION
from bacteriocin_lab.agents.candidate import default_knowledge_source, generate_candidates
from bacteriocin_lab.agents.evidence import LiteratureEvidenceAgent
from bacteriocin_lab.agents.knowledge import AGENT_NAME as KNOWLEDGE_AGENT
from bacteriocin_lab.agents.knowledge import MODEL_VERSION as KNOWLEDGE_VERSION
from bacteriocin_lab.agents.knowledge import knowledge_call
from bacteriocin_lab.agents.planner import AGENT_NAME as PLANNER_AGENT
from bacteriocin_lab.agents.planner import MODEL_VERSION as PLANNER_VERSION
from bacteriocin_lab.agents.simulator import __version__ as SIMULATOR_VERSION
from bacteriocin_lab.agents.simulator import describe_backends, run_experiment, run_experiments
from bacteriocin_lab.agents.simulator.errors import BacteriocinSimError
from bacteriocin_lab.agents.simulator.schemas import CandidateSpec
from bacteriocin_lab.agents.simulator.selftest import run_selftest
from bacteriocin_lab.orchestration import AgentRegistry, run_discovery
from bacteriocin_lab.presentation import build_discovery_response, infer_target
from bacteriocin_lab.shared.config import SCHEMA_VERSION

from .runs import MAX_ITERATIONS_LIMIT, RunManager

# ----------------------------------------------------------------------
# Who the specialists are. ``transport`` is how Omnigent reaches each one;
# the in-process loop this API drives calls the same Python directly, so the
# column describes the deployment, not a different implementation.
# ----------------------------------------------------------------------
AGENT_ROSTER: list[dict[str, Any]] = [
    {
        "role": "evidence",
        "label": "Literature & Evidence",
        "agent_name": "literature-evidence-agent",
        "transport": "mcp-tool",
        "deterministic": True,
        "produces": "literature-derived evidence",
        "claim": "Retrieved and structured from published abstracts, with provenance. "
        "Automated extraction is not independent verification.",
    },
    {
        "role": "candidate",
        "label": "Candidate Design",
        "agent_name": CANDIDATE_AGENT,
        "model_version": CANDIDATE_VERSION,
        "transport": "mcp-tool",
        "deterministic": True,
        "produces": "proposals",
        "claim": "Ranked candidates and falsifiable hypotheses. Never evidence of activity.",
    },
    {
        "role": "planner",
        "label": "Experiment Planner",
        "agent_name": PLANNER_AGENT,
        "model_version": PLANNER_VERSION,
        "transport": "sub-agent",
        "deterministic": True,
        "produces": "experiment specs",
        "claim": "Chooses the experiment whose outcome is least predictable, "
        "one variable at a time.",
    },
    {
        "role": "simulation",
        "label": "Simulator",
        "agent_name": "bacteriocin_sim",
        "model_version": SIMULATOR_VERSION,
        "transport": "mcp-tool",
        "deterministic": True,
        "produces": "simulation-derived predictions",
        "claim": "Predictions to be tested, never observations. The priors are coarse and "
        "uncalibrated against any dataset, so a confident number can be wrong by a decade.",
    },
    {
        "role": "analysis",
        "label": "Result Analysis",
        "agent_name": "result_analysis_agent",
        "transport": "sub-agent",
        "deterministic": True,
        "produces": "findings",
        "claim": "Says whether a result supports, weakens or fails to distinguish its "
        "hypothesis. Never calls a simulated result experimentally validated.",
    },
    {
        "role": "critic",
        "label": "Scientific Critic",
        "agent_name": "scientific_critic",
        "transport": "mcp-tool",
        "deterministic": True,
        "produces": "reviews",
        "claim": "Challenges a claim before the state accepts it. Approval is what is left "
        "when no rule objects, not the default.",
    },
    {
        "role": "knowledge",
        "label": "Research State",
        "agent_name": KNOWLEDGE_AGENT,
        "model_version": KNOWLEDGE_VERSION,
        "transport": "mcp-tool",
        "deterministic": True,
        "produces": "append-only state",
        "claim": "History is never overwritten. A hypothesis that went supported then "
        "weakened keeps both states.",
    },
]


# ----------------------------------------------------------------------
# Requests
# ----------------------------------------------------------------------
class RunRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=500)
    species: str = Field(min_length=2, max_length=120)
    # The candidate agent skips envelope-accessibility reasoning without this, and a
    # Gram-negative-specific candidate can then rank highly against a Gram-positive
    # target on information gain alone. Required rather than defaulted for that reason.
    gram: Literal["positive", "negative"]
    strain: str | None = Field(default=None, max_length=120)
    target_cell_density: float = Field(default=1e6, gt=0, le=1e12)
    ph: float = Field(default=7.0, ge=0, le=14)
    temperature_c: float = Field(default=37.0, ge=0, le=100)
    max_candidates: int = Field(default=4, ge=1, le=12)
    max_iterations: int = Field(default=6, ge=1, le=MAX_ITERATIONS_LIMIT)
    max_failures: int = Field(default=3, ge=1, le=10)
    seed: int | None = Field(default=42)

    def to_run_request(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "target": {"species": self.species, "gram": self.gram, "strain": self.strain},
            "desired_behavior": {
                "high_inhibition": True,
                "target_cell_density": self.target_cell_density,
                "ph": self.ph,
                "temperature_c": self.temperature_c,
            },
            "constraints": {"max_candidates": self.max_candidates},
            "max_iterations": self.max_iterations,
            "max_failures": self.max_failures,
            "seed": self.seed,
        }


class DiscoverRequest(BaseModel):
    """One product-level question; the orchestrator owns all agent dispatch."""

    prompt: str = Field(min_length=3, max_length=500)
    target_organism: str | None = Field(default=None, max_length=120)
    context: dict[str, Any] | None = None


class CandidateRequest(BaseModel):
    species: str = Field(min_length=2, max_length=120)
    gram: Literal["positive", "negative"]
    strain: str | None = Field(default=None, max_length=120)
    max_candidates: int = Field(default=5, ge=1, le=12)
    desired_behavior: dict[str, Any] = Field(default_factory=dict)


class EvidenceRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    bacteriocin: str | None = Field(default=None, max_length=120)
    target_organism: str | None = Field(default=None, max_length=120)
    target_strain: str | None = Field(default=None, max_length=120)
    max_results: int = Field(default=8, ge=1, le=50)
    #: Retrieval is off by default in the agent's own config, so reaching the
    #: network stays an explicit request rather than a side effect of asking.
    retrieve: bool = True
    timeout_seconds: float = Field(default=15.0, gt=0, le=60)


class ExperimentRequest(BaseModel):
    """One ``ExperimentSpec``, forwarded to the simulator unchanged.

    ``spec`` is validated by the simulator's own schema rather than restated
    here, so this API cannot drift from the contract it is forwarding.
    """

    spec: dict[str, Any]
    candidate_registry: dict[str, dict[str, Any]] | None = None


class ExperimentBatchRequest(BaseModel):
    """Many specs in one request, forwarded to the simulator's own batch call.

    ``run_experiments`` groups by backend and isolates per-spec failures, so one
    invalid spec returns a failed result instead of losing the batch. A dose
    sweep is the usual caller.
    """

    specs: list[dict[str, Any]] = Field(min_length=1, max_length=64)
    candidate_registry: dict[str, dict[str, Any]] | None = None


class TargetDesignAPIRequest(BaseModel):
    target_organism: str = Field(min_length=2, max_length=120)
    target_strain: str | None = Field(default=None, max_length=120)
    context: dict[str, Any] | None = None
    desired_properties: dict[str, Any] | None = None
    max_known_candidates: int = Field(default=10, ge=1, le=20)
    max_natural_variants: int = Field(default=10, ge=1, le=20)
    max_designed_candidates: int = Field(default=10, ge=1, le=25)
    seed: int | None = Field(default=42)
    known_threshold: float = Field(default=0.80)
    natural_threshold: float = Field(default=0.85)


def _candidate_registry(raw: dict[str, dict[str, Any]] | None) -> dict[str, CandidateSpec] | None:
    """Coerce a JSON registry into the ``CandidateSpec`` objects the adapter expects.

    The simulator cannot predict activity from an opaque id, so a registry
    carrying each candidate's sequence is what makes a result specific to the
    candidate it names. Supplying it as plain dicts fails inside the adapter, so
    it is validated here where the error can still be reported as a bad request.
    """
    if not raw:
        return None
    try:
        return {key: CandidateSpec.model_validate(value) for key, value in raw.items()}
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"invalid candidate_registry: {exc}") from exc


# ----------------------------------------------------------------------
def create_app(*, allow_origins: list[str] | None = None) -> FastAPI:
    app = FastAPI(
        title="BACTERION API",
        version=SCHEMA_VERSION if isinstance(SCHEMA_VERSION, str) else "1",
        description=(
            "HTTP transport over the bacteriocin-discovery lab. Every response is an "
            "existing agent's output. Literature-derived, proposal and "
            "simulation-derived claims are distinct and are never merged."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins or ["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    runs = RunManager()
    literature = LiteratureEvidenceAgent()

    # -- meta ----------------------------------------------------------
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "schema_version": SCHEMA_VERSION,
            "simulator_version": SIMULATOR_VERSION,
            "max_iterations_limit": MAX_ITERATIONS_LIMIT,
            "active_runs": runs.active_count(),
        }

    @app.get("/api/agents")
    def agents() -> dict[str, Any]:
        return {
            "agents": AGENT_ROSTER,
            "loop": [
                "evidence",
                "candidate",
                "planner",
                "simulation",
                "analysis",
                "critic",
                "knowledge",
            ],
        }

    # -- simulator -----------------------------------------------------
    @app.get("/api/simulator/backends")
    def backends() -> dict[str, Any]:
        return describe_backends()

    @app.get("/api/simulator/selftest")
    def selftest() -> dict[str, Any]:
        """The simulator's directional biology invariants, run live.

        Reported verbatim, including the invariants it already knows it
        violates: a self-test that hid its known failures would be worthless.
        """
        return run_selftest()

    @app.post("/api/simulator/experiment")
    def experiment(body: ExperimentRequest) -> dict[str, Any]:
        try:
            result = run_experiment(
                body.spec,
                candidate_registry=_candidate_registry(body.candidate_registry),
            )
        except BacteriocinSimError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return result.model_dump(mode="json")

    @app.post("/api/simulator/experiments")
    def experiments(body: ExperimentBatchRequest) -> dict[str, Any]:
        results = run_experiments(
            body.specs,
            candidate_registry=_candidate_registry(body.candidate_registry),
        )
        return {"results": [r.model_dump(mode="json") for r in results]}

    # -- candidates ----------------------------------------------------
    @app.post("/api/candidates")
    def candidates(body: CandidateRequest) -> dict[str, Any]:
        return generate_candidates(
            {
                "target": {
                    "organism": body.species,
                    "gram": body.gram,
                    "strain": body.strain,
                },
                "desired_behavior": body.desired_behavior,
                "constraints": {"max_candidates": body.max_candidates},
            }
        )

    @app.get("/api/reference-bacteriocins")
    def reference_bacteriocins() -> dict[str, Any]:
        """The characterised bacteriocins the candidate agent reasons from.

        Served rather than duplicated in the front end, so a sweep run from the
        browser uses the same sequences the candidate agent scores — there is
        one copy of this data and it is the knowledge source.
        """
        source = default_knowledge_source()
        return {
            "source_name": source.source_name,
            "records": [record.model_dump(mode="json") for record in source.records()],
        }

    # -- literature ----------------------------------------------------
    @app.post("/api/evidence")
    def evidence(body: EvidenceRequest) -> dict[str, Any]:
        """Query the literature agent, which retrieves from Europe PMC over the network."""
        try:
            response = literature.run(
                {
                    "question": body.question,
                    "bacteriocin": body.bacteriocin,
                    "target_organism": body.target_organism,
                    "target_strain": body.target_strain,
                    "retrieval": {
                        "enabled": body.retrieve,
                        "max_results": body.max_results,
                        "timeout_seconds": body.timeout_seconds,
                    },
                }
            )
        except Exception as exc:
            # Retrieval reaches an external service, so being unreachable is an
            # expected state and is reported as such rather than as a bug.
            raise HTTPException(
                status_code=502, detail=f"literature retrieval failed: {type(exc).__name__}: {exc}"
            ) from exc
        return response.model_dump(mode="json")

    # -- knowledge / research state ------------------------------------
    @app.get("/api/knowledge/{operation}")
    def knowledge(operation: str, state_dir: str | None = None) -> dict[str, Any]:
        """Read-only knowledge-agent operations against a persisted event-log store.

        Only queries are exposed: a web client may read the recorded history and
        check its integrity, but writing to it belongs to the loop.
        """
        allowed = {
            "summary": "summarize_current_state",
            "open-questions": "get_open_questions",
            "integrity": "verify_integrity",
        }
        if operation not in allowed:
            raise HTTPException(
                status_code=404, detail=f"unknown operation; expected one of {sorted(allowed)}"
            )
        payload: dict[str, Any] = {"operation": allowed[operation]}
        if state_dir:
            payload["state_dir"] = state_dir
        return knowledge_call(payload)

    # -- target-to-bacteriocin design ---------------------------------
    @app.post("/api/design/target")
    def design_target(body: TargetDesignAPIRequest) -> dict[str, Any]:
        """Execute target-to-bacteriocin design with hierarchical escalation."""
        from bacteriocin_lab.agents.design import design_for_target

        result = design_for_target(
            target_organism=body.target_organism,
            target_strain=body.target_strain,
            context=body.context,
            desired_properties=body.desired_properties,
            max_known_candidates=body.max_known_candidates,
            max_natural_variants=body.max_natural_variants,
            max_designed_candidates=body.max_designed_candidates,
            seed=body.seed,
            known_threshold=body.known_threshold,
            natural_threshold=body.natural_threshold,
        )
        return result.model_dump(mode="json")

    # -- product discovery -------------------------------------------------
    @app.post("/api/discover")
    def discover(body: DiscoverRequest) -> dict[str, Any]:
        """Run the complete workflow and return only its public scientific answer.

        The lower-level specialist routes remain available for engineering and
        Omnigent integration, but a product client never needs to coordinate
        them or understand their identifiers.
        """
        try:
            organism, gram = infer_target(body.prompt, body.target_organism)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        context = body.context or {}
        high_density = (
            "high-density" in body.prompt.casefold() or "high density" in body.prompt.casefold()
        )
        density = context.get("target_cell_density", 1e8 if high_density else 1e6)
        objective = {
            "goal": body.prompt,
            "target": {"species": organism, "gram": gram},
            "desired_behavior": {
                "high_inhibition": True,
                "target_cell_density": density,
                "ph": context.get("ph", 7.0),
                "temperature_c": context.get("temperature_c", 37.0),
            },
            # A single ranked candidate makes the adaptive condition change
            # legible instead of switching candidates between iterations.
            "constraints": {"max_candidates": 1},
        }
        try:
            result = run_discovery(
                objective=objective,
                max_iterations=2,
                max_failures=3,
                seed=42,
                registry=AgentRegistry.default(),
            )
        except Exception as exc:
            # Details stay in server logs and the developer routes.  Showing
            # a traceback as a scientific answer would be both unsafe and
            # unhelpful to a normal product user.
            raise HTTPException(
                status_code=503,
                detail=(
                    "Computational evaluation could not safely complete. Please try again later."
                ),
            ) from exc
        return build_discovery_response(result.to_dict())

    # -- runs ----------------------------------------------------------
    @app.post("/api/runs")
    def start_run(body: RunRequest) -> dict[str, Any]:
        try:
            record = runs.start(body.to_run_request())
        except RuntimeError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        return record.summary()

    @app.get("/api/runs")
    def list_runs() -> dict[str, Any]:
        return {"runs": runs.list()}

    def _record(run_id: str):
        record = runs.get(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"no run {run_id!r}")
        return record

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        record = _record(run_id)
        return {
            **record.summary(),
            "state": record.state,
            "execution_trace": (record.result or {}).get("execution_trace") or [],
        }

    @app.get("/api/runs/{run_id}/events")
    def get_events(run_id: str, since: int = 0) -> dict[str, Any]:
        record = _record(run_id)
        return {"run_id": run_id, "status": record.status, "events": record.events.since(since)}

    @app.get("/api/runs/{run_id}/stream")
    async def stream(run_id: str, request: Request) -> StreamingResponse:
        record = _record(run_id)

        async def generator():
            index = 0
            while True:
                if await request.is_disconnected():
                    return
                for event in record.events.since(index):
                    index += 1
                    yield f"data: {json.dumps(event)}\n\n"
                if record.status != "running" and index >= len(record.events):
                    yield "event: close\ndata: {}\n\n"
                    return
                await asyncio.sleep(0.2)

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def app_from_env() -> FastAPI:
    """Factory for ``uvicorn --reload``, which needs an import string, not an app."""
    import os

    origins = [o for o in (os.environ.get("BACTERION_ORIGINS") or "").split(",") if o]
    return create_app(allow_origins=origins or None)
