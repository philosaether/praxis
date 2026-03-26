"""Database connection and schema management."""

import sqlite3
from pathlib import Path


DB_DIR = Path.home() / ".praxis"
DB_PATH = DB_DIR / "praxis.db"


def get_connection() -> sqlite3.Connection:
    """Get a database connection with standard configuration."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
