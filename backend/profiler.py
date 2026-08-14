"""
backend/profiler.py
────────────────────
Privacy-first dataset profiler — co-located inside the backend package.

Identical functionality to the top-level ``profiler.py``; re-homed here
so the backend is a self-contained, importable package.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


# ── Dataset generator (development / testing utility) ─────────────────────────


def generate_mock_dataset(file_path: str, num_rows: int = 1000) -> None:
    """
    Generate a realistic mock dataset containing numerical, categorical,
    temporal, and PII data, and save it as a CSV.

    Parameters
    ----------
    file_path:
        Destination file path for the generated CSV.
    num_rows:
        Number of rows to generate (minimum 1 000).

    Raises
    ------
    ValueError
        If *num_rows* is less than 1 000.
    """
    if num_rows < 1000:
        raise ValueError("Dataset must have at least 1 000 rows.")

    np.random.seed(42)

    first_names = [
        "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael",
        "Elizabeth", "William", "Linda", "David", "Richard", "Barbara",
        "Joseph", "Susan", "Thomas", "Jessica", "Charles", "Sarah",
    ]
    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
        "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
        "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    ]
    departments = ["Sales", "Engineering", "Marketing", "HR", "Finance", "Product"]
    cities = ["New York", "San Francisco", "Austin", "Seattle", "Chicago", "Boston"]

    base_date = datetime(2020, 1, 1)
    rows = []

    for i in range(num_rows):
        f_name = np.random.choice(first_names)
        l_name = np.random.choice(last_names)
        email = f"{f_name.lower()}.{l_name.lower()}{np.random.randint(10, 999)}@example.com"
        phone = (
            f"+1-{np.random.randint(200, 999)}"
            f"-{np.random.randint(100, 999)}"
            f"-{np.random.randint(1000, 9999)}"
        )
        age: int | None = int(np.random.randint(22, 65))
        sales: float | None = float(round(np.random.uniform(5000.0, 150000.0), 2))
        dept: str | None = np.random.choice(departments)
        city = np.random.choice(cities)
        join_date = (
            base_date + timedelta(days=int(np.random.randint(0, 1800)))
        ).strftime("%Y-%m-%d")

        # Introduce ~5 % nulls in age / sales, ~2 % in department.
        if np.random.rand() <= 0.05:
            age = None
        if np.random.rand() <= 0.05:
            sales = None
        if np.random.rand() <= 0.02:
            dept = None

        rows.append(
            {
                "User ID": 10000 + i,
                "Full Name": f"{f_name} {l_name}",
                "Email Address": email,
                "Phone Number": phone,
                "Age": age,
                "Total Sales ($)": sales,
                "Department": dept,
                "City": city,
                "Join Date": join_date,
            }
        )

    df = pd.DataFrame(rows)
    dir_name = os.path.dirname(file_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    df.to_csv(file_path, index=False)


# ── DataProfiler ───────────────────────────────────────────────────────────────


class DataProfiler:
    """
    Analyze a CSV dataset to extract a privacy-first metadata schema.

    PII columns are detected via column-name heuristics and cell-level
    regex matching, then masked in the output schema so that raw PII is
    never forwarded to external LLM APIs.
    """

    # Regex patterns for PII cell detection.
    _EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
    _PHONE_RE = re.compile(
        r"^\+?(\d{1,3})?[-. ]?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}$"
    )

    def __init__(self, file_path: str) -> None:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found at: {file_path}")

        self.file_path = file_path
        self.df = pd.read_csv(file_path)
        self.masked_df: pd.DataFrame | None = None
        self.pii_columns: list[str] = []

    # ── PII detection & masking ────────────────────────────────────────────────

    def detect_and_mask_pii(self) -> pd.DataFrame:
        """
        Detect PII columns and return a masked copy of the DataFrame.

        Detection strategy:
        1. Column-name keyword heuristics (email, phone, name, …).
        2. Cell-level regex sampling (>60 % of non-null sample matches).
        """
        self.masked_df = self.df.copy()
        self.pii_columns = []

        for col in self.df.columns:
            is_pii = False
            pii_type = "GENERAL"
            col_lower = col.lower()

            if any(t in col_lower for t in ("email", "e-mail")):
                is_pii, pii_type = True, "EMAIL"
            elif any(t in col_lower for t in ("phone", "tel", "mobile", "contact")):
                is_pii, pii_type = True, "PHONE"
            elif any(t in col_lower for t in ("name", "fullname", "username")):
                is_pii, pii_type = True, "NAME"
            elif any(
                t in col_lower for t in ("ssn", "socialsecurity", "passport", "nationalid")
            ):
                is_pii, pii_type = True, "GOVERNMENT_ID"

            if not is_pii:
                sample = self.df[col].dropna().astype(str).head(50)
                if len(sample) > 0:
                    if sample.apply(lambda v: bool(self._EMAIL_RE.match(v))).mean() > 0.6:
                        is_pii, pii_type = True, "EMAIL"
                    elif sample.apply(lambda v: bool(self._PHONE_RE.match(v))).mean() > 0.6:
                        is_pii, pii_type = True, "PHONE"

            if is_pii:
                self.pii_columns.append(col)
                placeholder = f"<MASKED_{pii_type}>"
                self.masked_df[col] = self.df[col].apply(
                    lambda v: placeholder if pd.notnull(v) else v
                )

        return self.masked_df

    # ── Schema extraction ──────────────────────────────────────────────────────

    def extract_schema(self) -> dict:
        """
        Build a metadata schema dictionary from the masked dataset.

        Returns
        -------
        dict with ``dataset_info`` and per-column ``columns`` metadata.
        """
        if self.masked_df is None:
            self.detect_and_mask_pii()

        schema: dict = {
            "dataset_info": {
                "file_name": os.path.basename(self.file_path),
                "total_rows": int(len(self.df)),
                "total_columns": int(len(self.df.columns)),
            },
            "columns": {},
        }

        for col in self.df.columns:
            col_data = self.df[col]
            null_count = int(col_data.isnull().sum())
            is_pii_col = col in self.pii_columns

            # Sample values from the *masked* DataFrame to prevent PII leakage.
            raw_samples = self.masked_df[col].head(5).tolist()  # type: ignore[union-attr]
            safe_samples = []
            for x in raw_samples:
                if pd.isnull(x):
                    safe_samples.append(None)
                elif isinstance(x, (np.integer, int)):
                    safe_samples.append(int(x))
                elif isinstance(x, (np.floating, float)):
                    safe_samples.append(float(x))
                else:
                    safe_samples.append(str(x))

            col_schema: dict = {
                "data_type": str(col_data.dtype),
                "null_count": null_count,
                "is_pii": is_pii_col,
                "summary_statistics": None,
                "sample_values": safe_samples,
            }

            if pd.api.types.is_numeric_dtype(col_data):
                valid = col_data.dropna()
                if len(valid) > 0:
                    col_schema["summary_statistics"] = {
                        "min": float(valid.min()),
                        "max": float(valid.max()),
                        "mean": float(valid.mean()),
                    }

            schema["columns"][col] = col_schema

        return schema

    def to_json(self, indent: int = 4) -> str:
        """Return the privacy-first schema as a formatted JSON string."""
        return json.dumps(self.extract_schema(), indent=indent)
