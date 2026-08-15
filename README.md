# Datify: Data Scientist Copilot

Datify is an autonomous, privacy-first Data Scientist Copilot application. It allows users to upload datasets and query an AI agent (powered by Anthropic's Claude) to clean, analyze, and visualize the data automatically.

## Architecture

The project is divided into a modern web frontend and a sandboxed API backend:

### Frontend (`/frontend`)
- **Framework**: Next.js (React)
- **Styling**: Tailwind CSS
- **Notifications**: `react-hot-toast`
- **Visualizations**: Apache ECharts dynamically rendered from AI-generated JSON payloads.

### Backend (`/backend`)
- **Framework**: FastAPI
- **Dependency Management**: `uv`
- **Validation**: Strict Pydantic models (`backend/schemas.py`)
- **AI Agent**: Claude API via Anthropic SDK
- **Data Privacy**: A custom Data Profiler replaces sensitive column values (like emails) with `<MASKED_...>` tokens before sending schemas to the LLM.
- **Sandboxed Execution**: Agent-generated Python code (using Pandas/NumPy) is executed securely inside an isolated, read-only Docker container (`backend/sandbox.py`) running as a non-root user.
- **Testing**: Asynchronous end-to-end integration tests using `pytest` and `httpx.AsyncClient` (`backend/tests/test_api.py`).

## Quick Start

### Backend Setup
1. Navigate to the backend directory: `cd backend`
2. Install dependencies with `uv`: `uv sync`
3. Create a `.env` file containing your `ANTHROPIC_API_KEY`.
4. Build the sandbox Docker image: `docker build -t datify-sandbox .`
5. Run the server: `uv run uvicorn backend.main:app --reload`

### Frontend Setup
1. Navigate to the frontend directory: `cd frontend`
2. Install dependencies: `npm install`
3. Run the development server: `npm run dev`

Navigate to `http://localhost:3000` to interact with Datify.
