"""Task persistence: CRUD operations, schema, and migrations."""

import sqlite3
from datetime import datetime

from ulid import ULID

from praxis_core.model.tasks import Task, TaskStatus, Subtask
from praxis_core.persistence.database import get_connection


# ---------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------

TASKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    entity_id TEXT REFERENCES entities(id),
    assigned_to INTEGER REFERENCES users(id),
    created_by INTEGER REFERENCES users(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    description TEXT,
    due_date TEXT,
    priority_id TEXT REFERENCES priorities(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS subtasks (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority_id);
CREATE INDEX IF NOT EXISTS idx_tasks_entity ON tasks(entity_id);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_to);
CREATE INDEX IF NOT EXISTS idx_subtasks_task ON subtasks(task_id);

-- Tags (user-scoped labels for tasks and priorities)
CREATE TABLE IF NOT EXISTS tags (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    name TEXT NOT NULL,
    color TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(entity_id, name)
);
CREATE INDEX IF NOT EXISTS idx_tags_entity ON tags(entity_id);

-- Junction table: task <-> tag (many-to-many)
CREATE TABLE IF NOT EXISTS task_tags (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_task_tags_task ON task_tags(task_id);
CREATE INDEX IF NOT EXISTS idx_task_tags_tag ON task_tags(tag_id);

-- Junction table: priority <-> tag (many-to-many)
CREATE TABLE IF NOT EXISTS priority_tags (
    priority_id TEXT NOT NULL REFERENCES priorities(id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (priority_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_priority_tags_priority ON priority_tags(priority_id);
CREATE INDEX IF NOT EXISTS idx_priority_tags_tag ON priority_tags(tag_id);
"""


def ensure_schema() -> None:
    """Ensure the tasks schema exists."""
    with get_connection() as conn:
        conn.executescript(TASKS_SCHEMA)
        _migrate_outbox(conn)


# ---------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------

def _migrate_outbox(conn: sqlite3.Connection) -> None:
    """Add outbox columns if they don't exist."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    # Rename notes -> description if needed
    if "notes" in columns and "description" not in columns:
        conn.execute("ALTER TABLE tasks RENAME COLUMN notes TO description")
    if "is_in_outbox" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN is_in_outbox INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE tasks ADD COLUMN moved_to_outbox_at TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_outbox ON tasks(is_in_outbox)")


def _maybe_migrate(conn: sqlite3.Connection) -> None:
    """Handle schema migrations from older versions."""
    # Get current table info
    tables = {row["name"] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    if "tasks" not in tables:
        return  # Fresh install, no migration needed

    columns = {row["name"] for row in conn.execute(
        "PRAGMA table_info(tasks)"
    ).fetchall()}

    # Check if already migrated to ULID (id is TEXT, entity_id exists)
    if "entity_id" in columns:
        return  # Already migrated

    # Need to migrate from integer IDs to ULIDs
    _migrate_to_ulid(conn)


def _migrate_to_ulid(conn: sqlite3.Connection) -> None:
    """Migrate tasks from integer IDs to ULIDs with entity ownership."""
    # Get user entity mappings
    user_entities = {}
    for row in conn.execute("SELECT id, entity_id FROM users WHERE entity_id IS NOT NULL").fetchall():
        user_entities[row["id"]] = row["entity_id"]

    # Get valid priority IDs
    valid_priorities = {row["id"] for row in conn.execute("SELECT id FROM priorities").fetchall()}

    # Read existing tasks
    old_tasks = conn.execute("""
        SELECT id, user_id, name, status, description, due_date, priority_id, created_at
        FROM tasks
    """).fetchall()

    # Create ID mapping (old int -> new ULID)
    id_mapping = {}
    for row in old_tasks:
        id_mapping[row["id"]] = str(ULID())

    # Read existing subtasks (if any)
    old_subtasks = conn.execute("""
        SELECT id, task_id, title, completed, sort_order, completed_at
        FROM subtasks
    """).fetchall()

    subtask_id_mapping = {}
    for row in old_subtasks:
        subtask_id_mapping[row["id"]] = str(ULID())

    # Drop old tables and create new ones
    conn.executescript("""
        PRAGMA foreign_keys=OFF;
        DROP TABLE IF EXISTS subtasks;
        DROP TABLE IF EXISTS tasks;
        PRAGMA foreign_keys=ON;
    """)

    # Create new schema
    conn.executescript(TASKS_SCHEMA)

    # Insert migrated tasks
    for row in old_tasks:
        new_id = id_mapping[row["id"]]
        user_id = row["user_id"]
        entity_id = user_entities.get(user_id) if user_id else None

        # Clean up invalid priority_id references
        priority_id = row["priority_id"]
        if priority_id and priority_id not in valid_priorities:
            priority_id = None  # Orphaned reference, move to inbox

        conn.execute("""
            INSERT INTO tasks (id, entity_id, assigned_to, created_by, user_id,
                             name, status, notes, due_date, priority_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            new_id,
            entity_id,
            user_id,  # assigned_to = original user
            user_id,  # created_by = original user
            user_id,  # deprecated user_id
            row["name"],
            row["status"],
            row["notes"],
            row["due_date"],
            priority_id,
            row["created_at"],
        ))

    # Insert migrated subtasks
    for row in old_subtasks:
        new_id = subtask_id_mapping[row["id"]]
        new_task_id = id_mapping.get(row["task_id"])
        if new_task_id:  # Only if parent task exists
            conn.execute("""
                INSERT INTO subtasks (id, task_id, title, completed, sort_order, completed_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                new_id,
                new_task_id,
                row["title"],
                row["completed"],
                row["sort_order"],
                row["completed_at"],
            ))


# ---------------------------------------------------------------------
# Row Conversion
# ---------------------------------------------------------------------

def _row_to_task(row: sqlite3.Row) -> Task:
    """Convert a database row to a Task."""
    due_date = None
    if row["due_date"]:
        due_date = datetime.fromisoformat(row["due_date"])

    created_at = None
    if row["created_at"]:
        created_at = datetime.fromisoformat(row["created_at"])

    # Read entity fields (may not exist in older schemas during migration)
    keys = row.keys()
    entity_id = row["entity_id"] if "entity_id" in keys else None
    assigned_to = row["assigned_to"] if "assigned_to" in keys else None
    created_by = row["created_by"] if "created_by" in keys else None

    # Handle description (was 'notes' in older schemas)
    description = row["description"] if "description" in keys else (row["notes"] if "notes" in keys else None)

    # Outbox fields
    is_in_outbox = bool(row["is_in_outbox"]) if "is_in_outbox" in keys and row["is_in_outbox"] else False
    moved_to_outbox_at = None
    if "moved_to_outbox_at" in keys and row["moved_to_outbox_at"]:
        moved_to_outbox_at = datetime.fromisoformat(row["moved_to_outbox_at"])

    return Task(
        id=row["id"],
        name=row["name"],
        status=TaskStatus(row["status"]),
        entity_id=entity_id,
        assigned_to=assigned_to,
        created_by=created_by,
        description=description,
        due_date=due_date,
        created_at=created_at,
        priority_id=row["priority_id"] if "priority_id" in keys else None,
        is_in_outbox=is_in_outbox,
        moved_to_outbox_at=moved_to_outbox_at,
        priority_name=row["priority_name"] if "priority_name" in keys else None,
        priority_type=row["priority_type"] if "priority_type" in keys else None,
    )


def _get_subtasks(conn: sqlite3.Connection, task_id: str) -> list[Subtask]:
    """Get subtasks for a task, ordered by sort_order."""
    from praxis_core.persistence.subtask_repo import _row_to_subtask

    rows = conn.execute(
        """
        SELECT * FROM subtasks
        WHERE task_id = ?
        ORDER BY sort_order
        """,
        (task_id,),
    ).fetchall()

    return [_row_to_subtask(row) for row in rows]


# ---------------------------------------------------------------------
# Task CRUD
# ---------------------------------------------------------------------

def create_task(
    name: str,
    notes: str | None = None,  # Deprecated parameter name, use description
    due_date: datetime | None = None,
    priority_id: str | None = None,
    entity_id: str | None = None,
    assigned_to: int | None = None,
    created_by: int | None = None,
    description: str | None = None,
) -> Task:
    """Create a new task."""
    ensure_schema()
    task_id = str(ULID())
    now = datetime.now()

    # Support both 'notes' (deprecated) and 'description' parameters
    desc = description or notes

    with get_connection() as conn:
        due_str = due_date.isoformat() if due_date else None
        conn.execute(
            """
            INSERT INTO tasks (id, entity_id, assigned_to, created_by,
                             name, description, due_date, priority_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, entity_id, assigned_to, created_by,
             name, desc, due_str, priority_id, now.isoformat()),
        )
        return Task(
            id=task_id,
            name=name,
            status=TaskStatus.QUEUED,
            entity_id=entity_id,
            assigned_to=assigned_to,
            created_by=created_by,
            description=desc,
            due_date=due_date,
            priority_id=priority_id,
            created_at=now,
            subtasks=[],
        )


def get_task(task_id: str) -> Task | None:
    """Get a task by ID."""
    ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT t.*, p.name as priority_name, p.priority_type as priority_type
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


def _apply_outbox_fields(updates: list[str], params: list, status: TaskStatus) -> None:
    """Add outbox fields to an UPDATE query when task is marked done."""
    if status == TaskStatus.DONE:
        updates.append("is_in_outbox = 1")
        updates.append("moved_to_outbox_at = ?")
        params.append(datetime.now().isoformat())


def update_task_status(task_id: str, status: TaskStatus) -> None:
    """Update a task's status. Auto-moves to outbox when done."""
    ensure_schema()
    updates = ["status = ?"]
    params: list = [status.value]
    _apply_outbox_fields(updates, params, status)
    params.append(task_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", params)


def update_task(
    task_id: str,
    name: str | None = None,
    description: str | None = None,
    status: TaskStatus | None = None,
    due_date: datetime | None = None,
    priority_id: str | None = None,
    assigned_to: int | None = -1,  # -1 means "don't change", None means "unassign"
    notes: str | None = None,  # Deprecated, use description
) -> Task | None:
    """Update task fields. Returns updated task or None if not found."""
    ensure_schema()

    # Support both 'notes' (deprecated) and 'description' parameters
    desc = description if description is not None else notes

    with get_connection() as conn:
        updates = []
        params = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if desc is not None:
            updates.append("description = ?")
            params.append(desc if desc else None)
        if status is not None:
            updates.append("status = ?")
            params.append(status.value)
            _apply_outbox_fields(updates, params, status)
        if due_date is not None:
            updates.append("due_date = ?")
            params.append(due_date.isoformat() if due_date else None)
        if priority_id is not None:
            updates.append("priority_id = ?")
            # Allow empty string to clear priority
            params.append(priority_id if priority_id else None)
        if assigned_to != -1:
            updates.append("assigned_to = ?")
            params.append(assigned_to)

        if not updates:
            return get_task(task_id)

        params.append(task_id)
        conn.execute(
            f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
            params,
        )

    return get_task(task_id)


def restore_from_outbox(task_id: str) -> Task | None:
    """Restore a task from the outbox back to the queue."""
    ensure_schema()
    with get_connection() as conn:
        conn.execute(
            "UPDATE tasks SET status = 'queued', is_in_outbox = 0, moved_to_outbox_at = NULL WHERE id = ?",
            (task_id,),
        )
    return get_task(task_id)


def purge_old_outbox_tasks(days: int = 7) -> int:
    """Hard-delete outbox tasks older than N days. Returns count deleted."""
    ensure_schema()
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM tasks WHERE is_in_outbox = 1 AND moved_to_outbox_at < ?",
            (cutoff,),
        )
        return result.rowcount


def delete_task(task_id: str) -> bool:
    """Delete a task. Returns True if deleted."""
    ensure_schema()
    with get_connection() as conn:
        result = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return result.rowcount > 0


def unlink_tasks_from_priority(priority_id: str) -> int:
    """Unlink all tasks from a priority (move to inbox). Returns count of affected tasks."""
    ensure_schema()
    with get_connection() as conn:
        result = conn.execute(
            "UPDATE tasks SET priority_id = NULL WHERE priority_id = ?",
            (priority_id,),
        )
        return result.rowcount


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
    for name, notes in tasks_data:
        create_task(name, notes)
        task_count += 1

    return {"tasks": task_count}
