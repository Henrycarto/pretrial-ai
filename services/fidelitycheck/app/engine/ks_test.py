"""Two sample Kolmogorov-Smirnov testing, one test per feature.

The KS statistic D is the largest vertical gap between the two empirical
cumulative distribution functions. It is bounded in [0, 1] and it is
distribution free, so the same threshold means the same thing for an age
column and for a creatinine column.

Design note on the score. The feature score is derived from D, not from the
p-value. At the cohort sizes this product targets (10k to 100k synthetic
rows) a KS test rejects the null for differences far too small to affect
trial feasibility, so a p-value driven score would report near total failure
on cohorts that are visually and clinically indistinguishable. The p-value is
still returned because reviewers expect to see it, and it is the correct
statistic to quote at small sample sizes.

Categorical features have no meaningful ECDF, so they are scored with the
total variation distance between category frequencies. That is the natural
discrete analogue of D: both are a supremum of absolute probability
differences, both are bounded in [0, 1], and both equal 0 only when the two
distributions match exactly.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from .features import (
    MIN_SAMPLES,
    FeatureKind,
    align_schema,
    categorical_values,
    classify_feature,
    missingness,
    numeric_values,
)

DEFAULT_ALPHA = 0.05


@dataclass(frozen=True)
class KSFeatureResult:
    feature: str
    kind: str
    statistic: float
    p_value: float | None
    n_real: int
    n_synthetic: int
    alpha: float
    distributions_differ: bool
    score: float
    evaluated: bool
    method: str
    detail: dict[str, Any] = field(default_factory=dict)
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _not_evaluated(
    feature: str, kind: FeatureKind, n_real: int, n_synthetic: int, alpha: float, note: str
) -> KSFeatureResult:
    return KSFeatureResult(
        feature=feature,
        kind=kind.value,
        statistic=float("nan"),
        p_value=None,
        n_real=n_real,
        n_synthetic=n_synthetic,
        alpha=alpha,
        distributions_differ=False,
        score=0.0,
        evaluated=False,
        method="none",
        note=note,
    )


def ks_test_numeric(
    feature: str,
    real: pd.Series,
    synthetic: pd.Series,
    alpha: float = DEFAULT_ALPHA,
) -> KSFeatureResult:
    """Exact or asymptotic two sample KS test on a continuous feature."""
    a = numeric_values(real)
    b = numeric_values(synthetic)

    if len(a) < MIN_SAMPLES or len(b) < MIN_SAMPLES:
        return _not_evaluated(
            feature,
            FeatureKind.NUMERIC,
            len(a),
            len(b),
            alpha,
            f"Fewer than {MIN_SAMPLES} non null values on one side.",
        )

    outcome = stats.ks_2samp(a.to_numpy(), b.to_numpy(), alternative="two-sided", method="auto")
    statistic = float(outcome.statistic)
    p_value = float(outcome.pvalue)

    return KSFeatureResult(
        feature=feature,
        kind=FeatureKind.NUMERIC.value,
        statistic=round(statistic, 6),
        p_value=round(p_value, 8),
        n_real=len(a),
        n_synthetic=len(b),
        alpha=alpha,
        distributions_differ=p_value < alpha,
        score=round(1.0 - statistic, 6),
        evaluated=True,
        method="ks_2samp",
        detail={
            "real_mean": round(float(a.mean()), 6),
            "synthetic_mean": round(float(b.mean()), 6),
            "real_std": round(float(a.std(ddof=1)), 6) if len(a) > 1 else 0.0,
            "synthetic_std": round(float(b.std(ddof=1)), 6) if len(b) > 1 else 0.0,
            "real_median": round(float(a.median()), 6),
            "synthetic_median": round(float(b.median()), 6),
            **missingness(real, synthetic),
        },
    )


def tvd_test_categorical(
    feature: str,
    real: pd.Series,
    synthetic: pd.Series,
    alpha: float = DEFAULT_ALPHA,
) -> KSFeatureResult:
    """Total variation distance plus a chi squared goodness of fit p-value."""
    a = categorical_values(real)
    b = categorical_values(synthetic)

    if len(a) < MIN_SAMPLES or len(b) < MIN_SAMPLES:
        return _not_evaluated(
            feature,
            FeatureKind.CATEGORICAL,
            len(a),
            len(b),
            alpha,
            f"Fewer than {MIN_SAMPLES} non null values on one side.",
        )

    categories = sorted(set(a.unique()) | set(b.unique()))
    real_freq = a.value_counts(normalize=True).reindex(categories, fill_value=0.0)
    synth_freq = b.value_counts(normalize=True).reindex(categories, fill_value=0.0)

    tvd = 0.5 * float(np.abs(real_freq.to_numpy() - synth_freq.to_numpy()).sum())

    # Chi squared compares observed synthetic counts against the counts the
    # real proportions predict. Categories the real data never produced have
    # an expected count of zero and would divide by zero, so they are folded
    # into the TVD only and excluded from the test.
    p_value: float | None = None
    supported = [c for c in categories if real_freq[c] > 0]
    if len(supported) >= 2:
        observed = np.array([synth_freq[c] * len(b) for c in supported], dtype=float)
        expected = np.array([real_freq[c] * len(b) for c in supported], dtype=float)
        scale = observed.sum() / expected.sum() if expected.sum() else 1.0
        expected = expected * scale
        if (expected > 0).all():
            try:
                _, raw_p = stats.chisquare(f_obs=observed, f_exp=expected)
                p_value = float(raw_p)
            except ValueError:
                p_value = None

    unseen = [c for c in categories if real_freq[c] == 0 and synth_freq[c] > 0]

    return KSFeatureResult(
        feature=feature,
        kind=FeatureKind.CATEGORICAL.value,
        statistic=round(tvd, 6),
        p_value=round(p_value, 8) if p_value is not None else None,
        n_real=len(a),
        n_synthetic=len(b),
        alpha=alpha,
        distributions_differ=bool(p_value is not None and p_value < alpha),
        score=round(1.0 - tvd, 6),
        evaluated=True,
        method="total_variation_distance",
        detail={
            "categories": categories,
            "real_frequencies": {c: round(float(real_freq[c]), 6) for c in categories},
            "synthetic_frequencies": {c: round(float(synth_freq[c]), 6) for c in categories},
            "categories_not_present_in_real": unseen,
            **missingness(real, synthetic),
        },
    )


def ks_test_feature(
    feature: str,
    real: pd.Series,
    synthetic: pd.Series,
    alpha: float = DEFAULT_ALPHA,
    kind: FeatureKind | None = None,
) -> KSFeatureResult:
    resolved = kind or classify_feature(real, synthetic)
    if resolved is FeatureKind.NUMERIC:
        return ks_test_numeric(feature, real, synthetic, alpha)
    if resolved is FeatureKind.CATEGORICAL:
        return tvd_test_categorical(feature, real, synthetic, alpha)
    return _not_evaluated(
        feature,
        FeatureKind.UNSUPPORTED,
        int(real.notna().sum()),
        int(synthetic.notna().sum()),
        alpha,
        "Feature type is not supported by the two sample tests.",
    )


def ks_test_frame(
    real: pd.DataFrame,
    synthetic: pd.DataFrame,
    features: list[str] | None = None,
    alpha: float = DEFAULT_ALPHA,
    kinds: dict[str, FeatureKind] | None = None,
) -> list[KSFeatureResult]:
    """Run one test per shared feature, in the column order of the real frame."""
    columns = features or align_schema(real, synthetic).shared
    return [
        ks_test_feature(
            column,
            real[column],
            synthetic[column],
            alpha=alpha,
            kind=(kinds or {}).get(column),
        )
        for column in columns
    ]
