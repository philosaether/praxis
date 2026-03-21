from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class TaskStatus(Enum):
    """
    queued  - In the backlog, available for cue selection
    active  - Currently being worked on (optional - could skip this for MVP)
    done    - Completed
    dropped - Abandoned, won't be cued
    """
    QUEUED = "queued"
    ACTIVE = "active"
    DONE = "done"
    DROPPED = "dropped"

@dataclass
class Workstream:
    id: int
    name: str
    description: str | None = None

@dataclass
class Task:

    #Stored fields
    id: int
    workstream_id: int
    title: str
    status: TaskStatus
    notes: str | None = None
    due_date: datetime | None = None
    created_at: datetime | None = None

    # Inferred fields
    workstream_name: str | None = None