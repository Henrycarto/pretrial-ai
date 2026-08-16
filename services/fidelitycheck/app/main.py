"""FidelityCheck service entrypoint.

Statistical validation of a synthetic cohort against a reference cohort.
This service holds no state and no patient data between requests: datasets
arrive in the request body, the report goes back in the response, nothing is
written to disk. Persistence of reports is the caller's job, which keeps the
retention decision with the system that owns the audit log.
"""

from __future__ import annotations

import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from .envelope import SERVICE_NAME, SERVICE_VERSION, fail, meta_block, ok
from .routers import validate

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="Pretrial.ai FidelityCheck",
    version=SERVICE_VERSION,
    description=(
        "Statistical validation of synthetic patient cohorts. Kolmogorov-Smirnov "
        "per feature, Jensen-Shannon divergence, and correlation matrix comparison, "
        "aggregated into a single fidelity score."
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

app.include_router(validate.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Pydantic errors go out in the same envelope as everything else."""
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
    return ok(
        {"status": "ok", "service": SERVICE_NAME},
        meta_block(request, started),
    )


@app.get("/", include_in_schema=False)
async def root(request: Request):
    return ok(
        {
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "endpoints": ["/validate", "/validate/preview", "/health", "/docs"],
        },
        meta_block(request),
    )
