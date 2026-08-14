import os
import sqlite3
import shutil
from datetime import datetime

# Define database and directory paths relative to the datify-mvp root
DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "checkpoints.db")
CHECKPOINTS_DIR = os.path.join(DB_DIR, "checkpoints")

def init_db():
    """
    Initializes the SQLite database and creates the DatasetCheckpoints table if it doesn't exist.
    """
    os.makedirs(CHECKPOINTS_DIR, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS DatasetCheckpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            file_path TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def create_checkpoint(session_id: str, original_csv_path: str) -> str:
    """
    Copies the current CSV file state to a backup location and records it in the database.
    
    Args:
        session_id: The session or conversation ID.
        original_csv_path: The file path to the active CSV.
        
    Returns:
        The path to the created checkpoint CSV file.
    """
    if not os.path.exists(original_csv_path):
        raise FileNotFoundError(f"Original CSV not found at: {original_csv_path}")
        
    init_db()  # Ensure database and folders are initialized
    
    # Generate unique checkpoint file name
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    csv_filename = os.path.basename(original_csv_path)
    checkpoint_filename = f"{session_id}_{timestamp_str}_{csv_filename}"
    checkpoint_filepath = os.path.join(CHECKPOINTS_DIR, checkpoint_filename)
    
    # Copy the file
    shutil.copy2(original_csv_path, checkpoint_filepath)
    
    # Store record in SQLite
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO DatasetCheckpoints (session_id, timestamp, file_path) VALUES (?, ?, ?)",
        (session_id, datetime.now().isoformat(), checkpoint_filepath)
    )
    conn.commit()
    conn.close()
    
    return checkpoint_filepath

def rollback_checkpoint(session_id: str, original_csv_path: str) -> str:
    """
    Rolls back the active CSV file to its latest checkpoint state for the session.
    Deletes the checkpoint record and file after restoring it.
    
    Args:
        session_id: The session or conversation ID.
        original_csv_path: The file path to restore the data back to.
        
    Returns:
        The path to the restored CSV file.
    """
    init_db()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get the latest checkpoint for the session
    cursor.execute(
        "SELECT id, file_path FROM DatasetCheckpoints WHERE session_id = ? ORDER BY id DESC LIMIT 1",
        (session_id,)
    )
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise ValueError(f"No checkpoints found for session_id: {session_id}")
        
    checkpoint_id, checkpoint_filepath = row
    
    if not os.path.exists(checkpoint_filepath):
        # Clean up database entry if file was manually deleted
        cursor.execute("DELETE FROM DatasetCheckpoints WHERE id = ?", (checkpoint_id,))
        conn.commit()
        conn.close()
        raise FileNotFoundError(f"Checkpoint file not found on disk: {checkpoint_filepath}")
        
    # Copy checkpoint file back to restore
    shutil.copy2(checkpoint_filepath, original_csv_path)
    
    # Remove checkpoint record and file to clean up
    cursor.execute("DELETE FROM DatasetCheckpoints WHERE id = ?", (checkpoint_id,))
    conn.commit()
    conn.close()
    
    try:
        os.remove(checkpoint_filepath)
    except OSError:
        pass  # Ignore if file deletion fails
        
    return original_csv_path
