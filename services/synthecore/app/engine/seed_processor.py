"""Seed data parsing and normalisation.

Seed cohorts arrive as a CSV, a Parquet file, or a JSON array pulled out of a
sponsor's own extract. Whatever the source, the generator needs one thing: a
tidy frame with stable column names and honest types. This module produces
that and reports what it had to change, because a silent type coercion on a
lab value column is the kind of thing that surfaces three weeks later as an
inexplicable fidelity score.

Direct identifiers are dropped here rather than downstream. A generator that
never sees a name or an MRN cannot memorise one.
"""

from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Columns matched against this list are removed before the frame reaches the
# generator. The list is deliberately broad. A false positive costs one
# feature; a false negative puts an identifier in a released cohort.
DIRECT_IDENTIFIER_PATTERNS = [
    r"^mrn$",
    r"medical_record",
    r"^ssn$",
    r"social_security",
    r"^nhs_number$",
    r"patient_name",
    r"^name$",
    r"first_name",
    r"last_name",
    r"surname",
    r"^email",
    r"^phone",
    r"telephone",
    r"^address",
    r"street",
    r"postcode",
    r"post_code",
    r"^zip",
    r"passport",
    r"insurance_number",
    r"^dob$",
    r"date_of_birth",
    r"birth_date",
]

_IDENTIFIER_RE = re.compile("|".join(DIRECT_IDENTIFIER_PATTERNS), re.IGNORECASE)

# A free text column cannot be modelled by a tabular generator and is the
# most likely place for an identifier to hide inside prose.
MAX_TEXT_LENGTH = 120

SUPPORTED_SUFFIXES = {".csv", ".tsv", ".json", ".ndjson", ".parquet"}


@dataclass
class SeedProfile:
    rows: int
    columns: int
    feature_names: list[str]
    numeric_features: list[str]
    categorical_features: list[str]
    dropped_identifiers: list[str] = field(default_factory=list)
    dropped_free_text: list[str] = field(default_factory=list)
    null_rates: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "columns": self.columns,
            "feature_names": self.feature_names,
            "numeric_features": self.numeric_features,
            "categorical_features": self.categorical_features,
            "dropped_identifiers": self.dropped_identifiers,
            "dropped_free_text": self.dropped_free_text,
            "null_rates": self.null_rates,
            "warnings": self.warnings,
        }


def normalise_column_name(name: str) -> str:
    """snake_case, so `Patient Age (yrs)` and `patient_age_yrs` are one column.

    Deliberately does not split on camel case. Clinical column names are full
    of mixed case abbreviations, and splitting them does more damage than the
    rule is worth: HbA1c becomes hb_a1c while hba1c stays hba1c, so the same
    lab value arrives from two sponsors as two different features. Case is
    folded and punctuation collapses to underscores, nothing else.
    """
    cleaned = re.sub(r"[^\w\s]", " ", str(name)).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned.lower().strip("_") or "unnamed"


def read_tabular(content: bytes, filename: str) -> pd.DataFrame:
    """Parse an uploaded file into a frame based on its suffix."""
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"unsupported seed file type '{suffix or filename}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )

    if suffix == ".parquet":
        return pd.read_parquet(io.BytesIO(content))
    if suffix == ".tsv":
        return pd.read_csv(io.BytesIO(content), sep="\t")
    if suffix == ".ndjson":
        return pd.read_json(io.BytesIO(content), lines=True)
    if suffix == ".json":
        parsed = json.loads(content.decode("utf-8"))
        if isinstance(parsed, dict):
            # Accept both a bare array and the envelope shape the rest of the
            # system emits, so a cohort export can be fed straight back in.
            parsed = parsed.get("data") or parsed.get("rows") or parsed.get("patients")
        if not isinstance(parsed, list):
            raise ValueError("JSON seed data must be an array of row objects")
        return pd.DataFrame.from_records(parsed)

    return pd.read_csv(io.BytesIO(content))


def strip_identifiers(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Remove direct identifiers and unmodellable free text."""
    identifier_columns = [c for c in frame.columns if _IDENTIFIER_RE.search(str(c))]

    free_text_columns: list[str] = []
    for column in frame.columns:
        if column in identifier_columns:
            continue
        series = frame[column]
        if series.dtype != object:
            continue
        sample = series.dropna().astype(str).head(500)
        if sample.empty:
            continue
        if sample.str.len().mean() > MAX_TEXT_LENGTH:
            free_text_columns.append(column)

    dropped = identifier_columns + free_text_columns
    return frame.drop(columns=dropped), identifier_columns, free_text_columns


def coerce_types(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Turn numbers stored as text into numbers, and note where that happened."""
    warnings: list[str] = []
    out = frame.copy()

    for column in out.columns:
        series = out[column]
        if series.dtype != object:
            continue
        coerced = pd.to_numeric(series, errors="coerce")
        non_null = series.notna().sum()
        if non_null == 0:
            continue
        convertible = coerced.notna().sum() / non_null
        if convertible >= 0.99:
            out[column] = coerced
            if convertible < 1.0:
                warnings.append(
                    f"{column}: parsed as numeric, "
                    f"{non_null - coerced.notna().sum()} values became null"
                )

    return out, warnings


def drop_degenerate_columns(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Remove columns a generator cannot learn anything from."""
    warnings: list[str] = []
    to_drop: list[str] = []

    for column in frame.columns:
        series = frame[column]
        null_rate = float(series.isna().mean())
        if null_rate >= 0.95:
            to_drop.append(column)
            warnings.append(f"{column}: dropped, {null_rate * 100:.1f} percent null")
            continue
        if series.nunique(dropna=True) <= 1:
            to_drop.append(column)
            warnings.append(f"{column}: dropped, single value across the cohort")
            continue
        # A column with a unique value in every row is an identifier by
        # structure even when its name gives nothing away.
        if series.nunique(dropna=True) == len(series) and series.dtype == object:
            to_drop.append(column)
            warnings.append(f"{column}: dropped, unique per row and likely an identifier")

    return frame.drop(columns=to_drop), warnings


def process_seed(
    content: bytes | None = None,
    filename: str | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> tuple[pd.DataFrame, SeedProfile]:
    """Full parse and clean pass. Returns the frame and what was done to it."""
    if rows is not None:
        frame = pd.DataFrame.from_records(rows)
    elif content is not None and filename is not None:
        frame = read_tabular(content, filename)
    else:
        raise ValueError("provide either an uploaded file or a list of rows")

    if frame.empty:
        raise ValueError("seed data contains no rows")

    frame.columns = [normalise_column_name(c) for c in frame.columns]

    # Deduplicate names created by normalisation before anything indexes by
    # column, since pandas will happily hold two columns called `age`.
    seen: dict[str, int] = {}
    renamed: list[str] = []
    for column in frame.columns:
        if column in seen:
            seen[column] += 1
            renamed.append(f"{column}_{seen[column]}")
        else:
            seen[column] = 0
            renamed.append(column)
    frame.columns = renamed

    frame, identifiers, free_text = strip_identifiers(frame)
    frame, coercion_warnings = coerce_types(frame)
    frame, degenerate_warnings = drop_degenerate_columns(frame)

    if frame.empty or len(frame.columns) == 0:
        raise ValueError("no modellable features remain after cleaning the seed data")

    numeric = [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]
    categorical = [c for c in frame.columns if c not in numeric]

    warnings = coercion_warnings + degenerate_warnings
    if identifiers:
        warnings.append(
            f"Direct identifiers removed before modelling: {', '.join(identifiers)}"
        )
    if len(frame) < 100:
        warnings.append(
            f"Seed cohort has only {len(frame)} rows. Generated output will track "
            "sampling noise in the seed rather than the underlying population."
        )

    profile = SeedProfile(
        rows=int(len(frame)),
        columns=int(len(frame.columns)),
        feature_names=list(frame.columns),
        numeric_features=numeric,
        categorical_features=categorical,
        dropped_identifiers=identifiers,
        dropped_free_text=free_text,
        null_rates={c: round(float(frame[c].isna().mean()), 4) for c in frame.columns},
        warnings=warnings,
    )

    return frame, profile


def reference_cohort(n: int = 5000, seed: int = 20260816) -> pd.DataFrame:
    """A stand in reference population for demos with no seed upload.

    Parameters are set from published population level summary statistics for
    a type 2 diabetes cardiovascular outcomes population, which is a common
    feasibility target. It is a demo fixture and nothing else: it is not
    derived from any patient record and it should not be used to justify a
    feasibility conclusion.
    """
    rng = np.random.default_rng(seed)

    age = rng.normal(63.5, 10.2, n).clip(18, 94)
    sex = rng.choice(["female", "male"], n, p=[0.451, 0.549])
    bmi = rng.normal(31.8, 5.6, n).clip(15, 62)
    # eGFR falls with age. Modelling the dependency rather than the marginal
    # alone is what makes the correlation check meaningful on demo data.
    egfr = (140 - age) * rng.normal(1.0, 0.18, n) - (bmi - 30) * 0.35
    egfr = egfr.clip(8, 140)
    hba1c = rng.gamma(shape=11.0, scale=0.72, size=n).clip(4.5, 16.0)
    sbp = rng.normal(134, 16, n).clip(85, 210) + (bmi - 30) * 0.4
    on_insulin = rng.random(n) < (0.18 + 0.03 * (hba1c - 7.0)).clip(0.02, 0.85)

    return pd.DataFrame(
        {
            "age": np.rint(age).astype("int64"),
            "sex": sex,
            "bmi": np.round(bmi, 1),
            "egfr": np.round(egfr, 1),
            "hba1c": np.round(hba1c, 2),
            "systolic_bp": np.rint(sbp).astype("int64"),
            "on_insulin": on_insulin.astype(bool),
            "ecog_status": rng.choice([0, 1, 2], n, p=[0.55, 0.33, 0.12]),
            "prior_cv_event": rng.random(n) < 0.31,
        }
    )
