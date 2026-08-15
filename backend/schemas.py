from typing import Optional
from pydantic import BaseModel, Field


# ── Requests ───────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    model_config = {"populate_by_name": True}

    query: str
    csv_session_path: str
    schema_json_str: str = Field(alias="schema_json")


class RollbackRequest(BaseModel):
    file_path: str
    session_id: str = "default_session"


# ── Responses ──────────────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    csv_session_path: str
    schema_json: str


class QueryResponse(BaseModel):
    status: str
    message: str
    python_code: str
    chart_json: dict
    attempts: int
    new_csv_path: str


class RollbackResponse(BaseModel):
    status: str
    message: str


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str


class SandboxHealthResponse(BaseModel):
    status: str
    sandbox_image: str
    mem_limit: str
    timeout_sec: int
