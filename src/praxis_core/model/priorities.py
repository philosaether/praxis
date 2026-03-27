"""Priority models and enums."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


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


@dataclass
class Priority:
    id: str
    name: str
    priority_type: PriorityType
    status: PriorityStatus = PriorityStatus.ACTIVE

    agent_context: str | None = None
    notes: str | None = None

    # Importance ranking (only meaningful on root priorities)
    # Lower rank = higher importance (rank 1 is most important)
    rank: int | None = None

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
