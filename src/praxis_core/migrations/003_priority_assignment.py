"""
Migration 003: Priority-level assignment

- Add assigned_to_entity_id to priorities (replaces task-level assigned_to)
- Drop auto_assign_owner, auto_assign_creator from priorities
- Drop assigned_to from tasks
- Rename EntityType.ORGANIZATION to GROUP

Run with: python -m praxis_core.migrations.003_priority_assignment
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from praxis_core.persistence.database import get_connection, DB_PATH


def get_column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def migrate(conn: sqlite3.Connection) -> list[str]:
    changes = []

    # --- Priorities ---
    p_cols = get_column_names(conn, "priorities")

    if "assigned_to_entity_id" not in p_cols:
        conn.execute("ALTER TABLE priorities ADD COLUMN assigned_to_entity_id TEXT REFERENCES entities(id)")
        # For existing priorities with auto_assign_owner=True, assign to priority owner
        if "auto_assign_owner" in p_cols:
            conn.execute("""
                UPDATE priorities SET assigned_to_entity_id = entity_id
                WHERE auto_assign_owner = 1 AND entity_id IS NOT NULL
            """)
        changes.append("Added assigned_to_entity_id to priorities (migrated from auto_assign_owner)")

    # Note: SQLite 3.35+ supports DROP COLUMN
    for col in ("auto_assign_owner", "auto_assign_creator"):
        if col in p_cols:
            try:
                conn.execute(f"ALTER TABLE priorities DROP COLUMN {col}")
                changes.append(f"Dropped {col} from priorities")
            except Exception as e:
                changes.append(f"Could not drop {col}: {e} (SQLite < 3.35?)")

    # --- Tasks ---
    t_cols = get_column_names(conn, "tasks")

    if "assigned_to" in t_cols:
        try:
            conn.execute("ALTER TABLE tasks DROP COLUMN assigned_to")
            changes.append("Dropped assigned_to from tasks")
        except Exception as e:
            changes.append(f"Could not drop assigned_to from tasks: {e}")

    # --- Entities ---
    conn.execute("UPDATE entities SET type = 'group' WHERE type = 'organization'")
    changes.append("Renamed entity type 'organization' to 'group'")

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
            print("\nNo changes needed.")


if __name__ == "__main__":
    main()
