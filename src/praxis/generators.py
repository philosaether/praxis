from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import sqlite3

# ---------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------

class GeneratorType(StrEnum):
    GOAL = "goal"
    OBLIGATION = "obligation"
    CAPACITY = "capacity"
    ACCOMPLISHMENT = "accomplishment"
    PRACTICE = "practice"

class GeneratorStatus(StrEnum):
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
# Generator dataclasses
# ---------------------------------------------------------------------

@dataclass
class Generator:
    id: str
    name: str
    generator_type: GeneratorType
    status: GeneratorStatus = GeneratorStatus.ACTIVE

    agent_context: str | None = None
    notes_path: str | None = None

    # Metadata
    created_at: datetime | None = None
    updated_at: datetime | None = None

@dataclass
class Goal(Generator):
    """A chosen pursuit (telos)."""

    generator_type: GeneratorType = GeneratorType.GOAL
    success_looks_like: str | None = None
    obsolete_when: str | None = None

@dataclass
class Obligation(Generator):
    """An imposed requirement (telos)."""

    generator_type: GeneratorType = GeneratorType.OBLIGATION
    consequence_of_neglect: str | None = None
    
@dataclass
class Capacity(Generator):
    """A skill to develop and maintain (arete). Can atrophy if neglected."""

    generator_type: GeneratorType = GeneratorType.CAPACITY
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
class Accomplishment(Generator):
    """A threshold to reach. Done when done; no maintenance required."""

    generator_type: GeneratorType = GeneratorType.ACCOMPLISHMENT
    success_criteria: str | None = None
    due_date: datetime | None = None
    progress: str | None = None  # e.g., "3/10", "70%"

@dataclass
class Practice(Generator):
    """A recurring activity (ethea). Generates task instances on a rhythm."""

    generator_type: GeneratorType = GeneratorType.PRACTICE
    rhythm_frequency: str | None = None   # e.g., "daily", "weekly", "2x daily"
    rhythm_constraints: str | None = None # e.g., "morning only", "not after 9pm"
    generation_prompt: str | None = None  # how agent generates specific tasks

# ---------------------------------------------------------------------
# SQLite Schema
# ---------------------------------------------------------------------

GENERATORS_SCHEMA = """
CREATE TABLE IF NOT EXISTS generators (
    id TEXT PRIMARY KEY,
    generator_type TEXT NOT NULL,
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

CREATE TABLE IF NOT EXISTS generator_edges (
    child_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (child_id, parent_id),
    FOREIGN KEY (child_id) REFERENCES generators(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES generators(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_generators_type ON generators(generator_type);
CREATE INDEX IF NOT EXISTS idx_generators_status ON generators(status);
CREATE INDEX IF NOT EXISTS idx_edges_child ON generator_edges(child_id);
CREATE INDEX IF NOT EXISTS idx_edges_parent ON generator_edges(parent_id);
"""

# ---------------------------------------------------------------------
# Factory: Row to Generator subclass
# ---------------------------------------------------------------------

def generator_from_row(row: sqlite3.Row) -> Generator:
    generator_type = GeneratorType(row["generator_type"])

    created_at = _parse_datetime(row["created_at"])
    updated_at = _parse_datetime(row["updated_at"])

    common_kwargs = {
        "id": row["id"],
        "name": row["name"],
        "status": GeneratorStatus(row["status"]),
        "agent_context": row["agent_context"],
        "notes_path": row["notes_path"],
        "created_at": created_at,
        "updated_at": updated_at,
    }

    match generator_type:
        case GeneratorType.GOAL:
            return Goal(
                **common_kwargs,
                generator_type=generator_type,
                success_looks_like=row["success_looks_like"],
                obsolete_when=row["obsolete_when"],
            )

        case GeneratorType.OBLIGATION:
            return Obligation(
                **common_kwargs,
                generator_type=generator_type,
                consequence_of_neglect=row["consequence_of_neglect"],
            )

        case GeneratorType.CAPACITY:
            return Capacity(
                **common_kwargs,
                generator_type=generator_type,
                measurement_method=row["measurement_method"],
                measurement_rubric=row["measurement_rubric"],
                measurement_scale=row["measurement_scale"],
                current_level=row["current_level"],
                target_level=row["target_level"],
            )

        case GeneratorType.ACCOMPLISHMENT:
            return Accomplishment(
                **common_kwargs,
                generator_type=generator_type,
                success_criteria=row["success_criteria"],
                due_date=_parse_datetime(row["due_date"]),
                progress=row["progress"],
            )

        case GeneratorType.PRACTICE:
            return Practice(
                **common_kwargs,
                generator_type=generator_type,
                rhythm_frequency=row["rhythm_frequency"],
                rhythm_constraints=row["rhythm_constraints"],
                generation_prompt=row["generation_prompt"],
            )
        
    raise ValueError(f"Unknown generator type: {generator_type}")

def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)

# ---------------------------------------------------------------------
# Serialization: Generator to row values
# ---------------------------------------------------------------------

def generator_to_row_values(generator: Generator) -> tuple:
    """
    Convert a Generator (any subclass) to a tuple of values for SQL insert/update.
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
    if isinstance(generator, Goal):
        success_looks_like = generator.success_looks_like
        obsolete_when = generator.obsolete_when

    elif isinstance(generator, Obligation):
        consequence_of_neglect = generator.consequence_of_neglect

    elif isinstance(generator, Capacity):
        measurement_method = generator.measurement_method
        measurement_rubric = generator.measurement_rubric
        measurement_scale = generator.measurement_scale
        current_level = generator.current_level
        target_level = generator.target_level

    elif isinstance(generator, Accomplishment):
        success_criteria = generator.success_criteria
        due_date = generator.due_date.isoformat() if generator.due_date else None
        progress = generator.progress

    elif isinstance(generator, Practice):
        rhythm_frequency = generator.rhythm_frequency
        rhythm_constraints = generator.rhythm_constraints
        generation_prompt = generator.generation_prompt

    now = datetime.now().isoformat()
    return (
        generator.id,
        generator.generator_type.value,
        generator.name,
        generator.status.value,
        generator.agent_context,
        generator.notes_path,
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
        generator.created_at.isoformat() if generator.created_at else now,
        generator.updated_at.isoformat() if generator.updated_at else now,
    )

# ---------------------------------------------------------------------
# In-Memory Graph
# ---------------------------------------------------------------------

class GeneratorGraph:
    """
    In-memory graph of generators. Loaded from SQLite, provides
    traversal operations, syncs changes back to storage.
    """

    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

        self.nodes: dict[str, Generator] = {}

        self.parents: dict[str, set[str]] = {}   # child_id -> {parent_ids}
        self.children: dict[str, set[str]] = {}  # parent_id -> {child_ids}

    # Loading / Persistence

    def load(self) -> None:
        """Load all generators and edges from SQLite into memory."""
        with self.connection_factory() as conn:
            # Ensure schema exists
            conn.executescript(GENERATORS_SCHEMA)

            # Load generators
            rows = conn.execute("SELECT * FROM generators").fetchall()
            for row in rows:
                generator = generator_from_row(row)
                self.nodes[generator.id] = generator
                self.parents[generator.id] = set()
                self.children[generator.id] = set()

            # Load edges
            edge_rows = conn.execute(
                "SELECT child_id, parent_id FROM generator_edges"
            ).fetchall()
            for edge in edge_rows:
                child_id = edge["child_id"]
                parent_id = edge["parent_id"]
                self.parents[child_id].add(parent_id)
                self.children[parent_id].add(child_id)

    def save_generator(self, generator: Generator) -> None:
        """Persist a single generator to SQLite (insert or update)."""
        values = generator_to_row_values(generator)

        with self.connection_factory() as conn:
            conn.execute("""
                INSERT INTO generators (
                    id, generator_type, name, status,
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
                    generator_type = excluded.generator_type,
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
                INSERT OR IGNORE INTO generator_edges (child_id, parent_id)
                VALUES (?, ?)
            """, (child_id, parent_id))

    def delete_edge(self, child_id: str, parent_id: str) -> None:
        """Remove a parent-child edge from SQLite."""
        with self.connection_factory() as conn:
            conn.execute("""
                DELETE FROM generator_edges
                WHERE child_id = ? AND parent_id = ?
            """, (child_id, parent_id))


    # Graph Mutation

    def add(self, generator: Generator, parent_ids: list[str] | None = None) -> Generator:
        """
        Add a generator to the graph and persist it.
        Optionally link to parent generators.
        """
        # Add to in-memory graph
        self.nodes[generator.id] = generator
        self.parents[generator.id] = set()
        self.children.setdefault(generator.id, set())

        # Persist generator
        self.save_generator(generator)

        # Link to parents
        if parent_ids:
            for parent_id in parent_ids:
                self.link(generator.id, parent_id)

        return generator

    def link(self, child_id: str, parent_id: str) -> None:
        """Create a parent-child edge (child is generated by parent)."""
        if child_id not in self.nodes:
            raise ValueError(f"Child generator not found: {child_id}")
        if parent_id not in self.nodes:
            raise ValueError(f"Parent generator not found: {parent_id}")

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

    def get(self, generator_id: str) -> Generator | None:
        """Get a generator by ID."""
        return self.nodes.get(generator_id)

    def roots(self) -> list[Generator]:
        """Get all root generators (no parents)."""
        return [
            self.nodes[generator_id]
            for generator_id, parent_ids in self.parents.items()
            if not parent_ids
        ]
    
    def ancestors(self, generator_id: str) -> set[str]:
        """
        Get all ancestor IDs (parents, grandparents, etc.).
        Does not include the generator itself.
        """
        visited = set()
        stack = list(self.parents.get(generator_id, set()))

        while stack:
            current = stack.pop()
            if current not in visited:
                visited.add(current)
                stack.extend(self.parents.get(current, set()))

        return visited
    
    def descendants(self, generator_id: str) -> set[str]:
        """
        Get all descendant IDs (children, grandchildren, etc.).
        Does not include the generator itself.
        """
        visited = set()
        stack = list(self.children.get(generator_id, set()))

        while stack:
            current = stack.pop()
            if current not in visited:
                visited.add(current)
                stack.extend(self.children.get(current, set()))

        return visited
    
    def path_to_root(self, generator_id: str) -> list[str]:
        """
        Find a path from generator to a root (for priority inheritance).
        Returns list of IDs from generator to root (inclusive).
        If multiple paths exist, returns one (first parent, alphabetically).
        """
        path = [generator_id]
        current = generator_id

        while True:
            parent_ids = self.parents.get(current, set())
            if not parent_ids:
                break
            # Take first parent alphabetically (deterministic)
            first_parent = sorted(parent_ids)[0]
            path.append(first_parent)
            current = first_parent

        return path

    def by_type(self, generator_type: GeneratorType) -> list[Generator]:
        """Get all generators of a specific type."""
        return [
            generator
            for generator in self.nodes.values()
            if generator.generator_type == generator_type
        ]

    def active(self) -> list[Generator]:
        """Get all active generators."""
        return [
            generator
            for generator in self.nodes.values()
            if generator.status == GeneratorStatus.ACTIVE
        ]

    def goals(self) -> list[Goal]:
        """Get all Goal generators."""
        return [g for g in self.nodes.values() if isinstance(g, Goal)]

    def obligations(self) -> list[Obligation]:
        """Get all Obligation generators."""
        return [g for g in self.nodes.values() if isinstance(g, Obligation)]

    def capacities(self) -> list[Capacity]:
        """Get all Capacity generators."""
        return [g for g in self.nodes.values() if isinstance(g, Capacity)]

    def accomplishments(self) -> list[Accomplishment]:
        """Get all Accomplishment generators."""
        return [g for g in self.nodes.values() if isinstance(g, Accomplishment)]

    def practices(self) -> list[Practice]:
        """Get all Practice generators."""
        return [g for g in self.nodes.values() if isinstance(g, Practice)]