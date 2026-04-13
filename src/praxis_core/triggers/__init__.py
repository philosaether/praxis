"""Triggers package for automated task generation.

Triggers are inline DSL within Practices, executed via:
- Browser polling (every 60s when visible)
- Catch-up on app launch
- Midnight cron job

The v2 engine (engine_v2, executor_v2) handles all execution.
DSL models live in praxis_core.dsl.
"""

from praxis_core.triggers.engine_v2 import (
    ExecutionContext,
    ExecutionResult,
    execute_action,
)
from praxis_core.triggers.executor_v2 import execute_and_persist
from praxis_core.triggers.events import (
    on_task_completed,
    on_task_created,
    on_priority_completed,
    on_priority_created,
    on_priority_status_changed,
)

__all__ = [
    # Engine
    "ExecutionContext",
    "ExecutionResult",
    "execute_action",
    "execute_and_persist",
    # Event Handlers
    "on_task_completed",
    "on_task_created",
    "on_priority_completed",
    "on_priority_created",
    "on_priority_status_changed",
]
