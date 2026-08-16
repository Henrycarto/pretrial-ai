"""Request and response models for SyntheCore."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

MAX_COHORT_SIZE = 500_000
MAX_INLINE_SEED_ROWS = 50_000

Operator = Literal[
    "gt", "gte", "lt", "lte", "eq", "neq", "in", "not_in", "between",
    "is_true", "is_false", "is_null", "not_null",
]


class CriterionModel(BaseModel):
    feature: str = Field(..., description="Column name in the cohort schema.")
    operator: Operator
    value: Any = Field(
        default=None,
        description="Threshold, list, or two element range. Omit for the unary operators.",
    )
    kind: Literal["inclusion", "exclusion"] = "inclusion"
    label: str | None = Field(
        default=None,
        description="Protocol wording for this line. Shown verbatim in the attrition funnel.",
    )


class GenerateRequest(BaseModel):
    cohort_size: int = Field(default=1000, ge=1, le=MAX_COHORT_SIZE)
    criteria: list[CriterionModel] = Field(default_factory=list)
    seed_rows: list[dict[str, Any]] | None = Field(
        default=None, description="Seed cohort inline. Use for small extracts and demos."
    )
    seed_object_key: str | None = Field(
        default=None, description="Key of a previously uploaded seed file in object storage."
    )
    reference_cohort_size: int = Field(
        default=5000,
        ge=100,
        le=100_000,
        description=(
            "Size of the built in demo population, used only when no seed data "
            "is supplied."
        ),
    )
    preview_features: int = Field(default=5, ge=0, le=50)
    trial_name: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def check_seed(self) -> "GenerateRequest":
        if self.seed_rows is not None and self.seed_object_key is not None:
            raise ValueError("provide seed_rows or seed_object_key, not both")
        if self.seed_rows is not None and len(self.seed_rows) > MAX_INLINE_SEED_ROWS:
            raise ValueError(
                f"inline seed data is capped at {MAX_INLINE_SEED_ROWS} rows. "
                "Upload the file and pass seed_object_key instead."
            )
        return self


class StageModel(BaseModel):
    key: str
    label: str
    status: Literal["pending", "running", "done", "failed"]
    started_at: float | None = None
    finished_at: float | None = None
    detail: str | None = None


class JobStateModel(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    stage: str | None = None
    stage_label: str | None = None
    stage_index: int = -1
    stage_count: int = 4
    percent: float = 0.0
    message: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    stages: list[StageModel] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class ErrorModel(BaseModel):
    code: str
    message: str
    details: Any = None


class GenerateResponse(BaseModel):
    data: JobStateModel | None
    error: ErrorModel | None = None
    meta: dict[str, Any]


class SeedUploadResponse(BaseModel):
    data: dict[str, Any] | None
    error: ErrorModel | None = None
    meta: dict[str, Any]
