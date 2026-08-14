"""
backend/agent.py
─────────────────
Claude-powered data analysis agent.

Identical logic to the original ``datify-mvp/agent.py`` but uses
``DockerSandbox`` for isolated, sandboxed code execution instead of
the unsafe bare ``exec()`` call.

The self-debugging loop feeds sandboxed ``stderr`` (container traceback)
back to Claude on failure, preserving the same multi-turn repair flow.
"""

from __future__ import annotations

import logging
import os

from anthropic import Anthropic

from backend.config import settings
from backend.sandbox import get_sandbox

logger = logging.getLogger(__name__)

# ── Anthropic client ───────────────────────────────────────────────────────────

_client: Anthropic | None = None
if settings.ANTHROPIC_API_KEY:
    _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
else:
    logger.warning(
        "ANTHROPIC_API_KEY not set — agent will run in error-response mode."
    )

# ── Tool schema ────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "generate_data_insights",
        "description": (
            "Executes pandas and numpy python code on the active CSV file to clean, "
            "analyze, or process the dataset, and generates a valid Apache ECharts "
            "JSON config dictionary to visualize the results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "python_code": {
                    "type": "string",
                    "description": (
                        "Pandas/NumPy code to run. The dataset is already loaded in "
                        "the environment as a DataFrame named `df` and its path is in "
                        "`csv_path`. If your operations modify the data (e.g. drop "
                        "nulls, correct data types), make sure to modify `df` in-place "
                        "or assign it back to `df` so the modifications are "
                        "automatically saved."
                    ),
                },
                "chart_json": {
                    "type": "object",
                    "description": (
                        "A valid Apache ECharts configuration dictionary (e.g., "
                        "containing title, tooltip, xAxis, yAxis, series, etc.) "
                        "representing the visual output of the data analysis. "
                        "Do not include raw JavaScript callbacks."
                    ),
                },
            },
            "required": ["python_code", "chart_json"],
        },
    }
]

_SYSTEM_PROMPT = (
    "You are Datify, an autonomous, privacy-first Data Scientist Copilot.\n\n"
    "Your task is to analyze the user's dataset and generate Python code to "
    "process/clean it, and design a clean Apache ECharts configuration to "
    "visualize the output.\n\n"
    "Rules:\n"
    "1. The user's dataset is loaded into the local python environment as a "
    "pandas DataFrame named `df`.\n"
    "2. The file path is available in the variable `csv_path`.\n"
    "3. Any operations that clean or update the dataset should modify the "
    "variable `df` in-place, or re-assign to `df`. The backend will "
    "automatically write `df` back to `csv_path` post-execution.\n"
    "4. Your ECharts configuration should be a standard JSON-compatible Python "
    "dictionary. Ensure data points plotted match the calculations in your code.\n"
    "5. ALWAYS call the `generate_data_insights` tool to return your python "
    "code and chart configuration."
)


# ── Public API ─────────────────────────────────────────────────────────────────


def run_agent(
    query: str,
    schema_json: str,
    csv_path: str,
    max_retries: int = 3,
) -> dict:
    """
    Send the user query and dataset schema to Claude, extract the generated
    Pandas code and ECharts config, execute the code inside a
    ``DockerSandbox``, and self-debug on failure.

    Parameters
    ----------
    query:
        Natural-language user request.
    schema_json:
        PII-masked metadata schema string from ``DataProfiler``.
    csv_path:
        Absolute path to the active CSV dataset on the host.
    max_retries:
        Maximum number of self-debugging iterations.

    Returns
    -------
    dict with keys:
        ``status``       — ``"success"`` | ``"failed"`` | ``"error"``
        ``message``      — Human-readable summary (on error/failure).
        ``python_code``  — Last generated code string.
        ``chart_json``   — ECharts config dict.
        ``attempts``     — Number of LLM calls made.
    """
    if not _client:
        return {
            "status": "error",
            "message": (
                "Anthropic API Key is missing. "
                "Please set ANTHROPIC_API_KEY in your .env file."
            ),
            "python_code": "",
            "chart_json": {},
        }

    sandbox = get_sandbox()

    messages = [
        {
            "role": "user",
            "content": (
                f"Dataset Schema (PII Masked):\n{schema_json}\n\n"
                f"User Request: {query}"
            ),
        }
    ]

    python_code: str = ""
    chart_json: dict = {}

    for attempt in range(max_retries + 1):
        try:
            response = _client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4000,
                system=_SYSTEM_PROMPT,
                messages=messages,
                tools=TOOLS,
                tool_choice={"type": "tool", "name": "generate_data_insights"},
            )

            tool_use_block = next(
                (b for b in response.content if b.type == "tool_use"), None
            )

            if not tool_use_block:
                return {
                    "status": "error",
                    "message": "Claude failed to call the required tool.",
                    "python_code": python_code,
                    "chart_json": chart_json,
                }

            tool_use_id = tool_use_block.id
            tool_input = tool_use_block.input
            python_code = tool_input.get("python_code", "")
            chart_json = tool_input.get("chart_json", {})

            # ── Execute inside the Docker sandbox ──────────────────────────
            result = sandbox.run(python_code=python_code, csv_path=csv_path)

            if result["success"]:
                return {
                    "status": "success",
                    "python_code": python_code,
                    "chart_json": chart_json,
                    "attempts": attempt + 1,
                }

            # ── Self-debug loop ────────────────────────────────────────────
            logger.warning(
                "[Self-Debugging] Attempt %d/%d failed.\nStderr:\n%s",
                attempt + 1,
                max_retries + 1,
                result["stderr"],
            )

            messages.append({"role": "assistant", "content": response.content})
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": (
                                f"The Python code failed with the following error:\n"
                                f"{result['stderr']}\n\n"
                                f"Please debug the issue, fix the pandas/numpy code, "
                                f"and call the tool again with the corrected code."
                            ),
                            "is_error": True,
                        }
                    ],
                }
            )

        except Exception as exc:
            logger.exception("Anthropic API call failed on attempt %d", attempt + 1)
            return {
                "status": "error",
                "message": f"Anthropic API call failed: {exc}",
                "python_code": python_code,
                "chart_json": chart_json,
            }

    return {
        "status": "failed",
        "message": f"Failed to produce working code after {max_retries + 1} attempt(s).",
        "python_code": python_code,
        "chart_json": chart_json,
    }
