"""Omnigent integration adapter allowing external controllers to manage discovery campaigns."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .registry import AgentRegistry
from .types import DiscoveryResult, ResearchObjective, ResearchState
from .workflow import DiscoveryWorkflowEngine, run_discovery


class OmnigentAdapter:
    """Adapter for driving the discovery workflow from Omnigent or other external orchestrators."""

    def __init__(self, registry: AgentRegistry | None = None) -> None:
        self.registry = registry or AgentRegistry.default()
        self._runs: dict[str, DiscoveryResult] = {}
        self._states: dict[str, ResearchState] = {}

    def run(
        self,
        objective: dict[str, Any] | ResearchObjective,
        max_iterations: int = 10,
        max_failures: int = 3,
        seed: int | None = None,
        stop_condition: Callable[[ResearchState], bool] | None = None,
    ) -> DiscoveryResult:
        """Execute a full autonomous discovery campaign."""
        result = run_discovery(
            objective=objective,
            max_iterations=max_iterations,
            max_failures=max_failures,
            seed=seed,
            stop_condition=stop_condition,
            registry=self.registry,
        )
        self._runs[result.run_id] = result
        self._states[result.run_id] = ResearchState.model_validate(result.final_state)
        return result

    def inspect_state(self, run_id: str) -> dict[str, Any] | None:
        """Inspect the current ResearchState for a campaign run."""
        state = self._states.get(run_id)
        return state.to_dict() if state else None

    def inspect_trace(self, run_id: str) -> list[dict[str, Any]] | None:
        """Inspect the full execution trace for a campaign run."""
        run = self._runs.get(run_id)
        return run.execution_trace if run else None

    def resume(
        self,
        run_id: str,
        additional_iterations: int = 5,
        stop_condition: Callable[[ResearchState], bool] | None = None,
    ) -> DiscoveryResult:
        """Resume an existing campaign from its last known valid state."""
        state = self._states.get(run_id)
        if not state:
            raise KeyError(f"Run ID '{run_id}' not found in active adapter session.")

        engine = DiscoveryWorkflowEngine(
            registry=self.registry,
            max_iterations=state.iteration + additional_iterations,
            stop_condition=stop_condition,
        )
        result = engine.run(state.objective, initial_state=state)
        self._runs[result.run_id] = result
        self._states[result.run_id] = ResearchState.model_validate(result.final_state)
        return result

    @staticmethod
    def save_state_to_file(state: ResearchState, path: str | Path) -> None:
        """Serialize ResearchState to JSON on disk."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(state.to_dict(), indent=2))

    @staticmethod
    def load_state_from_file(path: str | Path) -> ResearchState:
        """Deserialize ResearchState from JSON on disk."""
        target = Path(path)
        data = json.loads(target.read_text())
        return ResearchState.model_validate(data)
