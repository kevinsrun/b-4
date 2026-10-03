"""Comparison against previous experiments: controlled series and uncertainty-aware verdicts."""

from __future__ import annotations

import math

from bacteriocin_discovery.contract import ExperimentResult
from bacteriocin_discovery.result_analysis_agent.comparison import Point, classify, compare
from result_analysis_helpers import make_result


def pts(*ys, sigma=0.03, xs=None):
    xs = xs or list(range(len(ys)))
    return [
        Point(f"r{i}", f"e{i}", float(x), 10.0**x, y, sigma, False)
        for i, (x, y) in enumerate(zip(xs, ys, strict=True))
    ]


class TestClassify:
    def test_large_drop_is_negative_with_per_log_effect_size(self):
        v = classify("target_cell_density", pts(0.86, 0.43, xs=[6, 8]))
        assert v.relationship == "negative"
        assert math.isclose(v.delta, -0.43)
        assert math.isclose(v.effect_size, -0.215)  # per log10 unit, 2 logs apart
        assert abs(v.z) > 5

    def test_rise_is_positive(self):
        assert classify("bacteriocin_concentration", pts(0.2, 0.7)).relationship == "positive"

    def test_tiny_difference_is_none_not_a_trend(self):
        assert classify("ph", pts(0.50, 0.52)).relationship == "none"

    def test_big_difference_inside_noise_is_unresolved_not_a_finding(self):
        v = classify("ph", pts(0.40, 0.55, sigma=0.15))
        assert v.relationship == "unresolved" and abs(v.z) < 2

    def test_single_point_is_unresolved(self):
        v = classify("ph", pts(0.5))
        assert v.relationship == "unresolved" and v.effect_size is None

    def test_non_monotonic_three_point_series(self):
        assert classify("ph", pts(0.3, 0.8, 0.35)).relationship == "non_monotonic"

    def test_monotonic_with_plateau_is_flagged_as_saturation(self):
        v = classify("bacteriocin_concentration", pts(0.1, 0.6, 0.62 + 0.0, xs=[0, 1, 2]))
        assert v.relationship == "positive" and v.plateau

    def test_steady_climb_is_not_a_plateau(self):
        assert not classify("bacteriocin_concentration", pts(0.1, 0.4, 0.7)).plateau


class TestControlledSeries:
    def test_only_single_variable_differences_form_a_series(self):
        cur = ExperimentResult.model_validate(make_result("cur", 0.86, density=1e6))
        outcome = compare(
            cur,
            [
                make_result("same_but_density", 0.43, density=1e8),  # controlled for density
                make_result(
                    "density_and_ph", 0.20, density=1e8, ph=5.0
                ),  # confounded: two variables differ
            ],
        )
        assert set(outcome.verdicts) == {"target_cell_density"}
        assert [p.result_id for p in outcome.verdicts["target_cell_density"].points] == [
            "cur",
            "same_but_density",
        ] or {p.result_id for p in outcome.verdicts["target_cell_density"].points} == {
            "cur",
            "same_but_density",
        }

    def test_other_candidates_are_not_evidence_about_this_one(self):
        cur = ExperimentResult.model_validate(make_result("cur", 0.86))
        outcome = compare(cur, [make_result("other", 0.2, density=1e8, candidate="cand_other")])
        assert outcome.verdicts == {} and outcome.usable_prior == []

    def test_different_assay_domain_is_excluded_and_reported(self):
        cur = ExperimentResult.model_validate(make_result("cur", 0.86))
        outcome = compare(cur, [make_result("viv", 0.2, density=1e8, assay_domain="in_vivo")])
        assert outcome.verdicts == {} and any("assay_domain" in s for s in outcome.skipped)

    def test_unit_mismatch_excludes_the_comparison(self):
        cur = ExperimentResult.model_validate(make_result("cur", 0.86, concentration_unit="ug/mL"))
        outcome = compare(cur, [make_result("nm", 0.4, density=1e8, concentration_unit="nM")])
        assert outcome.verdicts == {} and outcome.unit_mismatches

    def test_malformed_prior_record_is_skipped_not_fatal(self):
        cur = ExperimentResult.model_validate(make_result("cur", 0.86))
        outcome = compare(cur, [{"garbage": True}, make_result("good", 0.43, density=1e8)])
        assert "target_cell_density" in outcome.verdicts
        assert any("did not validate" in s for s in outcome.skipped)

    def test_duplicates_and_the_current_result_are_ignored(self):
        cur = ExperimentResult.model_validate(make_result("cur", 0.86))
        outcome = compare(
            cur,
            [
                make_result("cur", 0.1, density=1e9),
                make_result("p", 0.43, density=1e8),
                make_result("p", 0.0, density=1e9),
            ],
        )
        assert [r.result_id for r in outcome.usable_prior] == ["p"]

    def test_prior_only_verdict_excludes_the_current_result(self):
        cur = ExperimentResult.model_validate(make_result("cur", 0.9, density=1e7))
        prior = [make_result("a", 0.8, density=1e5), make_result("b", 0.3, density=1e9)]
        outcome = compare(cur, prior)
        assert {p.result_id for p in outcome.prior_only["target_cell_density"].points} == {"a", "b"}

    def test_missing_uncertainty_is_recorded_as_assumed(self):
        cur = ExperimentResult.model_validate(make_result("cur", 0.86, sigma=None))
        outcome = compare(cur, [make_result("p", 0.43, density=1e8)])
        assert "cur" in outcome.defaulted_sigma_ids
