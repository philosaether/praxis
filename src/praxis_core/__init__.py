"""Praxis Core: cue-based task management system."""

__version__ = "0.1.0"

# Re-export commonly used items for convenience
from praxis_core.model import (
    # Priorities
    Priority,
    PriorityType,
    PriorityStatus,
    Value,
    Goal,
    Practice,
    # Tasks
    Task,
    TaskStatus,
    Subtask,
    # Filters
    ScoredTask,
    apply_filters,
)
from praxis_core.persistence import (
    PriorityGraph,
    get_connection,
    # Task operations
    create_task,
    get_task,
    list_tasks,
    update_task,
    update_task_status,
    delete_task,
    seed_database,
)
from praxis_core.cli import app as cli_app
from praxis_core.web_api import app as api_app

__all__ = [
    "__version__",
    # Models
    "Priority",
    "PriorityType",
    "PriorityStatus",
    "Value",
    "Goal",
    "Practice",
    "Task",
    "TaskStatus",
    "Subtask",
    "ScoredTask",
    "apply_filters",
    # Persistence
    "PriorityGraph",
    "get_connection",
    "create_task",
    "get_task",
    "list_tasks",
    "update_task",
    "update_task_status",
    "delete_task",
    "seed_database",
    # Apps
    "cli_app",
    "api_app",
]
