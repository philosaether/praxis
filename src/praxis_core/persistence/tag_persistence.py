"""Tag persistence: CRUD operations for tags and junction tables."""

from datetime import datetime

from ulid import ULID

from praxis_core.model.tags import Tag
from praxis_core.persistence.database import get_connection
from praxis_core.persistence.task_persistence import ensure_schema


# ---------------------------------------------------------------------
# Tag CRUD
# ---------------------------------------------------------------------

def create_tag(entity_id: str, name: str, color: str | None = None) -> Tag:
    """Create a new tag for an entity."""
    ensure_schema()
    tag_id = str(ULID())
    now = datetime.now()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO tags (id, entity_id, name, color, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (tag_id, entity_id, name, color, now.isoformat()),
        )
        return Tag(
            id=tag_id,
            entity_id=entity_id,
            name=name,
            color=color,
            created_at=now,
        )


def get_tag(tag_id: str) -> Tag | None:
    """Get a tag by ID."""
    ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM tags WHERE id = ?", (tag_id,)
        ).fetchone()
        if row:
            return _row_to_tag(row)
        return None


def get_tag_by_name(entity_id: str, name: str) -> Tag | None:
    """Get a tag by name for a specific entity."""
    ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM tags WHERE entity_id = ? AND name = ?",
            (entity_id, name),
        ).fetchone()
        if row:
            return _row_to_tag(row)
        return None


def get_or_create_tag(entity_id: str, name: str, color: str | None = None) -> Tag:
    """Get existing tag by name or create it if it doesn't exist."""
    tag = get_tag_by_name(entity_id, name)
    if tag:
        return tag
    return create_tag(entity_id, name, color)


def get_tags_by_entity(entity_id: str) -> list[Tag]:
    """Get all tags for an entity."""
    ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM tags WHERE entity_id = ? ORDER BY name",
            (entity_id,),
        ).fetchall()
        return [_row_to_tag(row) for row in rows]


def search_tags(entity_id: str, query: str, limit: int = 10) -> list[Tag]:
    """Search tags by name prefix for autocomplete."""
    ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM tags
            WHERE entity_id = ? AND name LIKE ?
            ORDER BY name
            LIMIT ?
            """,
            (entity_id, f"{query}%", limit),
        ).fetchall()
        return [_row_to_tag(row) for row in rows]


def update_tag(tag_id: str, name: str | None = None, color: str | None = None) -> Tag | None:
    """Update tag fields. Returns updated tag or None if not found."""
    ensure_schema()
    with get_connection() as conn:
        updates = []
        params = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if color is not None:
            updates.append("color = ?")
            params.append(color if color else None)

        if not updates:
            return get_tag(tag_id)

        params.append(tag_id)
        conn.execute(
            f"UPDATE tags SET {', '.join(updates)} WHERE id = ?",
            params,
        )

    return get_tag(tag_id)


def delete_tag(tag_id: str) -> bool:
    """Delete a tag. Returns True if deleted."""
    ensure_schema()
    with get_connection() as conn:
        # Junction table rows will cascade delete
        result = conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        return result.rowcount > 0


def _row_to_tag(row) -> Tag:
    """Convert a database row to a Tag."""
    created_at = None
    if row["created_at"]:
        created_at = datetime.fromisoformat(row["created_at"])

    return Tag(
        id=row["id"],
        entity_id=row["entity_id"],
        name=row["name"],
        color=row["color"],
        created_at=created_at,
    )


# ---------------------------------------------------------------------
# Task <-> Tag Junction Operations
# ---------------------------------------------------------------------

def add_tag_to_task(task_id: str, tag_id: str) -> bool:
    """Add a tag to a task. Returns True if added, False if already exists."""
    ensure_schema()
    with get_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO task_tags (task_id, tag_id) VALUES (?, ?)",
                (task_id, tag_id),
            )
            return True
        except Exception:
            # Unique constraint violation - already exists
            return False


def remove_tag_from_task(task_id: str, tag_id: str) -> bool:
    """Remove a tag from a task. Returns True if removed."""
    ensure_schema()
    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM task_tags WHERE task_id = ? AND tag_id = ?",
            (task_id, tag_id),
        )
        return result.rowcount > 0


def get_tags_for_task(task_id: str) -> list[Tag]:
    """Get all tags for a task."""
    ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT t.* FROM tags t
            JOIN task_tags tt ON t.id = tt.tag_id
            WHERE tt.task_id = ?
            ORDER BY t.name
            """,
            (task_id,),
        ).fetchall()
        return [_row_to_tag(row) for row in rows]


def get_task_ids_by_tag(tag_id: str) -> list[str]:
    """Get all task IDs that have a specific tag."""
    ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT task_id FROM task_tags WHERE tag_id = ?",
            (tag_id,),
        ).fetchall()
        return [row["task_id"] for row in rows]


def get_task_ids_by_tag_names(entity_id: str, tag_names: list[str]) -> set[str]:
    """Get task IDs that have any of the specified tags (by name)."""
    ensure_schema()
    if not tag_names:
        return set()

    with get_connection() as conn:
        placeholders = ",".join("?" * len(tag_names))
        rows = conn.execute(
            f"""
            SELECT DISTINCT tt.task_id FROM task_tags tt
            JOIN tags t ON tt.tag_id = t.id
            WHERE t.entity_id = ? AND t.name IN ({placeholders})
            """,
            [entity_id] + tag_names,
        ).fetchall()
        return {row["task_id"] for row in rows}


def get_tags_for_tasks(task_ids: list[str]) -> dict[str, set[str]]:
    """
    Get tags for multiple tasks in a single query.

    Returns a dict mapping task_id -> set of tag names.
    """
    ensure_schema()
    if not task_ids:
        return {}

    with get_connection() as conn:
        placeholders = ",".join("?" * len(task_ids))
        rows = conn.execute(
            f"""
            SELECT tt.task_id, t.name FROM task_tags tt
            JOIN tags t ON tt.tag_id = t.id
            WHERE tt.task_id IN ({placeholders})
            """,
            task_ids,
        ).fetchall()

        result: dict[str, set[str]] = {tid: set() for tid in task_ids}
        for row in rows:
            result[row["task_id"]].add(row["name"])
        return result


# ---------------------------------------------------------------------
# Priority <-> Tag Junction Operations
# ---------------------------------------------------------------------

def add_tag_to_priority(priority_id: str, tag_id: str) -> bool:
    """Add a tag to a priority. Returns True if added, False if already exists."""
    ensure_schema()
    with get_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO priority_tags (priority_id, tag_id) VALUES (?, ?)",
                (priority_id, tag_id),
            )
            return True
        except Exception:
            # Unique constraint violation - already exists
            return False


def remove_tag_from_priority(priority_id: str, tag_id: str) -> bool:
    """Remove a tag from a priority. Returns True if removed."""
    ensure_schema()
    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM priority_tags WHERE priority_id = ? AND tag_id = ?",
            (priority_id, tag_id),
        )
        return result.rowcount > 0


def get_tags_for_priority(priority_id: str) -> list[Tag]:
    """Get all tags for a priority."""
    ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT t.* FROM tags t
            JOIN priority_tags pt ON t.id = pt.tag_id
            WHERE pt.priority_id = ?
            ORDER BY t.name
            """,
            (priority_id,),
        ).fetchall()
        return [_row_to_tag(row) for row in rows]
