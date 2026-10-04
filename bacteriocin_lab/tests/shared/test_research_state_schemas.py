"""The shared research-state schemas: serialisable, strict, and incapable of claiming validation."""

import pytest
from pydantic import ValidationError

from bacteriocin_lab.shared import (
    CandidateRecord,
    HypothesisRecord,
    ResearchState,
    StateEvent,
    StatusChange,
    UpdatedResearchState,
)


def test_empty_state_round_trips_through_json():
    s = ResearchState()
    assert ResearchState.model_validate_json(s.model_dump_json()) == s
    assert s.iteration == 1 and s.event_count == 0 and s.last_event_hash is None


def test_events_keep_event_specific_fields_flat():
    e = StateEvent(
        event_id="evt_000007",
        seq=7,
        iteration=7,
        timestamp="t",
        event="hypothesis_update",
        hypothesis_id="H12",
        previous_status="supported",
        new_status="weakened",
        triggered_by=["experiment:E17", "finding:F22"],
    )
    d = e.model_dump(mode="json")
    assert (
        d["hypothesis_id"] == "H12"
        and d["previous_status"] == "supported"
        and d["triggered_by"] == ["experiment:E17", "finding:F22"]
    )
    assert StateEvent.model_validate(d) == e


def test_records_reject_unknown_fields_but_events_accept_them():
    with pytest.raises(ValidationError):
        HypothesisRecord(hypothesis_id="h", surprise=1)
    with pytest.raises(ValidationError):
        ResearchState(surprise=1)
    StateEvent(event_id="e", seq=1, iteration=0, timestamp="t", event="x", anything="goes")


def test_hypothesis_statuses_are_a_closed_vocabulary_with_no_validated_state():
    for ok in ("open", "supported", "weakened", "rejected"):
        HypothesisRecord(hypothesis_id="h", status=ok)
    for bad in ("validated", "confirmed", "proven"):
        with pytest.raises(ValidationError):
            HypothesisRecord(hypothesis_id="h", status=bad)
    assert HypothesisRecord(hypothesis_id="h").epistemic_status == "inferred hypothesis, not a fact"


def test_candidates_default_to_unvalidated_and_status_is_closed():
    c = CandidateRecord(candidate_id="c")
    assert c.validation_status == "unvalidated" and c.status == "proposed"
    with pytest.raises(ValidationError):
        CandidateRecord(candidate_id="c", status="validated")


def test_derived_views_and_the_update_container():
    s = ResearchState()
    s.hypotheses["h"] = HypothesisRecord(
        hypothesis_id="h",
        status="rejected",
        status_history=[
            StatusChange(event_id="e", iteration=1, timestamp="t", new_status="rejected")
        ],
    )
    s.candidates["c"] = CandidateRecord(candidate_id="c", status="rejected")
    assert [h.hypothesis_id for h in s.rejected_hypotheses] == ["h"] and [
        c.candidate_id for c in s.rejected_candidates
    ] == ["c"]
    u = UpdatedResearchState(state=s)
    assert UpdatedResearchState.model_validate_json(u.model_dump_json()) == u
