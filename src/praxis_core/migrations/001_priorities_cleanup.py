"""
Migration 001: Priorities and Tasks cleanup

Priorities table changes:
- DROP: user_id (deprecated, replaced by entity_id)
- DROP: success_looks_like (unused Value field)
- DROP: obsolete_when (unused Value field)
- RENAME: notes → description
- ADD: actions_config (DSL v2 actions JSON)

Tasks table changes:
- DROP: user_id (deprecated, replaced by entity_id)
- RENAME: notes → description

Run with: python -m praxis_core.migrations.001_priorities_cleanup
"""

import sqlite3
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from praxis_core.persistence.database import get_connection, DB_PATH


def get_column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    """Get current column names for a table."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def migrate_priorities(conn: sqlite3.Connection) -> list[str]:
    """Migrate the priorities table. Returns list of changes made."""
    columns = get_column_names(conn, "priorities")
    print(f"\nPriorities columns: {sorted(columns)}")

    changes = []

    # DROP user_id
    if "user_id" in columns:
        print("  Dropping user_id...")
        conn.execute("ALTER TABLE priorities DROP COLUMN user_id")
        changes.append("priorities: dropped user_id")

    # DROP success_looks_like
    if "success_looks_like" in columns:
        print("  Dropping success_looks_like...")
        conn.execute("ALTER TABLE priorities DROP COLUMN success_looks_like")
        changes.append("priorities: dropped success_looks_like")

    # DROP obsolete_when
    if "obsolete_when" in columns:
        print("  Dropping obsolete_when...")
        conn.execute("ALTER TABLE priorities DROP COLUMN obsolete_when")
        changes.append("priorities: dropped obsolete_when")

    # RENAME notes → description
    if "notes" in columns and "description" not in columns:
        print("  Renaming notes → description...")
        conn.execute("ALTER TABLE priorities RENAME COLUMN notes TO description")
        changes.append("priorities: renamed notes → description")

    # ADD actions_config
    columns = get_column_names(conn, "priorities")  # Refresh after changes
    if "actions_config" not in columns:
        print("  Adding actions_config...")
        conn.execute("ALTER TABLE priorities ADD COLUMN actions_config TEXT")
        changes.append("priorities: added actions_config")

    return changes


def migrate_tasks(conn: sqlite3.Connection) -> list[str]:
    """Migrate the tasks table. Returns list of changes made."""
    columns = get_column_names(conn, "tasks")
    print(f"\nTasks columns: {sorted(columns)}")

    changes = []

    # DROP user_id
    if "user_id" in columns:
        print("  Dropping user_id...")
        conn.execute("ALTER TABLE tasks DROP COLUMN user_id")
        changes.append("tasks: dropped user_id")

    # RENAME notes → description
    if "notes" in columns and "description" not in columns:
        print("  Renaming notes → description...")
        conn.execute("ALTER TABLE tasks RENAME COLUMN notes TO description")
        changes.append("tasks: renamed notes → description")

    return changes


def migrate():
    """Run the migration."""
    print(f"Migrating database: {DB_PATH}")

    with get_connection() as conn:
        changes = []

        # Migrate priorities table
        changes.extend(migrate_priorities(conn))

        # Migrate tasks table
        changes.extend(migrate_tasks(conn))

        # Verify final state
        print("\n--- Verification ---")

        priority_cols = get_column_names(conn, "priorities")
        print(f"Priorities final: {sorted(priority_cols)}")
        assert "user_id" not in priority_cols, "priorities.user_id should be dropped"
        assert "success_looks_like" not in priority_cols, "priorities.success_looks_like should be dropped"
        assert "obsolete_when" not in priority_cols, "priorities.obsolete_when should be dropped"
        assert "description" in priority_cols, "priorities.description should exist"
        assert "actions_config" in priority_cols, "priorities.actions_config should exist"

        task_cols = get_column_names(conn, "tasks")
        print(f"Tasks final: {sorted(task_cols)}")
        assert "user_id" not in task_cols, "tasks.user_id should be dropped"
        assert "description" in task_cols, "tasks.description should exist"

        if changes:
            print(f"\nChanges made: {len(changes)}")
            for change in changes:
                print(f"  - {change}")
        else:
            print("\nNo changes needed - migration already applied.")

        print("\nMigration complete!")


if __name__ == "__main__":
    migrate()
