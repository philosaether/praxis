"""Vocabulary and parsing for the automation system."""

from .conditions import (
    ConditionType,
    Condition,
    EvaluationContext,
    evaluate_condition,
    evaluate_conditions,
)

from .triggers import (
    ScheduleInterval,
    EventType,
    Cadence,
    Schedule,
    Event,
    Trigger,
    should_schedule_fire,
    should_event_fire,
    next_fire_time,
)

from .effects import (
    EffectTarget,
    EffectOperator,
    Effect,
    EffectContext,
    EffectResult,
    apply_effect,
    apply_effects,
)

from .templates import (
    TaskTemplate,
    PriorityTemplate,
    TaskSpec,
    PrioritySpec,
    ActionContext,
    expand_template,
)

from .date_parsing import parse_due_date

from .actions import (
    ActionType,
    MoveSpec,
    DeleteSpec,
    CollateSpec,
    CreateAction,
    MoveAction,
    DeleteAction,
    CollateAction,
    CollateTarget,
    execute_create_action,
    execute_move_action,
    execute_delete_action,
    execute_collate_action,
)

from .practice_config import (
    PracticeAction,
    PracticeConfig,
)

__all__ = [
    # Conditions
    "ConditionType", "Condition", "EvaluationContext",
    "evaluate_condition", "evaluate_conditions",
    # Triggers
    "ScheduleInterval", "EventType", "Cadence", "Schedule", "Event", "Trigger",
    "should_schedule_fire", "should_event_fire", "next_fire_time",
    # Effects
    "EffectTarget", "EffectOperator", "Effect", "EffectContext", "EffectResult",
    "apply_effect", "apply_effects",
    # Templates
    "TaskTemplate", "PriorityTemplate", "TaskSpec", "PrioritySpec",
    "ActionContext", "expand_template",
    # Date parsing
    "parse_due_date",
    # Actions
    "ActionType", "MoveSpec", "DeleteSpec", "CollateSpec",
    "CreateAction", "MoveAction", "DeleteAction", "CollateAction", "CollateTarget",
    "execute_create_action", "execute_move_action", "execute_delete_action",
    "execute_collate_action",
    # Practice config
    "PracticeAction", "PracticeConfig",
]
