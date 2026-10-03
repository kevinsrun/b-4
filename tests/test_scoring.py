"""Tests for the scoring and ranking logic.

The behavioural claims worth defending here are the ones that stop the
discovery loop degenerating:

* information gain peaks on uncertain outcomes, not on likely successes;
* hypothesis discrimination rewards candidates that split the hypotheses;
* diversity selection does not return one family of near-identical peptides.
"""

from __future__ import annotations

import pytest

from bacteriocin_discovery.candidate_agent.features import compute_features
from bacteriocin_discovery.candidate_agent.schema import (
    CandidateConstraints,
    CandidateFeatures,
    CandidateProposal,
    CandidateTarget,
    CompetingHypothesis,
    DesiredBehavior,
    ScoreBreakdown,
    ScoringWeights,
)
from bacteriocin_discovery.candidate_agent.scoring import (
    experimental_redundancy,
    score_candidate,
    score_condition_fit,
    score_hypothesis_discrimination,
    score_information_gain,
    score_novelty,
    score_promise,
    score_uncertainty,
    select_diverse,
)

# Aliased on import: pytest would otherwise try to collect `tested_history` as a
# test function because of its name.
from bacteriocin_discovery.candidate_agent.scoring import tested_history as read_tested_history

PEDIOCIN = "KYYGNGVTCGKHSCSVDWGKATTCIINNGAMAWATGGHQGNHKC"
LEUCOCIN = "KYYGNGVHCTKSGCSVNWGEAFSAGVHRLANGGNGFW"
MICROCIN = "GGAGHVPEYFVGIGTPISFYG"

LISTERIA = CandidateTarget(organism="Listeria monocytogenes", gram="positive")
ECOLI = CandidateTarget(organism="Escherichia coli", gram="negative")


def make_candidate(
    name: str = "test",
    sequence: str | None = PEDIOCIN,
    *,
    origin: str = "literature",
    known_targets: list[str] | None = None,
    known_non_targets: list[str] | None = None,
    stability: dict | None = None,
    sensitivity: list[str] | None = None,
    resistance: list[str] | None = None,
    receptor: str | None = None,
    bacteriocin_class: str | None = "class_iia",
    verified: bool = True,
    cid: str | None = None,
) -> CandidateProposal:
    return CandidateProposal(
        candidate_id=cid or f"cand_{name}",
        origin=origin,  # type: ignore[arg-type]
        name=name,
        sequence=sequence,
        features=CandidateFeatures(
            computed=compute_features(sequence, bacteriocin_class=bacteriocin_class)
            if sequence
            else None,
            bacteriocin_class=bacteriocin_class,
            known_targets=known_targets or [],
            known_non_targets=known_non_targets or [],
            known_stability=stability or {},
            environmental_sensitivity=sensitivity or [],
            resistance_concerns=resistance or [],
            receptor=receptor,
        ),
        sequence_verified=verified,
        derived_from_candidate_id="cand_parent" if origin == "modified" else None,
    )


class TestPromise:
    def test_reported_activity_scores_higher_than_no_data(self):
        active, _ = score_promise(
            make_candidate(known_targets=["Listeria monocytogenes"]), LISTERIA, DesiredBehavior()
        )
        unknown, _ = score_promise(make_candidate(), LISTERIA, DesiredBehavior())
        assert active > unknown

    def test_reported_inactivity_scores_lowest(self):
        inactive, rationale = score_promise(
            make_candidate(known_non_targets=["Listeria monocytogenes"]),
            LISTERIA,
            DesiredBehavior(),
        )
        unknown, _ = score_promise(make_candidate(), LISTERIA, DesiredBehavior())
        assert inactive < unknown
        assert any("INACTIVE" in r for r in rationale)

    def test_genus_wildcard_matches_species(self):
        score, rationale = score_promise(
            make_candidate(known_targets=["Listeria spp."]), LISTERIA, DesiredBehavior()
        )
        assert any("Reported active" in r for r in rationale)
        assert score > 0.6

    def test_different_species_in_same_genus_do_not_match(self):
        """Bacteriocin spectra are species-specific; L. innocua is not L. monocytogenes."""
        _, rationale = score_promise(
            make_candidate(known_targets=["Listeria innocua"]), LISTERIA, DesiredBehavior()
        )
        assert any("No reported activity data" in r for r in rationale)

    def test_conflicting_reports_land_in_the_middle(self):
        _, rationale = score_promise(
            make_candidate(
                known_targets=["Listeria monocytogenes"],
                known_non_targets=["Listeria monocytogenes"],
            ),
            LISTERIA,
            DesiredBehavior(),
        )
        assert any("conflicting" in r for r in rationale)

    def test_known_resistance_in_target_is_penalised(self):
        candidate = make_candidate(
            known_targets=["Listeria monocytogenes"], resistance=["Man-PTS receptor loss"]
        )
        plain, _ = score_promise(candidate, LISTERIA, DesiredBehavior())
        resistant_target = CandidateTarget(
            organism="Listeria monocytogenes",
            gram="positive",
            known_resistance_factors=["Man-PTS receptor loss"],
        )
        penalised, rationale = score_promise(candidate, resistant_target, DesiredBehavior())
        assert penalised < plain
        assert any("resistance factor" in r for r in rationale)

    def test_gram_negative_without_uptake_route_is_penalised(self):
        candidate = make_candidate(known_targets=["Escherichia coli"])
        positive_score, _ = score_promise(candidate, LISTERIA, DesiredBehavior())
        negative_score, rationale = score_promise(candidate, ECOLI, DesiredBehavior())
        assert negative_score < positive_score
        assert any("Gram-negative" in r for r in rationale)

    def test_gram_positive_target_penalises_an_outer_membrane_uptake_route(self):
        """A Gram-positive cell has no outer membrane, so FhuA-dependent uptake
        cannot happen at all -- a harsher mismatch than poor permeability."""
        candidate = make_candidate(
            sequence=MICROCIN,
            receptor="FhuA (uptake), RNA polymerase",
            bacteriocin_class="lasso_peptide",
        )
        no_receptor = make_candidate(sequence=MICROCIN, bacteriocin_class="lasso_peptide")
        penalised, rationale = score_promise(candidate, LISTERIA, DesiredBehavior())
        assert penalised < score_promise(no_receptor, LISTERIA, DesiredBehavior())[0]
        assert any("does not possess" in r for r in rationale)

    def test_gram_negative_with_uptake_route_is_not_penalised(self):
        candidate = make_candidate(
            sequence=MICROCIN,
            known_targets=["Escherichia coli"],
            receptor="FhuA (uptake), RNA polymerase",
            bacteriocin_class="lasso_peptide",
        )
        _, rationale = score_promise(candidate, ECOLI, DesiredBehavior())
        assert not any("Gram-negative target and no known" in r for r in rationale)


class TestNovelty:
    def test_untested_campaign_is_fully_novel(self):
        score, _ = score_novelty(make_candidate(), [], set())
        assert score == 1.0

    def test_already_tested_candidate_has_zero_novelty(self):
        candidate = make_candidate(cid="cand_x")
        score, rationale = score_novelty(candidate, [PEDIOCIN], {"cand_x"})
        assert score == 0.0
        assert any("Already tested" in r for r in rationale)

    def test_similar_sequence_is_less_novel_than_unrelated_one(self):
        similar, _ = score_novelty(make_candidate(sequence=LEUCOCIN), [PEDIOCIN], set())
        unrelated, _ = score_novelty(make_candidate(sequence=MICROCIN), [PEDIOCIN], set())
        assert similar < unrelated


class TestUncertainty:
    def test_well_characterised_candidate_has_low_uncertainty(self):
        score, _ = score_uncertainty(
            make_candidate(
                known_targets=["Listeria monocytogenes"],
                stability={"ph_stable_range": [2.0, 9.0]},
                receptor="Man-PTS",
            )
        )
        assert score < 0.3

    def test_bare_candidate_has_high_uncertainty(self):
        score, _ = score_uncertainty(
            CandidateProposal(candidate_id="cand_bare", origin="generated", name="unknown peptide")
        )
        assert score > 0.7

    def test_generated_origin_adds_uncertainty(self):
        kwargs = dict(known_targets=["Listeria monocytogenes"], receptor="Man-PTS")
        known, _ = score_uncertainty(make_candidate(origin="literature", **kwargs))
        generated, _ = score_uncertainty(make_candidate(origin="generated", **kwargs))
        assert generated > known

    def test_unverified_sequence_adds_uncertainty(self):
        verified, _ = score_uncertainty(make_candidate(verified=True))
        unverified, _ = score_uncertainty(make_candidate(verified=False))
        assert unverified > verified


class TestInformationGain:
    def test_peaks_at_maximum_outcome_uncertainty(self):
        """A coin-flip outcome is the most informative experiment."""
        uncertain, _ = score_information_gain(promise=0.5, uncertainty=0.5, novelty=0.5)
        likely, _ = score_information_gain(promise=0.95, uncertainty=0.5, novelty=0.5)
        unlikely, _ = score_information_gain(promise=0.05, uncertainty=0.5, novelty=0.5)
        assert uncertain > likely
        assert uncertain > unlikely

    def test_is_symmetric_about_one_half(self):
        high, _ = score_information_gain(0.8, 0.5, 0.5)
        low, _ = score_information_gain(0.2, 0.5, 0.5)
        assert high == pytest.approx(low, abs=1e-9)

    def test_novelty_increases_gain_at_fixed_promise(self):
        novel, _ = score_information_gain(0.5, 0.5, novelty=1.0)
        stale, _ = score_information_gain(0.5, 0.5, novelty=0.0)
        assert novel > stale

    def test_near_certain_outcome_is_flagged_as_confirmatory(self):
        _, rationale = score_information_gain(0.97, 0.1, 0.1)
        assert any("confirmatory" in r for r in rationale)


class TestHypothesisDiscrimination:
    def test_zero_without_open_hypotheses(self):
        score, rationale = score_hypothesis_discrimination(make_candidate(), [])
        assert score == 0.0
        assert any("No open competing" in r for r in rationale)

    def test_candidate_splitting_hypotheses_beats_one_satisfying_all(self):
        """The decisive experiment is the one some hypotheses must lose."""
        hypotheses = [
            CompetingHypothesis(
                hypothesis_id="hyp_low",
                statement="Activity needs low net charge",
                discriminating_feature="net_charge",
                favourable_range=(-5.0, 1.0),
            ),
            CompetingHypothesis(
                hypothesis_id="hyp_high",
                statement="Activity needs high net charge",
                discriminating_feature="net_charge",
                favourable_range=(3.0, 12.0),
            ),
        ]
        # Pediocin is cationic: satisfies hyp_high, violates hyp_low -> a 1/2 split.
        splitter, rationale = score_hypothesis_discrimination(make_candidate(), hypotheses)
        assert splitter == pytest.approx(1.0)
        assert any("Splits 1/2" in r for r in rationale)

        # Both hypotheses favourable -> cannot distinguish them.
        agreeing = [
            CompetingHypothesis(
                hypothesis_id=f"hyp_{i}",
                statement="Any charge works",
                discriminating_feature="net_charge",
                favourable_range=(-20.0, 20.0),
            )
            for i in range(2)
        ]
        assert score_hypothesis_discrimination(make_candidate(), agreeing)[0] < splitter

    def test_closed_hypotheses_are_ignored(self):
        closed = [
            CompetingHypothesis(
                hypothesis_id="hyp_done",
                statement="Settled",
                discriminating_feature="net_charge",
                favourable_range=(0.0, 1.0),
                status="supported",
            )
        ]
        assert score_hypothesis_discrimination(make_candidate(), closed)[0] == 0.0

    def test_hypotheses_without_a_feature_report_the_gap(self):
        vague = [CompetingHypothesis(hypothesis_id="hyp_vague", statement="Something happens")]
        score, rationale = score_hypothesis_discrimination(make_candidate(), vague)
        assert score == 0.0
        assert any("none specify a discriminating_feature" in r for r in rationale)


class TestConditionFit:
    def test_full_ph_coverage_beats_partial(self):
        wide, _ = score_condition_fit(
            make_candidate(stability={"ph_stable_range": [2.0, 9.0]}),
            DesiredBehavior(ph_range=(6.0, 7.5)),
        )
        narrow, rationale = score_condition_fit(
            make_candidate(stability={"ph_stable_range": [2.0, 7.0]}),
            DesiredBehavior(ph_range=(6.0, 7.5)),
        )
        assert wide > narrow
        assert any("covers only" in r for r in rationale)

    def test_no_overlap_scores_lowest(self):
        score, rationale = score_condition_fit(
            make_candidate(stability={"ph_stable_range": [2.0, 4.0]}),
            DesiredBehavior(ph_range=(6.0, 7.5)),
        )
        assert score == pytest.approx(0.35, abs=1e-6)
        assert any("does not overlap" in r for r in rationale)

    def test_heat_labile_candidate_penalised_at_high_temperature(self):
        labile, rationale = score_condition_fit(
            make_candidate(stability={"thermostable": False}), DesiredBehavior(temperature_c=60.0)
        )
        stable, _ = score_condition_fit(
            make_candidate(stability={"thermostable": True}), DesiredBehavior(temperature_c=60.0)
        )
        assert labile < stable
        assert any("not thermostable" in r for r in rationale)

    def test_high_cell_density_penalises_sequestering_candidate(self):
        """Cell density is a real variable: dense cultures raise the dose needed."""
        dense = DesiredBehavior(target_cell_density=1e8)
        sequestering, rationale = score_condition_fit(
            make_candidate(sensitivity=["binds and is sequestered by food lipids"]), dense
        )
        clean, _ = score_condition_fit(make_candidate(sensitivity=["protease-sensitive"]), dense)
        assert sequestering < clean
        assert any("effective dose requirement" in r for r in rationale)

    def test_high_density_always_prompts_a_concentration_sweep(self):
        _, rationale = score_condition_fit(
            make_candidate(), DesiredBehavior(target_cell_density=5e8)
        )
        assert any("sweep concentration" in r for r in rationale)


class TestScoreCandidate:
    def _score(self, candidate, **kwargs):
        return score_candidate(
            candidate,
            target=kwargs.pop("target", LISTERIA),
            desired=kwargs.pop("desired", DesiredBehavior(ph_range=(6.0, 7.5))),
            constraints=kwargs.pop("constraints", CandidateConstraints()),
            tested_sequences=kwargs.pop("tested_sequences", []),
            tested_ids=kwargs.pop("tested_ids", set()),
            competing_hypotheses=kwargs.pop("competing_hypotheses", []),
        )

    def test_all_components_are_within_range(self):
        score = self._score(make_candidate(known_targets=["Listeria monocytogenes"]))
        for field in (
            "promise",
            "novelty",
            "uncertainty",
            "information_gain",
            "hypothesis_discrimination",
            "condition_fit",
            "total",
        ):
            assert 0.0 <= getattr(score, field) <= 1.0, field

    def test_is_deterministic(self):
        candidate = make_candidate(known_targets=["Listeria monocytogenes"])
        assert self._score(candidate).model_dump() == self._score(candidate).model_dump()

    def test_rationale_is_populated(self):
        assert self._score(make_candidate()).rationale

    def test_weights_change_the_ordering(self):
        """A promise-only weighting must rank differently from an exploration weighting."""
        safe = make_candidate(
            "safe",
            known_targets=["Listeria monocytogenes"],
            stability={"ph_stable_range": [2.0, 9.0]},
            receptor="Man-PTS",
        )
        unknown = make_candidate("unknown", sequence=MICROCIN, bacteriocin_class=None)

        promise_only = CandidateConstraints(
            scoring_weights=ScoringWeights(
                promise=1.0,
                novelty=0.0,
                uncertainty=0.0,
                information_gain=0.0,
                hypothesis_discrimination=0.0,
                condition_fit=0.0,
            )
        )
        explore_only = CandidateConstraints(
            scoring_weights=ScoringWeights(
                promise=0.0,
                novelty=0.0,
                uncertainty=1.0,
                information_gain=0.0,
                hypothesis_discrimination=0.0,
                condition_fit=0.0,
            )
        )
        assert self._score(safe, constraints=promise_only).total > self._score(
            unknown, constraints=promise_only
        ).total
        assert self._score(unknown, constraints=explore_only).total > self._score(
            safe, constraints=explore_only
        ).total


class TestExperimentalRedundancy:
    """Redundancy must track family and mechanism, not just sequence identity."""

    def test_same_candidate_is_fully_redundant(self):
        candidate = make_candidate("a", receptor="Man-PTS")
        assert experimental_redundancy(candidate, candidate) == pytest.approx(1.0)

    def test_same_class_counts_as_redundant_despite_low_sequence_identity(self):
        """The failure this function exists to fix: two class IIa peptides share
        only ~9% of their 3-mers, yet testing both answers the same question."""
        pediocin = make_candidate("pediocin", sequence=PEDIOCIN, bacteriocin_class="class_iia")
        leucocin = make_candidate("leucocin", sequence=LEUCOCIN, bacteriocin_class="class_iia")

        from bacteriocin_discovery.candidate_agent.features import sequence_similarity

        assert sequence_similarity(PEDIOCIN, LEUCOCIN) < 0.2
        assert experimental_redundancy(pediocin, leucocin) >= 0.6

    def test_different_class_and_receptor_is_not_redundant(self):
        pediocin = make_candidate(
            "pediocin", sequence=PEDIOCIN, bacteriocin_class="class_iia", receptor="Man-PTS"
        )
        microcin = make_candidate(
            "microcin", sequence=MICROCIN, bacteriocin_class="lasso_peptide", receptor="FhuA"
        )
        assert experimental_redundancy(pediocin, microcin) < 0.2

    def test_shared_receptor_counts_even_across_classes(self):
        a = make_candidate("a", sequence=PEDIOCIN, bacteriocin_class="class_iia", receptor="Man-PTS")
        b = make_candidate("b", sequence=MICROCIN, bacteriocin_class="class_iid", receptor="Man-PTS")
        assert experimental_redundancy(a, b) >= 0.5

    def test_missing_metadata_falls_back_to_sequence_only(self):
        a = make_candidate("a", sequence=PEDIOCIN, bacteriocin_class=None)
        b = make_candidate("b", sequence=MICROCIN, bacteriocin_class=None)
        assert experimental_redundancy(a, b) == pytest.approx(0.0)

    def test_is_symmetric(self):
        a = make_candidate("a", sequence=PEDIOCIN, receptor="Man-PTS")
        b = make_candidate("b", sequence=LEUCOCIN, bacteriocin_class="class_iia")
        assert experimental_redundancy(a, b) == experimental_redundancy(b, a)


class TestSelectDiverse:
    def _with_score(self, candidate: CandidateProposal, total: float) -> CandidateProposal:
        candidate.score = ScoreBreakdown(
            promise=total,
            novelty=total,
            uncertainty=total,
            information_gain=total,
            hypothesis_discrimination=total,
            condition_fit=total,
            total=total,
        )
        return candidate

    def test_returns_empty_for_zero_k(self):
        assert select_diverse([make_candidate()], k=0, diversity_weight=0.3) == []

    def test_zero_diversity_weight_is_a_plain_sort(self):
        low = self._with_score(make_candidate("low", sequence=PEDIOCIN, cid="cand_a"), 0.3)
        high = self._with_score(make_candidate("high", sequence=LEUCOCIN, cid="cand_b"), 0.9)
        assert [c.name for c in select_diverse([low, high], k=2, diversity_weight=0.0)] == [
            "high",
            "low",
        ]

    def test_diversity_prefers_a_different_family_over_a_near_duplicate(self):
        """This is the test that matters: avoid ten variations on one peptide."""
        best = self._with_score(
            make_candidate(
                "pediocin", sequence=PEDIOCIN, cid="cand_a", bacteriocin_class="class_iia"
            ),
            0.90,
        )
        near_duplicate = self._with_score(
            make_candidate(
                "leucocin", sequence=LEUCOCIN, cid="cand_b", bacteriocin_class="class_iia"
            ),
            0.88,
        )
        different = self._with_score(
            make_candidate(
                "microcin", sequence=MICROCIN, cid="cand_c", bacteriocin_class="lasso_peptide"
            ),
            0.70,
        )

        by_score = select_diverse([best, near_duplicate, different], k=2, diversity_weight=0.0)
        assert [c.name for c in by_score] == ["pediocin", "leucocin"]

        diverse = select_diverse([best, near_duplicate, different], k=2, diversity_weight=0.6)
        assert [c.name for c in diverse] == ["pediocin", "microcin"]

    def test_never_exceeds_k(self):
        pool = [
            self._with_score(make_candidate(f"c{i}", cid=f"cand_{i}"), 0.5 + i / 100)
            for i in range(6)
        ]
        assert len(select_diverse(pool, k=3, diversity_weight=0.4)) == 3

    def test_is_deterministic_across_runs(self):
        pool = [
            self._with_score(
                make_candidate(f"c{i}", sequence=seq, cid=f"cand_{i}"), 0.8 - i / 100
            )
            for i, seq in enumerate([PEDIOCIN, LEUCOCIN, MICROCIN])
        ]
        first = [c.candidate_id for c in select_diverse(pool, k=3, diversity_weight=0.5)]
        second = [c.candidate_id for c in select_diverse(pool, k=3, diversity_weight=0.5)]
        assert first == second

    def test_rejects_invalid_diversity_weight(self):
        with pytest.raises(ValueError, match="diversity_weight"):
            select_diverse([make_candidate()], k=1, diversity_weight=1.5)


class TestTestedHistory:
    def test_extracts_candidate_ids(self):
        tested, _ = read_tested_history([{"candidate_id": "cand_a"}, {"candidate_id": "cand_b"}])
        assert tested == {"cand_a", "cand_b"}

    def test_skips_malformed_entries_without_raising(self):
        """A single bad result record must not stop the loop."""
        tested, _ = read_tested_history(
            ["not a dict", {}, {"candidate_id": None}, {"candidate_id": "cand_ok"}]
        )
        assert tested == {"cand_ok"}
