"""Priority models and enums."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PriorityType(StrEnum):
    VALUE = "value"        # Guiding principle (direction, never completes)
    GOAL = "goal"          # Concrete outcome (destination, has end state)
    PRACTICE = "practice"  # Recurring activity (generates tasks on rhythm)


class PriorityStatus(StrEnum):
    # Universal
    ACTIVE = "active"
    DORMANT = "dormant"
    ABANDONED = "abandoned"    # no longer relevant

    # Goal-specific
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class Priority:
    id: str
    name: str
    priority_type: PriorityType
    status: PriorityStatus = PriorityStatus.ACTIVE

    entity_id: str | None = None  # ULID of owning entity
    agent_context: str | None = None
    notes: str | None = None

    # Importance ranking (only meaningful on root priorities)
    # Lower rank = higher importance (rank 1 is most important)
    rank: int | None = None

    # Task assignment settings (for shared priorities)
    # These are mutually exclusive; both False = unassigned (manual claim)
    auto_assign_owner: bool = True    # Assign new tasks to priority owner
    auto_assign_creator: bool = False  # Assign new tasks to task creator

    # Metadata
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Value(Priority):
    """A guiding principle (telos). Direction to travel, never completes."""

    priority_type: PriorityType = PriorityType.VALUE
    success_looks_like: str | None = None  # What living this value looks like
    obsolete_when: str | None = None       # When this value no longer applies


@dataclass
class Goal(Priority):
    """A concrete outcome to achieve. Done when done; has end state."""

    priority_type: PriorityType = PriorityType.GOAL
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
