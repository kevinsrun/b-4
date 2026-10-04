"""TEST 14: Duplicate event protection.

Verifies that retrying an agent call or repeating an insertion does not insert
duplicate experiments, results, candidates, or findings into ResearchState.
"""

from __future__ import annotations

from orchestration import (
    Candidate,
    Conditions,
    ExperimentResult,
    ExperimentSpec,
    Finding,
    Measurement,
    ResearchObjective,
    ResearchState,
    Review,
    Target,
)
from orchestration.state import ResearchStateManager


def test_duplicate_event_protection_and_idempotency() -> None:
    state = ResearchState(
        objective=ResearchObjective(
            goal="Test duplicate protection.",
            target={"species": "Listeria monocytogenes"},
        )
    )
    mgr = ResearchStateManager(state)

    # 1. Candidate idempotency
    cand = Candidate(candidate_id="cand_1", name="B17", score_total=0.8)
    added_1 = mgr.add_candidates([cand])
    added_2 = mgr.add_candidates([cand])  # Retry!

    assert len(state.candidates) == 1
    assert added_1 == ["cand_1"]
    assert added_2 == []

    # 2. Experiment spec idempotency
    spec = ExperimentSpec(
        experiment_id="exp_001",
        candidate_id="cand_1",
        target=Target(species="Listeria monocytogenes"),
        conditions=Conditions(bacteriocin_concentration=5.0),
    )
    res1 = mgr.add_experiment_spec(spec)
    res2 = mgr.add_experiment_spec(spec)  # Retry!

    assert res1 is True
    assert res2 is False
    assert len(state.experiments) == 1

    # 3. Experiment result idempotency
    result = ExperimentResult(
        result_id="res_001",
        experiment_id="exp_001",
        candidate_id="cand_1",
        measurement=Measurement(predicted_inhibition_fraction=0.85),
    )
    r_add1 = mgr.add_experiment_result(result)
    r_add2 = mgr.add_experiment_result(result)  # Retry!

    assert r_add1 is True
    assert r_add2 is False
    assert len(state.results) == 1

    # 4. Finding idempotency
    finding = Finding(
        finding_id="find_001",
        statement="Candidate is active.",
        status="supported",
    )
    f_add1 = mgr.add_finding(finding)
    f_add2 = mgr.add_finding(finding)  # Retry!

    assert f_add1 is True
    assert f_add2 is False
    assert len(state.findings) == 1

    # 5. Review idempotency
    review = Review(
        review_id="rev_001",
        status="approved",
        critique="Good.",
    )
    rev_add1 = mgr.add_review(review)
    rev_add2 = mgr.add_review(review)  # Retry!

    assert rev_add1 is True
    assert rev_add2 is False
    assert len(state.reviews) == 1
