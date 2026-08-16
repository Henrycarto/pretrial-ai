"""Response envelope shared by every Pretrial.ai service.

Every response, success or failure, is { data, error, meta }. The frontend
never has to branch on status code shape, and audit tooling can read the
meta block off any recorded response without knowing which service produced
it.

This file is duplicated in each service on purpose. The services build
independent Docker images and a shared Python package would force a common
build context for the sake of forty lines.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

SERVICE_NAME = "fidelitycheck"
SERVICE_VERSION = "0.1.0"


def request_id(request: Request | None = None) -> str:
    if request is not None:
        existing = request.headers.get("x-request-id")
        if existing:
            return existing
    return f"req_{uuid.uuid4().hex[:16]}"


def meta_block(
    request: Request | None = None,
    started_at: float | None = None,
    **extra: Any,
) -> dict[str, Any]:
    block: dict[str, Any] = {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "request_id": request_id(request),
    }
    if started_at is not None:
        block["duration_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
    block.update(extra)
    return block


def ok(data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"data": data, "error": None, "meta": meta or meta_block()}


def fail(
    code: str,
    message: str,
    status_code: int = 400,
    details: Any = None,
    meta: dict[str, Any] | None = None,
) -> JSONResponse:
    # jsonable_encoder rather than handing the dict straight to JSONResponse.
    # Pydantic validation errors carry the original exception object inside
    # their ctx, and plain json.dumps raises on it, which turns a 422 into an
    # unhandled 500 and hides the actual problem from the caller.
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            {
                "data": None,
                "error": {"code": code, "message": message, "details": details},
                "meta": meta or meta_block(),
            },
            custom_encoder={Exception: str},
        ),
    )
