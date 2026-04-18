"""
Migration 002: Add tutorial_completed to users

Adds a persistent flag so the onboarding tutorial doesn't re-trigger
when a user deletes all their priorities.

Run with: python -m praxis_core.migrations.002_tutorial_completed
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from praxis_core.persistence.database import get_connection, DB_PATH


def get_column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    """Get current column names for a table."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Add tutorial_completed column to users table."""
    columns = get_column_names(conn, "users")
    changes = []

    if "tutorial_completed" not in columns:
        conn.execute(
            "ALTER TABLE users ADD COLUMN tutorial_completed INTEGER NOT NULL DEFAULT 0"
        )
        # Mark all existing users as having completed the tutorial
        conn.execute("UPDATE users SET tutorial_completed = 1")
        changes.append("Added tutorial_completed column (existing users marked as completed)")

    return changes


def main():
    print(f"Database: {DB_PATH}")

    with get_connection() as conn:
        changes = migrate(conn)

        if changes:
            conn.commit()
            print("\nChanges applied:")
            for change in changes:
                print(f"  - {change}")
        else:
            print("\nNo changes needed — column already exists.")


if __name__ == "__main__":
    main()
