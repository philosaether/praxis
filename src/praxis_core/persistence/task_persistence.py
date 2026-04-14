"""Task persistence — backward-compatibility shim.

All functionality has moved to:
  - task_repo.py      (CRUD, schema, migrations)
  - task_queries.py   (list_tasks query builder)
  - subtask_repo.py   (subtask CRUD)

This module re-exports everything so existing imports keep working.
"""

# Task repo (CRUD, schema, migrations, seed)
from praxis_core.persistence.task_repo import (  # noqa: F401
    TASKS_SCHEMA,
    ensure_schema,
    create_task,
    get_task,
    update_task,
    update_task_status,
    delete_task,
    restore_from_outbox,
    purge_old_outbox_tasks,
    unlink_tasks_from_priority,
    clear_tasks,
    seed_database,
    _row_to_task,
    _get_subtasks,
    _apply_outbox_fields,
    _migrate_outbox,
    _maybe_migrate,
    _migrate_to_ulid,
)

# Task queries (list_tasks)
from praxis_core.persistence.task_queries import (  # noqa: F401
    list_tasks,
)

# Subtask repo
from praxis_core.persistence.subtask_repo import (  # noqa: F401
    create_subtask,
    toggle_subtask,
    delete_subtask,
    reorder_subtasks,
    _row_to_subtask,
)
