"""Triggers package for automated task generation.

Note: The scheduler module was removed in the triggers refactor.
Triggers are now inline DSL within Practices, executed via:
- Browser polling (every 60s when visible)
- Catch-up on app launch
- Midnight cron job

The dataclasses for trigger configuration are in praxis_core.model.practice_triggers.
"""

from praxis_core.model.practice_triggers import (
    PracticeTrigger,
    TriggerEvent,
    TriggerEventType,
    TaskTemplate,
    CollateConfig,
    ScheduleInterval,
)
from praxis_core.triggers.dsl import (
    parse_practice_trigger,
    serialize_practice_trigger,
    DSLParseError,
)
from praxis_core.triggers.engine import (
    TriggerContext,
    ExecutionResult,
    expand_template,
    parse_due_date_offset,
    evaluate_conditions,
    execute_practice_trigger,
    should_practice_trigger_fire,
)
from praxis_core.triggers.events import (
    on_task_completed,
    on_task_created,
    on_priority_completed,
    on_priority_status_changed,
)

__all__ = [
    # Model classes
    "PracticeTrigger",
    "TriggerEvent",
    "TriggerEventType",
    "TaskTemplate",
    "CollateConfig",
    "ScheduleInterval",
    # DSL
    "parse_practice_trigger",
    "serialize_practice_trigger",
    "DSLParseError",
    # Engine
    "TriggerContext",
    "ExecutionResult",
    "expand_template",
    "parse_due_date_offset",
    "evaluate_conditions",
    "execute_practice_trigger",
    "should_practice_trigger_fire",
    # Event Handlers
    "on_task_completed",
    "on_task_created",
    "on_priority_completed",
    "on_priority_status_changed",
]
