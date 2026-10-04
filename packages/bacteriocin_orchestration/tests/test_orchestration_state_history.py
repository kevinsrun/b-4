"""TEST 13: Append-only scientific history.

Verifies that when a hypothesis transitions (e.g. supported -> weakened),
both historical events remain permanently reconstructable with no silent overwrite.
"""

from __future__ import annotations

from orchestration import Hypothesis, ResearchObjective, ResearchState
from orchestration.state import ResearchStateManager


def test_state_history_is_append_only_and_reconstructable() -> None:
    state = ResearchState(
        objective=ResearchObjective(
            goal="Test hypothesis evolution.",
            target={"species": "Listeria monocytogenes"},
        )
    )
    mgr = ResearchStateManager(state)

    # 1. Create Hypothesis H1
    h1 = Hypothesis(
        hypothesis_id="hyp_h1",
        statement="H1 is potent across all test conditions.",
        status="open",
    )
    mgr.add_hypotheses([h1], source_agent="candidate_agent")
    assert state.get_hypothesis("hyp_h1").status == "open"

    # 2. Update H1 to supported after initial low-density screen
    state.iteration = 0
    mgr.update_hypothesis_status(
        "hyp_h1",
        new_status="supported",
        source_agent="analysis_agent",
        reason="Demonstrated high inhibition at low density 1e6 CFU/mL.",
    )
    assert state.get_hypothesis("hyp_h1").status == "supported"

    # 3. Later, update H1 to weakened after high-density challenge
    state.iteration = 1
    mgr.update_hypothesis_status(
        "hyp_h1",
        new_status="weakened",
        source_agent="analysis_agent",
        reason="Inhibition dropped significantly at high density 1e8 CFU/mL.",
    )
    assert state.get_hypothesis("hyp_h1").status == "weakened"

    # 4. Assert that BOTH events exist in scientific_history (no silent overwrite!)
    history = state.scientific_history
    status_change_events = [e for e in history if e.event_type == "hypothesis_status_changed"]

    assert len(status_change_events) == 2, (
        f"Expected 2 transition events, found {len(status_change_events)}"
    )

    first_transition = status_change_events[0]
    second_transition = status_change_events[1]

    # Reconstruct event 1
    assert first_transition.data["hypothesis_id"] == "hyp_h1"
    assert first_transition.data["old_status"] == "open"
    assert first_transition.data["new_status"] == "supported"
    assert first_transition.iteration == 0
    assert "low density" in first_transition.summary

    # Reconstruct event 2
    assert second_transition.data["hypothesis_id"] == "hyp_h1"
    assert second_transition.data["old_status"] == "supported"
    assert second_transition.data["new_status"] == "weakened"
    assert second_transition.iteration == 1
    assert "high density" in second_transition.summary
