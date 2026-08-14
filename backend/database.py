"""
backend/database.py
────────────────────
SQLite-backed checkpoint store for dataset rollback support.

Identical functionality to ``datify-mvp/database.py``, re-homed into
the backend package for co-location with the rest of the application.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime

# ── Path configuration ─────────────────────────────────────────────────────────

# Store database artefacts alongside this file, under backend/data/.
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(_PACKAGE_DIR, "data")
DB_PATH = os.path.join(DB_DIR, "checkpoints.db")
CHECKPOINTS_DIR = os.path.join(DB_DIR, "checkpoints")


# ── Internal helpers ───────────────────────────────────────────────────────────


def _init_db() -> None:
    """
    Ensure the SQLite database and directory structure exist, creating the
    ``DatasetCheckpoints`` table if it doesn't already.
    """
    os.makedirs(CHECKPOINTS_DIR, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS DatasetCheckpoints (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT    NOT NULL,
                timestamp   TEXT    NOT NULL,
                file_path   TEXT    NOT NULL
            )
            """
        )
        conn.commit()


# ── Public API ─────────────────────────────────────────────────────────────────


def create_checkpoint(session_id: str, original_csv_path: str) -> str:
    """
    Copy the current CSV to a timestamped backup and record it in the database.

    Parameters
    ----------
    session_id:
        Session / conversation identifier used to scope checkpoints.
    original_csv_path:
        Absolute path to the active CSV file.

    Returns
    -------
    Absolute path to the created checkpoint file.

    Raises
    ------
    FileNotFoundError
        If *original_csv_path* does not exist.
    """
    if not os.path.exists(original_csv_path):
        raise FileNotFoundError(f"Original CSV not found at: {original_csv_path}")

    _init_db()

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    csv_filename = os.path.basename(original_csv_path)
    checkpoint_filename = f"{session_id}_{timestamp_str}_{csv_filename}"
    checkpoint_filepath = os.path.join(CHECKPOINTS_DIR, checkpoint_filename)

    shutil.copy2(original_csv_path, checkpoint_filepath)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO DatasetCheckpoints (session_id, timestamp, file_path) "
            "VALUES (?, ?, ?)",
            (session_id, datetime.now().isoformat(), checkpoint_filepath),
        )
        conn.commit()

    return checkpoint_filepath


def rollback_checkpoint(session_id: str, original_csv_path: str) -> str:
    """
    Restore the active CSV file to its most recent checkpoint for *session_id*,
    then delete the checkpoint record and file.

    Parameters
    ----------
    session_id:
        Session / conversation identifier.
    original_csv_path:
        Absolute path where the restored data should be written.

    Returns
    -------
    *original_csv_path* (unchanged) on success.

    Raises
    ------
    ValueError
        If no checkpoints exist for *session_id*.
    FileNotFoundError
        If the checkpoint file is missing on disk.
    """
    _init_db()

    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT id, file_path FROM DatasetCheckpoints "
            "WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()

        if not row:
            raise ValueError(f"No checkpoints found for session_id: {session_id}")

        checkpoint_id, checkpoint_filepath = row

        if not os.path.exists(checkpoint_filepath):
            conn.execute(
                "DELETE FROM DatasetCheckpoints WHERE id = ?", (checkpoint_id,)
            )
            conn.commit()
            raise FileNotFoundError(
                f"Checkpoint file not found on disk: {checkpoint_filepath}"
            )

        shutil.copy2(checkpoint_filepath, original_csv_path)

        conn.execute(
            "DELETE FROM DatasetCheckpoints WHERE id = ?", (checkpoint_id,)
        )
        conn.commit()

    # Best-effort cleanup of the checkpoint file.
    try:
        os.remove(checkpoint_filepath)
    except OSError:
        pass

    return original_csv_path
