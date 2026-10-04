"""Main discovery workflow engine and public run_discovery entry point."""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

from .loop_guards import LoopGuards
from .registry import AgentRegistry
from .routing import Router
from .state import ResearchStateManager
from .trace import TraceRecorder
from .types import (
    DiscoveryResult,
    ResearchObjective,
    ResearchState,
    Route,
    make_run_id,
)


class DiscoveryWorkflowEngine:
    """Orchestrates the autonomous bacteriocin-discovery loop with safety guards and adaptive routing."""

    def __init__(
        self,
        registry: AgentRegistry | None = None,
        max_iterations: int = 10,
        max_failures: int = 3,
        stop_condition: Callable[[ResearchState], bool] | None = None,
        seed: int | None = None,
    ) -> None:
        self.registry = registry or AgentRegistry.default()
        self.max_iterations = max_iterations
        self.max_failures = max_failures
        self.stop_condition = stop_condition
        self.seed = seed

    def run(
        self,
        objective: dict[str, Any] | ResearchObjective,
        initial_state: ResearchState | None = None,
    ) -> DiscoveryResult:
        if self.seed is not None:
            random.seed(self.seed)

        if isinstance(objective, dict):
            obj = ResearchObjective.model_validate(objective)
        else:
            obj = objective

        state = initial_state.clone() if initial_state else ResearchState(objective=obj)
        state_mgr = ResearchStateManager(state)

        run_id = make_run_id(
            {
                "objective": obj.model_dump(),
                "iteration": state.iteration,
                "seed": self.seed,
            }
        )

        trace = TraceRecorder()
        loop_guards = LoopGuards(
            max_iterations=self.max_iterations,
            max_failures=self.max_failures,
        )
        router = Router(stop_condition=self.stop_condition)

        state_mgr.record_event(
            event_type="campaign_started",
            source_agent="orchestrator",
            summary=f"Campaign started for target {obj.species or 'unknown'}",
            data={"run_id": run_id, "objective": obj.model_dump()},
        )

        status: str = "completed"
        errors: list[str] = []
        last_agent: str | None = None
        last_route: Route | None = None

        while True:
            # 1. Check max iterations
            should_stop_iter, _iter_reason = loop_guards.should_terminate_iterations(state.iteration)
            if should_stop_iter:
                status = "max_iterations"
                break

            # 2. Determine next route
            route = router.determine_next_route(state, last_agent=last_agent, last_route=last_route)

            # 3. Check terminal route
            if route.terminal:
                if "Discovered" in route.reason or "satisfied" in route.reason:
                    status = "completed"
                else:
                    status = "stopped"
                break

            # 4. Check cycle detection guard
            is_cycle, cycle_reason = loop_guards.check_cycle(route)
            if is_cycle:
                status = "stopped"
                errors.append(cycle_reason)
                break

            # 5. Check per-iteration agent visit guard
            allowed_visit, visit_err = loop_guards.record_agent_visit(
                state.iteration, route.next_agent
            )
            if not allowed_visit:
                status = "stopped"
                errors.append(visit_err)
                break

            # 6. Validate route required inputs before dispatch
            valid_inputs, input_err = router.validate_inputs_for_route(route, state)
            if not valid_inputs:
                errors.append(f"Route validation error: {input_err}")
                # Fall back safely
                if route.next_agent == "planner":
                    route = Route(next_agent="candidate", reason=f"Safe fallback: {input_err}")
                elif route.next_agent == "simulation":
                    route = Route(next_agent="planner", reason=f"Safe fallback: {input_err}")
                else:
                    status = "failed"
                    break

            # 7. Dispatch agent with state preservation on failure
            input_ids: list[str] = []
            if route.next_agent == "planner" and state.candidates:
                input_ids = [c.candidate_id for c in state.candidates]
            elif route.next_agent == "simulation" and state.experiments:
                input_ids = [state.experiments[-1].experiment_id]
            elif route.next_agent == "analysis" and state.results:
                input_ids = [state.results[-1].result_id]
            elif route.next_agent == "critic" and state.findings:
                input_ids = [state.findings[-1].finding_id]

            trace_id = trace.record_start(
                iteration=state.iteration,
                agent=route.next_agent,
                routing_reason=route.reason,
                input_ids=input_ids,
            )

            # Snapshot state before dispatch
            snapshot = state.clone()

            try:
                agent = self.registry.get(route.next_agent)
                result_payload = agent.run(state)

                # Validate agent output envelope structure
                if not isinstance(result_payload, dict):
                    raise TypeError(f"Agent '{route.next_agent}' returned non-dict response")
                if result_payload.get("malformed"):
                    raise ValueError(
                        f"Agent '{route.next_agent}' returned malformed payload missing identifiers"
                    )

                out_ids = result_payload.get("output_ids", [])
                trace.record_success(trace_id, output_ids=out_ids)
                loop_guards.record_success()

                last_agent = route.next_agent
                last_route = route

            except Exception as exc:  # noqa: BLE001
                # Revert to snapshot to preserve state integrity
                state = snapshot
                state_mgr = ResearchStateManager(state)

                error_msg = f"Agent '{route.next_agent}' failed: {exc}"
                trace.record_failure(trace_id, error=str(exc))
                loop_guards.record_failure()
                errors.append(error_msg)

                should_stop_fail, fail_reason = loop_guards.should_terminate_failures()
                if should_stop_fail:
                    status = "failed"
                    errors.append(fail_reason)
                    break

        summary = {
            "iterations_completed": state.iteration,
            "total_candidates_screened": len(state.candidates),
            "tested_candidates": len(state.tested_candidate_ids),
            "experiments_run": len(state.results),
            "findings_count": len(state.findings),
            "reviews_count": len(state.reviews),
            "active_hypotheses": len([h for h in state.hypotheses if h.status == "open"]),
            "supported_hypotheses": len([h for h in state.hypotheses if h.status == "supported"]),
            "weakened_hypotheses": len([h for h in state.hypotheses if h.status == "weakened"]),
            "settled_candidates": list(state.settled_candidate_ids),
        }

        return DiscoveryResult(
            run_id=run_id,
            status=status,  # type: ignore
            objective=obj.model_dump(),
            final_state=state.to_dict(),
            execution_trace=trace.to_dicts(),
            iterations_completed=state.iteration,
            errors=errors,
            summary=summary,
        )


def run_discovery(
    objective: dict[str, Any] | ResearchObjective,
    max_iterations: int = 10,
    max_failures: int = 3,
    seed: int | None = None,
    stop_condition: Callable[[ResearchState], bool] | None = None,
    registry: AgentRegistry | None = None,
    initial_state: ResearchState | None = None,
) -> DiscoveryResult:
    """Public entry point for autonomous bacteriocin discovery.

    Args:
        objective: Scientific goal and target constraints.
        max_iterations: Maximum loop iterations before graceful termination.
        max_failures: Consecutive failure threshold before halting.
        seed: Random seed for deterministic reproducibility.
        stop_condition: Optional custom termination predicate over ResearchState.
        registry: Injected AgentRegistry (defaults to repository specialists).
        initial_state: Optional prior state to resume from.

    Returns:
        Structured DiscoveryResult with final_state, execution_trace, and metrics.
    """
    engine = DiscoveryWorkflowEngine(
        registry=registry,
        max_iterations=max_iterations,
        max_failures=max_failures,
        stop_condition=stop_condition,
        seed=seed,
    )
    return engine.run(objective, initial_state=initial_state)
