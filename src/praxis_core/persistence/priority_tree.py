"""PriorityTree: in-memory forest of priorities backed by SQLite."""

from praxis_core.model.priorities import (
    Priority,
    PriorityType,
    PriorityStatus,
    Value,
    Goal,
    Practice,
)
from praxis_core.persistence.priority_repo import (
    PRIORITIES_SCHEMA,
    priority_from_row,
    priority_to_row_values,
)
from praxis_core.persistence import priority_sharing


class PriorityTree:
    """
    In-memory forest of priorities. Loaded from SQLite, provides
    traversal operations, syncs changes back to storage.

    Each tree is rooted at a top-level priority (value, initiative, etc.).
    The forest is the collection of all such trees for an entity.

    Each forest is scoped to a specific entity (entity_id).
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

            # Migrate schema — add any columns missing from older DBs
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(priorities)").fetchall()}
            if "notes" in columns and "description" not in columns:
                conn.execute("ALTER TABLE priorities RENAME COLUMN notes TO description")
            for col, col_type in [
                ("substatus", "TEXT"),
                ("agent_context", "TEXT"),
                ("description", "TEXT"),
                ("rank", "INTEGER"),
                ("assigned_to_entity_id", "TEXT REFERENCES entities(id)"),
                ("complete_when", "TEXT"),
                ("due_date", "TEXT"),
                ("progress", "TEXT"),
                ("actions_config", "TEXT"),
                ("last_triggered_at", "TEXT"),
                ("last_engaged_at", "TEXT"),
            ]:
                if col not in columns:
                    conn.execute(f"ALTER TABLE priorities ADD COLUMN {col} {col_type}")

            # Load priorities (filtered by entity_id if set)
            if self.entity_id is not None:
                # Load owned priorities AND shared priorities (including descendants)
                rows = conn.execute("""
                    SELECT * FROM priorities WHERE entity_id = ?
                    UNION
                    SELECT p.* FROM priorities p
                    JOIN entity_shares es ON p.id = es.priority_id
                    WHERE es.shared_with_entity_id = ?
                    UNION
                    SELECT p.* FROM priorities p
                    WHERE p.id IN (
                        WITH RECURSIVE descendants(id, depth) AS (
                            SELECT pe.child_id, 1 FROM priority_edges pe
                            JOIN entity_shares es ON pe.parent_id = es.priority_id
                            WHERE es.shared_with_entity_id = ?
                            UNION ALL
                            SELECT pe.child_id, d.depth + 1 FROM priority_edges pe
                            JOIN descendants d ON pe.parent_id = d.id
                            WHERE d.depth < 50
                        )
                        SELECT id FROM descendants
                    )
                """, (self.entity_id, self.entity_id, self.entity_id)).fetchall()
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
                    agent_context, description, rank,
                    assigned_to_entity_id,
                    complete_when, due_date, progress,
                    actions_config, last_triggered_at, last_engaged_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    entity_id = excluded.entity_id,
                    priority_type = excluded.priority_type,
                    name = excluded.name,
                    status = excluded.status,
                    substatus = excluded.substatus,
                    agent_context = excluded.agent_context,
                    description = excluded.description,
                    rank = excluded.rank,
                    assigned_to_entity_id = excluded.assigned_to_entity_id,
                    complete_when = excluded.complete_when,
                    due_date = excluded.due_date,
                    progress = excluded.progress,
                    actions_config = excluded.actions_config,
                    last_triggered_at = excluded.last_triggered_at,
                    last_engaged_at = excluded.last_engaged_at,
                    updated_at = CURRENT_TIMESTAMP
            """, values)
            conn.commit()

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


    # Tree Mutation

    def add(self, priority: Priority, parent_ids: list[str] | None = None) -> Priority:
        """
        Add a priority to the forest and persist it.
        Optionally link to parent priorities.
        """
        # Add to in-memory forest
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

        # Delete from database BEFORE in-memory cleanup
        # so a FK constraint failure doesn't leave the forest inconsistent
        with self.connection_factory() as conn:
            conn.execute("DELETE FROM priorities WHERE id = ?", (priority_id,))

        # Remove from in-memory forest (only reached if DB delete succeeded)
        del self.nodes[priority_id]
        self.parents.pop(priority_id, None)
        self.children.pop(priority_id, None)

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
    # Sharing (delegates to priority_sharing module)
    # -------------------------------------------------------------------------

    def share(self, priority_id: str, target_entity_id: str, permission: str = "contributor") -> None:
        """Share a priority with another entity."""
        priority_sharing.share(self.connection_factory, priority_id, target_entity_id, permission)

    def share_with_user(self, priority_id: str, user_id: int, permission: str = "contributor", allow_adoption: bool = False) -> None:
        """Share a priority with a user (via their personal entity)."""
        priority_sharing.share_with_user(self.connection_factory, priority_id, user_id, permission, allow_adoption)

    def unshare(self, priority_id: str, target_entity_id: str) -> bool:
        """Remove sharing for a priority with an entity."""
        return priority_sharing.unshare(self.connection_factory, priority_id, target_entity_id)

    def unshare_user(self, priority_id: str, user_id: int) -> bool:
        """Remove sharing for a priority with a user (via their personal entity)."""
        return priority_sharing.unshare_user(self.connection_factory, priority_id, user_id)

    def get_shares(self, priority_id: str) -> list[dict]:
        """Get all entities a priority is shared with."""
        return priority_sharing.get_shares(self.connection_factory, priority_id)

    def get_permission(self, priority_id: str, entity_id: str) -> str | None:
        """Get an entity's permission level for a priority."""
        priority = self.get(priority_id)
        return priority_sharing.get_permission(self.connection_factory, priority_id, entity_id, priority)
