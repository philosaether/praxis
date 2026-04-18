"""Priority models and enums."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PriorityType(StrEnum):
    INITIATIVE = "initiative"  # Ongoing bucket of work (pull-based, tactical)
    VALUE = "value"            # Guiding principle (direction, never completes)
    GOAL = "goal"              # Concrete outcome (destination, has end state)
    PRACTICE = "practice"      # Recurring activity (generates tasks on rhythm)
    ORG = "org"                # Shared workspace with group inbox


class PriorityStatus(StrEnum):
    # Universal (values, practices, goals)
    ACTIVE = "active"
    DORMANT = "dormant"     # draft, backlog, abandoned, on-hold (see substatus)
    BLOCKED = "blocked"     # waiting on external dependency

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
    agent_context: str | None = None  # Scaffolding for AI integration
    description: str | None = None

    # Importance ranking (only meaningful on root priorities)
    # Lower rank = higher importance (rank 1 is most important)
    rank: int | None = None

    # Priority-level assignment (replaces task-level assigned_to)
    assigned_to_entity_id: str | None = None  # Entity responsible for this priority

    # Engagement tracking (updated when child tasks are completed)
    last_engaged_at: datetime | None = None

    # Metadata
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Value(Priority):
    """A guiding principle (telos). Direction to travel, never completes."""

    priority_type: PriorityType = PriorityType.VALUE


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

    # Actions configuration (JSON string containing DSL v2 actions array)
    actions_config: str | None = None

    # Tracking for fire-at-first-opportunity pattern
    last_triggered_at: datetime | None = None


@dataclass
class Initiative(Priority):
    """An ongoing bucket of work. Pull-based and tactical, no special fields."""

    priority_type: PriorityType = PriorityType.INITIATIVE


@dataclass
class Org(Priority):
    """A shared workspace with a group inbox. Tasks directly under an Org
    appear in the personal inboxes of all group members."""

    priority_type: PriorityType = PriorityType.ORG
