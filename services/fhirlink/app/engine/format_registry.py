"""Export formats FHIR-Link can produce.

A registry rather than a chain of if statements because the frontend export
panel is driven from it: /formats returns this list and the UI renders
whatever is in it. Adding a format is one entry here plus one writer, with no
frontend change.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass
from typing import Any, Callable

import pandas as pd

from .bundle_builder import Bundle, BundleReport, bundle_to_dict, bundle_to_ndjson


@dataclass(frozen=True)
class ExportFormat:
    id: str
    label: str
    media_type: str
    extension: str
    description: str
    bundle_type: str | None = None
    fhir: bool = True
    streamable: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


FORMATS: dict[str, ExportFormat] = {
    "fhir_r4_collection": ExportFormat(
        id="fhir_r4_collection",
        label="FHIR R4 collection bundle",
        media_type="application/fhir+json",
        extension="json",
        description=(
            "One JSON bundle holding every Patient and Observation. Right for "
            "review, for handing to an analyst, and for import tools that read "
            "a whole file."
        ),
        bundle_type="collection",
    ),
    "fhir_r4_transaction": ExportFormat(
        id="fhir_r4_transaction",
        label="FHIR R4 transaction bundle",
        media_type="application/fhir+json",
        extension="json",
        description=(
            "Every entry carries a PUT request, so the bundle can be posted to "
            "a FHIR server root and ingested in one call. Re-posting updates in "
            "place rather than duplicating."
        ),
        bundle_type="transaction",
    ),
    "fhir_r4_ndjson": ExportFormat(
        id="fhir_r4_ndjson",
        label="FHIR R4 NDJSON",
        media_type="application/fhir+ndjson",
        extension="ndjson",
        description=(
            "One resource per line, the FHIR Bulk Data shape. The right choice "
            "above roughly 10,000 patients, where a single bundle stops being "
            "practical to parse."
        ),
        bundle_type="collection",
        streamable=True,
    ),
    "csv_flat": ExportFormat(
        id="csv_flat",
        label="Flat CSV",
        media_type="text/csv",
        extension="csv",
        description=(
            "The cohort as delivered, one row per patient, no FHIR structure. "
            "For statisticians who want the table and nothing else."
        ),
        fhir=False,
    ),
}

DEFAULT_FORMAT = "fhir_r4_collection"


def list_formats() -> list[dict[str, Any]]:
    return [fmt.as_dict() for fmt in FORMATS.values()]


def get_format(format_id: str | None) -> ExportFormat:
    resolved = format_id or DEFAULT_FORMAT
    if resolved not in FORMATS:
        raise ValueError(
            f"unknown export format '{resolved}'. "
            f"Available: {', '.join(sorted(FORMATS))}"
        )
    return FORMATS[resolved]


def render_bundle(bundle: Bundle, fmt: ExportFormat) -> str:
    """Serialise a built bundle into the requested format."""
    if fmt.id == "fhir_r4_ndjson":
        return bundle_to_ndjson(bundle)
    return json.dumps(bundle_to_dict(bundle), indent=2)


def render_csv(rows: list[dict[str, Any]]) -> str:
    """Flat CSV straight from the cohort rows, bypassing FHIR entirely."""
    if not rows:
        return ""
    frame = pd.DataFrame.from_records(rows)
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    return buffer.getvalue()


def filename_for(cohort_id: str, fmt: ExportFormat) -> str:
    return f"pretrial-cohort-{cohort_id}.{fmt.extension}"


def summarise(
    report: BundleReport | dict[str, Any], fmt: ExportFormat, payload_bytes: int
) -> dict[str, Any]:
    """Takes either a BundleReport or an already flattened report dict.

    The CSV path has no bundle to report on and synthesises the block itself,
    so both shapes reach this function.
    """
    return {
        "format": fmt.as_dict(),
        "bundle": report if isinstance(report, dict) else report.as_dict(),
        "size_bytes": payload_bytes,
    }
