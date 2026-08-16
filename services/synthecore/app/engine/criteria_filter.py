"""Inclusion and exclusion criteria applied to a generated cohort.

The filtered cohort is only half of what this module produces. The other half
is the attrition funnel: how many candidates each criterion removed, in the
order the protocol states them. That funnel is the answer to the question the
tool exists to answer, which is not "can we build a cohort" but "which line
of this protocol is the one making recruitment impossible".

Criteria are evaluated against the generated cohort rather than folded into
the generator so that the funnel is measurable. A conditional sampler that
only ever emits eligible patients cannot tell you that the eGFR floor alone
disqualifies 61 percent of the population.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd


class Operator(str, Enum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"
    NEQ = "neq"
    IN = "in"
    NOT_IN = "not_in"
    BETWEEN = "between"
    IS_TRUE = "is_true"
    IS_FALSE = "is_false"
    IS_NULL = "is_null"
    NOT_NULL = "not_null"


class CriterionKind(str, Enum):
    INCLUSION = "inclusion"
    EXCLUSION = "exclusion"


OPERATOR_LABELS: dict[Operator, str] = {
    Operator.GT: "greater than",
    Operator.GTE: "at least",
    Operator.LT: "less than",
    Operator.LTE: "at most",
    Operator.EQ: "equal to",
    Operator.NEQ: "not equal to",
    Operator.IN: "one of",
    Operator.NOT_IN: "not one of",
    Operator.BETWEEN: "between",
    Operator.IS_TRUE: "is true",
    Operator.IS_FALSE: "is false",
    Operator.IS_NULL: "is missing",
    Operator.NOT_NULL: "is recorded",
}


@dataclass(frozen=True)
class Criterion:
    feature: str
    operator: Operator
    value: Any = None
    kind: CriterionKind = CriterionKind.INCLUSION
    label: str | None = None

    def describe(self) -> str:
        if self.label:
            return self.label
        op = OPERATOR_LABELS[self.operator]
        if self.operator in {Operator.IS_TRUE, Operator.IS_FALSE, Operator.IS_NULL, Operator.NOT_NULL}:
            return f"{self.feature} {op}"
        if self.operator == Operator.BETWEEN and isinstance(self.value, (list, tuple)):
            return f"{self.feature} {op} {self.value[0]} and {self.value[1]}"
        return f"{self.feature} {op} {self.value}"


@dataclass
class FunnelStep:
    criterion: str
    feature: str
    kind: str
    candidates_in: int
    removed: int
    candidates_out: int
    removal_rate: float
    note: str | None = None


@dataclass
class FilterResult:
    frame: pd.DataFrame
    funnel: list[FunnelStep] = field(default_factory=list)
    candidates_screened: int = 0
    eligible: int = 0
    eligibility_rate: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidates_screened": self.candidates_screened,
            "eligible": self.eligible,
            "eligibility_rate": self.eligibility_rate,
            "funnel": [asdict(step) for step in self.funnel],
            "warnings": self.warnings,
        }


TRUE_TOKENS = {"true", "t", "yes", "y", "1", "1.0"}
FALSE_TOKENS = {"false", "f", "no", "n", "0", "0.0"}


def _truthiness(series: pd.Series) -> pd.Series:
    """Nullable boolean view of a column, whatever type it arrived as.

    A flag column reaches this function as a real bool from one extract, as
    0 and 1 from the next, and as the strings "Y" and "N" from the one after
    that. `astype("boolean")` handles only the first and raises on the rest,
    which previously caused the criterion to be skipped and reported as
    removing nobody. A silently unapplied exclusion is worse than a loud
    failure, so every representation is handled here.
    """
    if pd.api.types.is_bool_dtype(series):
        return series.astype("boolean")

    if pd.api.types.is_numeric_dtype(series):
        numeric = pd.to_numeric(series, errors="coerce")
        return (numeric != 0).astype("boolean").where(numeric.notna())

    text = series.astype("string").str.strip().str.lower()
    result = pd.Series(pd.NA, index=series.index, dtype="boolean")
    result[text.isin(TRUE_TOKENS)] = True
    result[text.isin(FALSE_TOKENS)] = False
    return result


def _mask_for(frame: pd.DataFrame, criterion: Criterion) -> pd.Series:
    """Boolean mask of rows that satisfy the criterion's condition."""
    series = frame[criterion.feature]
    op = criterion.operator
    value = criterion.value

    if op is Operator.IS_NULL:
        return series.isna()
    if op is Operator.NOT_NULL:
        return series.notna()
    if op is Operator.IS_TRUE:
        return _truthiness(series).fillna(False).astype(bool)
    if op is Operator.IS_FALSE:
        # Null is not false. A patient with no record of a prior event has not
        # been shown not to have had one, and treating the two as the same
        # inflates the eligible count with unscreenable patients.
        return (~_truthiness(series).fillna(True)).astype(bool)

    if op in {Operator.GT, Operator.GTE, Operator.LT, Operator.LTE, Operator.BETWEEN}:
        numeric = pd.to_numeric(series, errors="coerce")
        if op is Operator.BETWEEN:
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise ValueError(f"'between' on {criterion.feature} needs a two element range")
            low, high = float(value[0]), float(value[1])
            return numeric.between(low, high, inclusive="both").fillna(False)
        bound = float(value)
        comparison = {
            Operator.GT: numeric > bound,
            Operator.GTE: numeric >= bound,
            Operator.LT: numeric < bound,
            Operator.LTE: numeric <= bound,
        }[op]
        # A null value cannot satisfy a threshold. Treating it as passing
        # would inflate the eligible count with unscreenable patients.
        return comparison.fillna(False)

    if op in {Operator.IN, Operator.NOT_IN}:
        if not isinstance(value, (list, tuple, set)):
            raise ValueError(f"'{op.value}' on {criterion.feature} needs a list of values")
        wanted = {str(v).lower() for v in value}
        as_text = series.astype("string").str.lower()
        member = as_text.isin(wanted).fillna(False)
        return member if op is Operator.IN else ~member

    as_text = series.astype("string").str.lower()
    target = str(value).lower()
    equal = (as_text == target).fillna(False)
    return equal if op is Operator.EQ else ~equal


def apply_criteria(
    frame: pd.DataFrame,
    criteria: list[Criterion],
) -> FilterResult:
    """Apply criteria in order, recording attrition at each step."""
    screened = int(len(frame))
    current = frame
    funnel: list[FunnelStep] = []
    warnings: list[str] = []

    for criterion in criteria:
        candidates_in = int(len(current))

        if criterion.feature not in current.columns:
            warnings.append(
                f"Criterion skipped, feature '{criterion.feature}' is not in the cohort."
            )
            funnel.append(
                FunnelStep(
                    criterion=criterion.describe(),
                    feature=criterion.feature,
                    kind=criterion.kind.value,
                    candidates_in=candidates_in,
                    removed=0,
                    candidates_out=candidates_in,
                    removal_rate=0.0,
                    note="Feature not present in the cohort. Criterion not applied.",
                )
            )
            continue

        try:
            satisfies = _mask_for(current, criterion)
        except (ValueError, TypeError) as exc:
            warnings.append(f"Criterion skipped, {criterion.describe()}: {exc}")
            funnel.append(
                FunnelStep(
                    criterion=criterion.describe(),
                    feature=criterion.feature,
                    kind=criterion.kind.value,
                    candidates_in=candidates_in,
                    removed=0,
                    candidates_out=candidates_in,
                    removal_rate=0.0,
                    note=str(exc),
                )
            )
            continue

        # An exclusion keeps the rows that do NOT match the condition.
        keep = satisfies if criterion.kind is CriterionKind.INCLUSION else ~satisfies
        current = current[keep.to_numpy()]
        candidates_out = int(len(current))
        removed = candidates_in - candidates_out

        funnel.append(
            FunnelStep(
                criterion=criterion.describe(),
                feature=criterion.feature,
                kind=criterion.kind.value,
                candidates_in=candidates_in,
                removed=removed,
                candidates_out=candidates_out,
                removal_rate=round(removed / candidates_in, 6) if candidates_in else 0.0,
            )
        )

        if candidates_out == 0:
            warnings.append(
                f"Cohort emptied at criterion: {criterion.describe()}. "
                "No later criterion could be evaluated."
            )
            break

    eligible = int(len(current))
    return FilterResult(
        frame=current.reset_index(drop=True),
        funnel=funnel,
        candidates_screened=screened,
        eligible=eligible,
        eligibility_rate=round(eligible / screened, 6) if screened else 0.0,
        warnings=warnings,
    )


def estimate_oversample_factor(eligibility_rate: float, safety: float = 1.25) -> float:
    """How much raw cohort to generate to land on the requested eligible size.

    The safety margin absorbs sampling variance in the rate estimate. Without
    it a rate measured on a small probe run lands short about half the time,
    and a second generation pass costs minutes.
    """
    if eligibility_rate <= 0:
        return float("inf")
    return float(np.clip(safety / eligibility_rate, 1.0, 200.0))


def criteria_from_payload(items: list[dict[str, Any]]) -> list[Criterion]:
    """Build criteria from the API request body."""
    parsed: list[Criterion] = []
    for item in items:
        parsed.append(
            Criterion(
                feature=str(item["feature"]),
                operator=Operator(str(item["operator"]).lower()),
                value=item.get("value"),
                kind=CriterionKind(str(item.get("kind", "inclusion")).lower()),
                label=item.get("label"),
            )
        )
    return parsed
