"""Export endpoints.

POST /export returns the serialised bundle as a downloadable body.
POST /export/preview returns a small bundle inline, for the UI preview pane.
GET  /formats drives the format selector in the export panel.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from ..engine.bundle_builder import build_bundle
from ..engine.format_registry import (
    filename_for,
    get_format,
    list_formats,
    render_bundle,
    render_csv,
    summarise,
)
from ..envelope import fail, meta_block, ok
from ..schemas import (
    MIN_FIDELITY_TO_EXPORT,
    ExportRequest,
    ExportResponse,
    PreviewRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["export"])


@router.get("/formats", summary="Export formats this gateway can produce")
async def formats(request: Request) -> Any:
    started = time.perf_counter()
    return ok({"formats": list_formats()}, meta_block(request, started))


@router.post("/export", response_model=ExportResponse, summary="Export a cohort")
async def export(payload: ExportRequest, request: Request) -> Any:
    started = time.perf_counter()

    try:
        fmt = get_format(payload.format)
    except ValueError as exc:
        return fail("unknown_format", str(exc), 422, meta=meta_block(request, started))

    # A cohort that failed validation can still be exported, but only on an
    # explicit acknowledgement, and the acknowledgement goes in the response
    # meta so it lands in the audit log alongside the export itself.
    if (
        payload.fidelity_score is not None
        and payload.fidelity_score < MIN_FIDELITY_TO_EXPORT
        and not payload.acknowledge_low_fidelity
    ):
        return fail(
            code="fidelity_below_export_floor",
            message=(
                f"Cohort fidelity is {payload.fidelity_score:.1f} percent, below the "
                f"{MIN_FIDELITY_TO_EXPORT:.0f} percent export floor. Re-send with "
                "acknowledge_low_fidelity set to true to export it anyway."
            ),
            status_code=409,
            details={
                "fidelity_score": payload.fidelity_score,
                "floor": MIN_FIDELITY_TO_EXPORT,
            },
            meta=meta_block(request, started),
        )

    try:
        if not fmt.fhir:
            body = render_csv(payload.rows)
            report_block = {
                "patients": len(payload.rows),
                "observations": 0,
                "mapped_features": [],
                "unmapped_features": [],
                "skipped_features": [],
                "warnings": [
                    "CSV export carries no FHIR structure and no synthetic data "
                    "marker. Only the FHIR formats tag the output as test data."
                ],
            }
        else:
            bundle, report = build_bundle(
                rows=payload.rows,
                cohort_id=payload.cohort_id,
                bundle_type=fmt.bundle_type or "collection",
                as_of=payload.as_of,
                include_observations=payload.include_observations,
            )
            body = render_bundle(bundle, fmt)
            report_block = report.as_dict()
    except Exception as exc:  # noqa: BLE001
        logger.exception("export failed for cohort %s", payload.cohort_id)
        return fail(
            code="export_failed",
            message="The cohort could not be converted to the requested format.",
            status_code=500,
            details={"exception": type(exc).__name__, "reason": str(exc)},
            meta=meta_block(request, started),
        )

    payload_bytes = len(body.encode("utf-8"))

    return ok(
        {
            "cohort_id": payload.cohort_id,
            "filename": filename_for(payload.cohort_id, fmt),
            "media_type": fmt.media_type,
            "content": body,
            **summarise(report_block, fmt, payload_bytes),
        },
        meta_block(
            request,
            started,
            rows=len(payload.rows),
            format=fmt.id,
            fidelity_score=payload.fidelity_score,
            low_fidelity_acknowledged=payload.acknowledge_low_fidelity,
        ),
    )


@router.post("/export/download", summary="Export a cohort as a file body")
async def export_download(payload: ExportRequest, request: Request) -> Any:
    """Same conversion as /export, returned as the raw file rather than JSON.

    Kept separate so the browser can stream a large bundle straight to disk
    instead of holding the whole thing in memory as a JSON string field.
    """
    result = await export(payload, request)
    if not isinstance(result, dict):
        return result

    data = result["data"]
    return PlainTextResponse(
        content=data["content"],
        media_type=data["media_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{data["filename"]}"',
            "X-Pretrial-Cohort-Id": payload.cohort_id,
        },
    )


@router.post("/export/preview", summary="Render the first few patients as a bundle")
async def export_preview(payload: PreviewRequest, request: Request) -> Any:
    started = time.perf_counter()

    try:
        fmt = get_format(payload.format)
    except ValueError as exc:
        return fail("unknown_format", str(exc), 422, meta=meta_block(request, started))

    subset = payload.rows[: payload.limit]

    if not fmt.fhir:
        content = render_csv(subset)
        return ok(
            {
                "cohort_id": payload.cohort_id,
                "format": fmt.as_dict(),
                "content": content,
                "patients_in_preview": len(subset),
                "patients_total": len(payload.rows),
            },
            meta_block(request, started),
        )

    bundle, report = build_bundle(
        rows=subset,
        cohort_id=payload.cohort_id,
        bundle_type=fmt.bundle_type or "collection",
        as_of=payload.as_of,
    )

    return ok(
        {
            "cohort_id": payload.cohort_id,
            "format": fmt.as_dict(),
            "content": render_bundle(bundle, fmt),
            "bundle": report.as_dict(),
            "patients_in_preview": len(subset),
            "patients_total": len(payload.rows),
        },
        meta_block(request, started),
    )
