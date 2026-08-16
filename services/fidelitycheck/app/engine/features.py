"""Feature typing and alignment shared by the statistical engines.

Every test in FidelityCheck compares a real column against a synthetic column
of the same name. Column typing lives here rather than inside each test so a
feature cannot be treated as numeric by the KS test and categorical by the
divergence test, which would make the two scores incomparable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd
from pandas.api import types as ptypes


class FeatureKind(str, Enum):
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    UNSUPPORTED = "unsupported"


# Below this many non null values a two sample test says more about the
# sample size than about the distributions, so we report it as not evaluated
# instead of emitting a confident looking number.
MIN_SAMPLES = 8

# A low cardinality integer column (trial arm coded 0/1/2, ECOG status) is
# categorical in clinical terms even though pandas reads it as numeric.
# Continuous lab values never land under this threshold at realistic cohort
# sizes, so the heuristic separates the two cases without a schema file.
MAX_DISCRETE_CARDINALITY = 10


@dataclass(frozen=True)
class SchemaAlignment:
    """Which columns the two frames actually have in common."""

    shared: list[str]
    real_only: list[str]
    synthetic_only: list[str]
    coverage: float
    warnings: list[str]


def classify_feature(real: pd.Series, synthetic: pd.Series) -> FeatureKind:
    """Decide how a feature should be tested, using both frames.

    Both sides are inspected because a synthetic column can arrive as strings
    ("62") where the real column is numeric. Treating that pair as categorical
    would score two identical distributions as a total mismatch.
    """
    combined = pd.concat([real, synthetic], ignore_index=True).dropna()
    if combined.empty:
        return FeatureKind.UNSUPPORTED

    if ptypes.is_bool_dtype(combined):
        return FeatureKind.CATEGORICAL

    if ptypes.is_numeric_dtype(combined):
        return _numeric_or_discrete(combined)

    # Object columns that are numbers wearing string clothes still get the
    # numeric path, but only when effectively every value converts.
    coerced = pd.to_numeric(combined, errors="coerce")
    if coerced.notna().mean() >= 0.99:
        return _numeric_or_discrete(coerced.dropna())

    if ptypes.is_datetime64_any_dtype(combined):
        return FeatureKind.UNSUPPORTED

    return FeatureKind.CATEGORICAL


def _numeric_or_discrete(values: pd.Series) -> FeatureKind:
    if values.nunique() <= MAX_DISCRETE_CARDINALITY:
        return FeatureKind.CATEGORICAL
    return FeatureKind.NUMERIC


def numeric_values(series: pd.Series) -> pd.Series:
    """Coerce to float and drop nulls, for the numeric test paths."""
    return pd.to_numeric(series, errors="coerce").dropna().astype(float)


def categorical_values(series: pd.Series) -> pd.Series:
    """Normalise to string labels and drop nulls, for the categorical paths.

    Missing values are dropped rather than mapped to a "missing" category.
    A generator that reproduces the real missingness rate should not be
    rewarded for it here. Missingness is reported separately.
    """
    return series.dropna().astype(str)


def align_schema(
    real: pd.DataFrame,
    synthetic: pd.DataFrame,
    requested: list[str] | None = None,
) -> SchemaAlignment:
    """Intersect the two frames and record what does not line up."""
    real_cols = list(real.columns)
    synthetic_cols = list(synthetic.columns)

    if requested:
        missing = [c for c in requested if c not in real_cols or c not in synthetic_cols]
        shared = [c for c in requested if c in real_cols and c in synthetic_cols]
        real_only = [c for c in requested if c in real_cols and c not in synthetic_cols]
        synthetic_only = [c for c in requested if c in synthetic_cols and c not in real_cols]
        warnings: list[str] = []
        unknown = [c for c in missing if c not in real_only and c not in synthetic_only]
        if unknown:
            warnings.append(
                f"Requested features absent from both datasets: {', '.join(unknown)}"
            )
    else:
        shared = [c for c in real_cols if c in set(synthetic_cols)]
        real_only = [c for c in real_cols if c not in set(synthetic_cols)]
        synthetic_only = [c for c in synthetic_cols if c not in set(real_cols)]
        warnings = []

    union_size = len(set(real_cols) | set(synthetic_cols)) if not requested else len(requested)
    coverage = (len(shared) / union_size) if union_size else 0.0

    if real_only:
        warnings.append(
            "Features present in the real dataset but missing from the synthetic "
            f"cohort: {', '.join(real_only)}"
        )
    if synthetic_only:
        warnings.append(
            "Features present in the synthetic cohort but absent from the real "
            f"dataset: {', '.join(synthetic_only)}"
        )

    return SchemaAlignment(
        shared=shared,
        real_only=real_only,
        synthetic_only=synthetic_only,
        coverage=round(coverage, 6),
        warnings=warnings,
    )


def missingness(real: pd.Series, synthetic: pd.Series) -> dict[str, float]:
    """Null rate on each side. Reported alongside every feature result."""
    return {
        "real_null_rate": round(float(real.isna().mean()), 6) if len(real) else 0.0,
        "synthetic_null_rate": round(float(synthetic.isna().mean()), 6) if len(synthetic) else 0.0,
    }
