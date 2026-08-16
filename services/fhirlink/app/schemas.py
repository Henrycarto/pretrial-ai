"""Request and response models for FHIR-Link."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

MAX_EXPORT_ROWS = 200_000

# Below this the export is refused unless the caller overrides it. An export
# is the point where a cohort leaves the system, and shipping one that failed
# its own validation should take a deliberate act.
MIN_FIDELITY_TO_EXPORT = 70.0


class ExportRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(..., description="Synthetic cohort rows.")
    cohort_id: str = Field(..., min_length=1, max_length=64)
    format: str = Field(default="fhir_r4_collection")
    include_observations: bool = Field(
        default=True,
        description="Set false for a Patient only bundle, which is much smaller.",
    )
    as_of: date | None = Field(
        default=None,
        description=(
            "Reference date for derived birth dates and observation timestamps. "
            "Set it to make an export byte reproducible."
        ),
    )
    fidelity_score: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Overall fidelity from FidelityCheck, recorded with the export.",
    )
    acknowledge_low_fidelity: bool = Field(
        default=False,
        description=(
            "Required to export a cohort scoring below the floor. The "
            "acknowledgement is recorded in the response meta."
        ),
    )

    @model_validator(mode="after")
    def check_rows(self) -> "ExportRequest":
        if not self.rows:
            raise ValueError("rows must not be empty")
        if len(self.rows) > MAX_EXPORT_ROWS:
            raise ValueError(f"exports are capped at {MAX_EXPORT_ROWS} rows per request")
        return self


class PreviewRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(..., min_length=1)
    cohort_id: str = Field(default="preview", min_length=1, max_length=64)
    format: str = Field(default="fhir_r4_collection")
    limit: int = Field(
        default=3,
        ge=1,
        le=25,
        description="How many patients to render in the preview bundle.",
    )
    as_of: date | None = None


class ExportFormatModel(BaseModel):
    id: str
    label: str
    media_type: str
    extension: str
    description: str
    bundle_type: str | None = None
    fhir: bool = True
    streamable: bool = False


class BundleReportModel(BaseModel):
    patients: int
    observations: int
    mapped_features: list[str]
    unmapped_features: list[str]
    skipped_features: list[str]
    warnings: list[str]


class ErrorModel(BaseModel):
    code: str
    message: str
    details: Any = None


class ExportResponse(BaseModel):
    data: dict[str, Any] | None
    error: ErrorModel | None = None
    meta: dict[str, Any]


class FormatsResponse(BaseModel):
    data: dict[str, Any] | None
    error: ErrorModel | None = None
    meta: dict[str, Any]


Compliance = Literal["r4", "r4b"]
