import os
import json
import pytest
from httpx import ASGITransport, AsyncClient
import pandas as pd
import numpy as np
import tempfile
from unittest.mock import patch

from backend.main import app

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.fixture(scope="module")
def mock_csv_path():
    """Generate a synthetic test dataset and save it as a CSV."""
    fd, path = tempfile.mkstemp(suffix=".csv", prefix="datify_test_")
    os.close(fd)
    
    np.random.seed(42)
    num_rows = 100
    categories = ["Alpha", "Beta", "Gamma", "Delta"]
    domains = ["example.com", "test.org", "mock.net"]

    data = {
        "id": range(1, num_rows + 1),
        "score": [
            float(np.random.uniform(10.0, 100.0)) if np.random.rand() > 0.10 else np.nan
            for _ in range(num_rows)
        ],
        "category": np.random.choice(categories, size=num_rows).tolist(),
        "email": [
            f"user{i}@{np.random.choice(domains)}"
            for i in range(1, num_rows + 1)
        ],
        "value": np.random.randint(100, 10_000, size=num_rows).tolist(),
    }

    df = pd.DataFrame(data)
    df.to_csv(path, index=False)
    
    yield path
    
    try:
        os.remove(path)
    except OSError:
        pass


@pytest.mark.anyio
async def test_health_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "app" in data
        assert "version" in data


@pytest.mark.anyio
async def test_upload_valid_csv(mock_csv_path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with open(mock_csv_path, "rb") as fh:
            response = await client.post(
                "/upload",
                files={"file": ("test_mock.csv", fh, "text/csv")}
            )
        
        assert response.status_code == 200
        data = response.json()
        assert "csv_session_path" in data
        assert "schema_json" in data
        
        csv_session_path = data["csv_session_path"]
        schema_json = data["schema_json"]
        
        assert os.path.exists(csv_session_path)
        
        # Check PII masking
        schema = json.loads(schema_json)
        assert "email" in schema.get("columns", {})
        samples = schema["columns"]["email"].get("sample_values", [])
        assert all(str(v).startswith("<MASKED_") for v in samples if v is not None)


@pytest.mark.anyio
async def test_upload_invalid_file():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Mock uploading a .txt file
        response = await client.post(
            "/upload",
            files={"file": ("test.txt", b"this is text", "text/plain")}
        )
        
        # Should be 400 Bad Request
        assert response.status_code == 400
        assert "Only .csv files are accepted" in response.json()["detail"]


@pytest.mark.anyio
async def test_query_valid(mock_csv_path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # First upload
        with open(mock_csv_path, "rb") as fh:
            upload_resp = await client.post(
                "/upload",
                files={"file": ("test_mock.csv", fh, "text/csv")}
            )
        
        assert upload_resp.status_code == 200
        upload_data = upload_resp.json()
        
        # Then query
        payload = {
            "query": "Clean the missing values in the 'score' column using median imputation and plot a bar chart showing the count of each category.",
            "csv_session_path": upload_data["csv_session_path"],
            "schema_json": upload_data["schema_json"],
        }
        
        response = await client.post("/query", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "python_code" in data
        assert "chart_json" in data
        assert "new_csv_path" in data
        
        assert data["python_code"]
        assert data["chart_json"]
        assert data["new_csv_path"]
        
        # Verify new CSV
        assert os.path.exists(data["new_csv_path"])
        df = pd.read_csv(data["new_csv_path"])
        assert df["score"].isna().sum() == 0


@pytest.mark.anyio
async def test_query_missing_session():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "query": "Clean the missing values",
            "csv_session_path": "/tmp/nonexistent_datify_session/data_v0.csv",
            "schema_json": "{}"
        }
        
        response = await client.post("/query", json=payload)
        
        # Should be 404 Not Found since the session CSV doesn't exist on disk
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_query_agent_failure(mock_csv_path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # First upload
        with open(mock_csv_path, "rb") as fh:
            upload_resp = await client.post(
                "/upload",
                files={"file": ("test_mock.csv", fh, "text/csv")}
            )
        
        assert upload_resp.status_code == 200
        upload_data = upload_resp.json()
        
        # Then query with a mock agent failure
        payload = {
            "query": "This will fail.",
            "csv_session_path": upload_data["csv_session_path"],
            "schema_json": upload_data["schema_json"],
        }
        
        with patch("backend.routers.api.run_agent") as mock_run_agent:
            mock_run_agent.return_value = {
                "status": "error",
                "message": "Simulated agent failure: JSON parsing error or 404 from LLM"
            }
            
            response = await client.post("/query", json=payload)
            
            # Since it's a general agent error, it should be mapped to HTTP 500
            assert response.status_code == 500
            assert "Simulated agent failure" in response.json()["detail"]
