"""
backend/main.py
────────────────
FastAPI application entrypoint for the Datify backend.

Start the server with:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

Endpoints
─────────
    POST /analyze          — Profile CSV, call Claude agent, return ECharts config.
    POST /rollback         — Restore dataset to last saved checkpoint.
    GET  /health           — Liveness probe.
    GET  /sandbox/health   — Verify Docker daemon connectivity and image availability.
"""

from __future__ import annotations

import logging
import os

import docker
import docker.errors
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from backend.agent import run_agent
from backend.config import settings
from backend.database import create_checkpoint, rollback_checkpoint
from backend.profiler import DataProfiler

logger = logging.getLogger(__name__)

# ── FastAPI app ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Datify Backend",
    description=(
        "Autonomous, privacy-first Data Scientist Copilot API — "
        "powered by Claude and sandboxed Docker execution."
    ),
    version="0.2.0",
)

# ── Request / response models ──────────────────────────────────────────────────


class AnalysisRequest(BaseModel):
    query: str
    file_path: str
    session_id: str = "default_session"


class RollbackRequest(BaseModel):
    file_path: str
    session_id: str = "default_session"


# ── Endpoints ──────────────────────────────────────────────────────────────────


@app.post("/analyze")
async def analyze_dataset(request: AnalysisRequest):
    """
    Main endpoint for analyzing the dataset.

    1. Validates that the CSV exists on disk.
    2. Saves a rollback checkpoint for undo support.
    3. Profiles the dataset (PII-masking via DataProfiler).
    4. Invokes the Claude agent — code runs in a DockerSandbox.
    5. Returns the ECharts config and execution metadata.
    """
    if not os.path.exists(request.file_path):
        raise HTTPException(
            status_code=404,
            detail=f"Dataset file not found at: {request.file_path}",
        )

    # Checkpoint — non-fatal on failure.
    try:
        checkpoint_path = create_checkpoint(request.session_id, request.file_path)
        logger.info("Checkpoint created: %s", checkpoint_path)
    except Exception as exc:
        logger.warning("Checkpoint creation failed (continuing): %s", exc)

    # Profile.
    try:
        profiler = DataProfiler(request.file_path)
        schema_json = profiler.to_json()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to profile dataset: {exc}",
        )

    # Agent.
    result = run_agent(
        query=request.query,
        schema_json=schema_json,
        csv_path=request.file_path,
    )

    if result.get("status") == "error" and "API Key" in result.get("message", ""):
        raise HTTPException(status_code=400, detail=result["message"])

    return {
        "status": result.get("status"),
        "message": result.get("message", "Analysis completed successfully."),
        "python_code": result.get("python_code", ""),
        "chart_json": result.get("chart_json", {}),
        "attempts": result.get("attempts", 1),
    }


@app.post("/rollback")
async def rollback_dataset(request: RollbackRequest):
    """
    Roll back the active dataset file to the last saved checkpoint for the session.
    """
    if not os.path.exists(request.file_path):
        raise HTTPException(
            status_code=404,
            detail=f"Active dataset file not found at: {request.file_path}",
        )

    try:
        restored_path = rollback_checkpoint(request.session_id, request.file_path)
        return {
            "status": "success",
            "message": f"Dataset rolled back to checkpoint: {restored_path}",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Rollback failed: {exc}")


@app.get("/health")
def health_check():
    """Liveness probe — always returns 200 if the server is up."""
    return {"status": "ok", "app": "Datify Backend", "version": "0.2.0"}


@app.get("/sandbox/health")
def sandbox_health():
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

    return {
        "status": "ok",
        "sandbox_image": settings.SANDBOX_IMAGE,
        "mem_limit": settings.SANDBOX_MEM_LIMIT,
        "timeout_sec": settings.SANDBOX_TIMEOUT_SEC,
    }
