"""
backend/main.py
────────────────
FastAPI application entrypoint for the Datify backend.

Start the server with:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

Endpoints
─────────
    POST /upload           — Accept CSV, profile it, return schema + session path.
    POST /query            — Run the Claude agent against a previously uploaded CSV.
    POST /rollback         — Restore dataset to last saved checkpoint.
    GET  /health           — Liveness probe.
    GET  /sandbox/health   — Verify Docker daemon connectivity and image availability.
"""

from __future__ import annotations

import logging
import os
import tempfile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

import docker
import docker.errors
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.routers import api
from backend.schemas import HealthResponse, SandboxHealthResponse

logger = logging.getLogger(__name__)

# ── FastAPI app ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Datify Backend",
    description=(
        "Autonomous, privacy-first Data Scientist Copilot API — "
        "powered by Claude and sandboxed Docker execution."
    ),
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────

app.include_router(api.router)


# ── Health Endpoints ───────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Liveness probe — always returns 200 if the server is up."""
    return HealthResponse(status="ok", app="Datify Backend", version="0.3.0")


@app.get("/sandbox/health", response_model=SandboxHealthResponse)
def sandbox_health() -> SandboxHealthResponse:
    """
    Verify that the Docker daemon is reachable and that the sandbox image
    (``SANDBOX_IMAGE``) is available locally.
    """
    try:
        client = docker.from_env()
        client.ping()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Docker daemon unreachable: {exc}",
        )

    try:
        client.images.get(settings.SANDBOX_IMAGE)
    except docker.errors.ImageNotFound:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Sandbox image '{settings.SANDBOX_IMAGE}' not found locally. "
                f"Build it with: docker build -t {settings.SANDBOX_IMAGE} ./backend"
            ),
        )

    return SandboxHealthResponse(
        status="ok",
        sandbox_image=settings.SANDBOX_IMAGE,
        mem_limit=settings.SANDBOX_MEM_LIMIT,
        timeout_sec=settings.SANDBOX_TIMEOUT_SEC,
    )
