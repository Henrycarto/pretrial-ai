"""Tests for the SyntheCore engine modules.

These cover the parts of SyntheCore that are real: seed cleaning, criteria
screening, and the attrition funnel. The generator itself is a stub, so what
is asserted about it is the contract the private engine has to satisfy, not
the quality of its output.

Redis and Celery are not touched here. The engine modules are importable
without a broker on purpose, which is what makes them testable in CI without
a service container.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engine.criteria_filter import (
    Criterion,
    CriterionKind,
    Operator,
    apply_criteria,
    criteria_from_payload,
    estimate_oversample_factor,
)
from app.engine.ctgan_pipeline import BootstrapCohortGenerator, load_generator
from app.engine.seed_processor import (
    normalise_column_name,
    process_seed,
    reference_cohort,
)


class TestSeedProcessor:
    def test_column_names_are_normalised(self):
        assert normalise_column_name("Patient Age (yrs)") == "patient_age_yrs"
        assert normalise_column_name("  eGFR  ") == "egfr"
        assert normalise_column_name("") == "unnamed"

    def test_mixed_case_lab_abbreviations_survive_normalisation(self):
        # Two sponsors spelling the same lab value differently have to land on
        # one feature name, otherwise the fidelity report compares a column
        # against nothing.
        for spelling in ("HbA1c", "HBA1C", "hba1c", "HbA1c%"):
            assert normalise_column_name(spelling) == "hba1c"

    def test_direct_identifiers_are_removed(self):
        rows = [
            {"MRN": f"A{i}", "Patient Name": "x y", "age": 60 + i % 20, "sex": "female"}
            for i in range(200)
        ]
        frame, profile = process_seed(rows=rows)
        assert "mrn" not in frame.columns
        assert "patient_name" not in frame.columns
        assert set(profile.dropped_identifiers) == {"mrn", "patient_name"}
        assert "age" in frame.columns

    def test_date_of_birth_is_treated_as_an_identifier(self):
        rows = [{"dob": "1961-04-02", "age": 60 + i % 10} for i in range(120)]
        frame, profile = process_seed(rows=rows)
        assert "dob" not in frame.columns
        assert "dob" in profile.dropped_identifiers

    def test_numeric_strings_are_coerced(self):
        rows = [{"hba1c": str(6.0 + i % 30 / 10), "sex": "male"} for i in range(150)]
        frame, _ = process_seed(rows=rows)
        assert pd.api.types.is_numeric_dtype(frame["hba1c"])

    def test_constant_and_empty_columns_are_dropped(self):
        rows = [
            {"age": 50 + i % 30, "study": "TRIAL-1", "empty": None, "bmi": 25 + i % 10}
            for i in range(150)
        ]
        frame, profile = process_seed(rows=rows)
        assert "study" not in frame.columns
        assert "empty" not in frame.columns
        assert any("single value" in w for w in profile.warnings)

    def test_small_seed_raises_a_warning_not_an_error(self):
        rows = [{"age": 50 + i, "bmi": 20 + i} for i in range(20)]
        _, profile = process_seed(rows=rows)
        assert any("sampling noise" in w for w in profile.warnings)

    def test_seed_with_no_modellable_features_fails(self):
        rows = [{"mrn": f"A{i}"} for i in range(50)]
        with pytest.raises(ValueError, match="no modellable features"):
            process_seed(rows=rows)

    def test_reference_cohort_has_dependency_structure(self):
        frame = reference_cohort(3000)
        assert len(frame) == 3000
        # eGFR is modelled as falling with age. If that link is ever lost the
        # correlation half of the fidelity report stops being demonstrable.
        assert frame["age"].corr(frame["egfr"]) < -0.5


class TestBootstrapGenerator:
    def test_sample_before_fit_is_an_error(self):
        with pytest.raises(RuntimeError):
            BootstrapCohortGenerator().sample(10)

    def test_output_shape_and_columns_match_the_seed(self):
        seed = reference_cohort(1000)
        generator = BootstrapCohortGenerator()
        generator.fit(seed)
        out = generator.sample(2500)
        assert len(out) == 2500
        assert list(out.columns) == list(seed.columns)

    def test_integer_columns_stay_integers_after_jitter(self):
        seed = reference_cohort(800)
        generator = BootstrapCohortGenerator()
        generator.fit(seed)
        out = generator.sample(500)
        assert pd.api.types.is_integer_dtype(out["age"])
        assert pd.api.types.is_integer_dtype(out["systolic_bp"])

    def test_marginals_are_preserved_within_tolerance(self):
        seed = reference_cohort(4000)
        generator = BootstrapCohortGenerator()
        generator.fit(seed)
        out = generator.sample(4000)
        assert abs(out["age"].mean() - seed["age"].mean()) < 1.0
        assert abs(out["hba1c"].std() - seed["hba1c"].std()) < 0.3

    def test_boolean_columns_survive_generation_as_booleans(self):
        # pandas reports bool as a numeric dtype, so an unguarded numeric
        # filter jitters True into 0.97 and destroys the feature. Regression
        # test for exactly that.
        seed = reference_cohort(1000)
        generator = BootstrapCohortGenerator()
        generator.fit(seed)
        out = generator.sample(1000)

        for column in ("on_insulin", "prior_cv_event"):
            assert pd.api.types.is_bool_dtype(out[column]), column
            assert set(out[column].unique()) <= {True, False}

    def test_low_cardinality_codes_are_not_jittered(self):
        seed = reference_cohort(1000)
        generator = BootstrapCohortGenerator()
        generator.fit(seed)
        out = generator.sample(1000)
        # ECOG is a code, not a measurement. 1.03 is not a valid value.
        assert set(out["ecog_status"].unique()) <= {0, 1, 2}

    def test_continuous_columns_are_still_jittered(self):
        seed = reference_cohort(1000)
        generator = BootstrapCohortGenerator()
        generator.fit(seed)
        out = generator.sample(1000)
        # If nothing were perturbed the output would be a pure resample, and
        # every value would appear in the seed.
        assert not set(out["hba1c"].round(6)).issubset(set(seed["hba1c"].round(6)))

    def test_generator_declares_itself_a_stub(self):
        described = BootstrapCohortGenerator().describe()
        assert described["is_stub"] is True
        assert described["privacy_guarantee"] == "none"

    def test_load_generator_returns_the_fallback_without_the_private_package(self):
        generator = load_generator("stub")
        assert generator.is_stub is True

    def test_requesting_ctgan_without_the_private_package_fails_loudly(self):
        # A deployment that asks for CTGAN must never be silently downgraded
        # to the stub. Failing here is the desired behaviour.
        with pytest.raises(RuntimeError, match="not installed"):
            load_generator("ctgan")


class TestCriteriaFilter:
    @pytest.fixture
    def cohort(self) -> pd.DataFrame:
        rng = np.random.default_rng(3)
        n = 2000
        return pd.DataFrame(
            {
                "age": rng.integers(18, 90, n),
                "egfr": rng.normal(70, 20, n).clip(5, 140),
                "hba1c": rng.normal(7.8, 1.3, n).clip(4, 15),
                "sex": rng.choice(["female", "male"], n),
                "prior_cv_event": rng.random(n) < 0.3,
                "ecog_status": rng.choice([0, 1, 2], n),
            }
        )

    def test_inclusion_keeps_matching_rows(self, cohort):
        result = apply_criteria(
            cohort, [Criterion("age", Operator.GTE, 65, CriterionKind.INCLUSION)]
        )
        assert (result.frame["age"] >= 65).all()
        assert result.eligible == len(result.frame)

    def test_exclusion_drops_matching_rows(self, cohort):
        result = apply_criteria(
            cohort,
            [Criterion("prior_cv_event", Operator.IS_TRUE, kind=CriterionKind.EXCLUSION)],
        )
        assert not result.frame["prior_cv_event"].any()

    def test_between_is_inclusive_on_both_ends(self):
        frame = pd.DataFrame({"age": [17, 18, 50, 75, 76]})
        result = apply_criteria(frame, [Criterion("age", Operator.BETWEEN, [18, 75])])
        assert result.frame["age"].tolist() == [18, 50, 75]

    def test_in_operator_is_case_insensitive(self):
        frame = pd.DataFrame({"sex": ["Female", "MALE", "female", "other"]})
        result = apply_criteria(frame, [Criterion("sex", Operator.IN, ["female"])])
        assert len(result.frame) == 2

    def test_truth_tests_work_on_every_flag_representation(self):
        # A flag arrives as a real bool from one sponsor, as 0/1 from the
        # next, and as Y/N from the one after. Previously only the first
        # worked and the others made the criterion silently remove nobody,
        # which is the most dangerous way for a filter to fail.
        for values, expected_true in [
            ([True, False, True], 2),
            ([1, 0, 1], 2),
            (["Y", "N", "yes"], 2),
            (["true", "false", "TRUE"], 2),
            ([1.0, 0.0, 1.0], 2),
        ]:
            frame = pd.DataFrame({"flag": values})
            kept = apply_criteria(frame, [Criterion("flag", Operator.IS_TRUE)])
            assert len(kept.frame) == expected_true, values
            assert kept.warnings == [], values

    def test_exclusion_on_a_flag_actually_removes_rows(self):
        frame = pd.DataFrame({"prior_cv_event": [True, False, True, False, True]})
        result = apply_criteria(
            frame,
            [Criterion("prior_cv_event", Operator.IS_TRUE, kind=CriterionKind.EXCLUSION)],
        )
        assert len(result.frame) == 2
        assert result.funnel[0].removed == 3

    def test_missing_flag_values_are_not_treated_as_false(self):
        frame = pd.DataFrame({"flag": [True, None, False]})
        assert len(apply_criteria(frame, [Criterion("flag", Operator.IS_TRUE)]).frame) == 1
        assert len(apply_criteria(frame, [Criterion("flag", Operator.IS_FALSE)]).frame) == 1

    def test_nulls_never_satisfy_a_threshold(self):
        frame = pd.DataFrame({"egfr": [80.0, None, 20.0, None, 95.0]})
        result = apply_criteria(frame, [Criterion("egfr", Operator.GTE, 60)])
        assert len(result.frame) == 2

    def test_funnel_records_attrition_per_criterion_in_order(self, cohort):
        criteria = [
            Criterion("age", Operator.GTE, 40, label="Age 40 or over"),
            Criterion("egfr", Operator.GTE, 60, label="eGFR at least 60"),
            Criterion("prior_cv_event", Operator.IS_TRUE, kind=CriterionKind.EXCLUSION),
        ]
        result = apply_criteria(cohort, criteria)

        assert len(result.funnel) == 3
        assert result.funnel[0].criterion == "Age 40 or over"
        assert result.funnel[0].candidates_in == len(cohort)
        # Each step starts where the previous one ended.
        for previous, following in zip(result.funnel, result.funnel[1:]):
            assert following.candidates_in == previous.candidates_out
        assert result.funnel[-1].candidates_out == result.eligible

    def test_missing_feature_is_reported_not_fatal(self, cohort):
        result = apply_criteria(cohort, [Criterion("troponin", Operator.GTE, 0.4)])
        assert len(result.frame) == len(cohort)
        assert any("not in the cohort" in w for w in result.warnings)
        assert result.funnel[0].note is not None

    def test_an_impossible_protocol_empties_the_cohort_and_stops(self, cohort):
        criteria = [
            Criterion("age", Operator.GTE, 100),
            Criterion("hba1c", Operator.GTE, 7.0),
        ]
        result = apply_criteria(cohort, criteria)
        assert result.eligible == 0
        assert any("emptied at criterion" in w for w in result.warnings)
        # The second criterion is never evaluated, and the funnel says so by
        # not containing it.
        assert len(result.funnel) == 1

    def test_criteria_parse_from_api_payload(self):
        parsed = criteria_from_payload(
            [
                {"feature": "age", "operator": "gte", "value": 18},
                {"feature": "ecog_status", "operator": "in", "value": [0, 1]},
                {"feature": "prior_cv_event", "operator": "is_true", "kind": "exclusion"},
            ]
        )
        assert parsed[0].operator is Operator.GTE
        assert parsed[2].kind is CriterionKind.EXCLUSION

    def test_criterion_description_falls_back_to_generated_text(self):
        assert Criterion("age", Operator.GTE, 65).describe() == "age at least 65"
        assert Criterion("egfr", Operator.BETWEEN, [30, 60]).describe() == (
            "egfr between 30 and 60"
        )


class TestOversampling:
    def test_factor_grows_as_eligibility_falls(self):
        assert estimate_oversample_factor(1.0) < estimate_oversample_factor(0.1)

    def test_factor_is_never_below_one(self):
        assert estimate_oversample_factor(1.0) >= 1.0

    def test_zero_eligibility_is_infinite(self):
        assert estimate_oversample_factor(0.0) == float("inf")

    def test_factor_is_capped(self):
        assert estimate_oversample_factor(1e-9) <= 200.0
