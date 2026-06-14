"""Spore FastAPI application entrypoint.

Story 1.1: stand up the stack — exposes GET /health for the docker-compose
healthcheck and a request-id logging middleware used by later stories.
"""

import logging
import time
import uuid

from fastapi import FastAPI, Request

from app.routers import capture as capture_router
from app.routers import devices as devices_router
from app.routers import internal as internal_router
from app.routers import pipeline as pipeline_router
from app.routers import review as review_router
from app.routers import skills as skills_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("spore")

app = FastAPI(title="Spore API")
app.include_router(capture_router.router)
app.include_router(devices_router.router)
app.include_router(internal_router.router)
app.include_router(pipeline_router.router)
app.include_router(review_router.router)
app.include_router(skills_router.router)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    request.state.request_id = request_id
    start = time.monotonic()

    response = await call_next(request)

    duration_ms = (time.monotonic() - start) * 1000
    response.headers["x-request-id"] = request_id
    logger.info(
        "request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
        },
    )
    return response


@app.get("/health")
async def health():
    return {"ok": True, "data": {"status": "healthy"}, "error": None}
