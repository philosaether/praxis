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

def seed_database() -> dict:

    # Sample workstreams
    streams = [
        ("Praxis", "Building the cue-based task system"),
        ("Leetcode", "Interview prep, algorithm practice"),
        ("Job Search", "Applications, resume updates, interview scheduling"),
        ("Reading - deep", "Books, papers, long-form technical content"),
        ("Reading - news", "Industry news, blog posts, light content"),
        ("Networking", "Outreach, relationship maintenance, intros"),
        ("Writing", "Essays, blog posts, documentation"),
        ("Proper Elevation", "PE business tasks"),
        ("Health", "Exercise, sleep, nutrition habits"),
    ]

    # Sample tasks per stream
    stream_tasks = {
        "Praxis": [
            "Implement task CRUD via CLI",
            "Add queue pull logic",
            "Integrate Claude API for cue generation",
            "Write project README",
        ],
        "Leetcode": [
            "Establish performance baseline",
            "Review array/string patterns",
            "Practice binary search problems",
        ],
        "Job Search": [
            "Update resume with Praxis project",
            "Research Block/Bitkey team",
            "Draft cover letter template",
        ],
        "Reading - deep": [
            "Finish 'Designing Data-Intensive Applications' ch. 5",
            "Read Anthropic's constitutional AI paper",
            "Review Python asyncio documentation",
        ],
        "Reading - news": [
            "Catch up on Hacker News weekly digest",
            "Read latest Python release notes",
        ],
        "Networking": [
            "Reply to James re: coffee chat",
            "Send intro email to potential mentor",
            "Update LinkedIn with recent project",
        ],
        "Writing": [
            "Outline 'I Used AI to Get a Job' essay",
        ],
        "Proper Elevation": [
            "Review PE task backlog with Ronique",
        ],
        "Health": [
            "Schedule annual physical",
            "Try new morning routine for one week",
        ],
    }

    workstream_count = 0
    task_count = 0

    for name, description in streams:
        if get_workstream_by_name(name):
            continue

        ws = create_workstream(name, description)
        workstream_count += 1

        for task_title in stream_tasks.get(name, []):
            create_task(ws.id, task_title)
            task_count += 1

    return {"workstreams": workstream_count, "tasks": task_count}