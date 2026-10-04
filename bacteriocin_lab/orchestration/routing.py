"""Explicit, structured routing logic with input validation and backtracking support."""

from __future__ import annotations

from collections.abc import Callable

from .types import ResearchState, Route


class Router:
    """Calculates the next agent route based on ResearchState and recent feedback."""

    def __init__(
        self,
        stop_condition: Callable[[ResearchState], bool] | None = None,
    ) -> None:
        self.stop_condition = stop_condition

    def validate_inputs_for_route(self, route: Route, state: ResearchState) -> tuple[bool, str]:
        """Verify that the required data structures exist before dispatching to an agent."""
        agent = route.next_agent
        if agent == "candidate":
            if not state.objective.species:
                return False, "Target organism / species is required for candidate generation"

        elif agent == "planner":
            active_cands = [
                c for c in state.candidates if c.candidate_id not in state.settled_candidate_ids
            ]
            if not state.candidates or not active_cands:
                return False, "No active candidates available for experiment planning"

        elif agent == "simulation":
            if not state.experiments:
                return False, "No experiment specs planned for simulation execution"

        elif agent == "analysis":
            if not state.results:
                return False, "No experiment results available for analysis"

        elif agent == "critic" and not state.findings and not state.results:
            return False, "No findings or experiment results available for scientific critique"

        elif agent == "knowledge" and not state.reviews and not state.findings:
            return False, "No reviews or findings available to update knowledge state"

        return True, ""

    def determine_next_route(
        self,
        state: ResearchState,
        last_agent: str | None = None,
        last_route: Route | None = None,
    ) -> Route:
        """Evaluate the current research state and decide the next agent or terminal stop."""
        # 1. Custom or objective stop condition
        if self.stop_condition and self.stop_condition(state):
            return Route(
                next_agent="terminal",
                terminal=True,
                reason="Custom stop condition satisfied.",
            )

        # 2. Starting condition: cold start -> evidence gathering
        if last_agent is None:
            return Route(
                next_agent="evidence",
                reason="Initial cold start: gather literature and known baseline evidence.",
                required_inputs=["objective.target.species"],
            )

        # 3. After evidence gathering -> candidate generation
        if last_agent == "evidence":
            return Route(
                next_agent="candidate",
                reason="Evidence gathered: propose ranked candidates and testable hypotheses.",
                required_inputs=["objective.target.species"],
            )

        # 4. After candidate generation -> experiment planner
        if last_agent == "candidate":
            active_cands = [
                c for c in state.candidates if c.candidate_id not in state.settled_candidate_ids
            ]
            if not active_cands:
                return Route(
                    next_agent="evidence",
                    reason="No viable candidates generated: query literature for alternative families.",
                )
            return Route(
                next_agent="planner",
                reason="Candidates ready: plan discriminative experiment.",
                required_inputs=["candidates"],
            )

        # 5. After experiment planning -> simulation runner
        if last_agent == "planner":
            if not state.experiments:
                return Route(
                    next_agent="candidate",
                    reason="Planner generated no specs: re-run candidate generation.",
                )
            return Route(
                next_agent="simulation",
                reason="Experiment planned: execute simulation against computational backend.",
                required_inputs=["experiments"],
            )

        # 6. After simulation runner -> result analysis
        if last_agent == "simulation":
            return Route(
                next_agent="analysis",
                reason="Simulation executed: interpret results against motivating hypotheses.",
                required_inputs=["results"],
            )

        # 7. After result analysis -> scientific critic
        if last_agent == "analysis":
            return Route(
                next_agent="critic",
                reason="Analysis complete: subject findings and validation claims to scientific critique.",
                required_inputs=["findings"],
            )

        # 8. After scientific critic -> evaluation of review
        if last_agent == "critic":
            latest_review = state.reviews[-1] if state.reviews else None
            review_status = latest_review.status if latest_review else "approved"

            if review_status == "approved":
                return Route(
                    next_agent="knowledge",
                    reason="Critic approved findings: commit to research state.",
                    required_inputs=["reviews"],
                )
            elif review_status == "needs_more_evidence":
                # Backtrack to Evidence Agent or Planner
                return Route(
                    next_agent="evidence",
                    reason=f"Critic requested more evidence: {latest_review.critique if latest_review else ''}",
                )
            elif review_status == "experiment_inconclusive":
                # Backtrack to Planner for sweep
                return Route(
                    next_agent="planner",
                    reason=f"Critic found experiment inconclusive: {latest_review.critique if latest_review else ''}",
                )
            elif review_status == "analysis_unsupported":
                # Backtrack to Analysis Agent
                return Route(
                    next_agent="analysis",
                    reason=f"Critic found analysis unsupported: {latest_review.critique if latest_review else ''}",
                )
            elif review_status == "rejected":
                # Backtrack to Candidate Agent
                return Route(
                    next_agent="candidate",
                    reason=f"Critic rejected candidate hypothesis: {latest_review.critique if latest_review else ''}",
                )
            else:
                return Route(
                    next_agent="knowledge",
                    reason="Defaulting to knowledge update with caveats.",
                )

        # 9. After knowledge state update -> decide next discovery turn
        if last_agent == "knowledge":
            # Check if active candidate needs initial or follow-up testing
            untested_cands = [
                c
                for c in state.candidates
                if c.candidate_id not in state.tested_candidate_ids
                and c.candidate_id not in state.settled_candidate_ids
            ]
            if untested_cands:
                return Route(
                    next_agent="planner",
                    reason=f"Plan follow-up experiment for candidate {untested_cands[0].name or untested_cands[0].candidate_id}.",
                )

            # Check if tested candidates have open hypotheses needing follow-up (e.g. sensitivity sweep)
            open_hyps = [
                h
                for h in state.hypotheses
                if h.status in ("open", "supported")
                and h.candidate_id not in state.settled_candidate_ids
            ]
            if open_hyps:
                return Route(
                    next_agent="planner",
                    reason=f"Plan discriminative condition sweep for hypothesis {open_hyps[0].hypothesis_id}.",
                )

            # Check if any candidate has proven potent and robust across multiple conditions
            for cand in state.candidates:
                cand_results = [r for r in state.results if r.candidate_id == cand.candidate_id]
                potent_findings = [
                    f
                    for f in state.findings
                    if cand.candidate_id in f.candidate_ids
                    and f.status == "supported"
                    and f.confidence >= 0.85
                ]
                if potent_findings and len(cand_results) >= 2:
                    return Route(
                        next_agent="terminal",
                        terminal=True,
                        reason=f"Discovered robust candidate {cand.name or cand.candidate_id}: {potent_findings[0].statement}",
                    )

            # If all current candidates are settled, generate fresh candidates
            return Route(
                next_agent="candidate",
                reason="Current candidate set exhausted or settled: generate new candidates.",
            )

        # Default fallback
        return Route(
            next_agent="terminal",
            terminal=True,
            reason=f"Workflow completed standard sequence after {last_agent}.",
        )
