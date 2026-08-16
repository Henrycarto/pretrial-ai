"""Statistical engines behind the fidelity score.

Public entrypoint is report_builder.build_report. The individual modules are
importable on their own so the tests can pin each statistic independently of
the aggregation weights.
"""

from .correlation import compare_correlations
from .js_divergence import js_divergence_feature, js_divergence_frame
from .ks_test import ks_test_feature, ks_test_frame
from .report_builder import build_report, grade_for

__all__ = [
    "build_report",
    "compare_correlations",
    "grade_for",
    "js_divergence_feature",
    "js_divergence_frame",
    "ks_test_feature",
    "ks_test_frame",
]
