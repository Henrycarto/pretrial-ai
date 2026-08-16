"""Aggregation of the individual tests into one fidelity report.

The single number this module produces is the number a clinical operations
director looks at to decide whether a synthetic cohort is usable, so how it
is built is stated openly rather than tuned to look good.

Composition:

    marginal agreement  (KS statistic / TVD)          weight 0.40
    shape agreement     (Jensen-Shannon divergence)   weight 0.35
    dependency structure (correlation matrix delta)   weight 0.25

Marginals carry the most weight because inclusion and exclusion criteria are
written against them directly: an age band, a lab value ceiling, a prior
therapy flag. Shape agreement is close behind because a matched marginal with
the wrong internal structure passes screening and then fails at analysis.
Dependency structure carries the least because it is the noisiest of the
three at the cohort sizes involved, not because it matters least.

Weights are renormalised over whichever components could actually be
evaluated, so a dataset with a single feature still returns a defensible
score rather than a silently deflated one.

Schema coverage is applied as a multiplier on top. A synthetic cohort that
reproduces six of twelve requested fields perfectly is not a 100 percent
faithful cohort, and the report should not say it is.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .correlation import CorrelationComparison, CorrelationMethod, compare_correlations
from .features import FeatureKind, SchemaAlignment, align_schema, classify_feature
from .js_divergence import JSFeatureResult, js_divergence_frame
from .ks_test import DEFAULT_ALPHA, KSFeatureResult, ks_test_frame

WEIGHT_MARGINAL = 0.40
WEIGHT_SHAPE = 0.35
WEIGHT_DEPENDENCY = 0.25

# Thresholds are shared with the frontend FidelityScoreBadge ring colours.
# Changing one without the other puts a green ring on a failing cohort.
PASS_THRESHOLD = 90.0
BORDERLINE_THRESHOLD = 70.0

DEFAULT_PREVIEW_FEATURES = 5


@dataclass(frozen=True)
class FeatureFidelity:
    feature: str
    kind: str
    fidelity: float
    ks_statistic: float | None
    ks_p_value: float | None
    js_divergence: float | None
    n_real: int
    n_synthetic: int
    grade: str
    evaluated: bool
    note: str | None = None


@dataclass(frozen=True)
class DistributionPreview:
    """Chart payload for one feature, real against synthetic."""

    feature: str
    kind: str
    fidelity: float
    bins: list[str]
    real: list[float]
    synthetic: list[float]
    bin_edges: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class FidelityReport:
    overall_fidelity: float
    raw_fidelity: float
    grade: str
    verdict: str
    components: dict[str, Any]
    weights: dict[str, float]
    schema: dict[str, Any]
    features: list[FeatureFidelity]
    ks_results: list[KSFeatureResult]
    js_results: list[JSFeatureResult]
    correlation: CorrelationComparison
    distribution_previews: list[DistributionPreview]
    distribution_preview_ranking: str
    row_counts: dict[str, int]
    warnings: list[str]
    thresholds: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "overall_fidelity": self.overall_fidelity,
            "raw_fidelity": self.raw_fidelity,
            "grade": self.grade,
            "verdict": self.verdict,
            "components": self.components,
            "weights": self.weights,
            "schema": self.schema,
            "features": [asdict(f) for f in self.features],
            "ks_results": [r.as_dict() for r in self.ks_results],
            "js_results": [r.as_dict() for r in self.js_results],
            "correlation": self.correlation.as_dict(),
            "distribution_previews": [asdict(d) for d in self.distribution_previews],
            "distribution_preview_ranking": self.distribution_preview_ranking,
            "row_counts": self.row_counts,
            "warnings": self.warnings,
            "thresholds": self.thresholds,
        }


def grade_for(score: float) -> str:
    if score >= PASS_THRESHOLD:
        return "pass"
    if score >= BORDERLINE_THRESHOLD:
        return "borderline"
    return "fail"


def _verdict(grade: str, coverage: float) -> str:
    if grade == "pass":
        base = "Cohort matches the reference distribution closely enough for feasibility work."
    elif grade == "borderline":
        base = (
            "Cohort is usable for directional feasibility only. Review the per feature "
            "results before sizing a protocol against it."
        )
    else:
        base = (
            "Cohort does not reproduce the reference distribution. Do not use it for "
            "feasibility decisions."
        )
    if coverage < 1.0:
        base += f" Schema coverage is {coverage * 100:.1f} percent of requested features."
    return base


def build_report(
    real: pd.DataFrame,
    synthetic: pd.DataFrame,
    features: list[str] | None = None,
    alpha: float = DEFAULT_ALPHA,
    bins: int | None = None,
    correlation_method: CorrelationMethod = "pearson",
    preview_features: int = DEFAULT_PREVIEW_FEATURES,
) -> FidelityReport:
    alignment: SchemaAlignment = align_schema(real, synthetic, features)
    columns = alignment.shared
    warnings = list(alignment.warnings)

    if not columns:
        return _empty_report(real, synthetic, alignment, correlation_method, warnings)

    # Classified once and threaded through every engine so a feature cannot be
    # numeric in one test and categorical in another.
    kinds: dict[str, FeatureKind] = {
        c: classify_feature(real[c], synthetic[c]) for c in columns
    }
    unsupported = [c for c, k in kinds.items() if k is FeatureKind.UNSUPPORTED]
    if unsupported:
        warnings.append(
            f"Features skipped, unsupported type: {', '.join(sorted(unsupported))}"
        )

    ks_results = ks_test_frame(real, synthetic, columns, alpha=alpha, kinds=kinds)
    js_results = js_divergence_frame(real, synthetic, columns, bins=bins, kinds=kinds)
    correlation = compare_correlations(
        real, synthetic, columns, method=correlation_method, kinds=kinds
    )
    if not correlation.evaluated and correlation.note:
        warnings.append(f"Correlation comparison skipped. {correlation.note}")

    ks_by_feature = {r.feature: r for r in ks_results}
    js_by_feature = {r.feature: r for r in js_results}

    feature_scores: list[FeatureFidelity] = []
    for column in columns:
        ks = ks_by_feature[column]
        js = js_by_feature[column]
        parts = [r.score for r in (ks, js) if r.evaluated]
        evaluated = bool(parts)
        fidelity = round(float(np.mean(parts)) * 100.0, 2) if evaluated else 0.0
        feature_scores.append(
            FeatureFidelity(
                feature=column,
                kind=kinds[column].value,
                fidelity=fidelity,
                ks_statistic=ks.statistic if ks.evaluated else None,
                ks_p_value=ks.p_value if ks.evaluated else None,
                js_divergence=js.divergence if js.evaluated else None,
                n_real=max(ks.n_real, js.n_real),
                n_synthetic=max(ks.n_synthetic, js.n_synthetic),
                grade=grade_for(fidelity) if evaluated else "not_evaluated",
                evaluated=evaluated,
                note=ks.note or js.note,
            )
        )

    marginal = _mean_score([r.score for r in ks_results if r.evaluated])
    shape = _mean_score([r.score for r in js_results if r.evaluated])
    dependency = correlation.score if correlation.evaluated else None

    raw = _weighted_score(marginal, shape, dependency)
    raw_fidelity = round(raw * 100.0, 2)
    overall = round(raw * alignment.coverage * 100.0, 2)
    grade = grade_for(overall)

    previews = _build_previews(js_results, feature_scores, preview_features)

    failing = [f.feature for f in feature_scores if f.evaluated and f.grade == "fail"]
    if failing:
        warnings.append(
            f"Features below the {BORDERLINE_THRESHOLD:.0f} percent floor: {', '.join(failing)}"
        )

    return FidelityReport(
        overall_fidelity=overall,
        raw_fidelity=raw_fidelity,
        grade=grade,
        verdict=_verdict(grade, alignment.coverage),
        components={
            "marginal_agreement": _pct(marginal),
            "shape_agreement": _pct(shape),
            "dependency_structure": _pct(dependency),
            "schema_coverage": round(alignment.coverage * 100.0, 2),
        },
        weights={
            "marginal_agreement": WEIGHT_MARGINAL,
            "shape_agreement": WEIGHT_SHAPE,
            "dependency_structure": WEIGHT_DEPENDENCY,
        },
        schema={
            "shared": alignment.shared,
            "real_only": alignment.real_only,
            "synthetic_only": alignment.synthetic_only,
            "coverage": alignment.coverage,
            "feature_kinds": {c: k.value for c, k in kinds.items()},
        },
        features=feature_scores,
        ks_results=ks_results,
        js_results=js_results,
        correlation=correlation,
        distribution_previews=previews,
        distribution_preview_ranking="lowest_fidelity_first",
        row_counts={"real": int(len(real)), "synthetic": int(len(synthetic))},
        warnings=warnings,
        thresholds={"pass": PASS_THRESHOLD, "borderline": BORDERLINE_THRESHOLD},
    )


def _mean_score(scores: list[float]) -> float | None:
    if not scores:
        return None
    return float(np.mean(scores))


def _pct(value: float | None) -> float | None:
    return None if value is None else round(value * 100.0, 2)


def _weighted_score(
    marginal: float | None, shape: float | None, dependency: float | None
) -> float:
    pairs = [
        (marginal, WEIGHT_MARGINAL),
        (shape, WEIGHT_SHAPE),
        (dependency, WEIGHT_DEPENDENCY),
    ]
    available = [(v, w) for v, w in pairs if v is not None]
    if not available:
        return 0.0
    total_weight = sum(w for _, w in available)
    return sum(v * w for v, w in available) / total_weight


def _build_previews(
    js_results: list[JSFeatureResult],
    feature_scores: list[FeatureFidelity],
    limit: int,
) -> list[DistributionPreview]:
    """Chart data for the features most likely to fail review.

    Ranked worst first rather than by declaration order. The five features a
    reviewer needs to see are the five the generator handled least well.
    """
    fidelity_by_feature = {f.feature: f.fidelity for f in feature_scores}
    usable = [r for r in js_results if r.evaluated and r.support]
    usable.sort(key=lambda r: fidelity_by_feature.get(r.feature, 0.0))

    return [
        DistributionPreview(
            feature=r.feature,
            kind=r.kind,
            fidelity=fidelity_by_feature.get(r.feature, 0.0),
            bins=r.support,
            real=r.real_density,
            synthetic=r.synthetic_density,
            bin_edges=r.bin_edges,
        )
        for r in usable[: max(0, limit)]
    ]


def _empty_report(
    real: pd.DataFrame,
    synthetic: pd.DataFrame,
    alignment: SchemaAlignment,
    correlation_method: CorrelationMethod,
    warnings: list[str],
) -> FidelityReport:
    warnings = warnings + ["No shared features between the two datasets. Nothing to compare."]
    return FidelityReport(
        overall_fidelity=0.0,
        raw_fidelity=0.0,
        grade="fail",
        verdict="The two datasets share no columns, so no comparison was possible.",
        components={
            "marginal_agreement": None,
            "shape_agreement": None,
            "dependency_structure": None,
            "schema_coverage": 0.0,
        },
        weights={
            "marginal_agreement": WEIGHT_MARGINAL,
            "shape_agreement": WEIGHT_SHAPE,
            "dependency_structure": WEIGHT_DEPENDENCY,
        },
        schema={
            "shared": alignment.shared,
            "real_only": alignment.real_only,
            "synthetic_only": alignment.synthetic_only,
            "coverage": alignment.coverage,
            "feature_kinds": {},
        },
        features=[],
        ks_results=[],
        js_results=[],
        correlation=compare_correlations(
            pd.DataFrame(), pd.DataFrame(), [], method=correlation_method
        ),
        distribution_previews=[],
        distribution_preview_ranking="lowest_fidelity_first",
        row_counts={"real": int(len(real)), "synthetic": int(len(synthetic))},
        warnings=warnings,
        thresholds={"pass": PASS_THRESHOLD, "borderline": BORDERLINE_THRESHOLD},
    )
