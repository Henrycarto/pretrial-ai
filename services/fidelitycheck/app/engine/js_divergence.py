"""Jensen-Shannon divergence between real and synthetic feature distributions.

JS divergence is used alongside the KS test because the two disagree in
useful ways. KS reports the single worst point of the CDF, so it is blind to
a distribution that is close everywhere except in shape: a synthetic cohort
that fills the same range but flattens a bimodal HbA1c distribution into one
broad hump can post a low D. JS divergence integrates the disagreement across
the whole support, so it catches exactly that failure. A cohort has to pass
both to be trusted.

Base 2 is used throughout, which bounds the divergence in [0, 1] bits: 0 when
the distributions are identical, 1 when their supports do not overlap at all.
That bound is what makes the score directly comparable across features and
mixable with the KS score in the aggregate.

The histogram edges are computed once from the pooled sample. Binning each
side independently would compare probability vectors defined over different
intervals, which produces a number that looks like a divergence but is not
one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial.distance import jensenshannon

from .features import (
    MIN_SAMPLES,
    FeatureKind,
    align_schema,
    categorical_values,
    classify_feature,
    numeric_values,
)

MIN_BINS = 5
MAX_BINS = 64


@dataclass(frozen=True)
class JSFeatureResult:
    feature: str
    kind: str
    divergence: float
    distance: float
    score: float
    n_real: int
    n_synthetic: int
    bins: int
    evaluated: bool
    support: list[str] = field(default_factory=list)
    real_density: list[float] = field(default_factory=list)
    synthetic_density: list[float] = field(default_factory=list)
    bin_edges: list[float] = field(default_factory=list)
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _not_evaluated(
    feature: str, kind: FeatureKind, n_real: int, n_synthetic: int, note: str
) -> JSFeatureResult:
    return JSFeatureResult(
        feature=feature,
        kind=kind.value,
        divergence=float("nan"),
        distance=float("nan"),
        score=0.0,
        n_real=n_real,
        n_synthetic=n_synthetic,
        bins=0,
        evaluated=False,
        note=note,
    )


def shared_bin_edges(
    real: np.ndarray, synthetic: np.ndarray, bins: int | None = None
) -> np.ndarray:
    """Histogram edges spanning the pooled support of both samples."""
    pooled = np.concatenate([real, synthetic])
    low, high = float(pooled.min()), float(pooled.max())

    if not np.isfinite(low) or not np.isfinite(high) or low == high:
        # A constant feature has no spread to bin. One bin wide enough to hold
        # the value keeps the divergence at 0 instead of raising.
        return np.array([low - 0.5, high + 0.5])

    if bins is None:
        # Freedman-Diaconis on the pooled sample, clamped. Left unclamped it
        # produces thousands of bins on a large cohort, which makes every bin
        # sparse and inflates the divergence for reasons of sampling noise
        # rather than distributional difference.
        edges = np.histogram_bin_edges(pooled, bins="auto")
        count = int(np.clip(len(edges) - 1, MIN_BINS, MAX_BINS))
    else:
        count = int(np.clip(bins, MIN_BINS, MAX_BINS))

    return np.linspace(low, high, count + 1)


def _js_from_counts(real_counts: np.ndarray, synthetic_counts: np.ndarray) -> tuple[float, float]:
    """Return (divergence, distance) in base 2 from two count vectors."""
    real_total = real_counts.sum()
    synthetic_total = synthetic_counts.sum()
    if real_total <= 0 or synthetic_total <= 0:
        return float("nan"), float("nan")

    p = real_counts / real_total
    q = synthetic_counts / synthetic_total

    # scipy returns the JS *distance*, the square root of the divergence.
    distance = float(jensenshannon(p, q, base=2))
    if np.isnan(distance):
        return float("nan"), float("nan")

    # Floating point can push the distance a hair past 1.0 on disjoint
    # supports, which would make the score negative.
    distance = float(np.clip(distance, 0.0, 1.0))
    return distance**2, distance


def js_divergence_numeric(
    feature: str, real: pd.Series, synthetic: pd.Series, bins: int | None = None
) -> JSFeatureResult:
    a = numeric_values(real).to_numpy()
    b = numeric_values(synthetic).to_numpy()

    if a.size < MIN_SAMPLES or b.size < MIN_SAMPLES:
        return _not_evaluated(
            feature,
            FeatureKind.NUMERIC,
            a.size,
            b.size,
            f"Fewer than {MIN_SAMPLES} non null values on one side.",
        )

    edges = shared_bin_edges(a, b, bins)
    real_counts, _ = np.histogram(a, bins=edges)
    synthetic_counts, _ = np.histogram(b, bins=edges)

    divergence, distance = _js_from_counts(
        real_counts.astype(float), synthetic_counts.astype(float)
    )
    if np.isnan(divergence):
        return _not_evaluated(
            feature, FeatureKind.NUMERIC, a.size, b.size, "Divergence undefined for this feature."
        )

    labels = [f"{edges[i]:.4g} to {edges[i + 1]:.4g}" for i in range(len(edges) - 1)]

    return JSFeatureResult(
        feature=feature,
        kind=FeatureKind.NUMERIC.value,
        divergence=round(divergence, 6),
        distance=round(distance, 6),
        score=round(1.0 - divergence, 6),
        n_real=int(a.size),
        n_synthetic=int(b.size),
        bins=len(edges) - 1,
        evaluated=True,
        support=labels,
        real_density=[round(float(v), 8) for v in real_counts / real_counts.sum()],
        synthetic_density=[round(float(v), 8) for v in synthetic_counts / synthetic_counts.sum()],
        bin_edges=[round(float(e), 6) for e in edges],
    )


def js_divergence_categorical(
    feature: str, real: pd.Series, synthetic: pd.Series
) -> JSFeatureResult:
    a = categorical_values(real)
    b = categorical_values(synthetic)

    if len(a) < MIN_SAMPLES or len(b) < MIN_SAMPLES:
        return _not_evaluated(
            feature,
            FeatureKind.CATEGORICAL,
            len(a),
            len(b),
            f"Fewer than {MIN_SAMPLES} non null values on one side.",
        )

    categories = sorted(set(a.unique()) | set(b.unique()))
    real_counts = a.value_counts().reindex(categories, fill_value=0).to_numpy(dtype=float)
    synthetic_counts = b.value_counts().reindex(categories, fill_value=0).to_numpy(dtype=float)

    divergence, distance = _js_from_counts(real_counts, synthetic_counts)
    if np.isnan(divergence):
        return _not_evaluated(
            feature,
            FeatureKind.CATEGORICAL,
            len(a),
            len(b),
            "Divergence undefined for this feature.",
        )

    return JSFeatureResult(
        feature=feature,
        kind=FeatureKind.CATEGORICAL.value,
        divergence=round(divergence, 6),
        distance=round(distance, 6),
        score=round(1.0 - divergence, 6),
        n_real=len(a),
        n_synthetic=len(b),
        bins=len(categories),
        evaluated=True,
        support=[str(c) for c in categories],
        real_density=[round(float(v), 8) for v in real_counts / real_counts.sum()],
        synthetic_density=[round(float(v), 8) for v in synthetic_counts / synthetic_counts.sum()],
    )


def js_divergence_feature(
    feature: str,
    real: pd.Series,
    synthetic: pd.Series,
    bins: int | None = None,
    kind: FeatureKind | None = None,
) -> JSFeatureResult:
    resolved = kind or classify_feature(real, synthetic)
    if resolved is FeatureKind.NUMERIC:
        return js_divergence_numeric(feature, real, synthetic, bins)
    if resolved is FeatureKind.CATEGORICAL:
        return js_divergence_categorical(feature, real, synthetic)
    return _not_evaluated(
        feature,
        FeatureKind.UNSUPPORTED,
        int(real.notna().sum()),
        int(synthetic.notna().sum()),
        "Feature type is not supported by the divergence test.",
    )


def js_divergence_frame(
    real: pd.DataFrame,
    synthetic: pd.DataFrame,
    features: list[str] | None = None,
    bins: int | None = None,
    kinds: dict[str, FeatureKind] | None = None,
) -> list[JSFeatureResult]:
    columns = features or align_schema(real, synthetic).shared
    return [
        js_divergence_feature(
            column,
            real[column],
            synthetic[column],
            bins=bins,
            kind=(kinds or {}).get(column),
        )
        for column in columns
    ]
