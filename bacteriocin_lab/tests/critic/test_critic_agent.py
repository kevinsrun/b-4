"""Tests for the scientific critic.

The three the brief names specifically are marked in their docstrings:
approval, rejection, and "needs more evidence" routing.

The bar these hold is that the critic *discriminates*. A reviewer that
approves everything and one that rejects everything are equally useless, so
several tests check that a rule stays quiet when it should as well as firing
when it should.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bacteriocin_lab.agents.critic import (
    ANALYSIS_AGENT,
    EVIDENCE_AGENT,
    PLANNER_AGENT,
    ClaimUnderReview,
    CriticRequest,
    ScientificCriticAgent,
    run_agent,
)
from bacteriocin_lab.agents.critic.rules import check_provenance_classified
from bacteriocin_lab.shared.contract import Evidence


def result(
    result_id: str,
    *,
    inhibition: float = 0.95,
    uncertainty: float | None = 0.02,
    ph: float = 6.5,
    temperature_c: float = 30.0,
    medium: str = "bhi",
    concentration: float = 1.0,
    evidence_type: str = "simulation-derived",
    hypothesis_id: str | None = None,
) -> dict:
    return {
        "result_id": result_id,
        "experiment_id": f"exp-{result_id}",
        "candidate_id": "cand-nisin",
        "hypothesis_id": hypothesis_id,
        "evidence_type": evidence_type,
        "conditions": {
            "ph": ph,
            "temperature_c": temperature_c,
            "medium": medium,
            "bacteriocin_concentration": concentration,
            "assay_domain": "simulated_in_vitro",
        },
        "measurement": {
            "predicted_inhibition_fraction": inhibition,
            "uncertainty": uncertainty,
        },
    }


def claim(**over) -> dict:
    base = {
        "claim_id": "claim-1",
        "statement": "Nisin reduces L. monocytogenes growth at 1 uM in BHI.",
        "result_ids": ["res-1", "res-2"],
    }
    base.update(over)
    return base


def sound_request(**over) -> dict:
    payload = {
        "claims": [claim()],
        "previous_results": [
            result("res-1", concentration=1.0),
            result("res-2", concentration=2.0),
        ],
    }
    payload.update(over)
    return payload


# ---------------------------------------------------------------------------
# the three named tests
# ---------------------------------------------------------------------------


def test_approves_a_well_supported_claim() -> None:
    """THE APPROVAL TEST. A sound claim must pass, or the critic is just noise."""
    review = ScientificCriticAgent().review(CriticRequest.model_validate(sound_request()))
    assert review.status == "approve", [i.model_dump() for i in review.issues]
    assert review.issues == []
    assert review.accepted_claims == ["claim-1"]
    assert review.rejected_claims == []
    assert review.required_followups == []
    assert review.confidence == 1.0


def test_rejects_simulated_evidence_described_as_experimentally_validated() -> None:
    """THE REJECTION TEST. Contract rule 9 -- the thing that must never pass."""
    payload = sound_request(
        claims=[
            claim(
                statement=(
                    "Nisin was experimentally validated to inhibit L. monocytogenes "
                    "at 1 uM."
                )
            )
        ]
    )
    review = ScientificCriticAgent().review(CriticRequest.model_validate(payload))

    assert review.status == "reject"
    assert review.rejected_claims == ["claim-1"]
    assert review.accepted_claims == []
    offending = [i for i in review.issues if i.type == "misdescribed_provenance"]
    assert len(offending) == 1
    assert offending[0].severity == "high"
    assert "simulation-derived" in offending[0].description
    assert offending[0].route_to == ANALYSIS_AGENT


def test_needs_more_evidence_routes_back_to_the_planner() -> None:
    """THE ROUTING TEST. A gap defers and names who closes it."""
    payload = sound_request(
        claims=[claim(result_ids=["res-1"])],
        previous_results=[result("res-1")],
    )
    review = ScientificCriticAgent().review(CriticRequest.model_validate(payload))

    assert review.status == "needs_more_evidence"
    # Held, not accepted and not rejected: silence must not read as approval.
    assert review.accepted_claims == []
    assert review.rejected_claims == []
    assert [i.type for i in review.issues] == ["insufficient_coverage"]
    assert [f.agent for f in review.required_followups] == [PLANNER_AGENT]
    assert review.required_followups[0].claim_ids == ["claim-1"]


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------


def test_a_disclaimer_is_not_a_validation_claim() -> None:
    """'NOT experimentally validated' must not trip the rule."""
    payload = sound_request(
        claims=[
            claim(
                statement=(
                    "Nisin reduces growth at 1 uM. This is simulation-derived and has "
                    "not been experimentally validated."
                )
            )
        ]
    )
    review = ScientificCriticAgent().review(CriticRequest.model_validate(payload))
    assert not [i for i in review.issues if i.type == "misdescribed_provenance"]


def test_validation_language_is_allowed_when_backed_by_wet_lab_evidence() -> None:
    payload = sound_request(
        claims=[
            claim(
                statement="Nisin was experimentally validated to inhibit L. monocytogenes.",
                evidence_ids=["ev-wet"],
            )
        ],
        evidence=[
            Evidence(
                evidence_id="ev-wet",
                evidence_type="wet-lab-derived",
                claim="Measured in a plate assay.",
            ).model_dump(mode="json")
        ],
    )
    review = ScientificCriticAgent().review(CriticRequest.model_validate(payload))
    assert not [i for i in review.issues if i.type == "misdescribed_provenance"]


def test_the_contract_blocks_unclassified_provenance_at_the_boundary() -> None:
    """The primary guard is the contract, not the critic.

    ``Evidence.evidence_type`` is a required Literal, so evidence with no
    provenance class cannot even be parsed into a request. Worth pinning: if
    this ever starts passing, the contract was relaxed and the critic's own
    check below becomes load-bearing rather than defence-in-depth.
    """
    ev = Evidence(
        evidence_id="ev-1", evidence_type="literature-derived", claim="X inhibits Y."
    ).model_dump(mode="json")
    ev["evidence_type"] = None
    with pytest.raises(ValidationError):
        CriticRequest.model_validate(
            sound_request(claims=[claim(evidence_ids=["ev-1"])], evidence=[ev])
        )


def test_unclassified_provenance_routes_to_the_evidence_agent() -> None:
    """Defence in depth, exercised at the rule level.

    Unreachable through a validated envelope today (see above), so the rule is
    called directly with evidence built to bypass validation -- which is what
    a future contract relaxation or a non-pydantic caller would produce.
    """
    ev = Evidence.model_construct(
        evidence_id="ev-1", evidence_type=None, claim="X inhibits Y."
    )
    issues = check_provenance_classified(
        ClaimUnderReview(claim_id="claim-1", statement="X.", evidence_ids=["ev-1"]),
        {"ev-1": ev},
    )
    assert [i.type for i in issues] == ["unclassified_provenance"]
    assert issues[0].route_to == EVIDENCE_AGENT


# ---------------------------------------------------------------------------
# the remaining responsibilities
# ---------------------------------------------------------------------------


def test_conclusion_contradicted_by_its_own_data_is_rejected() -> None:
    payload = sound_request(
        claims=[claim(statement="Nisin effectively kills L. monocytogenes at 1 uM.")],
        previous_results=[
            result("res-1", inhibition=0.02),
            result("res-2", inhibition=0.05),
        ],
    )
    review = ScientificCriticAgent().review(CriticRequest.model_validate(payload))
    assert review.status == "reject"
    assert any(i.type == "unsupported_conclusion" for i in review.issues)


def test_extrapolation_outside_the_tested_range_is_caught() -> None:
    payload = sound_request(
        claims=[
            claim(
                statement="Nisin remains active against L. monocytogenes.",
                conditions_claimed={"ph": 5.0},
            )
        ],
        previous_results=[result("res-1", ph=6.5), result("res-2", ph=7.0)],
    )
    review = ScientificCriticAgent().review(CriticRequest.model_validate(payload))
    found = [i for i in review.issues if i.type == "unsupported_extrapolation"]
    assert found, [i.model_dump() for i in review.issues]
    assert "5" in found[0].description and "6.5-7" in found[0].description
    assert review.status == "reject"


def test_conditions_inside_the_tested_range_are_not_flagged() -> None:
    payload = sound_request(
        claims=[
            claim(
                statement="Nisin reduces growth.",
                conditions_claimed={"ph": 6.8, "medium": "bhi"},
            )
        ],
        previous_results=[result("res-1", ph=6.5), result("res-2", ph=7.0)],
    )
    review = ScientificCriticAgent().review(CriticRequest.model_validate(payload))
    assert not [i for i in review.issues if i.type == "unsupported_extrapolation"]


def test_confounded_comparison_is_flagged() -> None:
    payload = sound_request(
        claims=[claim(statement="Lower pH increases nisin activity.")],
        previous_results=[
            result("res-1", ph=5.5, temperature_c=30.0, medium="bhi", inhibition=0.95),
            result("res-2", ph=7.5, temperature_c=37.0, medium="skim_milk", inhibition=0.10),
        ],
    )
    review = ScientificCriticAgent().review(CriticRequest.model_validate(payload))
    found = [i for i in review.issues if i.type == "confounded_comparison"]
    assert found and found[0].route_to == PLANNER_AGENT


def test_a_single_varying_condition_is_not_confounded() -> None:
    payload = sound_request(
        claims=[claim(statement="Dose increases nisin activity.")],
        previous_results=[
            result("res-1", concentration=0.1, inhibition=0.05),
            result("res-2", concentration=5.0, inhibition=0.98),
        ],
    )
    review = ScientificCriticAgent().review(CriticRequest.model_validate(payload))
    assert not [i for i in review.issues if i.type == "confounded_comparison"]


def test_overstated_certainty_against_wide_uncertainty() -> None:
    payload = sound_request(
        claims=[claim(statement="Nisin always inhibits L. monocytogenes at 1 uM.")],
        previous_results=[
            result("res-1", uncertainty=0.40),
            result("res-2", uncertainty=0.45),
        ],
    )
    review = ScientificCriticAgent().review(CriticRequest.model_validate(payload))
    found = [i for i in review.issues if i.type == "overstated_certainty"]
    assert found and found[0].route_to == ANALYSIS_AGENT
    assert review.status == "approve_with_caveats"


def test_hedged_wording_against_wide_uncertainty_is_accepted() -> None:
    payload = sound_request(
        claims=[claim(statement="Nisin may inhibit L. monocytogenes at 1 uM.")],
        previous_results=[
            result("res-1", uncertainty=0.40),
            result("res-2", uncertainty=0.45),
        ],
    )
    review = ScientificCriticAgent().review(CriticRequest.model_validate(payload))
    assert not [i for i in review.issues if i.type == "overstated_certainty"]


def test_competing_hypothesis_not_distinguished() -> None:
    payload = sound_request(
        claims=[claim(hypothesis_id="hyp-a")],
        previous_results=[result("res-1", ph=6.5), result("res-2", ph=6.5)],
        competing_hypotheses=[
            {"hypothesis_id": "hyp-a", "statement": "Activity is pH driven."},
            {
                "hypothesis_id": "hyp-b",
                "statement": "Activity is receptor driven.",
                "discriminating_variable": "ph",
            },
        ],
    )
    review = ScientificCriticAgent().review(CriticRequest.model_validate(payload))
    found = [i for i in review.issues if i.type == "hypotheses_not_distinguished"]
    assert found and "hyp-b" in found[0].description
    assert review.status == "needs_more_evidence"


def test_varying_the_discriminating_variable_settles_it() -> None:
    payload = sound_request(
        claims=[claim(hypothesis_id="hyp-a")],
        previous_results=[result("res-1", ph=5.5), result("res-2", ph=7.5)],
        competing_hypotheses=[
            {"hypothesis_id": "hyp-a", "statement": "Activity is pH driven."},
            {
                "hypothesis_id": "hyp-b",
                "statement": "Activity is receptor driven.",
                "discriminating_variable": "ph",
            },
        ],
    )
    review = ScientificCriticAgent().review(CriticRequest.model_validate(payload))
    assert not [i for i in review.issues if i.type == "hypotheses_not_distinguished"]


def test_uncited_claim_is_reported_not_silently_accepted() -> None:
    payload = sound_request(claims=[claim(result_ids=[], evidence_ids=[])])
    review = ScientificCriticAgent().review(CriticRequest.model_validate(payload))
    found = [i for i in review.issues if i.type == "missing_citation"]
    assert found and found[0].severity == "high"
    assert review.accepted_claims == []


def test_dangling_result_id_is_reported() -> None:
    payload = sound_request(claims=[claim(result_ids=["res-1", "res-nope"])])
    review = ScientificCriticAgent().review(CriticRequest.model_validate(payload))
    found = [i for i in review.issues if i.type == "missing_citation"]
    assert found and "res-nope" in found[0].description


# ---------------------------------------------------------------------------
# verdict logic
# ---------------------------------------------------------------------------


def test_integrity_failure_outranks_an_evidence_gap() -> None:
    """A claim wrong about itself is not merely under-evidenced."""
    payload = sound_request(
        claims=[
            claim(
                statement="Nisin was experimentally validated to inhibit L. monocytogenes.",
                result_ids=["res-1"],
            )
        ],
        previous_results=[result("res-1")],
    )
    review = ScientificCriticAgent().review(CriticRequest.model_validate(payload))
    assert {i.type for i in review.issues} >= {"misdescribed_provenance", "insufficient_coverage"}
    assert review.status == "reject"


def test_no_claims_is_not_an_approval() -> None:
    review = ScientificCriticAgent().review(CriticRequest.model_validate({"claims": []}))
    assert review.status == "needs_more_evidence"
    assert review.confidence == 0.0


def test_confidence_falls_as_issues_accumulate() -> None:
    clean = ScientificCriticAgent().review(CriticRequest.model_validate(sound_request()))
    messy = ScientificCriticAgent().review(
        CriticRequest.model_validate(
            sound_request(
                claims=[
                    claim(
                        statement=(
                            "Nisin always proves experimentally validated activity "
                            "against L. monocytogenes."
                        ),
                        conditions_claimed={"ph": 3.0},
                    )
                ]
            )
        )
    )
    assert messy.confidence < clean.confidence


def test_review_id_is_deterministic_and_content_addressed() -> None:
    a = ScientificCriticAgent().review(CriticRequest.model_validate(sound_request()))
    b = ScientificCriticAgent().review(CriticRequest.model_validate(sound_request()))
    c = ScientificCriticAgent().review(
        CriticRequest.model_validate(sound_request(claims=[claim(statement="Something else.")]))
    )
    assert a.review_id == b.review_id
    assert a.review_id != c.review_id


def test_agent_keeps_no_state_between_reviews() -> None:
    agent = ScientificCriticAgent()
    first = agent.review(CriticRequest.model_validate(sound_request()))
    agent.review(
        CriticRequest.model_validate(
            sound_request(claims=[claim(statement="Nisin was experimentally validated.")])
        )
    )
    again = agent.review(CriticRequest.model_validate(sound_request()))
    assert again.model_dump() == first.model_dump()


# ---------------------------------------------------------------------------
# Omnigent-callable interface
# ---------------------------------------------------------------------------


def test_envelope_has_every_contract_field() -> None:
    env = run_agent(sound_request())
    for field in (
        "agent",
        "decision",
        "evidence",
        "confidence",
        "uncertainties",
        "artifacts",
        "warnings",
        "recommended_next_action",
    ):
        assert hasattr(env, field)
    assert env.agent == "scientific_critic_agent"
    assert env.model_version


def test_envelope_carries_the_review_as_an_artifact() -> None:
    env = run_agent(sound_request())
    review = env.artifacts["review"]
    assert review["status"] == "approve"
    assert review["review_id"]


def test_envelope_routes_on_needs_more_evidence() -> None:
    env = run_agent(
        sound_request(claims=[claim(result_ids=["res-1"])], previous_results=[result("res-1")])
    )
    assert env.decision["status"] == "needs_more_evidence"
    assert env.recommended_next_action is not None
    assert env.recommended_next_action.agent == PLANNER_AGENT
    assert env.recommended_next_action.payload_hint["claim_ids"] == ["claim-1"]


def test_approved_review_recommends_nothing() -> None:
    env = run_agent(sound_request())
    assert env.recommended_next_action is None


def test_high_severity_issues_surface_as_warnings() -> None:
    env = run_agent(
        sound_request(
            claims=[claim(statement="Nisin was experimentally validated to inhibit Listeria.")]
        )
    )
    assert any("misdescribed_provenance" in w for w in env.warnings)


def test_the_critic_emits_no_new_evidence() -> None:
    """A review is not a scientific finding and must not enter the state as one."""
    assert run_agent(sound_request()).evidence == []


def test_malformed_envelope_is_reported_structurally_not_raised() -> None:
    env = run_agent({"claims": "not a list"})
    assert env.decision["status"] == "rejected_input"
    assert env.confidence == 0.0
    assert env.warnings


def test_an_unparseable_result_does_not_sink_the_review() -> None:
    payload = sound_request(previous_results=[result("res-1"), {"garbage": True}])
    env = run_agent(payload)
    assert env.decision["status"] in {"needs_more_evidence", "approve_with_caveats", "reject"}
    assert "res-2" in env.artifacts["review"]["issues"][0]["description"]


def test_envelope_is_json_serialisable() -> None:
    import json

    json.dumps(run_agent(sound_request()).model_dump(mode="json"))


def test_describe_exposes_schemas_and_boundaries() -> None:
    described = ScientificCriticAgent().describe()
    assert described["agent"] == "scientific_critic_agent"
    assert "input_schema" in described and "output_schema" in described
    assert set(described["can_route_to"]) == {PLANNER_AGENT, EVIDENCE_AGENT, ANALYSIS_AGENT}
    assert any("approve by default" in d for d in described["does_not"])


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Experimentally validated activity.", True),
        ("This was not experimentally validated.", False),
        ("Wet-lab confirmed.", True),
        ("Simulation-derived prediction only.", False),
    ],
)
def test_validation_detector_matches_the_analysis_agents(text: str, expected: bool) -> None:
    """Guards the deliberate duplication of this detector.

    The critic owns its own copy so it does not depend on a sibling agent's
    internals. This fails if the two implementations drift apart.
    """
    from bacteriocin_lab.agents.analysis.agent import (
        claims_experimental_validation as theirs,
    )
    from bacteriocin_lab.agents.critic import claims_experimental_validation as ours

    assert ours(text) == expected
    assert ours(text) == theirs(text)
