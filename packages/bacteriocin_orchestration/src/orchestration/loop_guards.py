"""Loop guards and safety protections preventing infinite loops, runaway recursion, and cycles."""

from __future__ import annotations

from .types import Route


class CycleDetector:
    """Detects repeating cycles in agent routing (e.g. planner -> critic -> planner -> critic)."""

    def __init__(self, max_cycle_repeats: int = 2) -> None:
        self.max_cycle_repeats = max_cycle_repeats
        self._route_history: list[str] = []

    def record_route(self, route: Route) -> None:
        """Record an executed route."""
        # Include agent and key reason/payload characteristics
        signature = f"{route.next_agent}:{route.reason.strip()[:30]}"
        self._route_history.append(signature)

    def is_cycle_detected(self) -> tuple[bool, str]:
        """Check if any cycle has repeated at least max_cycle_repeats times.

        Returns (is_cycle, reason_description).
        """
        n = len(self._route_history)
        if n < 4:
            return False, ""

        # Check cycle periods from 2 up to 4
        for period in (2, 3, 4):
            pattern_len = period * self.max_cycle_repeats
            if n < pattern_len:
                continue
            slice_end = self._route_history[-pattern_len:]
            cycle_candidate = slice_end[:period]
            # Verify if this period repeats across the whole slice
            is_repeating = True
            for i in range(self.max_cycle_repeats):
                if slice_end[i * period : (i + 1) * period] != cycle_candidate:
                    is_repeating = False
                    break
            if is_repeating:
                cycle_str = " -> ".join(c.split(":")[0] for c in cycle_candidate)
                return (
                    True,
                    f"Detected recurring cycle ({cycle_str}) repeated {self.max_cycle_repeats} times.",
                )

        return False, ""


class LoopGuards:
    """Manages all safety guards across the discovery execution."""

    def __init__(
        self,
        max_iterations: int = 10,
        max_failures: int = 3,
        max_visits_per_agent_per_iteration: int = 3,
        max_cycle_repeats: int = 2,
    ) -> None:
        self.max_iterations = max_iterations
        self.max_failures = max_failures
        self.max_visits_per_agent_per_iteration = max_visits_per_agent_per_iteration
        self.consecutive_failures = 0
        self.total_failures = 0
        self.cycle_detector = CycleDetector(max_cycle_repeats=max_cycle_repeats)
        self._visits_in_current_iteration: dict[str, int] = {}
        self._current_iteration = -1

    def record_agent_visit(self, iteration: int, agent: str) -> tuple[bool, str]:
        """Record visit to an agent in the given iteration. Returns (allowed, error_msg)."""
        if iteration != self._current_iteration:
            self._current_iteration = iteration
            self._visits_in_current_iteration = {}

        count = self._visits_in_current_iteration.get(agent, 0) + 1
        self._visits_in_current_iteration[agent] = count

        if count > self.max_visits_per_agent_per_iteration:
            return (
                False,
                (
                    f"Agent '{agent}' exceeded maximum visits ({self.max_visits_per_agent_per_iteration}) "
                    f"in iteration {iteration}."
                ),
            )
        return True, ""

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self.total_failures += 1

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def should_terminate_failures(self) -> tuple[bool, str]:
        if self.consecutive_failures >= self.max_failures:
            return (
                True,
                f"Terminated after exceeding max consecutive failures ({self.consecutive_failures}/{self.max_failures}).",
            )
        return False, ""

    def should_terminate_iterations(self, current_iteration: int) -> tuple[bool, str]:
        if current_iteration >= self.max_iterations:
            return (
                True,
                f"Terminated: reached max iterations limit ({current_iteration}/{self.max_iterations}).",
            )
        return False, ""

    def check_cycle(self, route: Route) -> tuple[bool, str]:
        self.cycle_detector.record_route(route)
        return self.cycle_detector.is_cycle_detected()
