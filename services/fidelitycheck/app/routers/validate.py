"""POST /validate. Runs the full fidelity comparison and returns the report."""

from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from ..engine.report_builder import FidelityReport, build_report
from ..envelope import fail, meta_block, ok
from ..schemas import ValidateRequest, ValidateResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["validation"])


def _to_frame(rows: list[dict[str, Any]], label: str) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(rows)
    if frame.empty:
        raise ValueError(f"{label} produced an empty table")
    return frame


def _run(payload: ValidateRequest) -> FidelityReport:
    real = _to_frame(payload.real, "real")
    synthetic = _to_frame(payload.synthetic, "synthetic")
    return build_report(
        real=real,
        synthetic=synthetic,
        features=payload.features,
        alpha=payload.alpha,
        bins=payload.bins,
        correlation_method=payload.correlation_method,
        preview_features=payload.preview_features,
    )


@router.post(
    "/validate",
    response_model=ValidateResponse,
    summary="Score a synthetic cohort against a reference cohort",
)
async def validate(payload: ValidateRequest, request: Request) -> Any:
    started = time.perf_counter()

    try:
        # scipy and pandas hold the GIL for long stretches on a large cohort.
        # Off the event loop so one validation cannot stall every other
        # request on the worker.
        report = await run_in_threadpool(_run, payload)
    except ValueError as exc:
        return fail(
            code="invalid_dataset",
            message=str(exc),
            status_code=422,
            meta=meta_block(request, started),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("validation failed")
        return fail(
            code="validation_failed",
            message="The comparison could not be completed.",
            status_code=500,
            details={"reason": type(exc).__name__},
            meta=meta_block(request, started),
        )

    body = report.as_dict()
    # Pydantic v2 reserves `schema` on BaseModel, so the alignment block is
    # exposed under a name that does not shadow it.
    body["schema_alignment"] = body.pop("schema")
    body["cohort_id"] = payload.cohort_id

    return ok(
        body,
        meta_block(
            request,
            started,
            rows_real=len(payload.real),
            rows_synthetic=len(payload.synthetic),
            features_compared=len(report.features),
        ),
    )


@router.post(
    "/validate/preview",
    summary="Schema alignment and row counts only, without running the tests",
)
async def validate_preview(payload: ValidateRequest, request: Request) -> Any:
    """Cheap pre-flight so the UI can warn about column mismatches on upload."""
    started = time.perf_counter()

    from ..engine.features import align_schema, classify_feature

    real = pd.DataFrame.from_records(payload.real)
    synthetic = pd.DataFrame.from_records(payload.synthetic)
    alignment = align_schema(real, synthetic, payload.features)
    kinds = {c: classify_feature(real[c], synthetic[c]).value for c in alignment.shared}

    return ok(
        {
            "shared": alignment.shared,
            "real_only": alignment.real_only,
            "synthetic_only": alignment.synthetic_only,
            "coverage": alignment.coverage,
            "feature_kinds": kinds,
            "warnings": alignment.warnings,
            "row_counts": {"real": len(real), "synthetic": len(synthetic)},
        },
        meta_block(request, started),
    )
