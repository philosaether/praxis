from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class TaskStatus(Enum):
    """
    queued  - In the backlog, available for cue selection
    active  - Currently being worked on
    done    - Completed
    dropped - Abandoned, won't be cued
    """
    QUEUED = "queued"
    ACTIVE = "active"
    DONE = "done"
    DROPPED = "dropped"


@dataclass
class Subtask:
    """A phase of completion within a task."""
    id: int
    task_id: int
    title: str
    completed: bool = False
    sort_order: int = 0
    completed_at: datetime | None = None


@dataclass
class Task:
    # Stored fields
    id: int
    title: str
    status: TaskStatus
    notes: str | None = None
    due_date: datetime | None = None
    created_at: datetime | None = None

    # Priority link (replaces workstream)
    priority_id: str | None = None

    # Inferred/joined fields
    priority_name: str | None = None

    # Subtasks (phases)
    subtasks: list[Subtask] = field(default_factory=list)

    @property
    def current_subtask(self) -> Subtask | None:
        """Get the first uncompleted subtask (current phase)."""
        for subtask in sorted(self.subtasks, key=lambda s: s.sort_order):
            if not subtask.completed:
                return subtask
        return None
