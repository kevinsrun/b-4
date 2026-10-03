"""End-to-end tests for the Candidate Generation & Design Agent.

These tests defend the contract obligations, not just the happy path:
no false validation claims, reproducible IDs, graceful failure, and the
requirement that a previous result can change the next decision.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bacteriocin_discovery.candidate_agent import (
    AGENT_NAME,
    MODEL_VERSION,
    CandidateGenerationAgent,
    CandidateRequest,
    EmptyKnowledgeSource,
    InMemoryKnowledgeSource,
    generate_candidates,
)
from bacteriocin_discovery.candidate_agent.schema import CandidateProposal
from bacteriocin_discovery.contract import AgentResponseEnvelope, Evidence

PEDIOCIN = "KYYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC"
LEUCOCIN = "KYYGNGVHCTKSGCSVNWGEAFSAGVHRLANGGNGFW"
MICROCIN = "GGAGHVPEYFVGIGTPISFYG"

RECORDS = [
    {
        "name": "pediocin PA-1",
        "sequence": PEDIOCIN,
        "origin": "literature",
        "bacteriocin_class": "class_iia",
        "known_targets": ["Listeria monocytogenes"],
        "known_stability": {"ph_stable_range": [2.0, 9.0], "thermostable": True},
        "resistance_concerns": ["Man-PTS receptor loss"],
        "receptor": "mannose phosphotransferase system (Man-PTS)",
        "accession": "P29430",
        "sequence_verified": True,
    },
    {
        "name": "leucocin A",
        "sequence": LEUCOCIN,
        "origin": "literature",
        "bacteriocin_class": "class_iia",
        "known_targets": ["Listeria monocytogenes"],
        "known_stability": {"ph_stable_range": [2.0, 8.0], "thermostable": True},
        "receptor": "mannose phosphotransferase system (Man-PTS)",
        "sequence_verified": True,
    },
    {
        "name": "microcin J25",
        "sequence": MICROCIN,
        "origin": "literature",
        "bacteriocin_class": "lasso_peptide",
        "known_targets": ["Escherichia coli"],
        "known_non_targets": ["Staphylococcus aureus"],
        "known_stability": {"ph_stable_range": [2.0, 10.0], "thermostable": True},
        "receptor": "FhuA (uptake), RNA polymerase",
        "sequence_verified": True,
    },
    {
        "name": "uncharacterised peptide X",
        "sequence": "KWKLFKKIGIGKFLHSAKKF",
        "origin": "database",
        "sequence_verified": False,
    },
]

BASE_REQUEST = {
    "target": {"organism": "Listeria monocytogenes", "gram": "positive"},
    "desired_behavior": {
        "high_inhibition": True,
        "ph_range": [6.0, 7.5],
        "target_cell_density": 100000000,
        "temperature_c": 37,
    },
    "constraints": {"max_candidates": 3},
}


@pytest.fixture
def agent() -> CandidateGenerationAgent:
    return CandidateGenerationAgent(
        knowledge_source=InMemoryKnowledgeSource(RECORDS, name="test-records")
    )


class TestBasicOperation:
    def test_returns_ranked_candidates(self, agent):
        result = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        assert 0 < len(result.candidates) <= 3
        assert [c.rank for c in result.candidates] == list(range(1, len(result.candidates) + 1))

    def test_every_candidate_has_an_id_and_provenance(self, agent):
        result = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        for candidate in result.candidates:
            assert candidate.candidate_id.startswith("cand_")
            assert candidate.origin in ("literature", "database", "generated", "modified")
            assert candidate.score is not None

    def test_respects_max_candidates(self, agent):
        payload = {**BASE_REQUEST, "constraints": {"max_candidates": 2}}
        assert len(agent.run(CandidateRequest.model_validate(payload)).candidates) == 2

    def test_selection_logic_explains_the_ranking(self, agent):
        logic = agent.run(CandidateRequest.model_validate(BASE_REQUEST)).selection_logic
        assert "information_gain" in logic
        assert "not a potency ordering" in logic

    def test_reports_considered_count(self, agent):
        result = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        assert result.considered_count >= len(result.candidates)

    def test_each_candidate_explains_why_it_was_selected(self, agent):
        """Responsibility 3: explain why each candidate was selected."""
        for candidate in agent.run(CandidateRequest.model_validate(BASE_REQUEST)).candidates:
            assert candidate.score is not None
            assert candidate.score.rationale


class TestNeverClaimsValidation:
    """Contract rule 9 -- the obligation this agent must never breach."""

    def test_all_candidates_are_unvalidated(self, agent):
        for candidate in agent.run(CandidateRequest.model_validate(BASE_REQUEST)).candidates:
            assert candidate.validation_status == "unvalidated"

    def test_schema_rejects_an_experimentally_validated_claim(self):
        with pytest.raises(ValidationError, match="never emit"):
            CandidateProposal(
                candidate_id="cand_x",
                origin="literature",
                name="test",
                validation_status="experimentally-validated",
            )

    def test_emitted_evidence_is_marked_inferred(self, agent):
        result = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        assert result.evidence
        for item in result.evidence:
            assert item.evidence_type == "inferred-hypothesis"
            assert not item.is_experimentally_validated

    def test_warns_that_output_is_not_experimental(self, agent):
        warnings = " ".join(agent.run(CandidateRequest.model_validate(BASE_REQUEST)).warnings)
        assert "None is experimentally validated" in warnings
        assert "is a measurement" in warnings

    def test_hypotheses_are_tagged_as_inferred(self, agent):
        for candidate in agent.run(CandidateRequest.model_validate(BASE_REQUEST)).candidates:
            for hypothesis in candidate.hypotheses:
                assert hypothesis.evidence_type == "inferred-hypothesis"


class TestHypotheses:
    def test_every_candidate_gets_a_falsifiable_hypothesis(self, agent):
        for candidate in agent.run(CandidateRequest.model_validate(BASE_REQUEST)).candidates:
            assert candidate.hypotheses
            primary = candidate.hypotheses[0]
            assert primary.hypothesis_id.startswith("hyp_")
            assert primary.falsified_if
            assert primary.predicted_inhibition_fraction is not None

    def test_hypothesis_records_the_conditions_it_depends_on(self, agent):
        result = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        conditions = result.candidates[0].hypotheses[0].key_conditions
        assert conditions["ph_range"] == [6.0, 7.5]
        assert conditions["target_cell_density"] == 100000000

    def test_mechanism_hypothesis_added_when_receptor_is_known(self, agent):
        result = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        with_receptor = [c for c in result.candidates if c.features.receptor]
        assert with_receptor
        assert any(len(c.hypotheses) >= 2 for c in with_receptor)

    def test_strengths_and_failure_modes_are_populated(self, agent):
        for candidate in agent.run(CandidateRequest.model_validate(BASE_REQUEST)).candidates:
            assert candidate.expected_failure_modes

    def test_high_cell_density_appears_as_a_failure_mode(self, agent):
        result = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        modes = " ".join(m for c in result.candidates for m in c.expected_failure_modes)
        assert "peptide-to-cell ratio" in modes


class TestResultsChangeTheNextDecision:
    """The loop requirement: a result must be able to change the next decision."""

    def test_testing_a_candidate_demotes_it(self, agent):
        first = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        top = first.candidates[0]

        payload = {
            **BASE_REQUEST,
            "constraints": {"max_candidates": 3, "diversity_weight": 0.0},
            "previous_results": [
                {
                    "result_id": "res_1",
                    "experiment_id": "exp_1",
                    "candidate_id": top.candidate_id,
                    "measurement": {"predicted_inhibition_fraction": 0.9},
                    "evidence_type": "simulation-derived",
                }
            ],
        }
        second = agent.run(CandidateRequest.model_validate(payload))

        before = next(c for c in first.candidates if c.candidate_id == top.candidate_id)
        after = next(
            (c for c in second.candidates if c.candidate_id == top.candidate_id), None
        )
        # Either dropped from the set, or kept with strictly lower novelty.
        assert after is None or after.score.novelty < before.score.novelty

    def test_competing_hypotheses_change_the_scores(self, agent):
        without = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        payload = {
            **BASE_REQUEST,
            "competing_hypotheses": [
                {
                    "hypothesis_id": "hyp_charge_low",
                    "statement": "Activity requires low net charge",
                    "discriminating_feature": "net_charge",
                    "favourable_range": [-5.0, 1.0],
                },
                {
                    "hypothesis_id": "hyp_charge_high",
                    "statement": "Activity requires high net charge",
                    "discriminating_feature": "net_charge",
                    "favourable_range": [3.0, 12.0],
                },
            ],
        }
        with_hypotheses = agent.run(CandidateRequest.model_validate(payload))

        assert all(c.score.hypothesis_discrimination == 0.0 for c in without.candidates)
        assert any(c.score.hypothesis_discrimination > 0.0 for c in with_hypotheses.candidates)

    def test_excluded_candidates_are_not_returned(self, agent):
        first = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        excluded = first.candidates[0].candidate_id
        payload = {
            **BASE_REQUEST,
            "constraints": {"max_candidates": 3, "exclude_candidate_ids": [excluded]},
        }
        second = agent.run(CandidateRequest.model_validate(payload))
        assert excluded not in {c.candidate_id for c in second.candidates}
        assert any(r.get("candidate_id") == excluded for r in second.rejected)


class TestTargetSensitivity:
    def test_gram_negative_target_promotes_a_gram_negative_active_candidate(self, agent):
        payload = {
            "target": {"organism": "Escherichia coli", "gram": "negative"},
            "desired_behavior": {"ph_range": [6.0, 7.5], "target_cell_density": 1000000},
            "constraints": {"max_candidates": 2, "diversity_weight": 0.0},
        }
        result = agent.run(CandidateRequest.model_validate(payload))
        assert result.candidates[0].name == "microcin J25"

    def test_gram_positive_target_promotes_an_anti_listerial_candidate(self, agent):
        result = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        top_names = {c.name for c in result.candidates[:2]}
        assert top_names & {"pediocin PA-1", "leucocin A"}

    def test_net_charge_is_computed_at_the_requested_ph(self, agent):
        payload = {**BASE_REQUEST, "desired_behavior": {"ph_range": [4.0, 5.0]}}
        result = agent.run(CandidateRequest.model_validate(payload))
        computed = result.candidates[0].features.computed
        assert computed is not None
        assert computed.charge_ph == 4.5


class TestConstraintsAndFiltering:
    def test_require_known_sequence_filters_records_without_one(self):
        agent = CandidateGenerationAgent(
            knowledge_source=InMemoryKnowledgeSource(
                [{"name": "no sequence", "origin": "database"}, RECORDS[0]], name="mixed"
            )
        )
        payload = {**BASE_REQUEST, "constraints": {"require_known_sequence": True}}
        result = agent.run(CandidateRequest.model_validate(payload))
        assert all(c.sequence for c in result.candidates)
        assert any("require_known_sequence" in r["reason"] for r in result.rejected)

    def test_length_bounds_are_enforced(self, agent):
        payload = {**BASE_REQUEST, "constraints": {"max_sequence_length": 25}}
        result = agent.run(CandidateRequest.model_validate(payload))
        assert all(len(c.sequence) <= 25 for c in result.candidates if c.sequence)

    def test_allowed_origins_is_enforced(self, agent):
        payload = {**BASE_REQUEST, "constraints": {"allowed_origins": ["database"]}}
        result = agent.run(CandidateRequest.model_validate(payload))
        assert all(c.origin == "database" for c in result.candidates)

    def test_score_floor_rejects_with_a_reason(self, agent):
        payload = {**BASE_REQUEST, "constraints": {"min_total_score": 0.99}}
        result = agent.run(CandidateRequest.model_validate(payload))
        assert result.candidates == []
        assert any("below min_total_score" in r["reason"] for r in result.rejected)

    def test_rejects_inverted_ph_range(self):
        with pytest.raises(ValidationError, match="inverted"):
            CandidateRequest.model_validate(
                {
                    "target": {"organism": "Listeria monocytogenes"},
                    "desired_behavior": {"ph_range": [8.0, 6.0]},
                }
            )

    def test_rejects_empty_organism(self):
        with pytest.raises(ValidationError, match="must not be empty"):
            CandidateRequest.model_validate({"target": {"organism": "   "}})

    def test_rejects_inverted_length_bounds(self):
        with pytest.raises(ValidationError, match="exceeds max_sequence_length"):
            CandidateRequest.model_validate(
                {
                    "target": {"organism": "Listeria monocytogenes"},
                    "constraints": {"min_sequence_length": 50, "max_sequence_length": 20},
                }
            )


class TestSequenceModification:
    def test_disabled_by_default(self, agent):
        result = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        assert all(c.origin != "modified" for c in result.candidates)

    def test_produces_variants_when_enabled(self, agent):
        payload = {
            **BASE_REQUEST,
            "constraints": {
                "max_candidates": 8,
                "allow_sequence_modification": True,
                "max_modified_candidates": 3,
            },
        }
        result = agent.run(CandidateRequest.model_validate(payload))
        modified = [c for c in result.candidates if c.origin == "modified"]
        assert modified
        for candidate in modified:
            assert candidate.derived_from_candidate_id
            assert candidate.modifications
            assert not candidate.sequence_verified
            assert any("Computationally proposed" in m for m in candidate.expected_failure_modes)

    def test_variants_trigger_an_explicit_warning(self, agent):
        payload = {
            **BASE_REQUEST,
            "constraints": {"max_candidates": 8, "allow_sequence_modification": True},
        }
        result = agent.run(CandidateRequest.model_validate(payload))
        assert any("computationally modified" in w for w in result.warnings)

    def test_budget_of_zero_produces_no_variants(self, agent):
        payload = {
            **BASE_REQUEST,
            "constraints": {
                "max_candidates": 8,
                "allow_sequence_modification": True,
                "max_modified_candidates": 0,
            },
        }
        result = agent.run(CandidateRequest.model_validate(payload))
        assert all(c.origin != "modified" for c in result.candidates)


class TestErrorHandling:
    def test_empty_knowledge_source_returns_a_usable_result(self):
        agent = CandidateGenerationAgent(knowledge_source=EmptyKnowledgeSource())
        result = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        assert result.candidates == []
        assert result.recommended_next_action.agent == "evidence_gathering_agent"
        assert any("No candidates available" in w for w in result.warnings)

    def test_invalid_sequence_is_rejected_with_a_reason_not_an_exception(self):
        agent = CandidateGenerationAgent(
            knowledge_source=InMemoryKnowledgeSource(
                [{"name": "bad", "sequence": "KYYXXZZ123"}, RECORDS[0]], name="mixed"
            )
        )
        result = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        assert any("Unusable sequence" in r["reason"] for r in result.rejected)
        assert result.candidates

    def test_malformed_candidate_pool_entry_does_not_abort_the_run(self, agent):
        payload = {**BASE_REQUEST, "candidate_pool": [{"no_name_field": True}]}
        result = agent.run(CandidateRequest.model_validate(payload))
        assert any("Invalid candidate_pool entry" in r["reason"] for r in result.rejected)
        assert result.candidates

    def test_failing_knowledge_source_degrades_gracefully(self):
        class Broken:
            @property
            def source_name(self) -> str:
                return "broken"

            def records(self):
                raise RuntimeError("database unreachable")

        agent = CandidateGenerationAgent(knowledge_source=Broken())
        payload = {**BASE_REQUEST, "candidate_pool": [RECORDS[0]]}
        result = agent.run(CandidateRequest.model_validate(payload))
        assert result.candidates
        assert any("could not be read" in w for w in result.warnings)

    def test_invalid_request_returns_a_well_formed_envelope(self):
        response = generate_candidates({"desired_behavior": {"high_inhibition": True}})
        assert response["agent"] == AGENT_NAME
        assert response["confidence"] == 0.0
        assert response["decision"]["candidates"] == []
        assert any("Invalid request" in w for w in response["warnings"])


class TestToolInterface:
    def test_envelope_matches_the_shared_contract(self, agent):
        envelope = agent.run_envelope(BASE_REQUEST)
        assert isinstance(envelope, AgentResponseEnvelope)
        assert envelope.agent == AGENT_NAME
        assert envelope.model_version == MODEL_VERSION
        assert 0.0 <= envelope.confidence <= 1.0
        assert envelope.recommended_next_action.agent == "experiment_planner"

    def test_output_is_json_serialisable(self, agent):
        import json

        payload = agent.run_envelope(BASE_REQUEST).model_dump(mode="json")
        assert json.loads(json.dumps(payload))

    def test_artifacts_record_how_the_run_was_configured(self, agent):
        artifacts = agent.run_envelope(BASE_REQUEST).artifacts
        assert artifacts["knowledge_source"] == "test-records"
        assert artifacts["run_id"].startswith("run_")
        assert artifacts["scoring_weights"]["promise"] == pytest.approx(0.35, abs=1e-6)

    def test_next_action_tells_the_planner_to_sweep_density(self, agent):
        reason = agent.run_envelope(BASE_REQUEST).recommended_next_action.reason
        assert "dose per cell" in reason
        assert "single concentration cannot" in reason

    def test_module_level_function_round_trips(self):
        response = generate_candidates(
            BASE_REQUEST, knowledge_source=InMemoryKnowledgeSource(RECORDS, name="test-records")
        )
        assert response["decision"]["candidates"]
        assert response["recommended_next_action"]["agent"] == "experiment_planner"


class TestReproducibility:
    def test_identical_input_gives_identical_output(self, agent):
        """Contract rule 13."""
        first = agent.run_envelope(BASE_REQUEST).model_dump(mode="json")
        second = agent.run_envelope(BASE_REQUEST).model_dump(mode="json")
        assert first == second

    def test_candidate_ids_are_stable_across_agent_instances(self):
        source = InMemoryKnowledgeSource(RECORDS, name="test-records")
        a = CandidateGenerationAgent(knowledge_source=source).run(
            CandidateRequest.model_validate(BASE_REQUEST)
        )
        b = CandidateGenerationAgent(knowledge_source=source).run(
            CandidateRequest.model_validate(BASE_REQUEST)
        )
        assert [c.candidate_id for c in a.candidates] == [c.candidate_id for c in b.candidates]

    def test_same_peptide_from_two_sources_collapses_to_one_candidate(self):
        """Content-addressed IDs mean a duplicate record is not a duplicate candidate."""
        duplicate = {**RECORDS[0], "name": "pediocin PA-1", "source": "another database"}
        agent = CandidateGenerationAgent(
            knowledge_source=InMemoryKnowledgeSource([RECORDS[0], duplicate], name="dupes")
        )
        result = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        assert len({c.candidate_id for c in result.candidates}) == len(result.candidates)
        assert result.considered_count == 1


class TestUncertaintyReporting:
    def test_always_reports_the_heuristic_limitation(self, agent):
        result = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        assert any(u.kind == "model-limitation" for u in result.uncertainties)

    def test_flags_a_missing_cell_density_as_high_severity(self, agent):
        payload = {**BASE_REQUEST, "desired_behavior": {"ph_range": [6.0, 7.5]}}
        result = agent.run(CandidateRequest.model_validate(payload))
        density = [u for u in result.uncertainties if "target_cell_density" in u.description]
        assert density and density[0].severity == "high"

    def test_flags_absent_previous_results_and_hypotheses(self, agent):
        result = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        descriptions = " ".join(u.description for u in result.uncertainties)
        assert "No previous_results" in descriptions
        assert "No competing_hypotheses" in descriptions

    def test_unverified_sequence_produces_a_warning(self):
        agent = CandidateGenerationAgent(
            knowledge_source=InMemoryKnowledgeSource([RECORDS[3]], name="unverified")
        )
        result = agent.run(CandidateRequest.model_validate(BASE_REQUEST))
        assert any("unverified sequence" in w for w in result.warnings)

    def test_confidence_is_lower_when_the_pool_is_thin(self):
        thin = CandidateGenerationAgent(
            knowledge_source=InMemoryKnowledgeSource([RECORDS[0]], name="thin")
        ).run_envelope(BASE_REQUEST)
        wide = CandidateGenerationAgent(
            knowledge_source=InMemoryKnowledgeSource(RECORDS * 4, name="wide")
        ).run_envelope(BASE_REQUEST)
        assert thin.confidence < wide.confidence


class TestEvidenceIntegration:
    def test_candidate_carried_on_evidence_is_picked_up(self):
        agent = CandidateGenerationAgent(knowledge_source=EmptyKnowledgeSource())
        evidence = Evidence(
            evidence_id="ev_test_1",
            evidence_type="literature-derived",
            claim="Plantaricin-like peptide reported active against Listeria",
            source="doi:10.0000/example",
        )
        payload = {
            **BASE_REQUEST,
            "evidence": [
                {
                    **evidence.model_dump(),
                    "candidate": {
                        "name": "plantaricin-like peptide",
                        "sequence": LEUCOCIN,
                        "known_targets": ["Listeria monocytogenes"],
                    },
                }
            ],
        }
        result = agent.run(CandidateRequest.model_validate(payload))
        assert len(result.candidates) == 1
        candidate = result.candidates[0]
        assert candidate.name == "plantaricin-like peptide"
        assert candidate.origin == "literature"
        assert "ev_test_1" in candidate.evidence_ids

    def test_evidence_without_a_candidate_payload_is_ignored(self, agent):
        payload = {
            **BASE_REQUEST,
            "evidence": [
                {
                    "evidence_id": "ev_plain",
                    "evidence_type": "literature-derived",
                    "claim": "General background on bacteriocin classification",
                }
            ],
        }
        assert agent.run(CandidateRequest.model_validate(payload)).candidates
