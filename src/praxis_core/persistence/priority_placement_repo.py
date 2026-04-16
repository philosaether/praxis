"""Priority placement (adoption) persistence.

A placement positions a shared priority within the adopter's own tree.
The priority data stays shared — placement is just positioning metadata.
"""

from praxis_core.persistence.database import get_connection


# -----------------------------------------------------------------------------
# Schema
# -----------------------------------------------------------------------------

PRIORITY_PLACEMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS priority_placements (
    priority_id TEXT NOT NULL REFERENCES priorities(id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    parent_priority_id TEXT REFERENCES priorities(id) ON DELETE SET NULL,
    rank INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (priority_id, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_placements_entity ON priority_placements(entity_id);
"""


# -----------------------------------------------------------------------------
# Placement CRUD
# -----------------------------------------------------------------------------

def adopt_priority(
    priority_id: str,
    entity_id: str,
    parent_priority_id: str | None = None,
    rank: int | None = None,
) -> dict:
    """
    Place a shared priority into the adopter's tree.
    If already adopted, updates the position.
    """
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        # Auto-assign rank if not provided: append after existing siblings
        if rank is None:
            if parent_priority_id:
                # Count children of the parent (via edge table)
                row = conn.execute(
                    """SELECT COUNT(*) as n FROM priority_edges pe
                       JOIN priorities p ON pe.child_id = p.id
                       WHERE pe.parent_id = ? AND p.entity_id = ?""",
                    (parent_priority_id, entity_id)
                ).fetchone()
            else:
                # Count root priorities (no parent edge) for this entity
                row = conn.execute(
                    """SELECT COUNT(*) as n FROM priorities p
                       WHERE p.entity_id = ?
                       AND p.id NOT IN (SELECT child_id FROM priority_edges)""",
                    (entity_id,)
                ).fetchone()
            # Count existing placements at same level too
            if parent_priority_id:
                placement_count = conn.execute(
                    "SELECT COUNT(*) as n FROM priority_placements WHERE entity_id = ? AND parent_priority_id = ?",
                    (entity_id, parent_priority_id)
                ).fetchone()["n"]
            else:
                placement_count = conn.execute(
                    "SELECT COUNT(*) as n FROM priority_placements WHERE entity_id = ? AND parent_priority_id IS NULL",
                    (entity_id,)
                ).fetchone()["n"]
            rank = (row["n"] if row else 0) + placement_count + 1

        conn.execute(
            """
            INSERT INTO priority_placements (priority_id, entity_id, parent_priority_id, rank)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(priority_id, entity_id) DO UPDATE SET
                parent_priority_id = excluded.parent_priority_id,
                rank = excluded.rank
            """,
            (priority_id, entity_id, parent_priority_id, rank)
        )

    return {
        "priority_id": priority_id,
        "entity_id": entity_id,
        "parent_priority_id": parent_priority_id,
        "rank": rank,
    }


def unadopt_priority(priority_id: str, entity_id: str) -> bool:
    """Remove a placement, returning the priority to 'Shared with Me'.
    Also cleans up any priority_edges that were created by drag-and-drop
    while the priority was adopted (edges to/from adopter-owned priorities).
    """
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM priority_placements WHERE priority_id = ? AND entity_id = ?",
            (priority_id, entity_id)
        )
        if cursor.rowcount == 0:
            return False

        # Clean up edges connecting this shared priority to the adopter's owned priorities.
        # The adopted priority isn't owned by this entity, so any edge linking it
        # to an entity-owned priority was created by drag-and-drop during adoption.
        conn.execute(
            """DELETE FROM priority_edges WHERE child_id = ? AND parent_id IN (
                SELECT id FROM priorities WHERE entity_id = ?
            )""",
            (priority_id, entity_id)
        )
        conn.execute(
            """DELETE FROM priority_edges WHERE parent_id = ? AND child_id IN (
                SELECT id FROM priorities WHERE entity_id = ?
            )""",
            (priority_id, entity_id)
        )

        return True


def get_placement(priority_id: str, entity_id: str) -> dict | None:
    """Get the placement for a specific priority + entity, or None."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        row = conn.execute(
            """SELECT priority_id, entity_id, parent_priority_id, rank
               FROM priority_placements WHERE priority_id = ? AND entity_id = ?""",
            (priority_id, entity_id)
        ).fetchone()

    return dict(row) if row else None


def list_placements(entity_id: str) -> list[dict]:
    """List all placements for an entity (all adopted priorities)."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT pp.priority_id, pp.parent_priority_id, pp.rank,
                      p.name, p.priority_type, p.status, p.entity_id as owner_entity_id
               FROM priority_placements pp
               JOIN priorities p ON pp.priority_id = p.id
               WHERE pp.entity_id = ?
               ORDER BY pp.rank""",
            (entity_id,)
        ).fetchall()

    return [dict(row) for row in rows]


def fork_on_unshare(priority_id: str, adopter_entity_id: str, adopter_user_id: int) -> str | None:
    """
    Fork a priority tree for an adopter when the owner unshares.
    Deep-copies the priority + sub-priorities + adopter's tasks into the adopter's entity.
    Returns the new root priority ID, or None if no placement existed.
    """
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    placement = get_placement(priority_id, adopter_entity_id)
    if not placement:
        return None

    from ulid import ULID
    from datetime import datetime

    now = datetime.now().isoformat()

    with get_connection() as conn:
        # Collect the priority and all descendants via edge table
        def collect_descendants(pid):
            """Recursively collect priority IDs in the subtree."""
            ids = [pid]
            children = conn.execute(
                "SELECT child_id FROM priority_edges WHERE parent_id = ?", (pid,)
            ).fetchall()
            for child in children:
                ids.extend(collect_descendants(child["child_id"]))
            return ids

        source_ids = collect_descendants(priority_id)

        # Collect parent edges for the subtree
        edge_map = {}  # child_id -> parent_id (within subtree)
        for sid in source_ids:
            parent_row = conn.execute(
                "SELECT parent_id FROM priority_edges WHERE child_id = ? AND parent_id IN ({})".format(
                    ",".join("?" * len(source_ids))
                ),
                (sid, *source_ids)
            ).fetchone()
            if parent_row:
                edge_map[sid] = parent_row["parent_id"]

        # Map old IDs to new IDs
        id_map = {old_id: str(ULID()) for old_id in source_ids}

        # Copy each priority
        for old_id in source_ids:
            new_id = id_map[old_id]
            source = conn.execute(
                "SELECT * FROM priorities WHERE id = ?", (old_id,)
            ).fetchone()
            if not source:
                continue

            source = dict(source)
            conn.execute(
                """INSERT INTO priorities (id, entity_id, name, priority_type, status,
                   description, rank, created_at, updated_at,
                   auto_assign_owner, auto_assign_creator, last_engaged_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_id, adopter_entity_id, source["name"], source["priority_type"],
                    source["status"], source.get("description"),
                    source["rank"] if old_id != priority_id else placement["rank"],
                    now, now,
                    source.get("auto_assign_owner", 0), source.get("auto_assign_creator", 0),
                    source.get("last_engaged_at"),
                )
            )

        # Recreate edges within the copied subtree
        for child_id, parent_id in edge_map.items():
            conn.execute(
                "INSERT INTO priority_edges (child_id, parent_id) VALUES (?, ?)",
                (id_map[child_id], id_map[parent_id])
            )

        # Connect the root copy to the placement parent (if any)
        if placement["parent_priority_id"]:
            conn.execute(
                "INSERT INTO priority_edges (child_id, parent_id) VALUES (?, ?)",
                (id_map[priority_id], placement["parent_priority_id"])
            )

        # Copy tasks belonging to the adopter
        for old_id in source_ids:
            new_id = id_map[old_id]
            tasks = conn.execute(
                """SELECT * FROM tasks WHERE priority_id = ?
                   AND (assigned_to = ? OR created_by = ? OR entity_id = ?)""",
                (old_id, adopter_user_id, adopter_user_id, adopter_entity_id)
            ).fetchall()

            for task in tasks:
                task = dict(task)
                new_task_id = str(ULID())
                conn.execute(
                    """INSERT INTO tasks (id, entity_id, name, status, description,
                       due_date, priority_id, assigned_to, created_by,
                       created_at, is_in_outbox, moved_to_outbox_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        new_task_id, adopter_entity_id, task["name"], task["status"],
                        task.get("description"), task.get("due_date"), new_id,
                        task.get("assigned_to"), task.get("created_by"),
                        task.get("created_at", now),
                        task.get("is_in_outbox", 0), task.get("moved_to_outbox_at"),
                    )
                )

        # Update placement to point at the new copy
        new_root_id = id_map[priority_id]
        conn.execute(
            """UPDATE priority_placements SET priority_id = ?
               WHERE priority_id = ? AND entity_id = ?""",
            (new_root_id, priority_id, adopter_entity_id)
        )

    return new_root_id
