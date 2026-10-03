"""Tests for the shared contract types, ID generation, and sequence design."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bacteriocin_discovery.candidate_agent.design import (
    PROTECTED_MOTIFS,
    propose_variants,
)
from bacteriocin_discovery.candidate_agent.features import net_charge
from bacteriocin_discovery.candidate_agent.knowledge import (
    JsonFileKnowledgeSource,
    default_knowledge_source,
)
from bacteriocin_discovery.contract import (
    Evidence,
    ExperimentConditions,
    ExperimentResult,
    ExperimentSpec,
    ExperimentTarget,
)
from bacteriocin_discovery.ids import candidate_id, content_id, hypothesis_id

PEDIOCIN = "KYYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC"


class TestContractTypes:
    def test_experiment_spec_round_trips(self):
        spec = ExperimentSpec(
            experiment_id="exp_1",
            candidate_id="cand_1",
            hypothesis_id="hyp_1",
            target=ExperimentTarget(species="Listeria monocytogenes", strain="EGD-e"),
            conditions=ExperimentConditions(
                bacteriocin_concentration=50.0,
                concentration_unit="nM",
                target_cell_density=1e8,
                target_cell_density_unit="CFU/mL",
                ph=6.5,
                temperature_c=37.0,
                growth_phase="exponential",
            ),
        )
        assert ExperimentSpec.model_validate(spec.model_dump()) == spec

    def test_simulation_result_is_not_experimentally_validated(self):
        result = ExperimentResult(
            result_id="res_1", experiment_id="exp_1", candidate_id="cand_1"
        )
        assert result.evidence_type == "simulation-derived"
        assert not result.is_experimentally_validated

    def test_only_wet_lab_evidence_counts_as_validated(self):
        wet = Evidence(evidence_id="ev_1", evidence_type="wet-lab-derived", claim="Measured")
        sim = Evidence(evidence_id="ev_2", evidence_type="simulation-derived", claim="Predicted")
        assert wet.is_experimentally_validated
        assert not sim.is_experimentally_validated

    def test_inhibition_fraction_is_bounded(self):
        with pytest.raises(ValidationError):
            ExperimentResult(
                result_id="res_1",
                experiment_id="exp_1",
                candidate_id="cand_1",
                measurement={"predicted_inhibition_fraction": 1.5},
            )

    def test_ph_is_bounded(self):
        with pytest.raises(ValidationError):
            ExperimentConditions(ph=15.0)

    def test_negative_concentration_is_rejected(self):
        with pytest.raises(ValidationError):
            ExperimentConditions(bacteriocin_concentration=-1.0)

    def test_conditions_default_to_simulation(self):
        """The current system must work without wet-lab data."""
        assert ExperimentConditions().assay_domain == "simulated_in_vitro"

    def test_extra_fields_are_allowed_on_extensible_models(self):
        conditions = ExperimentConditions.model_validate({"ph": 7.0, "oxygen_tension": "anaerobic"})
        assert conditions.model_dump()["oxygen_tension"] == "anaerobic"


class TestIds:
    def test_are_deterministic(self):
        assert content_id("candidate", {"a": 1}) == content_id("candidate", {"a": 1})

    def test_are_order_independent(self):
        assert content_id("candidate", {"a": 1, "b": 2}) == content_id(
            "candidate", {"b": 2, "a": 1}
        )

    def test_differ_by_content(self):
        assert content_id("candidate", {"a": 1}) != content_id("candidate", {"a": 2})

    def test_differ_by_kind(self):
        assert content_id("candidate", {"a": 1}) != content_id("hypothesis", {"a": 1})

    def test_carry_a_readable_prefix(self):
        assert content_id("experiment", {"x": 1}).startswith("exp_")
        assert content_id("result", {"x": 1}).startswith("res_")

    def test_unknown_kind_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown entity kind"):
            content_id("not_a_kind", {"a": 1})

    def test_candidate_id_is_keyed_on_the_sequence(self):
        """The same peptide reached by two routes is one candidate."""
        assert candidate_id(
            sequence=PEDIOCIN, name="pediocin PA-1", origin="literature"
        ) == candidate_id(sequence=PEDIOCIN, name="a different name", origin="database")

    def test_candidate_id_is_case_and_whitespace_insensitive(self):
        assert candidate_id(sequence=PEDIOCIN, name=None, origin="literature") == candidate_id(
            sequence=f"  {PEDIOCIN.lower()}  ", name=None, origin="literature"
        )

    def test_candidate_id_falls_back_to_name(self):
        assert candidate_id(sequence=None, name="unsequenced peptide", origin="literature")

    def test_candidate_id_requires_an_identifier(self):
        with pytest.raises(ValueError, match="at least a sequence or a name"):
            candidate_id(sequence=None, name=None, origin="literature")

    def test_hypothesis_id_is_keyed_on_candidate_target_and_prediction(self):
        base = dict(candidate="cand_1", target_species="Listeria monocytogenes")
        assert hypothesis_id(**base, prediction="A") != hypothesis_id(**base, prediction="B")


class TestSequenceDesign:
    def test_variants_differ_from_the_parent(self):
        for variant in propose_variants(PEDIOCIN):
            assert variant.sequence != PEDIOCIN
            assert len(variant.sequence) == len(PEDIOCIN)
            assert variant.modifications

    def test_conserved_motif_is_never_altered(self):
        """The YGNGV box sits in the receptor-binding region of class IIa peptides."""
        for variant in propose_variants(PEDIOCIN):
            assert any(motif in variant.sequence for motif in PROTECTED_MOTIFS)

    def test_cysteines_are_preserved(self):
        """Disulfide topology is load-bearing; losing a bridge is a confound."""
        for variant in propose_variants(PEDIOCIN):
            assert variant.sequence.count("C") == PEDIOCIN.count("C")

    def test_prolines_are_preserved(self):
        parent = "KYYGNGVTCGKPSCSVDWGKATTC"
        for variant in propose_variants(parent):
            assert variant.sequence.count("P") == parent.count("P")

    def test_termini_are_preserved(self):
        for variant in propose_variants(PEDIOCIN):
            assert variant.sequence[0] == PEDIOCIN[0]
            assert variant.sequence[-1] == PEDIOCIN[-1]

    def test_substitution_count_is_capped(self):
        for variant in propose_variants(PEDIOCIN, max_substitutions=2):
            assert len(variant.modifications) <= 2

    def test_modifications_use_standard_notation(self):
        variant = propose_variants(PEDIOCIN, max_variants=1)[0]
        for modification in variant.modifications:
            assert modification[0].isalpha()
            assert modification[-1].isalpha()
            assert modification[1:-1].isdigit()

    def test_variants_bracket_the_parent_charge(self):
        """The pair is the useful unit: it tests charge dependence in both directions."""
        variants = propose_variants(PEDIOCIN, max_variants=2)
        assert len(variants) == 2
        charges = [net_charge(v.sequence) for v in variants]
        parent_charge = net_charge(PEDIOCIN)
        assert max(charges) > parent_charge
        assert min(charges) < parent_charge

    def test_every_variant_states_its_intent(self):
        for variant in propose_variants(PEDIOCIN):
            assert variant.design_intent

    def test_is_deterministic(self):
        first = [v.sequence for v in propose_variants(PEDIOCIN)]
        second = [v.sequence for v in propose_variants(PEDIOCIN)]
        assert first == second

    def test_zero_variants_requested_returns_nothing(self):
        assert propose_variants(PEDIOCIN, max_variants=0) == []

    def test_sequence_with_no_substitutable_positions_yields_nothing(self):
        assert propose_variants("CCCCCCCC") == []


class TestSeedData:
    def test_default_source_loads(self):
        records = default_knowledge_source().records()
        assert len(records) >= 5

    def test_every_seed_record_is_marked_unverified(self):
        """The seed file is an example dataset, not an authority."""
        for record in default_knowledge_source().records():
            assert record.sequence_verified is False, record.name

    def test_every_seed_record_carries_a_source(self):
        for record in default_knowledge_source().records():
            assert record.source or record.accession, record.name

    def test_seed_sequences_are_computable(self):
        from bacteriocin_discovery.candidate_agent.features import compute_features

        for record in default_knowledge_source().records():
            if record.sequence:
                compute_features(record.sequence, bacteriocin_class=record.bacteriocin_class)

    def test_seed_covers_both_gram_types(self):
        """A Gram-negative-active option must exist or those targets are unservable."""
        targets = {
            t for record in default_knowledge_source().records() for t in record.known_targets
        }
        assert any("Listeria" in t for t in targets)
        assert any("Escherichia" in t for t in targets)

    def test_missing_file_raises_clearly(self, tmp_path):
        source = JsonFileKnowledgeSource(tmp_path / "nope.json")
        with pytest.raises(FileNotFoundError, match="Knowledge file not found"):
            source.records()

    def test_non_array_file_is_rejected(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text('{"name": "not an array"}', encoding="utf-8")
        with pytest.raises(ValueError, match="must contain a JSON array"):
            JsonFileKnowledgeSource(path).records()

    def test_invalid_json_is_rejected(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            JsonFileKnowledgeSource(path).records()
