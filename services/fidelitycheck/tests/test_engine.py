"""Property tests for the statistical engines.

These pin behaviour that the fidelity score depends on: identical cohorts
must score at the ceiling, disjoint cohorts must score at the floor, and the
correlation check must react to dependency structure that the marginal tests
cannot see.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engine.correlation import compare_correlations
from app.engine.features import FeatureKind, align_schema, classify_feature
from app.engine.js_divergence import js_divergence_feature
from app.engine.ks_test import ks_test_feature
from app.engine.report_builder import build_report, grade_for

RNG = np.random.default_rng(20260816)


def cohort(n: int = 2000, age_shift: float = 0.0, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    age = rng.normal(62 + age_shift, 11, n).clip(18, 95)
    # Creatinine tracks age in the real population. The correlation test is
    # the only one of the three that notices when a generator drops this.
    creatinine = 0.6 + 0.012 * age + rng.normal(0, 0.12, n)
    return pd.DataFrame(
        {
            "age": age,
            "creatinine": creatinine,
            "hba1c": rng.gamma(shape=9.0, scale=0.85, size=n),
            "sex": rng.choice(["female", "male"], n, p=[0.52, 0.48]),
            "ecog": rng.choice([0, 1, 2], n, p=[0.5, 0.35, 0.15]),
        }
    )


class TestFeatureTyping:
    def test_continuous_column_is_numeric(self):
        frame = cohort(200)
        assert classify_feature(frame["age"], frame["age"]) is FeatureKind.NUMERIC

    def test_low_cardinality_integer_is_categorical(self):
        frame = cohort(200)
        assert classify_feature(frame["ecog"], frame["ecog"]) is FeatureKind.CATEGORICAL

    def test_numeric_strings_are_not_treated_as_categories(self):
        frame = cohort(200)
        as_text = frame["age"].astype(str)
        assert classify_feature(frame["age"], as_text) is FeatureKind.NUMERIC

    def test_alignment_reports_both_sides(self):
        real = pd.DataFrame({"a": [1], "b": [2]})
        synthetic = pd.DataFrame({"b": [2], "c": [3]})
        alignment = align_schema(real, synthetic)
        assert alignment.shared == ["b"]
        assert alignment.real_only == ["a"]
        assert alignment.synthetic_only == ["c"]
        assert alignment.coverage == pytest.approx(1 / 3)


class TestKSTest:
    def test_identical_samples_give_zero_statistic(self):
        frame = cohort(1000)
        result = ks_test_feature("age", frame["age"], frame["age"].copy())
        assert result.evaluated
        assert result.statistic == pytest.approx(0.0, abs=1e-12)
        assert result.score == pytest.approx(1.0)
        assert not result.distributions_differ

    def test_shifted_distribution_is_detected(self):
        a = cohort(2000, seed=1)["age"]
        b = cohort(2000, age_shift=15.0, seed=2)["age"]
        result = ks_test_feature("age", a, b)
        assert result.statistic > 0.4
        assert result.p_value < 0.001
        assert result.distributions_differ

    def test_disjoint_support_saturates_the_statistic(self):
        a = pd.Series(np.linspace(0, 1, 500))
        b = pd.Series(np.linspace(100, 101, 500))
        result = ks_test_feature("x", a, b)
        assert result.statistic == pytest.approx(1.0)
        assert result.score == pytest.approx(0.0)

    def test_categorical_uses_total_variation_distance(self):
        real = pd.Series(["a"] * 80 + ["b"] * 20)
        synthetic = pd.Series(["a"] * 20 + ["b"] * 80)
        result = ks_test_feature("arm", real, synthetic)
        assert result.method == "total_variation_distance"
        assert result.statistic == pytest.approx(0.6, abs=1e-9)
        assert result.score == pytest.approx(0.4, abs=1e-9)

    def test_too_few_rows_is_reported_not_scored(self):
        result = ks_test_feature("age", pd.Series([1.0, 2.0]), pd.Series([1.0, 2.0]))
        assert not result.evaluated
        assert result.note is not None


class TestJensenShannon:
    def test_identical_samples_have_zero_divergence(self):
        frame = cohort(1000)
        result = js_divergence_feature("hba1c", frame["hba1c"], frame["hba1c"].copy())
        assert result.evaluated
        assert result.divergence == pytest.approx(0.0, abs=1e-12)
        assert result.score == pytest.approx(1.0)

    def test_disjoint_support_reaches_one_bit(self):
        a = pd.Series(np.linspace(0, 1, 500))
        b = pd.Series(np.linspace(100, 101, 500))
        result = js_divergence_feature("x", a, b)
        assert result.divergence == pytest.approx(1.0, abs=1e-6)
        assert result.score == pytest.approx(0.0, abs=1e-6)

    def test_divergence_is_bounded(self):
        for shift in (0.0, 2.0, 10.0, 40.0):
            a = cohort(800, seed=3)["age"]
            b = cohort(800, age_shift=shift, seed=4)["age"]
            result = js_divergence_feature("age", a, b)
            assert 0.0 <= result.divergence <= 1.0

    def test_bins_are_shared_between_the_two_samples(self):
        a = pd.Series(RNG.normal(0, 1, 600))
        b = pd.Series(RNG.normal(5, 1, 600))
        result = js_divergence_feature("x", a, b)
        assert len(result.real_density) == len(result.synthetic_density)
        assert sum(result.real_density) == pytest.approx(1.0, abs=1e-6)
        assert sum(result.synthetic_density) == pytest.approx(1.0, abs=1e-6)

    def test_categorical_support_is_the_union_of_levels(self):
        real = pd.Series(["a"] * 50 + ["b"] * 50)
        synthetic = pd.Series(["a"] * 50 + ["c"] * 50)
        result = js_divergence_feature("site", real, synthetic)
        assert result.support == ["a", "b", "c"]
        assert 0.0 < result.divergence < 1.0


class TestCorrelation:
    def test_same_cohort_has_no_delta(self):
        frame = cohort(1500)
        comparison = compare_correlations(frame, frame.copy())
        assert comparison.evaluated
        assert comparison.mean_absolute_delta == pytest.approx(0.0, abs=1e-12)
        assert comparison.score == pytest.approx(1.0)

    def test_broken_dependency_is_caught_when_marginals_match(self):
        real = cohort(3000, seed=11)
        # Shuffling one column preserves its marginal exactly and destroys
        # every correlation it participated in. This is the failure mode the
        # per feature tests are structurally unable to see.
        shuffled = real.copy()
        shuffled["creatinine"] = (
            shuffled["creatinine"].sample(frac=1.0, random_state=5).to_numpy()
        )

        ks = ks_test_feature("creatinine", real["creatinine"], shuffled["creatinine"])
        assert ks.statistic == pytest.approx(0.0, abs=1e-12)

        comparison = compare_correlations(real, shuffled)
        assert comparison.mean_absolute_delta > 0.05
        assert comparison.score < 1.0
        worst = comparison.worst_pairs[0]
        assert "creatinine" in (worst.feature_a, worst.feature_b)

    def test_one_destroyed_relationship_is_not_averaged_away(self):
        """The regression this scoring change exists to prevent.

        With many well behaved feature pairs around it, a single correlation
        going from strongly negative to zero used to leave the dependency
        score above 98 percent, because the mean absolute delta over a one
        hot expanded matrix dilutes it. The score has to react.
        """
        rng = np.random.default_rng(77)
        n = 4000
        age = rng.normal(62, 11, n)
        frame = pd.DataFrame({"age": age, "egfr": (140 - age) + rng.normal(0, 8, n)})
        # Padding features that both cohorts reproduce perfectly. These are
        # what dilute the mean.
        for i in range(10):
            column = rng.normal(0, 1, n)
            frame[f"noise_{i}"] = column

        broken = frame.copy()
        broken["egfr"] = rng.permutation(broken["egfr"].to_numpy())

        comparison = compare_correlations(frame, broken)
        assert comparison.max_absolute_delta > 0.5
        # The mean stays small, which is exactly why it is not the summary
        # the score is built from.
        assert comparison.mean_absolute_delta < 0.15
        assert comparison.score < 0.85

    def test_rms_is_reported_alongside_the_mean(self):
        frame = cohort(1000)
        comparison = compare_correlations(frame, frame.copy())
        assert comparison.rms_delta == pytest.approx(0.0, abs=1e-12)
        assert comparison.score == pytest.approx(1.0)

    def test_constant_columns_do_not_raise(self):
        real = cohort(300)
        real["flag"] = 1
        synthetic = cohort(300, seed=9)
        synthetic["flag"] = 1
        comparison = compare_correlations(real, synthetic)
        assert comparison.evaluated
        assert "flag" not in comparison.matrix_features


class TestReportBuilder:
    def test_identical_cohorts_score_at_the_ceiling(self):
        frame = cohort(1500)
        report = build_report(frame, frame.copy())
        assert report.overall_fidelity == pytest.approx(100.0, abs=1e-6)
        assert report.grade == "pass"

    def test_a_good_generator_scores_high(self):
        real = cohort(3000, seed=21)
        synthetic = cohort(3000, seed=22)
        report = build_report(real, synthetic)
        assert report.overall_fidelity > 90.0
        assert report.grade == "pass"

    def test_a_bad_generator_scores_low(self):
        real = cohort(2000, seed=31)
        synthetic = pd.DataFrame(
            {
                "age": RNG.uniform(18, 95, 2000),
                "creatinine": RNG.uniform(0, 6, 2000),
                "hba1c": RNG.uniform(0, 20, 2000),
                "sex": RNG.choice(["female", "male"], 2000, p=[0.1, 0.9]),
                "ecog": RNG.choice([0, 1, 2], 2000, p=[0.1, 0.1, 0.8]),
            }
        )
        report = build_report(real, synthetic)
        assert report.overall_fidelity < 80.0
        assert report.grade in {"borderline", "fail"}

    def test_missing_columns_reduce_the_score_through_coverage(self):
        real = cohort(1200, seed=41)
        partial = real.drop(columns=["hba1c", "ecog"]).copy()
        report = build_report(real, partial)
        assert report.schema["coverage"] == pytest.approx(3 / 5)
        assert report.overall_fidelity < report.raw_fidelity
        assert any("missing from the synthetic" in w for w in report.warnings)

    def test_previews_are_ranked_worst_first(self):
        real = cohort(1500, seed=51)
        synthetic = cohort(1500, seed=52)
        synthetic["hba1c"] = synthetic["hba1c"] * 3.0
        report = build_report(real, synthetic, preview_features=3)
        assert len(report.distribution_previews) == 3
        assert report.distribution_previews[0].feature == "hba1c"
        fidelities = [p.fidelity for p in report.distribution_previews]
        assert fidelities == sorted(fidelities)

    def test_no_shared_columns_fails_cleanly(self):
        real = pd.DataFrame({"a": range(50)})
        synthetic = pd.DataFrame({"b": range(50)})
        report = build_report(real, synthetic)
        assert report.overall_fidelity == 0.0
        assert report.grade == "fail"
        assert report.features == []

    def test_report_serialises_to_plain_types(self):
        real = cohort(400, seed=61)
        synthetic = cohort(400, seed=62)
        body = build_report(real, synthetic).as_dict()
        import json

        json.dumps(body)  # raises if a numpy scalar leaked into the payload

    @pytest.mark.parametrize(
        "score,expected",
        [(100.0, "pass"), (90.0, "pass"), (89.9, "borderline"), (70.0, "borderline"), (69.9, "fail")],
    )
    def test_grade_thresholds(self, score, expected):
        assert grade_for(score) == expected
