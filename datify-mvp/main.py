import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from profiler import DataProfiler
from database import create_checkpoint, rollback_checkpoint
from agent import run_agent

app = FastAPI(
    title="Datify MVP Backend",
    description="Autonomous, privacy-first Data Scientist Copilot API",
    version="0.1.0"
)

# Pydantic request models
class AnalysisRequest(BaseModel):
    query: str
    file_path: str
    session_id: str = "default_session"

class RollbackRequest(BaseModel):
    file_path: str
    session_id: str = "default_session"

@app.post("/analyze")
async def analyze_dataset(request: AnalysisRequest):
    """
    Main endpoint for analyzing the dataset.
    Saves a rollback checkpoint, profiles the data to get a masked schema,
    runs the Anthropic Claude agent, executes the pandas code locally, and returns the ECharts config.
    """
    # 1. Input Validation
    if not os.path.exists(request.file_path):
        raise HTTPException(
            status_code=404, 
            detail=f"Dataset file not found at: {request.file_path}"
        )
    
    # 2. Save a Checkpoint for Rollback Support (Undo Feature)
    try:
        checkpoint_path = create_checkpoint(request.session_id, request.file_path)
        print(f"[Database] Checkpoint created successfully at: {checkpoint_path}")
    except Exception as e:
        print(f"[Database] Error creating checkpoint: {e}")
        # Note: We don't crash the analysis request if checkpointing fails, but we log it.

    # 3. Extract the Privacy-First Schema using DataProfiler
    try:
        profiler = DataProfiler(request.file_path)
        schema_json = profiler.to_json()
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to profile dataset: {str(e)}"
        )

    # 4. Invoke Agent (Anthropic Claude 3.5 Sonnet + Local Execution Loop + Self-Debugging)
    result = run_agent(request.query, schema_json, request.file_path)

    if result.get("status") == "error" and "API Key" in result.get("message", ""):
        # Provide clean guidance on missing key
        raise HTTPException(
            status_code=400,
            detail=result["message"]
        )

    return {
        "status": result.get("status"),
        "message": result.get("message", "Analysis completed successfully."),
        "python_code": result.get("python_code", ""),
        "chart_json": result.get("chart_json", {}),
        "attempts": result.get("attempts", 1)
    }

@app.post("/rollback")
async def rollback_dataset(request: RollbackRequest):
    """
    Rolls back the active dataset file to the last saved checkpoint for the session.
    """
    if not os.path.exists(request.file_path):
        raise HTTPException(
            status_code=404, 
            detail=f"Active dataset file not found at: {request.file_path}"
        )
        
    try:
        restored_path = rollback_checkpoint(request.session_id, request.file_path)
        return {
            "status": "success",
            "message": f"Successfully rolled back dataset to latest checkpoint: {restored_path}"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rollback failed: {str(e)}")

@app.get("/health")
def health_check():
    return {"status": "ok", "app": "Datify MVP"}
