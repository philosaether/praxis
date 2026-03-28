"""Task persistence: CRUD operations and schema."""

import sqlite3
from datetime import datetime

from praxis_core.model.tasks import Task, TaskStatus, Subtask
from praxis_core.persistence.database import get_connection


# ---------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------

TASKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    notes TEXT,
    due_date TEXT,
    priority_id TEXT REFERENCES priorities(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS subtasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority_id);
CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_subtasks_task ON subtasks(task_id);
"""


def ensure_schema() -> None:
    """Ensure the tasks schema exists."""
    with get_connection() as conn:
        _maybe_migrate(conn)
        conn.executescript(TASKS_SCHEMA)


def _maybe_migrate(conn: sqlite3.Connection) -> None:
    """Handle schema migrations from older versions."""
    # Get current table info
    tables = {row["name"] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    # Check if tasks table has old schema (workstream_id column)
    if "tasks" in tables:
        columns = {row["name"] for row in conn.execute(
            "PRAGMA table_info(tasks)"
        ).fetchall()}

        # Add user_id column if missing
        if "user_id" not in columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN user_id INTEGER REFERENCES users(id)")

        if "workstream_id" in columns:
            # Full migration: recreate table without workstream_id
            # Disable foreign keys during migration
            conn.executescript("""
                PRAGMA foreign_keys=OFF;

                -- Create new table with correct schema
                CREATE TABLE IF NOT EXISTS tasks_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    notes TEXT,
                    due_date TEXT,
                    priority_id TEXT REFERENCES priorities(id),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                -- Copy data (map workstream_id to priority_id if priority_id doesn't exist)
                INSERT INTO tasks_new (id, title, status, notes, due_date, priority_id, created_at)
                SELECT id, title, status, notes, due_date,
                       COALESCE(priority_id, workstream_id), created_at
                FROM tasks;

                -- Drop old table and rename new one
                DROP TABLE tasks;
                ALTER TABLE tasks_new RENAME TO tasks;

                -- Recreate indexes
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority_id);

                PRAGMA foreign_keys=ON;
            """)


# ---------------------------------------------------------------------
# Task Operations
# ---------------------------------------------------------------------

def create_task(
    title: str,
    notes: str | None = None,
    due_date: datetime | None = None,
    priority_id: str | None = None,
    user_id: int | None = None,
) -> Task:
    """Create a new task."""
    ensure_schema()
    now = datetime.now()
    with get_connection() as conn:
        due_str = due_date.isoformat() if due_date else None
        cursor = conn.execute(
            """
            INSERT INTO tasks (user_id, title, notes, due_date, priority_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, title, notes, due_str, priority_id, now.isoformat()),
        )
        return Task(
            id=cursor.lastrowid,
            title=title,
            status=TaskStatus.QUEUED,
            notes=notes,
            due_date=due_date,
            priority_id=priority_id,
            created_at=now,
            subtasks=[],
        )


def get_task(task_id: int) -> Task | None:
    """Get a task by ID."""
    ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT t.*, p.name as priority_name
            FROM tasks t
            LEFT JOIN priorities p ON t.priority_id = p.id
            WHERE t.id = ?
            """,
            (task_id,),
        ).fetchone()
        if row:
            task = _row_to_task(row)
            task.subtasks = _get_subtasks(conn, task_id)
            return task
        return None


def list_tasks(
    priority_id: str | None = None,
    status: TaskStatus | None = None,
    include_done: bool = True,
    user_id: int | None = None,
) -> list[Task]:
    """List tasks with optional filters. Done tasks sorted to bottom."""
    ensure_schema()
    with get_connection() as conn:
        query = """
            SELECT t.*, p.name as priority_name
            FROM tasks t
            LEFT JOIN priorities p ON t.priority_id = p.id
            WHERE 1=1
        """
        params = []

        if user_id is not None:
            query += " AND t.user_id = ?"
            params.append(user_id)

        if priority_id:
            query += " AND t.priority_id = ?"
            params.append(priority_id)

        if status:
            query += " AND t.status = ?"
            params.append(status.value)
        elif not include_done:
            query += " AND t.status NOT IN ('done', 'dropped')"

        # Sort: active tasks first (by created_at), then done tasks
        query += """ ORDER BY
            CASE WHEN t.status = 'done' THEN 1 ELSE 0 END,
            t.created_at
        """
        rows = conn.execute(query, params).fetchall()

        tasks = []
        for row in rows:
            task = _row_to_task(row)
            task.subtasks = _get_subtasks(conn, task.id)
            tasks.append(task)

        return tasks


def update_task_status(task_id: int, status: TaskStatus) -> None:
    """Update a task's status."""
    ensure_schema()
    with get_connection() as conn:
        conn.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (status.value, task_id),
        )


def update_task(
    task_id: int,
    title: str | None = None,
    notes: str | None = None,
    status: TaskStatus | None = None,
    due_date: datetime | None = None,
    priority_id: str | None = None,
) -> Task | None:
    """Update task fields. Returns updated task or None if not found."""
    ensure_schema()
    with get_connection() as conn:
        updates = []
        params = []

        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes if notes else None)
        if status is not None:
            updates.append("status = ?")
            params.append(status.value)
        if due_date is not None:
            updates.append("due_date = ?")
            params.append(due_date.isoformat() if due_date else None)
        if priority_id is not None:
            updates.append("priority_id = ?")
            # Allow empty string to clear priority
            params.append(priority_id if priority_id else None)

        if not updates:
            return get_task(task_id)

        params.append(task_id)
        conn.execute(
            f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
            params,
        )

    return get_task(task_id)


def delete_task(task_id: int) -> bool:
    """Delete a task. Returns True if deleted."""
    ensure_schema()
    with get_connection() as conn:
        result = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return result.rowcount > 0


def _row_to_task(row: sqlite3.Row) -> Task:
    """Convert a database row to a Task."""
    due_date = None
    if row["due_date"]:
        due_date = datetime.fromisoformat(row["due_date"])

    created_at = None
    if row["created_at"]:
        created_at = datetime.fromisoformat(row["created_at"])

    return Task(
        id=row["id"],
        title=row["title"],
        status=TaskStatus(row["status"]),
        notes=row["notes"],
        due_date=due_date,
        created_at=created_at,
        priority_id=row["priority_id"] if "priority_id" in row.keys() else None,
        priority_name=row["priority_name"] if "priority_name" in row.keys() else None,
    )


def _get_subtasks(conn: sqlite3.Connection, task_id: int) -> list[Subtask]:
    """Get subtasks for a task, ordered by sort_order."""
    rows = conn.execute(
        """
        SELECT * FROM subtasks
        WHERE task_id = ?
        ORDER BY sort_order
        """,
        (task_id,),
    ).fetchall()

    return [_row_to_subtask(row) for row in rows]


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
# Subtask Operations
# ---------------------------------------------------------------------

def create_subtask(task_id: int, title: str, sort_order: int | None = None) -> Subtask:
    """Create a subtask. If sort_order not specified, appends to end."""
    ensure_schema()
    with get_connection() as conn:
        if sort_order is None:
            # Get max sort_order for this task
            result = conn.execute(
                "SELECT MAX(sort_order) as max_order FROM subtasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            sort_order = (result["max_order"] or 0) + 1

        cursor = conn.execute(
            """
            INSERT INTO subtasks (task_id, title, sort_order)
            VALUES (?, ?, ?)
            """,
            (task_id, title, sort_order),
        )
        return Subtask(
            id=cursor.lastrowid,
            task_id=task_id,
            title=title,
            sort_order=sort_order,
        )


def toggle_subtask(subtask_id: int) -> Subtask | None:
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


def delete_subtask(subtask_id: int) -> bool:
    """Delete a subtask. Returns True if deleted."""
    ensure_schema()
    with get_connection() as conn:
        result = conn.execute("DELETE FROM subtasks WHERE id = ?", (subtask_id,))
        return result.rowcount > 0


def reorder_subtasks(task_id: int, subtask_ids: list[int]) -> None:
    """Reorder subtasks by providing new order of IDs."""
    ensure_schema()
    with get_connection() as conn:
        for order, subtask_id in enumerate(subtask_ids):
            conn.execute(
                "UPDATE subtasks SET sort_order = ? WHERE id = ? AND task_id = ?",
                (order, subtask_id, task_id),
            )


# ---------------------------------------------------------------------
# Seed Data (for development)
# ---------------------------------------------------------------------

def clear_tasks() -> int:
    """Delete all tasks. Returns count deleted."""
    ensure_schema()
    with get_connection() as conn:
        result = conn.execute("DELETE FROM tasks")
        return result.rowcount


def seed_database() -> dict:
    """Seed with sample tasks (no priority associations yet)."""
    tasks_data = [
        ("Leetcode baseline x2", "11, Two Pointers next"),
        ("Renew Mint", None),
        ("Check if bills arrived yet", None),
        ("Forward Sarah's email to Ronique", None),
        ("Get precise dates / times for Teacher Appreciation Day visit", None),
        ("Make a list of things we want to learn from the kids this May", None),
        ("Create PE LinkedIn profile", "Research what established nonprofit LinkedIns look like, then make ours similar"),
        ("Double check vendor status - make sure we still have it", None),
        ("Work on business model", "Include school discretionary funding"),
        ("Get a project management system set up", None),
        ("LinkedIn Networking", "Get on Twitter? Where are engineers? VC approaches"),
        ("Serve networking suggestions", None),
        ("Reach out to Adam", "Introduce Akanksa to return some stuff to the apartment"),
        ("Update personal LinkedIn profile", "Do a thorough review"),
        ("Look at Ronique's LinkedIn and update", None),
        ("Restore MoE", "Double check that it's live"),
        ("Restore Vida", "Figure out why it's not live"),
    ]

    task_count = 0
    for title, notes in tasks_data:
        create_task(title, notes)
        task_count += 1

    return {"tasks": task_count}
