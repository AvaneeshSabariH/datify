import json
import os
import re
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

def generate_mock_dataset(file_path: str, num_rows: int = 1000) -> None:
    """
    Generates a realistic mock dataset containing numerical, categorical,
    temporal, and PII data, and saves it as a CSV.
    
    Args:
        file_path: The destination file path for the CSV.
        num_rows: Number of rows to generate (minimum 1000).
    """
    if num_rows < 1000:
        raise ValueError("Dataset must have at least 1000 rows.")

    np.random.seed(42)

    # Lists for generating PII and categorical columns
    first_names = [
        "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", 
        "Elizabeth", "William", "Linda", "David", "Elizabeth", "Richard", 
        "Barbara", "Joseph", "Susan", "Thomas", "Jessica", "Charles", "Sarah"
    ]
    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", 
        "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", 
        "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin"
    ]
    departments = ["Sales", "Engineering", "Marketing", "HR", "Finance", "Product"]
    cities = ["New York", "San Francisco", "Austin", "Seattle", "Chicago", "Boston"]

    data = []
    
    # Base date for join dates
    base_date = datetime(2020, 1, 1)

    for i in range(num_rows):
        f_name = np.random.choice(first_names)
        l_name = np.random.choice(last_names)
        full_name = f"{f_name} {l_name}"
        
        # Realistic email and phone
        email = f"{f_name.lower()}.{l_name.lower()}{np.random.randint(10, 999)}@example.com"
        phone = f"+1-{np.random.randint(200, 999)}-{np.random.randint(100, 999)}-{np.random.randint(1000, 9999)}"
        
        age = int(np.random.randint(22, 65))
        sales = float(round(np.random.uniform(5000.0, 150000.0), 2))
        dept = np.random.choice(departments)
        city = np.random.choice(cities)
        
        # Join date within the last 5 years
        join_date = (base_date + timedelta(days=int(np.random.randint(0, 1800)))).strftime("%Y-%m-%d")

        # Introduce some nulls for testing (approx 5% probability in age and sales)
        age_val = age if np.random.rand() > 0.05 else None
        sales_val = sales if np.random.rand() > 0.05 else None
        dept_val = dept if np.random.rand() > 0.02 else None

        data.append({
            "User ID": 10000 + i,
            "Full Name": full_name,
            "Email Address": email,
            "Phone Number": phone,
            "Age": age_val,
            "Total Sales ($)": sales_val,
            "Department": dept_val,
            "City": city,
            "Join Date": join_date
        })

    df = pd.DataFrame(data)
    
    # Create directory if it doesn't exist
    dir_name = os.path.dirname(file_path)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name)
        
    df.to_csv(file_path, index=False)


class DataProfiler:
    """
    Analyzes datasets to extract metadata schema, identify and mask
    Personally Identifiable Information (PII), and output a secure metadata JSON.
    """
    def __init__(self, file_path: str):
        """
        Initializes the profiler and loads the dataset.
        
        Args:
            file_path: The path to the CSV dataset.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found at: {file_path}")
        
        self.file_path = file_path
        self.df = pd.read_csv(file_path)
        self.masked_df = None
        self.pii_columns = []

        # Common regular expressions for PII detection
        self.email_regex = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')
        # Flexible phone regex matching standard and international formats
        self.phone_regex = re.compile(r'^\+?(\d{1,3})?[-. ]?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}$')

    def detect_and_mask_pii(self) -> pd.DataFrame:
        """
        Detects PII columns based on column name heuristics and cell regex matching,
        and returns a masked copy of the DataFrame.
        
        Returns:
            A pandas DataFrame with PII masked.
        """
        self.masked_df = self.df.copy()
        self.pii_columns = []

        for col in self.df.columns:
            is_pii = False
            pii_type = "GENERAL"
            col_lower = col.lower()

            # 1. Check heuristics based on column names
            if any(term in col_lower for term in ["email", "e-mail"]):
                is_pii = True
                pii_type = "EMAIL"
            elif any(term in col_lower for term in ["phone", "tel", "mobile", "contact"]):
                is_pii = True
                pii_type = "PHONE"
            elif any(term in col_lower for term in ["name", "fullname", "username"]):
                is_pii = True
                pii_type = "NAME"
            elif any(term in col_lower for term in ["ssn", "socialsecurity", "passport", "nationalid"]):
                is_pii = True
                pii_type = "GOVERNMENT_ID"

            # 2. If name heuristics fail, sample values to check for format matches (e.g. Email/Phone regex)
            if not is_pii:
                non_null_samples = self.df[col].dropna().astype(str).head(50)
                if len(non_null_samples) > 0:
                    email_matches = non_null_samples.apply(lambda val: bool(self.email_regex.match(val)))
                    phone_matches = non_null_samples.apply(lambda val: bool(self.phone_regex.match(val)))

                    # If > 60% of sample non-null cells match the pattern, classify as PII
                    if email_matches.mean() > 0.6:
                        is_pii = True
                        pii_type = "EMAIL"
                    elif phone_matches.mean() > 0.6:
                        is_pii = True
                        pii_type = "PHONE"

            # 3. Apply masking if classified as PII
            if is_pii:
                self.pii_columns.append(col)
                mask_placeholder = f"<MASKED_{pii_type}>"
                self.masked_df[col] = self.df[col].apply(
                    lambda val: mask_placeholder if pd.notnull(val) else val
                )

        return self.masked_df

    def extract_schema(self) -> dict:
        """
        Extracts metadata schema from the masked dataset.
        
        Returns:
            A dictionary containing column statistics, metadata, and masked samples.
        """
        # Ensure PII detection and masking has been run
        if self.masked_df is None:
            self.detect_and_mask_pii()

        schema = {
            "dataset_info": {
                "file_name": os.path.basename(self.file_path),
                "total_rows": int(len(self.df)),
                "total_columns": int(len(self.df.columns))
            },
            "columns": {}
        }

        for col in self.df.columns:
            # Determine basic metadata
            col_data = self.df[col]
            dtype_str = str(col_data.dtype)
            null_count = int(col_data.isnull().sum())
            is_pii_col = col in self.pii_columns

            col_schema = {
                "data_type": dtype_str,
                "null_count": null_count,
                "is_pii": is_pii_col,
                "summary_statistics": None,
                # Sample values taken from the masked DataFrame to prevent leaking PII
                "sample_values": self.masked_df[col].head(5).tolist()
            }

            # Normalize values in sample_values for JSON compatibility (converting np types if any)
            col_schema["sample_values"] = [
                int(x) if isinstance(x, (np.integer, int)) and not pd.isnull(x)
                else float(x) if isinstance(x, (np.floating, float)) and not pd.isnull(x)
                else None if pd.isnull(x)
                else str(x)
                for x in col_schema["sample_values"]
            ]

            # Calculate summary stats for numerical columns
            if pd.api.types.is_numeric_dtype(col_data):
                # Filter out nulls for calculation
                valid_data = col_data.dropna()
                if len(valid_data) > 0:
                    col_schema["summary_statistics"] = {
                        "min": float(valid_data.min()) if isinstance(valid_data.min(), (np.floating, float, np.integer, int)) else valid_data.min(),
                        "max": float(valid_data.max()) if isinstance(valid_data.max(), (np.floating, float, np.integer, int)) else valid_data.max(),
                        "mean": float(valid_data.mean())
                    }

            schema["columns"][col] = col_schema

        return schema

    def to_json(self, indent: int = 4) -> str:
        """
        Generates a clean JSON string of the masked metadata schema.
        
        Args:
            indent: JSON formatting indent width.
            
        Returns:
            JSON-formatted string containing the privacy-first schema.
        """
        schema_dict = self.extract_schema()
        return json.dumps(schema_dict, indent=indent)


if __name__ == "__main__":
    # Test Block
    csv_filename = "mock_data.csv"
    
    print("--- STEP 1: Generating Mock Dataset ---")
    try:
        generate_mock_dataset(csv_filename, num_rows=1000)
        print(f"Successfully generated '{csv_filename}' with 1000 rows.")
    except Exception as e:
        print(f"Error generating dataset: {e}")
        exit(1)

    print("\n--- STEP 2: Initializing DataProfiler & Processing ---")
    try:
        profiler = DataProfiler(csv_filename)
        
        # Perform profiling and get JSON
        schema_json = profiler.to_json()
        
        print("\n--- STEP 3: Resulting JSON Schema Output (Privacy-First) ---")
        print(schema_json)
        
        # Verify no raw PII leaked (quick check)
        assert "Mary" not in schema_json, "Security Check Failed: Raw PII name 'Mary' found in JSON schema!"
        assert "@example.com" not in schema_json, "Security Check Failed: Raw PII email domain found in JSON schema!"
        print("\n--- Security Verification Passed: No raw PII leaked in the JSON Schema. ---")
        
    except Exception as e:
        print(f"Error profiling dataset: {e}")
        exit(1)
    finally:
        # Clean up mock file after test
        if os.path.exists(csv_filename):
            os.remove(csv_filename)
            print(f"\nCleaned up temporary file: {csv_filename}")
