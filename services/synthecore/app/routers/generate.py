"""Cohort generation endpoints.

POST /generate enqueues and returns immediately with a job id. Progress is
read back either by polling GET /jobs/{id} or, preferred, by holding open
GET /jobs/{id}/stream, which is a Server Sent Events feed fed by the Redis
progress channel the worker publishes to.

SSE rather than WebSockets because the traffic is one directional and SSE
survives an ALB and a corporate proxy without special handling. A pharma
network is not a place to discover that WebSocket upgrades are filtered.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from ..engine.seed_processor import process_seed
from ..envelope import fail, meta_block, ok
from ..progress import ProgressReader, ProgressWriter
from ..schemas import GenerateRequest, GenerateResponse
from ..storage import frame_to_rows, get_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["generation"])
reader = ProgressReader()

# Uploads are read fully into memory to be parsed, so the ceiling is a memory
# ceiling, not a policy preference.
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


@router.post("/generate", response_model=GenerateResponse, summary="Queue a cohort generation job")
async def generate(payload: GenerateRequest, request: Request) -> Any:
    started = time.perf_counter()
    job_id = f"coh_{uuid.uuid4().hex[:12]}"

    writer = ProgressWriter(job_id)
    state = writer.create(message="Queued for generation")

    try:
        from ..celery_app import celery_app

        celery_app.send_task(
            "synthecore.generate_cohort",
            args=[job_id, payload.model_dump(mode="json")],
            task_id=job_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("failed to enqueue job %s", job_id)
        writer.failure("enqueue_failed", "Could not queue the generation job.")
        return fail(
            code="enqueue_failed",
            message="The generation job could not be queued. Check the broker connection.",
            status_code=503,
            details={"exception": type(exc).__name__},
            meta=meta_block(request, started),
        )

    return ok(state.as_dict(), meta_block(request, started, job_id=job_id))


@router.get("/jobs", summary="Recent generation jobs")
async def list_jobs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    status: str | None = Query(default=None),
) -> Any:
    """List jobs, newest first.

    Backed by a Redis key scan, which is correct at the scale a single
    deployment runs and wrong at the scale a multi tenant account will. The
    replacement is the Postgres `cohort_jobs` table, which is where job
    records belong once they need to be queried by sponsor, protocol, or
    date range rather than just listed. Redis remains the progress
    transport either way.
    """
    started = time.perf_counter()

    summaries: list[dict[str, Any]] = []
    async for key in reader.client.scan_iter(match="cohort:job:*", count=200):
        raw = await reader.client.get(key)
        if not raw:
            continue
        state = json.loads(raw)
        if status and state.get("status") != status:
            continue

        result = state.get("result") or {}
        validation = result.get("validation") or {}
        summaries.append(
            {
                "job_id": state.get("job_id"),
                "status": state.get("status"),
                "percent": state.get("percent"),
                "stage_label": state.get("stage_label"),
                "message": state.get("message"),
                "created_at": state.get("created_at"),
                "updated_at": state.get("updated_at"),
                "cohort_size": result.get("cohort_size"),
                "features": len(result.get("features") or []),
                "engine": (result.get("engine") or {}).get("name"),
                "is_stub": (result.get("engine") or {}).get("is_stub"),
                "overall_fidelity": validation.get("overall_fidelity"),
                "grade": validation.get("grade"),
                "duration_seconds": result.get("duration_seconds"),
            }
        )

    summaries.sort(key=lambda item: item.get("created_at") or 0, reverse=True)

    return ok(
        {"jobs": summaries[:limit]},
        meta_block(request, started, total=len(summaries), returned=min(limit, len(summaries))),
    )


@router.get("/jobs/{job_id}", response_model=GenerateResponse, summary="Current job state")
async def job_status(job_id: str, request: Request) -> Any:
    started = time.perf_counter()
    state = await reader.get(job_id)
    if state is None:
        return fail(
            code="job_not_found",
            message=f"No job with id '{job_id}'.",
            status_code=404,
            meta=meta_block(request, started),
        )
    return ok(state, meta_block(request, started))


@router.get("/jobs/{job_id}/stream", summary="Live job progress as Server Sent Events")
async def job_stream(job_id: str, request: Request) -> Any:
    state = await reader.get(job_id)
    if state is None:
        return fail(
            code="job_not_found",
            message=f"No job with id '{job_id}'.",
            status_code=404,
            meta=meta_block(request),
        )

    async def event_source():
        try:
            async for update in reader.stream(job_id):
                yield f"event: progress\ndata: {json.dumps(update)}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.warning("progress stream for %s ended: %s", job_id, exc)
            error = {"code": "stream_interrupted", "message": str(exc)}
            yield f"event: error\ndata: {json.dumps(error)}\n\n"
        finally:
            yield "event: close\ndata: {}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Nginx and most reverse proxies buffer by default, which holds
            # every stage update until the response closes and makes the live
            # progress view useless.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/jobs/{job_id}/cohort", summary="Generated cohort rows")
async def job_cohort(
    job_id: str,
    request: Request,
    limit: int = Query(default=1000, ge=1, le=100_000),
    offset: int = Query(default=0, ge=0),
) -> Any:
    started = time.perf_counter()
    frame = get_store().get_cohort(job_id)
    if frame is None:
        return fail(
            code="cohort_not_found",
            message=f"No stored cohort for job '{job_id}'.",
            status_code=404,
            meta=meta_block(request, started),
        )

    window = frame.iloc[offset : offset + limit]
    return ok(
        {
            "job_id": job_id,
            "features": list(frame.columns),
            "rows": frame_to_rows(window),
        },
        meta_block(request, started, total_rows=int(len(frame)), offset=offset, limit=limit),
    )


@router.post("/seed/upload", summary="Upload and profile a seed cohort file")
async def upload_seed(request: Request, file: UploadFile = File(...)) -> Any:
    """Parse, clean, and store a seed file, returning the profile only.

    The rows themselves never come back in the response. The caller gets the
    object key and a description of what was parsed, which is everything the
    cohort builder needs and none of the patient data.
    """
    started = time.perf_counter()

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        return fail(
            code="upload_too_large",
            message=f"Seed files are capped at {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
            status_code=413,
            meta=meta_block(request, started),
        )

    try:
        frame, profile = process_seed(content=content, filename=file.filename or "seed.csv")
    except ValueError as exc:
        return fail(
            code="seed_parse_failed",
            message=str(exc),
            status_code=422,
            meta=meta_block(request, started),
        )

    key = f"seed_{uuid.uuid4().hex[:12]}_{file.filename or 'seed.csv'}"
    store = get_store()
    location = store.put_seed(key, content) if hasattr(store, "put_seed") else None

    return ok(
        {
            "seed_object_key": key,
            "storage": {"backend": store.backend, "location": location},
            "profile": profile.as_dict(),
            "sample_schema": {
                column: str(frame[column].dtype) for column in frame.columns
            },
        },
        meta_block(request, started),
    )
