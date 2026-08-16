"""SyntheCore service entrypoint.

Generates synthetic patient cohorts and tracks the jobs that produce them.
The API process does no generation work itself: it validates the request,
enqueues, and serves progress. All computation happens in the Celery worker,
which runs the same image with a different command.
"""

from __future__ import annotations

import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from .engine.ctgan_pipeline import generator_info, load_generator
from .envelope import SERVICE_NAME, SERVICE_VERSION, fail, meta_block, ok
from .routers import generate

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="Pretrial.ai SyntheCore",
    version=SERVICE_VERSION,
    description=(
        "Synthetic patient cohort generation. Seed parsing, generative model "
        "sampling, and inclusion and exclusion screening, run as async jobs."
    ),
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if o.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(generate.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return fail(
        code="request_validation_failed",
        message="The request body did not match the expected shape.",
        status_code=422,
        details=exc.errors(),
        meta=meta_block(request),
    )


@app.get("/health", summary="Liveness and readiness probe")
async def health(request: Request):
    started = time.perf_counter()
    return ok({"status": "ok", "service": SERVICE_NAME}, meta_block(request, started))


@app.get("/engine", summary="Which generation engine this deployment is running")
async def engine(request: Request):
    """Exposed deliberately.

    A cohort produced by the bootstrap stub and a cohort produced by CTGAN
    are not interchangeable, and the difference has to be visible in the UI
    rather than buried in a deployment variable.
    """
    started = time.perf_counter()
    info = generator_info(load_generator())
    return ok(
        {
            "engine": info.name,
            "is_stub": info.is_stub,
            "method": info.detail,
            "warning": (
                "This deployment is running the placeholder generator. Output is "
                "not releasable and carries no privacy guarantee."
            )
            if info.is_stub
            else None,
        },
        meta_block(request, started),
    )


@app.get("/", include_in_schema=False)
async def root(request: Request):
    return ok(
        {
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "endpoints": [
                "/generate",
                "/jobs/{job_id}",
                "/jobs/{job_id}/stream",
                "/jobs/{job_id}/cohort",
                "/seed/upload",
                "/engine",
                "/health",
                "/docs",
            ],
        },
        meta_block(request),
    )
