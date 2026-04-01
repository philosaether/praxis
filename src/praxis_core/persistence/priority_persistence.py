"""Priority persistence: PriorityGraph and SQLite operations."""

import sqlite3
from datetime import datetime

from praxis_core.model.priorities import (
    Priority,
    PriorityType,
    PriorityStatus,
    Value,
    Goal,
    Practice,
    Initiative,
)


# ---------------------------------------------------------------------
# SQLite Schema
# ---------------------------------------------------------------------

PRIORITIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS priorities (
    id TEXT PRIMARY KEY,
    entity_id TEXT REFERENCES entities(id),
    user_id INTEGER REFERENCES users(id),  -- deprecated, use entity_id
    priority_type TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',

    -- Common
    substatus TEXT,  -- Extension field (e.g., draft, backlog, abandoned)
    agent_context TEXT,
    notes TEXT,
    rank INTEGER,

    -- Task assignment settings
    auto_assign_owner INTEGER NOT NULL DEFAULT 1,
    auto_assign_creator INTEGER NOT NULL DEFAULT 0,

    -- Value (direction/principle, never completes)
    success_looks_like TEXT,
    obsolete_when TEXT,

    -- Goal (concrete outcome with end state)
    complete_when TEXT,
    due_date TEXT,
    progress TEXT,

    -- Practice
    rhythm_frequency TEXT,
    rhythm_constraints TEXT,
    generation_prompt TEXT,

    -- Metadata
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS priority_edges (
    child_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (child_id, parent_id),
    FOREIGN KEY (child_id) REFERENCES priorities(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES priorities(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_priorities_type ON priorities(priority_type);
CREATE INDEX IF NOT EXISTS idx_priorities_status ON priorities(status);
CREATE INDEX IF NOT EXISTS idx_priorities_entity ON priorities(entity_id);
CREATE INDEX IF NOT EXISTS idx_priorities_user ON priorities(user_id);  -- deprecated
CREATE INDEX IF NOT EXISTS idx_priority_edges_child ON priority_edges(child_id);
CREATE INDEX IF NOT EXISTS idx_priority_edges_parent ON priority_edges(parent_id);

-- Entity-based sharing (replaces priority_shares)
CREATE TABLE IF NOT EXISTS entity_shares (
    priority_id TEXT NOT NULL REFERENCES priorities(id) ON DELETE CASCADE,
    shared_with_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    permission TEXT NOT NULL DEFAULT 'contributor',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (priority_id, shared_with_entity_id)
);

CREATE INDEX IF NOT EXISTS idx_entity_shares_entity ON entity_shares(shared_with_entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_shares_priority ON entity_shares(priority_id);

-- Legacy table (deprecated, kept for migration)
CREATE TABLE IF NOT EXISTS priority_shares (
    priority_id TEXT NOT NULL REFERENCES priorities(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission TEXT NOT NULL DEFAULT 'contributor',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (priority_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_priority_shares_user ON priority_shares(user_id);
CREATE INDEX IF NOT EXISTS idx_priority_shares_priority ON priority_shares(priority_id);
"""


# ---------------------------------------------------------------------
# Row Conversion
# ---------------------------------------------------------------------

def priority_from_row(row: sqlite3.Row) -> Priority:
    """Convert a database row to a Priority subclass."""
    priority_type = PriorityType(row["priority_type"])
    status = PriorityStatus(row["status"])
    created_at = _parse_datetime(row["created_at"])
    updated_at = _parse_datetime(row["updated_at"])

    # Handle fields that may not exist in older schemas
    keys = row.keys()
    entity_id = row["entity_id"] if "entity_id" in keys else None
    substatus = row["substatus"] if "substatus" in keys else None
    auto_assign_owner = bool(row["auto_assign_owner"]) if "auto_assign_owner" in keys else True
    auto_assign_creator = bool(row["auto_assign_creator"]) if "auto_assign_creator" in keys else False

    common_kwargs = {
        "id": row["id"],
        "name": row["name"],
        "status": status,
        "substatus": substatus,
        "entity_id": entity_id,
        "agent_context": row["agent_context"],
        "notes": row["notes"],
        "rank": row["rank"],
        "auto_assign_owner": auto_assign_owner,
        "auto_assign_creator": auto_assign_creator,
        "created_at": created_at,
        "updated_at": updated_at,
    }

    match priority_type:
        case PriorityType.VALUE:
            return Value(
                **common_kwargs,
                priority_type=priority_type,
                success_looks_like=row["success_looks_like"],
                obsolete_when=row["obsolete_when"],
            )

        case PriorityType.GOAL:
            return Goal(
                **common_kwargs,
                priority_type=priority_type,
                complete_when=row["complete_when"],
                due_date=_parse_datetime(row["due_date"]),
                progress=row["progress"],
            )

        case PriorityType.PRACTICE:
            return Practice(
                **common_kwargs,
                priority_type=priority_type,
                rhythm_frequency=row["rhythm_frequency"],
                rhythm_constraints=row["rhythm_constraints"],
                generation_prompt=row["generation_prompt"],
            )

        case PriorityType.INITIATIVE:
            return Initiative(
                **common_kwargs,
                priority_type=priority_type,
            )

    raise ValueError(f"Unknown priority type: {priority_type}")


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def priority_to_row_values(priority: Priority) -> tuple:
    """
    Convert a Priority (any subclass) to a tuple of values for SQL insert/update.
    Returns values in column order matching the INSERT statement.
    Includes entity_id in the tuple.
    """
    # Type-specific fields default to None
    success_looks_like = None
    obsolete_when = None
    complete_when = None
    due_date = None
    progress = None
    rhythm_frequency = None
    rhythm_constraints = None
    generation_prompt = None

    # Extract type-specific fields based on actual type
    if isinstance(priority, Value):
        success_looks_like = priority.success_looks_like
        obsolete_when = priority.obsolete_when

    elif isinstance(priority, Goal):
        complete_when = priority.complete_when
        due_date = priority.due_date.isoformat() if priority.due_date else None
        progress = priority.progress

    elif isinstance(priority, Practice):
        rhythm_frequency = priority.rhythm_frequency
        rhythm_constraints = priority.rhythm_constraints
        generation_prompt = priority.generation_prompt

    now = datetime.now().isoformat()
    return (
        priority.id,
        priority.entity_id,
        priority.priority_type.value,
        priority.name,
        priority.status.value,
        priority.substatus,
        priority.agent_context,
        priority.notes,
        priority.rank,
        int(priority.auto_assign_owner),
        int(priority.auto_assign_creator),
        success_looks_like,
        obsolete_when,
        complete_when,
        due_date,
        progress,
        rhythm_frequency,
        rhythm_constraints,
        generation_prompt,
        priority.created_at.isoformat() if priority.created_at else now,
        priority.updated_at.isoformat() if priority.updated_at else now,
    )


# ---------------------------------------------------------------------
# PriorityGraph
# ---------------------------------------------------------------------

class PriorityGraph:
    """
    In-memory graph of priorities. Loaded from SQLite, provides
    traversal operations, syncs changes back to storage.

    Each graph is scoped to a specific entity (entity_id).
    """

    def __init__(self, connection_factory, entity_id: str | None = None):
        self.connection_factory = connection_factory
        self.entity_id = entity_id  # None means load all (for admin)

        self.nodes: dict[str, Priority] = {}

        self.parents: dict[str, set[str]] = {}   # child_id -> {parent_ids}
        self.children: dict[str, set[str]] = {}  # parent_id -> {child_ids}

    # Loading / Persistence

    def load(self) -> None:
        """Load priorities and edges from SQLite into memory.

        If entity_id is set, only loads priorities for that entity.
        If entity_id is None, loads all priorities (for admin).
        """
        with self.connection_factory() as conn:
            # Ensure schema exists
            conn.executescript(PRIORITIES_SCHEMA)

            # Migrations disabled - database is up-to-date
            # If you need to add columns, do it manually via sqlite3 CLI

            # Load priorities (filtered by entity_id if set)
            if self.entity_id is not None:
                # Load owned priorities AND shared priorities
                rows = conn.execute("""
                    SELECT * FROM priorities WHERE entity_id = ?
                    UNION
                    SELECT p.* FROM priorities p
                    JOIN entity_shares es ON p.id = es.priority_id
                    WHERE es.shared_with_entity_id = ?
                """, (self.entity_id, self.entity_id)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM priorities").fetchall()

            for row in rows:
                priority = priority_from_row(row)
                self.nodes[priority.id] = priority
                self.parents[priority.id] = set()
                self.children[priority.id] = set()

            # Load edges (only for loaded priorities)
            if self.nodes:
                # Build WHERE clause for loaded priority IDs
                priority_ids = list(self.nodes.keys())
                placeholders = ",".join("?" * len(priority_ids))
                edge_rows = conn.execute(
                    f"""SELECT child_id, parent_id FROM priority_edges
                        WHERE child_id IN ({placeholders})
                        AND parent_id IN ({placeholders})""",
                    priority_ids + priority_ids
                ).fetchall()
            else:
                edge_rows = []

            for edge in edge_rows:
                child_id = edge["child_id"]
                parent_id = edge["parent_id"]
                if child_id in self.nodes and parent_id in self.nodes:
                    self.parents[child_id].add(parent_id)
                    self.children[parent_id].add(child_id)

    def save_priority(self, priority: Priority) -> None:
        """Persist a single priority to SQLite (insert or update)."""
        values = priority_to_row_values(priority)

        with self.connection_factory() as conn:
            conn.execute("""
                INSERT INTO priorities (
                    id, entity_id, priority_type, name, status, substatus,
                    agent_context, notes, rank,
                    auto_assign_owner, auto_assign_creator,
                    success_looks_like, obsolete_when,
                    complete_when, due_date, progress,
                    rhythm_frequency, rhythm_constraints, generation_prompt,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    entity_id = excluded.entity_id,
                    priority_type = excluded.priority_type,
                    name = excluded.name,
                    status = excluded.status,
                    substatus = excluded.substatus,
                    agent_context = excluded.agent_context,
                    notes = excluded.notes,
                    rank = excluded.rank,
                    auto_assign_owner = excluded.auto_assign_owner,
                    auto_assign_creator = excluded.auto_assign_creator,
                    success_looks_like = excluded.success_looks_like,
                    obsolete_when = excluded.obsolete_when,
                    complete_when = excluded.complete_when,
                    due_date = excluded.due_date,
                    progress = excluded.progress,
                    rhythm_frequency = excluded.rhythm_frequency,
                    rhythm_constraints = excluded.rhythm_constraints,
                    generation_prompt = excluded.generation_prompt,
                    updated_at = CURRENT_TIMESTAMP
            """, values)

    def save_edge(self, child_id: str, parent_id: str) -> None:
        """Persist a parent-child edge to SQLite."""
        with self.connection_factory() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO priority_edges (child_id, parent_id)
                VALUES (?, ?)
            """, (child_id, parent_id))

    def delete_edge(self, child_id: str, parent_id: str) -> None:
        """Remove a parent-child edge from SQLite."""
        with self.connection_factory() as conn:
            conn.execute("""
                DELETE FROM priority_edges
                WHERE child_id = ? AND parent_id = ?
            """, (child_id, parent_id))


    # Graph Mutation

    def add(self, priority: Priority, parent_ids: list[str] | None = None) -> Priority:
        """
        Add a priority to the graph and persist it.
        Optionally link to parent priorities.
        """
        # Add to in-memory graph
        self.nodes[priority.id] = priority
        self.parents[priority.id] = set()
        self.children.setdefault(priority.id, set())

        # Persist priority
        self.save_priority(priority)

        # Link to parents
        if parent_ids:
            for parent_id in parent_ids:
                self.link(priority.id, parent_id)

        return priority

    def link(self, child_id: str, parent_id: str) -> None:
        """Create a parent-child edge (child serves parent)."""
        if child_id not in self.nodes:
            raise ValueError(f"Child priority not found: {child_id}")
        if parent_id not in self.nodes:
            raise ValueError(f"Parent priority not found: {parent_id}")

        # Check for cycles
        if self._would_create_cycle(child_id, parent_id):
            raise ValueError(f"Edge would create cycle: {parent_id} -> {child_id}")

        # Update in-memory
        self.parents[child_id].add(parent_id)
        self.children[parent_id].add(child_id)

        # Persist
        self.save_edge(child_id, parent_id)

    def unlink(self, child_id: str, parent_id: str) -> None:
        """Remove a parent-child edge."""
        self.parents[child_id].discard(parent_id)
        self.children[parent_id].discard(child_id)
        self.delete_edge(child_id, parent_id)

    def delete(self, priority_id: str) -> bool:
        """
        Delete a priority and all its edges.
        Returns True if deleted, False if not found.
        """
        if priority_id not in self.nodes:
            return False

        # Remove all edges where this is a child
        for parent_id in list(self.parents.get(priority_id, set())):
            self.unlink(priority_id, parent_id)

        # Remove all edges where this is a parent
        for child_id in list(self.children.get(priority_id, set())):
            self.unlink(child_id, priority_id)

        # Remove from in-memory graph
        del self.nodes[priority_id]
        self.parents.pop(priority_id, None)
        self.children.pop(priority_id, None)

        # Delete from database
        with self.connection_factory() as conn:
            conn.execute("DELETE FROM priorities WHERE id = ?", (priority_id,))

        return True

    def _would_create_cycle(self, child_id: str, parent_id: str) -> bool:
        """Check if adding edge parent_id -> child_id would create a cycle."""
        return child_id in self.ancestors(parent_id)

    # Traversal

    def get(self, priority_id: str) -> Priority | None:
        """Get a priority by ID."""
        return self.nodes.get(priority_id)

    def roots(self) -> list[Priority]:
        """Get all root priorities (no parents)."""
        return [
            self.nodes[priority_id]
            for priority_id, parent_ids in self.parents.items()
            if not parent_ids
        ]

    def ancestors(self, priority_id: str) -> set[str]:
        """
        Get all ancestor IDs (parents, grandparents, etc.).
        Does not include the priority itself.
        """
        visited = set()
        stack = list(self.parents.get(priority_id, set()))

        while stack:
            current = stack.pop()
            if current not in visited:
                visited.add(current)
                stack.extend(self.parents.get(current, set()))

        return visited

    def descendants(self, priority_id: str) -> set[str]:
        """
        Get all descendant IDs (children, grandchildren, etc.).
        Does not include the priority itself.
        """
        visited = set()
        stack = list(self.children.get(priority_id, set()))

        while stack:
            current = stack.pop()
            if current not in visited:
                visited.add(current)
                stack.extend(self.children.get(current, set()))

        return visited

    def path_to_root(self, priority_id: str) -> list[str]:
        """
        Find a path from priority to a root.
        Returns list of IDs from priority to root (inclusive).
        If multiple paths exist, returns one (first parent, alphabetically).
        """
        path = [priority_id]
        current = priority_id

        while True:
            parent_ids = self.parents.get(current, set())
            if not parent_ids:
                break
            # Take first parent alphabetically (deterministic)
            first_parent = sorted(parent_ids)[0]
            path.append(first_parent)
            current = first_parent

        return path

    def by_type(self, priority_type: PriorityType) -> list[Priority]:
        """Get all priorities of a specific type."""
        return [
            priority
            for priority in self.nodes.values()
            if priority.priority_type == priority_type
        ]

    def active(self) -> list[Priority]:
        """Get all active priorities."""
        return [
            priority
            for priority in self.nodes.values()
            if priority.status == PriorityStatus.ACTIVE
        ]

    def values(self) -> list[Value]:
        """Get all Value priorities."""
        return [p for p in self.nodes.values() if isinstance(p, Value)]

    def goals(self) -> list[Goal]:
        """Get all Goal priorities."""
        return [p for p in self.nodes.values() if isinstance(p, Goal)]

    def practices(self) -> list[Practice]:
        """Get all Practice priorities."""
        return [p for p in self.nodes.values() if isinstance(p, Practice)]

    # -------------------------------------------------------------------------
    # Sharing
    # -------------------------------------------------------------------------

    def share(self, priority_id: str, target_entity_id: str, permission: str = "contributor") -> None:
        """
        Share a priority with another entity.

        Args:
            priority_id: The priority to share
            target_entity_id: The entity to share with (personal or organization)
            permission: One of 'viewer', 'contributor', 'editor'
        """
        if permission not in ("viewer", "contributor", "editor"):
            raise ValueError(f"Invalid permission: {permission}")

        with self.connection_factory() as conn:
            conn.execute("""
                INSERT INTO entity_shares (priority_id, shared_with_entity_id, permission)
                VALUES (?, ?, ?)
                ON CONFLICT(priority_id, shared_with_entity_id) DO UPDATE SET
                    permission = excluded.permission
            """, (priority_id, target_entity_id, permission))

    def share_with_user(self, priority_id: str, user_id: int, permission: str = "contributor") -> None:
        """
        Share a priority with a user (via their personal entity).

        Args:
            priority_id: The priority to share
            user_id: The user to share with
            permission: One of 'viewer', 'contributor', 'editor'
        """
        # Look up user's personal entity
        with self.connection_factory() as conn:
            row = conn.execute(
                "SELECT entity_id FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if not row or not row["entity_id"]:
                raise ValueError(f"User {user_id} has no personal entity")
            target_entity_id = row["entity_id"]

        self.share(priority_id, target_entity_id, permission)

    def unshare(self, priority_id: str, target_entity_id: str) -> bool:
        """
        Remove sharing for a priority with an entity.
        Returns True if a share was removed.
        """
        with self.connection_factory() as conn:
            cursor = conn.execute("""
                DELETE FROM entity_shares
                WHERE priority_id = ? AND shared_with_entity_id = ?
            """, (priority_id, target_entity_id))
            return cursor.rowcount > 0

    def unshare_user(self, priority_id: str, user_id: int) -> bool:
        """
        Remove sharing for a priority with a user (via their personal entity).
        Returns True if a share was removed.
        """
        with self.connection_factory() as conn:
            row = conn.execute(
                "SELECT entity_id FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if not row or not row["entity_id"]:
                return False
            target_entity_id = row["entity_id"]

        return self.unshare(priority_id, target_entity_id)

    def get_shares(self, priority_id: str) -> list[dict]:
        """
        Get all entities a priority is shared with.
        Returns list of {entity_id, entity_name, permission, created_at, user_id, username}.
        For personal entities, includes the user info.
        """
        with self.connection_factory() as conn:
            rows = conn.execute("""
                SELECT es.shared_with_entity_id, es.permission, es.created_at,
                       e.name as entity_name, e.type as entity_type,
                       u.id as user_id, u.username
                FROM entity_shares es
                JOIN entities e ON es.shared_with_entity_id = e.id
                LEFT JOIN users u ON e.id = u.entity_id
                WHERE es.priority_id = ?
            """, (priority_id,)).fetchall()
            return [
                {
                    "entity_id": row["shared_with_entity_id"],
                    "entity_name": row["entity_name"],
                    "entity_type": row["entity_type"],
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "permission": row["permission"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

    def get_permission(self, priority_id: str, entity_id: str) -> str | None:
        """
        Get an entity's permission level for a priority.
        Returns 'owner', 'viewer', 'contributor', 'editor', or None.
        """
        priority = self.get(priority_id)
        if priority is None:
            return None

        # Check if owner (entity owns the priority)
        if priority.entity_id == entity_id:
            return "owner"

        # Check entity_shares
        with self.connection_factory() as conn:
            share_row = conn.execute("""
                SELECT permission FROM entity_shares
                WHERE priority_id = ? AND shared_with_entity_id = ?
            """, (priority_id, entity_id)).fetchone()
            if share_row:
                return share_row["permission"]

        return None
