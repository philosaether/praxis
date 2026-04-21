"""
Unified condition model for Rules and Practices.

Conditions are predicates that evaluate to true/false. They check:
- Context: current time, day of week (no subject needed)
- Entity: properties of a task (rules) or event (practices)

Subject syntax (Option C from design doc):
- Context conditions are implicit: `time: 08:00 to 12:00`
- Entity subjects are implicit for rules (always task)
- Entity subjects are explicit for practices: `event.type: goal`
"""

from dataclasses import dataclass, field
from datetime import datetime, time
from enum import StrEnum
from typing import Any

from praxis_core.model import Task


class ConditionType(StrEnum):
    """Types of conditions that can be evaluated."""

    # Context conditions (check current moment, no subject)
    TIME_WINDOW = "time"
    DAY_OF_WEEK = "day"

    # Entity conditions (check task or event properties)
    TAGGED = "tagged"
    NOT_TAGGED = "not_tagged"
    PRIORITY_TYPE = "type"
    PRIORITY_ANCESTOR = "ancestor"
    STATUS = "status"
    IN_LOCATION = "in"  # inbox, outbox

    # Task-specific conditions
    DUE_DATE = "due_date"
    OVERDUE = "overdue"
    DUE_WITHIN = "due_within"
    STALENESS = "stale"
    ASSIGNED_TO = "assigned_to"
    COMPLETED_BEFORE = "completed_before"
    MOVED_BEFORE = "moved_before"

    # Capacity conditions (post-beta)
    CAPACITY = "capacity"


@dataclass
class Condition:
    """
    A condition that evaluates to true/false.

    Attributes:
        condition_type: What kind of check to perform
        params: Type-specific parameters (e.g., tag name, time range)
        subject: Optional explicit subject ("event" for practices)
                 If None, subject is inferred from context (task for rules)
    """

    condition_type: ConditionType
    params: dict[str, Any] = field(default_factory=dict)
    subject: str | None = None  # "event" for practices, None for rules

    def to_dict(self) -> dict:
        result = {"type": self.condition_type.value, "params": self.params}
        if self.subject:
            result["subject"] = self.subject
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "Condition":
        return cls(
            condition_type=ConditionType(data["type"]),
            params=data.get("params", {}),
            subject=data.get("subject"),
        )


@dataclass
class EvaluationContext:
    """
    Context for condition evaluation.

    Provides access to current time and other contextual data
    needed to evaluate conditions.
    """

    now: datetime
    capacities: dict[str, float] = field(default_factory=dict)

    # For task-specific computed values (populated by caller)
    task_tags: set[str] | None = None
    task_ancestors: set[str] | None = None  # Priority IDs in ancestry chain

    def current_time(self) -> time:
        return self.now.time()

    def current_day(self) -> str:
        return self.now.strftime("%A").lower()


# --- Evaluator imports (extracted to condition_eval/ submodules) ---
from praxis_core.dsl.condition_eval import (  # noqa: E402
    _evaluate_assigned_to,
    _evaluate_capacity,
    _evaluate_completed_before,
    _evaluate_day_of_week,
    _evaluate_due_date,
    _evaluate_due_within,
    _evaluate_in_location,
    _evaluate_moved_before,
    _evaluate_not_tagged,
    _evaluate_overdue,
    _evaluate_priority_ancestor,
    _evaluate_priority_type,
    _evaluate_staleness,
    _evaluate_status,
    _evaluate_tagged,
    _evaluate_time_window,
)


# -----------------------------------------------------------------------------
# Main Evaluation Functions
# -----------------------------------------------------------------------------


def evaluate_condition(
    condition: Condition,
    ctx: EvaluationContext,
    task: Task | None = None,
    event: dict | None = None,
) -> bool:
    """
    Evaluate a single condition.

    Args:
        condition: The condition to evaluate
        ctx: Evaluation context (time, capacities, etc.)
        task: Task being evaluated (for rules)
        event: Event that triggered evaluation (for practices)

    Returns:
        True if condition matches, False otherwise
    """
    params = condition.params
    condition_type = condition.condition_type

    # Determine subject based on condition.subject field
    # If subject is "event", use event dict; otherwise use task
    use_event = condition.subject == "event"
    subject_task = None if use_event else task
    subject_event = event if use_event else None

    # Context conditions (no subject needed)
    match condition_type:
        case ConditionType.TIME_WINDOW:
            return _evaluate_time_window(params, ctx)

        case ConditionType.DAY_OF_WEEK:
            return _evaluate_day_of_week(params, ctx)

        case ConditionType.CAPACITY:
            return _evaluate_capacity(params, ctx)

        # Entity conditions
        case ConditionType.TAGGED:
            return _evaluate_tagged(params, subject_task, subject_event, ctx)

        case ConditionType.NOT_TAGGED:
            return _evaluate_not_tagged(params, subject_task, subject_event, ctx)

        case ConditionType.PRIORITY_TYPE:
            return _evaluate_priority_type(params, subject_task, subject_event)

        case ConditionType.PRIORITY_ANCESTOR:
            return _evaluate_priority_ancestor(params, subject_task, subject_event, ctx)

        case ConditionType.STATUS:
            return _evaluate_status(params, subject_task, subject_event)

        case ConditionType.IN_LOCATION:
            return _evaluate_in_location(params, subject_task)

        # Task-specific conditions
        case ConditionType.OVERDUE:
            return _evaluate_overdue(params, subject_task, ctx)

        case ConditionType.DUE_WITHIN:
            return _evaluate_due_within(params, subject_task, ctx)

        case ConditionType.DUE_DATE:
            return _evaluate_due_date(params, subject_task, ctx)

        case ConditionType.STALENESS:
            return _evaluate_staleness(params, subject_task, ctx)

        case ConditionType.ASSIGNED_TO:
            return _evaluate_assigned_to(params, subject_task)

        case ConditionType.COMPLETED_BEFORE:
            return _evaluate_completed_before(params, subject_task, ctx)

        case ConditionType.MOVED_BEFORE:
            return _evaluate_moved_before(params, subject_task, ctx)

        case _:
            # Unknown condition type, pass by default
            return True


def evaluate_conditions(
    conditions: list[Condition],
    ctx: EvaluationContext,
    task: Task | None = None,
    event: dict | None = None,
) -> bool:
    """
    Evaluate multiple conditions with AND logic.

    All conditions must pass for the result to be True.
    """
    for condition in conditions:
        if not evaluate_condition(condition, ctx, task, event):
            return False
    return True
