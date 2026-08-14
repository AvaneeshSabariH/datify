import os
import sys
import traceback
import json
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from anthropic import Anthropic

# Load environment variables from the local .env file
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# Initialize Anthropic Client
# Anthropic automatically uses the ANTHROPIC_API_KEY environment variable.
# We fall back to a mock/dry-run mode if no API key is set so the app doesn't crash on startup.
api_key = os.getenv("ANTHROPIC_API_KEY")
if api_key:
    client = Anthropic(api_key=api_key)
else:
    client = None

# Define the Claude Tool Schema
TOOLS = [
    {
        "name": "generate_data_insights",
        "description": (
            "Executes pandas and numpy python code on the active CSV file to clean, analyze, or process the dataset, "
            "and generates a valid Apache ECharts JSON config dictionary to visualize the results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "python_code": {
                    "type": "string",
                    "description": (
                        "Pandas/NumPy code to run. The dataset is already loaded in the environment as a DataFrame named `df` "
                        "and its path is in `csv_path`. If your operations modify the data (e.g. drop nulls, correct data type), "
                        "make sure to modify `df` in-place or assign it back to `df` so the modifications are automatically saved."
                    )
                },
                "chart_json": {
                    "type": "object",
                    "description": (
                        "A valid Apache ECharts configuration dictionary (e.g., containing title, tooltip, xAxis, yAxis, series, etc.) "
                        "representing the visual output of the data analysis. Do not include raw javascript callbacks."
                    )
                }
            },
            "required": ["python_code", "chart_json"]
        }
    }
]

def execute_code(python_code: str, csv_path: str) -> tuple[bool, str]:
    """
    Executes the generated Python code inside a controlled local namespace.
    Automatically saves changes to the df DataFrame back to the CSV.
    
    Args:
        python_code: The Python script string to execute.
        csv_path: The file path of the active dataset.
        
    Returns:
        A tuple of (success_boolean, error_traceback_string)
    """
    if not os.path.exists(csv_path):
        return False, f"File not found: {csv_path}"

    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        return False, f"Failed to load CSV: {str(e)}"

    # Set up execution environment
    local_vars = {
        "pd": pd,
        "np": np,
        "df": df,
        "csv_path": csv_path
    }
    
    try:
        # Run the code
        exec(python_code, globals(), local_vars)
        
        # Save df back if modified
        if "df" in local_vars and isinstance(local_vars["df"], pd.DataFrame):
            local_vars["df"].to_csv(csv_path, index=False)
            
        return True, ""
    except Exception:
        tb = traceback.format_exc()
        return False, tb

def run_agent(query: str, schema_json: str, csv_path: str, max_retries: int = 3) -> dict:
    """
    Sends the user query and dataset schema to Claude 3.5 Sonnet, extracts the ECharts config
    and Python code, runs the Python code locally, and performs self-debugging if code fails.
    
    Args:
        query: User natural language request.
        schema_json: Masked metadata schema from the DataProfiler.
        csv_path: Local filepath of the CSV dataset to be manipulated.
        max_retries: Max self-debugging loops.
        
    Returns:
        A dictionary containing execution results, status, code, and ECharts config.
    """
    if not client:
        return {
            "status": "error",
            "message": "Anthropic API Key is missing. Please set ANTHROPIC_API_KEY in your .env file.",
            "python_code": "",
            "chart_json": {}
        }

    system_prompt = (
        "You are Datify, an autonomous, privacy-first Data Scientist Copilot.\n\n"
        "Your task is to analyze the user's dataset and generate Python code to process/clean it, "
        "and design a clean Apache ECharts configuration to visualize the output.\n\n"
        "Rules:\n"
        "1. The user's dataset is loaded into the local python environment as a pandas DataFrame named `df`.\n"
        "2. The file path is available in the variable `csv_path`.\n"
        "3. Any operations that clean or update the dataset should modify the variable `df` in-place, "
        "or re-assign to `df`. The backend will automatically write `df` back to `csv_path` post-execution.\n"
        "4. Your ECharts configuration should be a standard JSON-compatible Python dictionary. Ensure data points "
        "plotted match the calculations in your code.\n"
        "5. ALWAYS call the `generate_data_insights` tool to return your python code and chart configuration."
    )

    messages = [
        {
            "role": "user",
            "content": (
                f"Dataset Schema (PII Masked):\n{schema_json}\n\n"
                f"User Request: {query}"
            )
        }
    ]

    for attempt in range(max_retries + 1):
        try:
            # Call Claude with forced tool use
            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4000,
                system=system_prompt,
                messages=messages,
                tools=TOOLS,
                tool_choice={"type": "tool", "name": "generate_data_insights"}
            )
            
            # Find the tool use block
            tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
            
            if not tool_use_block:
                return {
                    "status": "error",
                    "message": "Claude failed to call the required tool.",
                    "python_code": "",
                    "chart_json": {}
                }
                
            tool_use_id = tool_use_block.id
            tool_input = tool_use_block.input
            python_code = tool_input.get("python_code", "")
            chart_json = tool_input.get("chart_json", {})
            
            # Run the generated code
            success, error_trace = execute_code(python_code, csv_path)
            
            if success:
                return {
                    "status": "success",
                    "python_code": python_code,
                    "chart_json": chart_json,
                    "attempts": attempt + 1
                }
            
            # If execution fails, perform self-debugging by sending the traceback back to Claude
            print(f"[Self-Debugging] Attempt {attempt + 1} failed. Error traceback captured.")
            
            # Format messages for the next turn
            # Anthropic requires providing the Assistant response (containing tool_use) followed by the Tool Result
            messages.append({
                "role": "assistant",
                "content": response.content
            })
            
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": f"The Python code failed with the following traceback:\n{error_trace}\n\nPlease debug the issue, fix the pandas/numpy code, and call the tool again with the corrected code.",
                        "is_error": True
                    }
                ]
            })
            
        except Exception as e:
            return {
                "status": "error",
                "message": f"Anthropic API call failed: {str(e)}",
                "python_code": "",
                "chart_json": {}
            }

    # If loop ends without success
    return {
        "status": "failed",
        "message": f"Failed to execute code after {max_retries + 1} attempts.",
        "python_code": python_code if 'python_code' in locals() else "",
        "chart_json": chart_json if 'chart_json' in locals() else {}
    }
