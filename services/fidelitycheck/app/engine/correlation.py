"""Correlation matrix comparison between real and synthetic cohorts.

Per feature tests are marginal. A generator can reproduce the age
distribution perfectly and the creatinine distribution perfectly and still
produce a cohort where the two are uncorrelated, which for a renal exclusion
criterion makes the cohort useless. This module is the check that catches
that: it compares the pairwise dependency structure, not the marginals.

Categorical features are one hot encoded before correlation so that ordinal
and nominal fields still contribute. Encoding drops one level per feature to
avoid a perfectly collinear column, which would put an undefined entry in the
matrix.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from .features import (
    MIN_SAMPLES,
    FeatureKind,
    align_schema,
    classify_feature,
    numeric_values,
)

CorrelationMethod = Literal["pearson", "spearman"]

# One hot encoding a high cardinality field (an ICD-10 code column with 400
# levels) would swamp the matrix with near empty indicator columns whose
# correlations are dominated by noise.
MAX_ONE_HOT_LEVELS = 12


@dataclass(frozen=True)
class PairDelta:
    feature_a: str
    feature_b: str
    real: float
    synthetic: float
    delta: float


@dataclass(frozen=True)
class CorrelationComparison:
    method: str
    features: list[str]
    matrix_features: list[str]
    real_matrix: list[list[float | None]]
    synthetic_matrix: list[list[float | None]]
    delta_matrix: list[list[float | None]]
    mean_absolute_delta: float
    rms_delta: float
    max_absolute_delta: float
    frobenius_norm: float
    pairs_compared: int
    score: float
    evaluated: bool
    worst_pairs: list[PairDelta] = field(default_factory=list)
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["worst_pairs"] = [asdict(p) for p in self.worst_pairs]
        return payload


def _not_evaluated(method: str, features: list[str], note: str) -> CorrelationComparison:
    return CorrelationComparison(
        method=method,
        features=features,
        matrix_features=[],
        real_matrix=[],
        synthetic_matrix=[],
        delta_matrix=[],
        mean_absolute_delta=float("nan"),
        rms_delta=float("nan"),
        max_absolute_delta=float("nan"),
        frobenius_norm=float("nan"),
        pairs_compared=0,
        score=0.0,
        evaluated=False,
        note=note,
    )


def encode_for_correlation(
    frame: pd.DataFrame,
    features: list[str],
    kinds: dict[str, FeatureKind],
    categorical_levels: dict[str, list[str]],
) -> pd.DataFrame:
    """Project a frame into the numeric space the correlation is computed in.

    The level list is passed in rather than derived per frame so that both
    cohorts encode to the same columns in the same order. Deriving it per
    frame would silently compare matrices with different axes.
    """
    encoded: dict[str, pd.Series] = {}

    for feature in features:
        kind = kinds.get(feature, FeatureKind.UNSUPPORTED)
        if kind is FeatureKind.NUMERIC:
            encoded[feature] = pd.to_numeric(frame[feature], errors="coerce")
        elif kind is FeatureKind.CATEGORICAL:
            levels = categorical_levels.get(feature, [])
            as_text = frame[feature].astype("string")
            for level in levels:
                encoded[f"{feature}={level}"] = (as_text == level).astype(float)

    return pd.DataFrame(encoded, index=frame.index)


def _categorical_levels(
    real: pd.DataFrame,
    synthetic: pd.DataFrame,
    features: list[str],
    kinds: dict[str, FeatureKind],
) -> dict[str, list[str]]:
    levels: dict[str, list[str]] = {}
    for feature in features:
        if kinds.get(feature) is not FeatureKind.CATEGORICAL:
            continue
        pooled = pd.concat(
            [real[feature].astype("string"), synthetic[feature].astype("string")],
            ignore_index=True,
        ).dropna()
        unique = sorted(pooled.unique().tolist())
        if len(unique) < 2 or len(unique) > MAX_ONE_HOT_LEVELS:
            continue
        # Drop the last level. With k indicators summing to 1 the matrix is
        # singular and the deltas become unstable.
        levels[feature] = [str(u) for u in unique[:-1]]
    return levels


def compare_correlations(
    real: pd.DataFrame,
    synthetic: pd.DataFrame,
    features: list[str] | None = None,
    method: CorrelationMethod = "pearson",
    kinds: dict[str, FeatureKind] | None = None,
    top_n_pairs: int = 5,
) -> CorrelationComparison:
    columns = features or align_schema(real, synthetic).shared
    resolved_kinds = kinds or {
        c: classify_feature(real[c], synthetic[c]) for c in columns
    }

    if len(real) < MIN_SAMPLES or len(synthetic) < MIN_SAMPLES:
        return _not_evaluated(
            method, columns, f"Fewer than {MIN_SAMPLES} rows on one side."
        )

    levels = _categorical_levels(real, synthetic, columns, resolved_kinds)
    real_encoded = encode_for_correlation(real, columns, resolved_kinds, levels)
    synthetic_encoded = encode_for_correlation(synthetic, columns, resolved_kinds, levels)

    # A column that is constant in either cohort has zero variance and yields
    # an undefined correlation with everything. Drop it from both sides so the
    # matrices stay the same shape.
    usable = [
        c
        for c in real_encoded.columns
        if real_encoded[c].nunique(dropna=True) > 1
        and synthetic_encoded[c].nunique(dropna=True) > 1
    ]
    if len(usable) < 2:
        return _not_evaluated(
            method,
            columns,
            "At least two features with non zero variance in both cohorts are required.",
        )

    real_matrix = real_encoded[usable].corr(method=method)
    synthetic_matrix = synthetic_encoded[usable].corr(method=method)
    delta = synthetic_matrix - real_matrix

    # Only the strict upper triangle carries information. The diagonal is
    # always 1 and would drag the mean delta toward zero.
    mask = np.triu(np.ones(delta.shape, dtype=bool), k=1)
    values = delta.to_numpy()[mask]
    finite = values[np.isfinite(values)]

    if finite.size == 0:
        return _not_evaluated(method, columns, "No comparable feature pairs.")

    mean_absolute = float(np.abs(finite).mean())
    rms = float(np.sqrt(np.square(finite).mean()))
    max_absolute = float(np.abs(finite).max())
    frobenius = float(np.sqrt(np.square(finite).sum()))

    pairs: list[PairDelta] = []
    for i, a in enumerate(usable):
        for j, b in enumerate(usable):
            if j <= i:
                continue
            d = delta.iat[i, j]
            if not np.isfinite(d):
                continue
            pairs.append(
                PairDelta(
                    feature_a=a,
                    feature_b=b,
                    real=round(float(real_matrix.iat[i, j]), 6),
                    synthetic=round(float(synthetic_matrix.iat[i, j]), 6),
                    delta=round(float(d), 6),
                )
            )
    pairs.sort(key=lambda p: abs(p.delta), reverse=True)

    # The penalty is built from the RMS delta and the single worst delta, not
    # from the arithmetic mean.
    #
    # The mean is the wrong summary here and measurably so. One hot encoding
    # expands a handful of clinical features into dozens of matrix entries,
    # most of which are near zero on both sides, so averaging over all pairs
    # drowns the few that matter. On a cohort whose age to eGFR correlation
    # had been destroyed outright, moving from -0.60 to +0.02, the mean based
    # score still read 98 percent. That is precisely the failure this test
    # exists to catch, and it was reporting it as a pass.
    #
    # RMS weights large deltas quadratically, and the max term makes a single
    # destroyed relationship visible no matter how many well behaved pairs
    # surround it.
    penalty = 0.5 * rms + 0.5 * max_absolute

    # Pearson r lives in [-1, 1], so a delta can reach 2. Dividing by 2 keeps
    # the score on the same 0 to 1 footing as the KS and divergence scores,
    # which is what makes the weighted aggregate meaningful.
    score = max(0.0, 1.0 - (penalty / 2.0))

    return CorrelationComparison(
        method=method,
        features=columns,
        matrix_features=usable,
        real_matrix=_matrix_to_list(real_matrix),
        synthetic_matrix=_matrix_to_list(synthetic_matrix),
        delta_matrix=_matrix_to_list(delta),
        mean_absolute_delta=round(mean_absolute, 6),
        rms_delta=round(rms, 6),
        max_absolute_delta=round(max_absolute, 6),
        frobenius_norm=round(frobenius, 6),
        pairs_compared=int(finite.size),
        score=round(score, 6),
        evaluated=True,
        worst_pairs=pairs[:top_n_pairs],
    )


def _matrix_to_list(matrix: pd.DataFrame) -> list[list[float | None]]:
    return [
        [None if not np.isfinite(v) else round(float(v), 6) for v in row]
        for row in matrix.to_numpy()
    ]
