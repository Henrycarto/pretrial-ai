"""Tests for the job pipeline's reporting logic.

The Celery task itself needs Redis and a running FidelityCheck, so it is
covered by the end to end job in CI rather than here. What is unit testable,
and what broke in practice, is the funnel merge.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engine.criteria_filter import Criterion, CriterionKind, Operator, apply_criteria
from app.tasks.generation_job import _merge_screening


def batch(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "age": rng.integers(18, 90, n),
            "hba1c": rng.normal(7.8, 1.3, n).clip(4, 15),
            "prior_cv_event": rng.random(n) < 0.3,
        }
    )


CRITERIA = [
    Criterion("age", Operator.GTE, 45, label="Age 45 or over"),
    Criterion("hba1c", Operator.GTE, 7.0, label="HbA1c at least 7.0"),
    Criterion("prior_cv_event", Operator.IS_TRUE, kind=CriterionKind.EXCLUSION,
              label="Exclude prior CV event"),
]


class TestFunnelMerge:
    def test_counts_add_across_batches(self):
        results = [apply_criteria(batch(1000, s), CRITERIA) for s in (1, 2, 3)]
        merged = _merge_screening(results)

        assert merged["candidates_screened"] == 3000
        assert merged["eligible"] == sum(r.eligible for r in results)
        assert len(merged["funnel"]) == 3
        assert merged["funnel"][0]["candidates_in"] == 3000

    def test_funnel_stays_internally_consistent(self):
        # The regression. Reporting only the final batch produced a funnel
        # whose eligible count was smaller than the cohort actually delivered,
        # which makes the whole report untrustworthy.
        results = [apply_criteria(batch(800, s), CRITERIA) for s in (11, 12)]
        merged = _merge_screening(results)

        for previous, following in zip(merged["funnel"], merged["funnel"][1:]):
            assert following["candidates_in"] == previous["candidates_out"]

        assert merged["funnel"][-1]["candidates_out"] == merged["eligible"]
        assert merged["funnel"][0]["candidates_in"] == merged["candidates_screened"]

    def test_criterion_labels_are_preserved(self):
        merged = _merge_screening([apply_criteria(batch(500, 5), CRITERIA)])
        assert [step["criterion"] for step in merged["funnel"]] == [
            "Age 45 or over",
            "HbA1c at least 7.0",
            "Exclude prior CV event",
        ]

    def test_a_batch_that_empties_early_does_not_truncate_the_funnel(self):
        # A batch whose cohort empties at criterion 2 stops there and has a
        # shorter funnel. The merge is driven by the longest one, so the
        # remaining criteria still appear.
        impossible = [Criterion("age", Operator.GTE, 200), Criterion("hba1c", Operator.GTE, 7.0)]
        empty = apply_criteria(batch(300, 7), impossible)
        full = apply_criteria(batch(300, 8), [Criterion("age", Operator.GTE, 20),
                                              Criterion("hba1c", Operator.GTE, 7.0)])
        merged = _merge_screening([empty, full])
        assert len(merged["funnel"]) == 2

    def test_no_batches_produces_an_empty_funnel(self):
        merged = _merge_screening([])
        assert merged["eligible"] == 0
        assert merged["funnel"] == []
        assert merged["eligibility_rate"] == 0.0

    def test_warnings_are_deduplicated_across_batches(self):
        missing = [Criterion("troponin", Operator.GTE, 0.4)]
        results = [apply_criteria(batch(200, s), missing) for s in (21, 22, 23)]
        merged = _merge_screening(results)
        assert len(merged["warnings"]) == 1

    def test_eligibility_rate_is_over_the_combined_denominator(self):
        results = [apply_criteria(batch(1000, s), CRITERIA) for s in (31, 32)]
        merged = _merge_screening(results)
        expected = merged["eligible"] / merged["candidates_screened"]
        assert merged["eligibility_rate"] == pytest.approx(expected, abs=1e-6)
