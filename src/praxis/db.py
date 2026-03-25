import sqlite3
from datetime import datetime
from pathlib import Path

from praxis.models import Task, TaskStatus, Workstream

DB_DIR = Path.home() / ".praxis"
DB_PATH = DB_DIR / "praxis.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS workstreams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workstream_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    notes TEXT,
    due_date TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (workstream_id) REFERENCES workstreams(id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
"""

def get_connection() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn

# ---------------------------------------------------------------------
# Workstream operations
# ---------------------------------------------------------------------

def create_workstream(name: str, description: str | None = None) -> Workstream:
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO workstreams (name, description) VALUES (?, ?)",
            (name, description),
        )
        return Workstream(id=cursor.lastrowid, name=name, description=description)

def get_workstream_by_name(name: str) -> Workstream | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, description FROM workstreams WHERE LOWER(name) = LOWER(?)",
            (name,),
        ).fetchone()
        if row:
            return Workstream(id=row["id"], name=row["name"], description=row["description"])
        return None

def list_workstreams() -> list[Workstream]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, description FROM workstreams ORDER BY name"
        ).fetchall()
        return [
            Workstream(id=row["id"], name=row["name"], description=row["description"])
            for row in rows
        ]

# ---------------------------------------------------------------------
# Task operations
# ---------------------------------------------------------------------

def create_task(
        workstream_id: int,
        title: str,
        notes: str | None = None,
        due_date: datetime | None = None,
) -> Task:
    with get_connection() as conn:
        due_str = due_date.isoformat() if due_date else None
        cursor = conn.execute(
            """
            INSERT INTO tasks (workstream_id, title, notes, due_date)
            VALUES (?, ?, ?, ?)
            """,
            (workstream_id, title, notes, due_str),
        )
        return Task(
            id=cursor.lastrowid,  
            workstream_id=workstream_id,
            title=title,
            status=TaskStatus.QUEUED,
            notes=notes,
            due_date=due_date,
        )

def get_queued_tasks(workstream_id: int | None = None) -> list[Task]:
    with get_connection() as conn:
        if workstream_id:
            rows = conn.execute(
                """
                SELECT t.*, w.name as workstream_name
                FROM tasks t
                JOIN workstreams w ON t.workstream_id = w.id
                WHERE t.status = 'queued' AND t.workstream_id = ?
                ORDER BY t.created_at
                """,
                (workstream_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT t.*, w.name as workstream_name
                FROM tasks t
                JOIN workstreams w ON t.workstream_id = w.id
                WHERE t.status = 'queued'
                ORDER BY t.created_at
                """
            ).fetchall()
        return [_row_to_task(row) for row in rows]
    
def update_task_status(task_id: int, status: TaskStatus) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE tasks SET status = ? WHERE id = ?",
            (status.value, task_id),
        )


def get_task(task_id: int) -> Task | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT t.*, w.name as workstream_name
            FROM tasks t
            JOIN workstreams w ON t.workstream_id = w.id
            WHERE t.id = ?
            """,
            (task_id,),
        ).fetchone()
        if row:
            return _row_to_task(row)
        return None


def list_tasks(
    workstream_id: int | None = None,
    status: TaskStatus | None = None,
    include_done: bool = True,
) -> list[Task]:
    """List tasks with optional filters. Done tasks sorted to bottom."""
    with get_connection() as conn:
        query = """
            SELECT t.*, w.name as workstream_name
            FROM tasks t
            JOIN workstreams w ON t.workstream_id = w.id
            WHERE 1=1
        """
        params = []

        if workstream_id:
            query += " AND t.workstream_id = ?"
            params.append(workstream_id)

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
        return [_row_to_task(row) for row in rows]


def update_task(
    task_id: int,
    title: str | None = None,
    notes: str | None = None,
    status: TaskStatus | None = None,
    due_date: datetime | None = None,
    workstream_id: int | None = None,
) -> Task | None:
    """Update task fields. Returns updated task or None if not found."""
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
        if workstream_id is not None:
            updates.append("workstream_id = ?")
            params.append(workstream_id)

        if not updates:
            return get_task(task_id)

        params.append(task_id)
        conn.execute(
            f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
            params,
        )

    return get_task(task_id)

def _row_to_task(row: sqlite3.Row) -> Task:
    due_date = None
    if row["due_date"]:
        due_date = datetime.fromisoformat(row["due_date"])

    created_at = None
    if row["created_at"]:
        created_at = datetime.fromisoformat(row["created_at"])
    
    return Task(
        id=row["id"],
        workstream_id=row["workstream_id"],
        title=row["title"],
        status=TaskStatus(row["status"]),
        notes=row["notes"],
        due_date=due_date,
        created_at=created_at,
        workstream_name=row["workstream_name"] if "workstream_name" in row.keys() else None,
    )

# ---------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------

def clear_tasks() -> int:
    """Delete all tasks. Returns count deleted."""
    with get_connection() as conn:
        result = conn.execute("DELETE FROM tasks")
        return result.rowcount


def seed_database() -> dict:
    """Seed with Phil's actual to-do list (2026-03-25)."""

    # Workstreams
    streams = [
        ("Leetcode", "Interview prep, algorithm practice"),
        ("Personal", "Personal admin and errands"),
        ("Proper Elevation", "PE nonprofit tasks"),
        ("Networking", "Outreach, relationship building"),
        ("Tech Projects", "Side projects and web properties"),
    ]

    # Tasks organized by workstream
    stream_tasks = {
        "Leetcode": [
            ("Leetcode baseline x2", "11, Two Pointers next"),
        ],
        "Personal": [
            ("Renew Mint", None),
            ("Check if bills arrived yet", None),
        ],
        "Proper Elevation": [
            ("Forward Sarah's email to Ronique", None),
            ("Get precise dates / times for Teacher Appreciation Day visit", None),
            ("Make a list of things we want to learn from the kids this May", None),
            ("Create PE LinkedIn profile", "Research what established nonprofit LinkedIns look like, then make ours similar"),
            ("Double check vendor status - make sure we still have it", None),
            ("Work on business model", "Include school discretionary funding"),
            ("Get a project management system set up", None),
        ],
        "Networking": [
            ("LinkedIn Networking", "Get on Twitter? Where are engineers? VC approaches"),
            ("Serve networking suggestions", None),
            ("Reach out to Adam", "Introduce Akanksa to return some stuff to the apartment"),
            ("Update personal LinkedIn profile", "Do a thorough review"),
            ("Look at Ronique's LinkedIn and update", None),
        ],
        "Tech Projects": [
            ("Restore MoE", "Double check that it's live"),
            ("Restore Vida", "Figure out why it's not live"),
        ],
    }

    workstream_count = 0
    task_count = 0

    for name, description in streams:
        ws = get_workstream_by_name(name)
        if not ws:
            ws = create_workstream(name, description)
            workstream_count += 1

        for task_data in stream_tasks.get(name, []):
            title, notes = task_data if isinstance(task_data, tuple) else (task_data, None)
            create_task(ws.id, title, notes)
            task_count += 1

    return {"workstreams": workstream_count, "tasks": task_count}