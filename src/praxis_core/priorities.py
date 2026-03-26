from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import sqlite3

# ---------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------

class PriorityType(StrEnum):
    GOAL = "goal"
    OBLIGATION = "obligation"
    CAPACITY = "capacity"
    ACCOMPLISHMENT = "accomplishment"
    PRACTICE = "practice"

class PriorityStatus(StrEnum):
    # Universal
    ACTIVE = "active"
    DORMANT = "dormant"

    # Goal/Obligation
    ACHIEVED = "achieved"      # success criteria met
    ABANDONED = "abandoned"    # no longer relevant
    LAPSED = "lapsed"          # obligation neglected

    # Accomplishment
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"

# ---------------------------------------------------------------------
# Priority dataclasses
# ---------------------------------------------------------------------

@dataclass
class Priority:
    id: str
    name: str
    priority_type: PriorityType
    status: PriorityStatus = PriorityStatus.ACTIVE

    agent_context: str | None = None
    notes_path: str | None = None

    # Metadata
    created_at: datetime | None = None
    updated_at: datetime | None = None

@dataclass
class Goal(Priority):
    """A chosen pursuit (telos)."""

    priority_type: PriorityType = PriorityType.GOAL
    success_looks_like: str | None = None
    obsolete_when: str | None = None

@dataclass
class Obligation(Priority):
    """An imposed requirement (telos)."""

    priority_type: PriorityType = PriorityType.OBLIGATION
    consequence_of_neglect: str | None = None

@dataclass
class Capacity(Priority):
    """A skill to develop and maintain (arete). Can atrophy if neglected."""

    priority_type: PriorityType = PriorityType.CAPACITY
    measurement_method: str | None = None
    measurement_rubric: str | None = None
    measurement_scale: str | None = None
    current_level: str | None = None
    target_level: str | None = None

    @property
    def delta_description(self) -> str:
        """Describe the gap between current and target level."""
        if self.current_level is None:
            return "unknown (baseline not established)"
        if self.target_level is None:
            return "unknown (no target set)"
        return f"current: {self.current_level}, target: {self.target_level}"

@dataclass
class Accomplishment(Priority):
    """A threshold to reach. Done when done; no maintenance required."""

    priority_type: PriorityType = PriorityType.ACCOMPLISHMENT
    success_criteria: str | None = None
    due_date: datetime | None = None
    progress: str | None = None  # e.g., "3/10", "70%"

@dataclass
class Practice(Priority):
    """A recurring activity (ethea). Generates task instances on a rhythm."""

    priority_type: PriorityType = PriorityType.PRACTICE
    rhythm_frequency: str | None = None   # e.g., "daily", "weekly", "2x daily"
    rhythm_constraints: str | None = None # e.g., "morning only", "not after 9pm"
    generation_prompt: str | None = None  # how agent generates specific tasks

# ---------------------------------------------------------------------
# SQLite Schema
# ---------------------------------------------------------------------

PRIORITIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS priorities (
    id TEXT PRIMARY KEY,
    priority_type TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',

    -- Common
    agent_context TEXT,
    notes_path TEXT,

    -- Goal
    success_looks_like TEXT,
    obsolete_when TEXT,

    -- Obligation
    consequence_of_neglect TEXT,

    -- Capacity
    measurement_method TEXT,
    measurement_rubric TEXT,
    measurement_scale TEXT,
    current_level TEXT,
    target_level TEXT,

    -- Accomplishment
    success_criteria TEXT,
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
CREATE INDEX IF NOT EXISTS idx_priority_edges_child ON priority_edges(child_id);
CREATE INDEX IF NOT EXISTS idx_priority_edges_parent ON priority_edges(parent_id);
"""

# Migration: rename old tables if they exist
MIGRATION_FROM_GENERATORS = """
-- Rename generators to priorities if generators exists
ALTER TABLE generators RENAME TO priorities;
ALTER TABLE generator_edges RENAME TO priority_edges;

-- Rename column
ALTER TABLE priorities RENAME COLUMN generator_type TO priority_type;
"""

# ---------------------------------------------------------------------
# Factory: Row to Priority subclass
# ---------------------------------------------------------------------

def priority_from_row(row: sqlite3.Row) -> Priority:
    # Handle both old column name (generator_type) and new (priority_type)
    type_value = row["priority_type"] if "priority_type" in row.keys() else row["generator_type"]
    priority_type = PriorityType(type_value)

    created_at = _parse_datetime(row["created_at"])
    updated_at = _parse_datetime(row["updated_at"])

    common_kwargs = {
        "id": row["id"],
        "name": row["name"],
        "status": PriorityStatus(row["status"]),
        "agent_context": row["agent_context"],
        "notes_path": row["notes_path"],
        "created_at": created_at,
        "updated_at": updated_at,
    }

    match priority_type:
        case PriorityType.GOAL:
            return Goal(
                **common_kwargs,
                priority_type=priority_type,
                success_looks_like=row["success_looks_like"],
                obsolete_when=row["obsolete_when"],
            )

        case PriorityType.OBLIGATION:
            return Obligation(
                **common_kwargs,
                priority_type=priority_type,
                consequence_of_neglect=row["consequence_of_neglect"],
            )

        case PriorityType.CAPACITY:
            return Capacity(
                **common_kwargs,
                priority_type=priority_type,
                measurement_method=row["measurement_method"],
                measurement_rubric=row["measurement_rubric"],
                measurement_scale=row["measurement_scale"],
                current_level=row["current_level"],
                target_level=row["target_level"],
            )

        case PriorityType.ACCOMPLISHMENT:
            return Accomplishment(
                **common_kwargs,
                priority_type=priority_type,
                success_criteria=row["success_criteria"],
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

    raise ValueError(f"Unknown priority type: {priority_type}")

def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)

# ---------------------------------------------------------------------
# Serialization: Priority to row values
# ---------------------------------------------------------------------

def priority_to_row_values(priority: Priority) -> tuple:
    """
    Convert a Priority (any subclass) to a tuple of values for SQL insert/update.
    Returns values in column order matching the INSERT statement.
    """
    # Type-specific fields default to None
    success_looks_like = None
    obsolete_when = None
    consequence_of_neglect = None
    measurement_method = None
    measurement_rubric = None
    measurement_scale = None
    current_level = None
    target_level = None
    success_criteria = None
    due_date = None
    progress = None
    rhythm_frequency = None
    rhythm_constraints = None
    generation_prompt = None

    # Extract type-specific fields based on actual type
    if isinstance(priority, Goal):
        success_looks_like = priority.success_looks_like
        obsolete_when = priority.obsolete_when

    elif isinstance(priority, Obligation):
        consequence_of_neglect = priority.consequence_of_neglect

    elif isinstance(priority, Capacity):
        measurement_method = priority.measurement_method
        measurement_rubric = priority.measurement_rubric
        measurement_scale = priority.measurement_scale
        current_level = priority.current_level
        target_level = priority.target_level

    elif isinstance(priority, Accomplishment):
        success_criteria = priority.success_criteria
        due_date = priority.due_date.isoformat() if priority.due_date else None
        progress = priority.progress

    elif isinstance(priority, Practice):
        rhythm_frequency = priority.rhythm_frequency
        rhythm_constraints = priority.rhythm_constraints
        generation_prompt = priority.generation_prompt

    now = datetime.now().isoformat()
    return (
        priority.id,
        priority.priority_type.value,
        priority.name,
        priority.status.value,
        priority.agent_context,
        priority.notes_path,
        success_looks_like,
        obsolete_when,
        consequence_of_neglect,
        measurement_method,
        measurement_rubric,
        measurement_scale,
        current_level,
        target_level,
        success_criteria,
        due_date,
        progress,
        rhythm_frequency,
        rhythm_constraints,
        generation_prompt,
        priority.created_at.isoformat() if priority.created_at else now,
        priority.updated_at.isoformat() if priority.updated_at else now,
    )

# ---------------------------------------------------------------------
# In-Memory Graph
# ---------------------------------------------------------------------

class PriorityGraph:
    """
    In-memory graph of priorities. Loaded from SQLite, provides
    traversal operations, syncs changes back to storage.
    """

    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

        self.nodes: dict[str, Priority] = {}

        self.parents: dict[str, set[str]] = {}   # child_id -> {parent_ids}
        self.children: dict[str, set[str]] = {}  # parent_id -> {child_ids}

    # Loading / Persistence

    def load(self) -> None:
        """Load all priorities and edges from SQLite into memory."""
        with self.connection_factory() as conn:
            # Check if we need to migrate from old schema
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [t["name"] for t in tables]

            if "generators" in table_names and "priorities" not in table_names:
                # Migrate from old schema: rename tables
                conn.execute("ALTER TABLE generators RENAME TO priorities")
                conn.execute("ALTER TABLE generator_edges RENAME TO priority_edges")

            # Check if priorities table has old column name (generator_type)
            if "priorities" in table_names or "generators" in table_names:
                columns = conn.execute("PRAGMA table_info(priorities)").fetchall()
                column_names = [c[1] for c in columns]
                if "generator_type" in column_names and "priority_type" not in column_names:
                    # Rename the column (SQLite 3.25+)
                    conn.execute("ALTER TABLE priorities RENAME COLUMN generator_type TO priority_type")

            # Ensure schema exists (creates if not present)
            conn.executescript(PRIORITIES_SCHEMA)

            # Load priorities
            rows = conn.execute("SELECT * FROM priorities").fetchall()
            for row in rows:
                priority = priority_from_row(row)
                self.nodes[priority.id] = priority
                self.parents[priority.id] = set()
                self.children[priority.id] = set()

            # Load edges
            edge_rows = conn.execute(
                "SELECT child_id, parent_id FROM priority_edges"
            ).fetchall()
            for edge in edge_rows:
                child_id = edge["child_id"]
                parent_id = edge["parent_id"]
                self.parents[child_id].add(parent_id)
                self.children[parent_id].add(child_id)

    def save_priority(self, priority: Priority) -> None:
        """Persist a single priority to SQLite (insert or update)."""
        values = priority_to_row_values(priority)

        with self.connection_factory() as conn:
            conn.execute("""
                INSERT INTO priorities (
                    id, priority_type, name, status,
                    agent_context, notes_path,
                    success_looks_like, obsolete_when,
                    consequence_of_neglect,
                    measurement_method, measurement_rubric, measurement_scale,
                    current_level, target_level,
                    success_criteria, due_date, progress,
                    rhythm_frequency, rhythm_constraints, generation_prompt,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    priority_type = excluded.priority_type,
                    name = excluded.name,
                    status = excluded.status,
                    agent_context = excluded.agent_context,
                    notes_path = excluded.notes_path,
                    success_looks_like = excluded.success_looks_like,
                    obsolete_when = excluded.obsolete_when,
                    consequence_of_neglect = excluded.consequence_of_neglect,
                    measurement_method = excluded.measurement_method,
                    measurement_rubric = excluded.measurement_rubric,
                    measurement_scale = excluded.measurement_scale,
                    current_level = excluded.current_level,
                    target_level = excluded.target_level,
                    success_criteria = excluded.success_criteria,
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

    def goals(self) -> list[Goal]:
        """Get all Goal priorities."""
        return [p for p in self.nodes.values() if isinstance(p, Goal)]

    def obligations(self) -> list[Obligation]:
        """Get all Obligation priorities."""
        return [p for p in self.nodes.values() if isinstance(p, Obligation)]

    def capacities(self) -> list[Capacity]:
        """Get all Capacity priorities."""
        return [p for p in self.nodes.values() if isinstance(p, Capacity)]

    def accomplishments(self) -> list[Accomplishment]:
        """Get all Accomplishment priorities."""
        return [p for p in self.nodes.values() if isinstance(p, Accomplishment)]

    def practices(self) -> list[Practice]:
        """Get all Practice priorities."""
        return [p for p in self.nodes.values() if isinstance(p, Practice)]
