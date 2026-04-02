"""Triggers package for automated task generation."""

from praxis_core.triggers.dsl import (
    parse_triggers,
    serialize_triggers,
    serialize_trigger,
    DSLParseError,
)
from praxis_core.triggers.engine import (
    TriggerContext,
    ExecutionResult,
    expand_template,
    parse_due_date_offset,
    evaluate_conditions,
    execute_trigger,
    should_trigger_fire,
)
from praxis_core.triggers.scheduler import (
    TriggerScheduler,
    get_scheduler,
    start_scheduler,
    stop_scheduler,
)
from praxis_core.triggers.events import (
    on_task_completed,
    on_task_created,
    on_priority_completed,
    on_priority_status_changed,
)

__all__ = [
    # DSL
    "parse_triggers",
    "serialize_triggers",
    "serialize_trigger",
    "DSLParseError",
    # Engine
    "TriggerContext",
    "ExecutionResult",
    "expand_template",
    "parse_due_date_offset",
    "evaluate_conditions",
    "execute_trigger",
    "should_trigger_fire",
    # Scheduler
    "TriggerScheduler",
    "get_scheduler",
    "start_scheduler",
    "stop_scheduler",
    # Event Handlers
    "on_task_completed",
    "on_task_created",
    "on_priority_completed",
    "on_priority_status_changed",
]
