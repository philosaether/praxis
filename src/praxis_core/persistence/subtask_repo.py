"""Subtask persistence: CRUD operations."""

import sqlite3
from datetime import datetime

from ulid import ULID

from praxis_core.model.tasks import Subtask
from praxis_core.persistence.database import get_connection
from praxis_core.persistence.task_repo import ensure_schema


# ---------------------------------------------------------------------
# Row Conversion
# ---------------------------------------------------------------------

def _row_to_subtask(row: sqlite3.Row) -> Subtask:
    """Convert a database row to a Subtask."""
    completed_at = None
    if row["completed_at"]:
        completed_at = datetime.fromisoformat(row["completed_at"])

    return Subtask(
        id=row["id"],
        task_id=row["task_id"],
        title=row["title"],
        completed=bool(row["completed"]),
        sort_order=row["sort_order"],
        completed_at=completed_at,
    )


# ---------------------------------------------------------------------
# Subtask CRUD
# ---------------------------------------------------------------------

def create_subtask(task_id: str, title: str, sort_order: int | None = None) -> Subtask:
    """Create a subtask. If sort_order not specified, appends to end."""
    ensure_schema()
    subtask_id = str(ULID())
    with get_connection() as conn:
        if sort_order is None:
            # Get max sort_order for this task
            result = conn.execute(
                "SELECT MAX(sort_order) as max_order FROM subtasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            sort_order = (result["max_order"] or 0) + 1

        conn.execute(
            """
            INSERT INTO subtasks (id, task_id, title, sort_order)
            VALUES (?, ?, ?, ?)
            """,
            (subtask_id, task_id, title, sort_order),
        )
        return Subtask(
            id=subtask_id,
            task_id=task_id,
            title=title,
            sort_order=sort_order,
        )


def toggle_subtask(subtask_id: str) -> Subtask | None:
    """Toggle subtask completion status. Returns updated subtask."""
    ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM subtasks WHERE id = ?", (subtask_id,)
        ).fetchone()
        if not row:
            return None

        new_completed = not bool(row["completed"])
        completed_at = datetime.now().isoformat() if new_completed else None

        conn.execute(
            "UPDATE subtasks SET completed = ?, completed_at = ? WHERE id = ?",
            (int(new_completed), completed_at, subtask_id),
        )

        return Subtask(
            id=row["id"],
            task_id=row["task_id"],
            title=row["title"],
            completed=new_completed,
            sort_order=row["sort_order"],
            completed_at=datetime.fromisoformat(completed_at) if completed_at else None,
        )


def delete_subtask(subtask_id: str) -> bool:
    """Delete a subtask. Returns True if deleted."""
    ensure_schema()
    with get_connection() as conn:
        result = conn.execute("DELETE FROM subtasks WHERE id = ?", (subtask_id,))
        return result.rowcount > 0


def reorder_subtasks(task_id: str, subtask_ids: list[str]) -> None:
    """Reorder subtasks by providing new order of IDs."""
    ensure_schema()
    with get_connection() as conn:
        for order, subtask_id in enumerate(subtask_ids):
            conn.execute(
                "UPDATE subtasks SET sort_order = ? WHERE id = ? AND task_id = ?",
                (order, subtask_id, task_id),
            )
