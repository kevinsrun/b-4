"""Tests for deterministic physicochemical feature computation."""

from __future__ import annotations

import pytest

from bacteriocin_discovery.candidate_agent.features import (
    SequenceValidationError,
    compute_features,
    gravy,
    kmer_profile,
    molecular_weight,
    net_charge,
    normalise_sequence,
    sequence_similarity,
)


class TestNormaliseSequence:
    def test_uppercases_and_strips_whitespace(self):
        assert normalise_sequence("  it si\nsl c  ") == "ITSISLC"

    def test_rejects_empty(self):
        with pytest.raises(SequenceValidationError, match="empty"):
            normalise_sequence("   ")

    @pytest.mark.parametrize("bad", ["ITSX", "ITSB", "ITS1", "ITS-SL", "ITSZ"])
    def test_rejects_non_standard_residues(self, bad):
        """Ambiguity codes must be rejected, not silently substituted."""
        with pytest.raises(SequenceValidationError, match="non-standard"):
            normalise_sequence(bad)


class TestMolecularWeight:
    def test_single_glycine_is_residue_plus_water(self):
        assert molecular_weight("G") == pytest.approx(57.0519 + 18.01528, abs=1e-4)

    def test_unmodified_mass_exceeds_the_mature_lantibiotic_mass(self):
        """Nisin A: the primary-sequence mass is deliberately NOT the mature mass.

        Mature nisin A is ~3354 Da. The unmodified primary sequence computes
        ~3498 Da, because the eight dehydrations that form its thioether rings
        each remove ~18 Da and have not been applied. The gap is the point: it
        is why ``compute_features`` attaches a caveat for modified classes
        instead of reporting a confident-looking number.
        """
        mass = molecular_weight("ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK")
        assert 3450 < mass < 3550
        assert mass - 3354 == pytest.approx(8 * 18.0, abs=12.0)

    def test_additive_over_concatenation(self):
        a, b = "ITSIS", "LCTPG"
        combined = molecular_weight(a + b)
        separate = molecular_weight(a) + molecular_weight(b) - 18.01528
        # Residue masses are tabulated to 4 dp, so agreement is ~1e-4, not exact.
        assert combined == pytest.approx(separate, abs=1e-3)


class TestNetCharge:
    def test_lysine_is_positive_at_neutral_ph(self):
        assert net_charge("KKKK", ph=7.0) > 3.0

    def test_glutamate_is_negative_at_neutral_ph(self):
        assert net_charge("EEEE", ph=7.0) < -3.0

    def test_charge_decreases_monotonically_with_ph(self):
        seq = "KYYGNGVTCGKHSCSVDWGK"
        charges = [net_charge(seq, ph=p) for p in (4.0, 6.0, 7.0, 9.0, 11.0)]
        assert charges == sorted(charges, reverse=True)

    def test_histidine_titrates_across_its_pka(self):
        """His pKa 6.5, so charge should drop materially between pH 5 and 8."""
        assert net_charge("HHHH", ph=5.0) - net_charge("HHHH", ph=8.0) > 2.0

    def test_rejects_out_of_range_ph(self):
        with pytest.raises(ValueError, match="pH must be within"):
            net_charge("KKKK", ph=15.0)


class TestGravy:
    def test_hydrophobic_sequence_is_positive(self):
        assert gravy("IIIVVVLLL") > 3.0

    def test_charged_sequence_is_negative(self):
        assert gravy("KKKRRREEE") < -3.0


class TestComputeFeatures:
    def test_reports_expected_fields(self):
        features = compute_features("KYYGNGVTCGKHSCSVDWGK", ph=7.0)
        assert features.sequence_length == 20
        assert features.cysteine_count == 2
        assert features.max_disulfide_bonds == 1
        assert features.charge_ph == 7.0
        assert features.charge_density == pytest.approx(features.net_charge / 20, abs=1e-4)
        assert sum(features.residue_composition.values()) == pytest.approx(1.0, abs=1e-3)

    def test_is_deterministic(self):
        """Contract rule 13: identical input must give identical output."""
        seq = "KYYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC"
        assert compute_features(seq).model_dump() == compute_features(seq).model_dump()

    def test_caveats_flag_post_translational_modification(self):
        """A lantibiotic's primary-sequence mass does not describe the mature peptide."""
        features = compute_features(
            "ITSISLCTPGCKTGALMGCNMKTATCHCSIHVSK", bacteriocin_class="class_i"
        )
        assert any("post-translationally modified" in c for c in features.caveats)

    def test_no_modification_caveat_for_unmodified_class(self):
        features = compute_features("KYYGNGVTCGKHSCSVDWGK", bacteriocin_class="class_iia")
        assert not any("post-translationally modified" in c for c in features.caveats)

    def test_cysteine_caveat_is_an_upper_bound_not_a_prediction(self):
        features = compute_features("CCKYYGNGVCC")
        assert any("upper bound" in c for c in features.caveats)

    def test_charge_follows_requested_ph(self):
        seq = "KYYGNGVTCGKHSCSVDWGK"
        assert compute_features(seq, ph=5.0).net_charge > compute_features(seq, ph=9.0).net_charge


class TestSimilarity:
    def test_identical_sequences_are_fully_similar(self):
        assert sequence_similarity("KYYGNGVTC", "KYYGNGVTC") == 1.0

    def test_unrelated_sequences_are_dissimilar(self):
        assert sequence_similarity("KYYGNGVTC", "WWWWWWWWW") == 0.0

    def test_is_symmetric(self):
        a, b = "KYYGNGVTCGKHSC", "KYYGNGVHCTKSGC"
        assert sequence_similarity(a, b) == sequence_similarity(b, a)

    def test_shared_motif_raises_similarity_above_unrelated(self):
        """Two class IIa peptides share the YGNGV box and should register as related."""
        pediocin = "KYYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC"
        leucocin = "KYYGNGVHCTKSGCSVNWGEAFSAGVHRLANGGNGFW"
        unrelated = "GGAGHVPEYFVGIGTPISFYG"
        assert sequence_similarity(pediocin, leucocin) > sequence_similarity(pediocin, unrelated)

    def test_short_sequence_falls_back_to_whole_sequence(self):
        assert kmer_profile("KY", k=3) == {"KY"}

    def test_rejects_non_positive_k(self):
        with pytest.raises(ValueError, match="k must be positive"):
            kmer_profile("KYYGNGV", k=0)
