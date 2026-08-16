"""Request and response models for FidelityCheck."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# Guard rails on the synchronous endpoint. Anything larger belongs in the
# Celery path, where the caller gets a job id instead of blocking on an HTTP
# request for minutes.
MAX_ROWS = 200_000
MIN_ROWS = 8


class ValidateRequest(BaseModel):
    real: list[dict[str, Any]] = Field(
        ..., description="Reference cohort rows. One object per patient."
    )
    synthetic: list[dict[str, Any]] = Field(
        ..., description="Generated cohort rows. Same column names as the reference."
    )
    features: list[str] | None = Field(
        default=None,
        description=(
            "Restrict the comparison to these columns. Omit to compare every "
            "column the two datasets share."
        ),
    )
    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)
    bins: int | None = Field(
        default=None,
        ge=2,
        le=256,
        description=(
            "Histogram bin count for the divergence test. Omit to derive it "
            "from the pooled sample."
        ),
    )
    correlation_method: Literal["pearson", "spearman"] = "pearson"
    preview_features: int = Field(
        default=5,
        ge=0,
        le=50,
        description="How many distribution comparison charts to return.",
    )
    cohort_id: str | None = Field(
        default=None, description="Links the report to a SyntheCore generation job."
    )

    @model_validator(mode="after")
    def check_sizes(self) -> "ValidateRequest":
        if len(self.real) < MIN_ROWS:
            raise ValueError(f"real must contain at least {MIN_ROWS} rows")
        if len(self.synthetic) < MIN_ROWS:
            raise ValueError(f"synthetic must contain at least {MIN_ROWS} rows")
        if len(self.real) > MAX_ROWS or len(self.synthetic) > MAX_ROWS:
            raise ValueError(
                f"each dataset is capped at {MAX_ROWS} rows on the synchronous endpoint"
            )
        return self


class FeatureFidelityModel(BaseModel):
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


class DistributionPreviewModel(BaseModel):
    feature: str
    kind: str
    fidelity: float
    bins: list[str]
    real: list[float]
    synthetic: list[float]
    bin_edges: list[float] = Field(default_factory=list)


class FidelityReportModel(BaseModel):
    overall_fidelity: float
    raw_fidelity: float
    grade: Literal["pass", "borderline", "fail"]
    verdict: str
    components: dict[str, Any]
    weights: dict[str, float]
    schema_alignment: dict[str, Any] = Field(
        ..., description="Which columns matched, and which did not."
    )
    features: list[FeatureFidelityModel]
    ks_results: list[dict[str, Any]]
    js_results: list[dict[str, Any]]
    correlation: dict[str, Any]
    distribution_previews: list[DistributionPreviewModel]
    distribution_preview_ranking: str
    row_counts: dict[str, int]
    warnings: list[str]
    thresholds: dict[str, float]
    cohort_id: str | None = None


class ErrorModel(BaseModel):
    code: str
    message: str
    details: Any = None


class ValidateResponse(BaseModel):
    data: FidelityReportModel | None
    error: ErrorModel | None = None
    meta: dict[str, Any]


class HealthResponse(BaseModel):
    data: dict[str, Any] | None
    error: ErrorModel | None = None
    meta: dict[str, Any]
