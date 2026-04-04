"""Priority models and enums."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PriorityType(StrEnum):
    INITIATIVE = "initiative"  # Ongoing bucket of work (pull-based, tactical)
    VALUE = "value"            # Guiding principle (direction, never completes)
    GOAL = "goal"              # Concrete outcome (destination, has end state)
    PRACTICE = "practice"      # Recurring activity (generates tasks on rhythm)


class PriorityStatus(StrEnum):
    # Universal (values, practices, goals)
    ACTIVE = "active"
    DORMANT = "dormant"     # draft, backlog, abandoned, on-hold (see substatus)

    # Goal-specific
    COMPLETED = "completed"  # goal achieved


@dataclass
class Priority:
    id: str
    name: str
    priority_type: PriorityType
    status: PriorityStatus = PriorityStatus.ACTIVE
    substatus: str | None = None  # Extension field (e.g., draft, backlog, abandoned)

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
    complete_when: str | None = None  # What "done" looks like
    due_date: datetime | None = None
    progress: str | None = None  # e.g., "3/10", "70%"


@dataclass
class Practice(Priority):
    """A recurring activity (ethea). Generates task instances via triggers."""

    priority_type: PriorityType = PriorityType.PRACTICE

    # Trigger configuration (JSON string containing PracticeTrigger)
    # Includes: event (schedule/task_completed/priority_completed),
    # task_template, collate_config, conditions
    trigger_config: str | None = None

    # Tracking for fire-at-first-opportunity pattern
    last_triggered_at: datetime | None = None


@dataclass
class Initiative(Priority):
    """An ongoing bucket of work. Pull-based and tactical, no special fields."""

    priority_type: PriorityType = PriorityType.INITIATIVE
