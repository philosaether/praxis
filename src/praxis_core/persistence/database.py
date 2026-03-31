"""Database connection and schema management."""

import os
import sqlite3
from pathlib import Path


def _get_db_path() -> Path:
    """Get database path from environment or default."""
    env_path = os.environ.get("PRAXIS_DB_PATH")
    if env_path:
        return Path(env_path)
    return Path.home() / ".praxis" / "praxis.db"


DB_PATH = _get_db_path()
DB_DIR = DB_PATH.parent


def get_connection() -> sqlite3.Connection:
    """Get a database connection with standard configuration."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
