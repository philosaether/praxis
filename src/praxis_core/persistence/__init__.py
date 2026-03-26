"""Praxis Core persistence layer."""

from praxis_core.persistence.database import (
    get_connection,
    DB_DIR,
    DB_PATH,
)
from praxis_core.persistence.priority_persistence import (
    PriorityGraph,
    priority_from_row,
    priority_to_row_values,
    PRIORITIES_SCHEMA,
)
from praxis_core.persistence.task_persistence import (
    create_task,
    get_task,
    list_tasks,
    update_task,
    update_task_status,
    delete_task,
    create_subtask,
    toggle_subtask,
    delete_subtask,
    reorder_subtasks,
    clear_tasks,
    seed_database,
    TASKS_SCHEMA,
)

__all__ = [
    # Database
    "get_connection",
    "DB_DIR",
    "DB_PATH",
    # Priority persistence
    "PriorityGraph",
    "priority_from_row",
    "priority_to_row_values",
    "PRIORITIES_SCHEMA",
    # Task persistence
    "create_task",
    "get_task",
    "list_tasks",
    "update_task",
    "update_task_status",
    "delete_task",
    "create_subtask",
    "toggle_subtask",
    "delete_subtask",
    "reorder_subtasks",
    "clear_tasks",
    "seed_database",
    "TASKS_SCHEMA",
]
