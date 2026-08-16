"""FHIR-Link service entrypoint.

The compliance export gateway. Takes a validated synthetic cohort and emits
FHIR R4 Patient bundles that a hospital network or a CTMS can ingest.

Like FidelityCheck, this service is stateless. Rows arrive in the request,
the bundle goes back in the response, nothing is retained.
"""

from __future__ import annotations

import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from .engine.bundle_builder import FEATURE_MAP
from .envelope import SERVICE_NAME, SERVICE_VERSION, fail, meta_block, ok
from .routers import export
from .schemas import MIN_FIDELITY_TO_EXPORT

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="Pretrial.ai FHIR-Link",
    version=SERVICE_VERSION,
    description=(
        "Compliance export gateway. Converts validated synthetic cohorts into "
        "FHIR R4 Patient bundles, tagged as test health data."
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

app.include_router(export.router)


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


@app.get("/terminology", summary="Feature to LOINC mappings this gateway applies")
async def terminology(request: Request):
    """Published so an integration partner can review the map before ingesting.

    Anything not in this list still exports, under the Pretrial.ai local code
    system, and the export report names it.
    """
    started = time.perf_counter()
    return ok(
        {
            "mappings": [
                {
                    "feature": feature,
                    "system": spec.system,
                    "code": spec.code,
                    "display": spec.display,
                    "unit": spec.unit,
                    "ucum": spec.ucum,
                    "category": spec.category,
                }
                for feature, spec in sorted(FEATURE_MAP.items())
            ],
            "notice": (
                "Starter terminology map. It has not been through a formal "
                "terminology review and should be checked against the receiving "
                "system's value sets before production ingestion."
            ),
        },
        meta_block(request, started, mapped_features=len(FEATURE_MAP)),
    )


@app.get("/", include_in_schema=False)
async def root(request: Request):
    return ok(
        {
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "fhir_version": "R4 (built on the R4B resource models, wire identical "
            "for Patient, Observation, and Bundle)",
            "export_fidelity_floor": MIN_FIDELITY_TO_EXPORT,
            "endpoints": [
                "/export",
                "/export/download",
                "/export/preview",
                "/formats",
                "/terminology",
                "/health",
                "/docs",
            ],
        },
        meta_block(request),
    )
