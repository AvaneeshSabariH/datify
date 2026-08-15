import logging
import os
import tempfile
from fastapi import APIRouter, HTTPException, UploadFile

from backend.agent import run_agent
from backend.database import create_checkpoint, rollback_checkpoint
from backend.profiler import DataProfiler
from backend.schemas import (
    QueryRequest,
    RollbackRequest,
    UploadResponse,
    QueryResponse,
    RollbackResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/upload", response_model=UploadResponse)
async def upload_dataset(file: UploadFile) -> UploadResponse:
    """
    Accept a CSV upload, save it to an ephemeral session directory, profile it,
    and return the session path together with the PII-masked schema.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Only .csv files are accepted.",
        )

    try:
        session_dir = tempfile.mkdtemp(prefix="datify_session_")
        csv_session_path = os.path.join(session_dir, "data_v0.csv")

        contents = await file.read()
        with open(csv_session_path, "wb") as f:
            f.write(contents)
    except Exception as exc:
        logger.error(f"Profiler Error: {str(exc)}")
        raise HTTPException(
            status_code=500,
            detail=f"Stage 1 (Profiler) failed: {str(exc)}",
        )

    try:
        profiler = DataProfiler(csv_session_path)
        schema_json = profiler.to_json()
    except Exception as exc:
        logger.error(f"Profiler Error: {str(exc)}")
        raise HTTPException(
            status_code=500,
            detail=f"Stage 1 (Profiler) failed: {str(exc)}",
        )

    return UploadResponse(
        csv_session_path=csv_session_path,
        schema_json=schema_json,
    )


@router.post("/query", response_model=QueryResponse)
async def query_dataset(request: QueryRequest) -> QueryResponse:
    """
    Run the Claude agent against a previously uploaded CSV.
    """
    if not os.path.exists(request.csv_session_path):
        raise HTTPException(
            status_code=404,
            detail=f"Session CSV not found at: {request.csv_session_path}",
        )

    # Checkpoint — non-fatal on failure.
    try:
        checkpoint_path = create_checkpoint("default_session", request.csv_session_path)
        logger.info("Checkpoint created: %s", checkpoint_path)
    except Exception as exc:
        logger.warning("Checkpoint creation failed (continuing): %s", exc)

    # Agent.
    result = run_agent(
        query=request.query,
        schema_json=request.schema_json_str,
        csv_path=request.csv_session_path,
    )

    if result.get("status") == "error":
        if "API Key" in result.get("message", ""):
            raise HTTPException(status_code=400, detail=result["message"])
        else:
            raise HTTPException(status_code=500, detail=result["message"])

    return QueryResponse(
        status=result.get("status", ""),
        message=result.get("message", "Analysis completed successfully."),
        python_code=result.get("python_code", ""),
        chart_json=result.get("chart_json", {}),
        attempts=result.get("attempts", 1),
        new_csv_path=result.get("new_csv_path", ""),
    )


@router.post("/rollback", response_model=RollbackResponse)
async def rollback_dataset(request: RollbackRequest) -> RollbackResponse:
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
        return RollbackResponse(
            status="success",
            message=f"Dataset rolled back to checkpoint: {restored_path}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Rollback failed: {exc}")
