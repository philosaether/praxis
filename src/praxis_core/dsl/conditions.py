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


# -----------------------------------------------------------------------------
# Context Condition Evaluation (no subject)
# -----------------------------------------------------------------------------


def _evaluate_time_window(params: dict, ctx: EvaluationContext) -> bool:
    """Check if current time is within a time window."""
    # Handle both "08:00 to 12:00" string format and structured format
    if "value" in params:
        value = params["value"]
        if isinstance(value, str) and " to " in value:
            start_str, end_str = value.split(" to ", 1)
        else:
            return True  # No valid range specified
    else:
        start_str = params.get("start", "00:00")
        end_str = params.get("end", "23:59")

    try:
        start = time.fromisoformat(start_str.strip())
        end = time.fromisoformat(end_str.strip())
    except (ValueError, AttributeError):
        return True  # Invalid format, pass by default

    current = ctx.current_time()

    # Handle overnight windows (e.g., 22:00 to 06:00)
    if start <= end:
        return start <= current <= end
    else:
        return current >= start or current <= end


def _evaluate_day_of_week(params: dict, ctx: EvaluationContext) -> bool:
    """Check if current day matches specified days."""
    days_param = params.get("value") or params.get("days", [])

    if isinstance(days_param, str):
        # Handle "weekdays", "weekends", or comma-separated list
        days_param = days_param.lower()
        if days_param == "weekdays":
            allowed = {"monday", "tuesday", "wednesday", "thursday", "friday"}
        elif days_param == "weekends":
            allowed = {"saturday", "sunday"}
        else:
            allowed = {d.strip().lower() for d in days_param.split(",")}
    elif isinstance(days_param, list):
        allowed = {d.lower() for d in days_param}
    else:
        return True  # No days specified, pass by default

    return ctx.current_day() in allowed


def _evaluate_capacity(params: dict, ctx: EvaluationContext) -> bool:
    """Check capacity thresholds (post-beta)."""
    capacity_name = params.get("name") or params.get("id", "")
    capacity_value = ctx.capacities.get(capacity_name, 0.0)

    if "less_than" in params:
        if capacity_value >= params["less_than"]:
            return False
    if "at_most" in params:
        if capacity_value > params["at_most"]:
            return False
    if "at_least" in params:
        if capacity_value < params["at_least"]:
            return False
    if "greater_than" in params:
        if capacity_value <= params["greater_than"]:
            return False
    if "equals" in params:
        if capacity_value != params["equals"]:
            return False

    return True


# -----------------------------------------------------------------------------
# Entity Condition Evaluation (task or event subject)
# -----------------------------------------------------------------------------


def _evaluate_tagged(
    params: dict, task: Task | None, event: dict | None, ctx: EvaluationContext
) -> bool:
    """Check if entity has a specific tag."""
    tag = params.get("value") or params.get("tag", "")
    tag = tag.lower()

    if task is not None:
        tags = ctx.task_tags or set()
        return tag in {t.lower() for t in tags}

    if event is not None:
        event_tags = event.get("tags", [])
        return tag in {t.lower() for t in event_tags}

    return False


def _evaluate_not_tagged(
    params: dict, task: Task | None, event: dict | None, ctx: EvaluationContext
) -> bool:
    """Check if entity does not have a specific tag."""
    return not _evaluate_tagged(params, task, event, ctx)


def _evaluate_priority_type(
    params: dict, task: Task | None, event: dict | None
) -> bool:
    """Check entity's priority type."""
    expected_type = params.get("value") or params.get("type", "")

    if task is not None:
        # Task's priority type would need to be looked up
        # For now, check if task has priority_type attribute
        task_type = getattr(task, "priority_type", None)
        return str(task_type) == expected_type if task_type else False

    if event is not None:
        return event.get("priority_type") == expected_type

    return False


def _evaluate_priority_ancestor(
    params: dict, task: Task | None, event: dict | None, ctx: EvaluationContext
) -> bool:
    """Check if entity is under a specific priority ancestor."""
    ancestor = params.get("value") or params.get("ancestor", "")

    if task is not None:
        ancestors = ctx.task_ancestors or set()
        # ancestor could be a name or ID
        return ancestor in ancestors

    if event is not None:
        event_ancestors = event.get("ancestors", [])
        return ancestor in event_ancestors

    return False


def _evaluate_status(params: dict, task: Task | None, event: dict | None) -> bool:
    """Check entity status."""
    expected_status = params.get("value") or params.get("status", "")

    if task is not None:
        return task.status.value == expected_status

    if event is not None:
        return event.get("status") == expected_status

    return False


def _evaluate_in_location(params: dict, task: Task | None) -> bool:
    """Check if task is in inbox or outbox."""
    location = params.get("value") or params.get("location", "")

    if task is None:
        return False

    if location == "inbox":
        # Inbox = no priority assigned
        return task.priority_id is None

    if location == "outbox":
        # Outbox = marked for deletion (needs outbox field on Task)
        return getattr(task, "in_outbox", False)

    return False


def _evaluate_overdue(params: dict, task: Task | None, ctx: EvaluationContext) -> bool:
    """Check if task is overdue."""
    if task is None or task.due_date is None:
        return False

    is_overdue = task.due_date < ctx.now

    # params might specify `overdue: true` or `overdue: false`
    expected = params.get("value", True)
    if isinstance(expected, bool):
        return is_overdue == expected

    return is_overdue


def _evaluate_due_within(
    params: dict, task: Task | None, ctx: EvaluationContext
) -> bool:
    """Check if task is due within a time period."""
    if task is None or task.due_date is None:
        return False

    within = params.get("value") or params.get("hours", 24)

    # Parse duration string like "24h", "2d"
    if isinstance(within, str):
        within = within.lower().strip()
        if within.endswith("h"):
            hours = float(within[:-1])
        elif within.endswith("d"):
            hours = float(within[:-1]) * 24
        else:
            try:
                hours = float(within)
            except ValueError:
                hours = 24
    else:
        hours = float(within)

    delta = task.due_date - ctx.now
    hours_until_due = delta.total_seconds() / 3600

    return 0 <= hours_until_due <= hours


def _evaluate_staleness(
    params: dict, task: Task | None, ctx: EvaluationContext
) -> bool:
    """Check if task has been untouched for N days."""
    if task is None:
        return False

    days_threshold = params.get("value") or params.get("days", 0)

    # Parse "3 days" format
    if isinstance(days_threshold, str):
        import re

        match = re.match(r"(\d+)\s*days?", days_threshold)
        if match:
            days_threshold = int(match.group(1))
        else:
            try:
                days_threshold = float(days_threshold)
            except ValueError:
                days_threshold = 0

    # Use updated_at if available, otherwise created_at
    last_touched = getattr(task, "updated_at", None) or task.created_at
    if last_touched is None:
        return False

    delta = ctx.now - last_touched
    days_since_touched = delta.total_seconds() / 86400

    return days_since_touched >= days_threshold


def _evaluate_due_date(params: dict, task: Task | None, ctx: EvaluationContext) -> bool:
    """Check various due date conditions."""
    if task is None:
        return False

    # has_due_date check
    if "has_due_date" in params:
        has_due = task.due_date is not None
        if params["has_due_date"] != has_due:
            return False

    # overdue check
    if "overdue" in params:
        if task.due_date is None:
            return False
        is_overdue = task.due_date < ctx.now
        if params["overdue"] != is_overdue:
            return False

    # within_hours check
    if "within_hours" in params:
        if task.due_date is None:
            return False
        delta = task.due_date - ctx.now
        hours_until = delta.total_seconds() / 3600
        if hours_until < 0 or hours_until > params["within_hours"]:
            return False

    return True


def _evaluate_assigned_to(params: dict, task: Task | None) -> bool:
    """Check task assignment."""
    if task is None:
        return False

    expected = params.get("value") or params.get("assigned_to", "")

    if expected == "me":
        # Caller should resolve "me" to actual user ID before evaluation
        # For now, just check if assigned
        return task.assigned_to is not None

    return str(task.assigned_to) == str(expected)


def _evaluate_completed_before(
    params: dict, task: Task | None, ctx: EvaluationContext
) -> bool:
    """Check if task was completed before a relative time."""
    if task is None:
        return False

    completed_at = getattr(task, "completed_at", None)
    if completed_at is None:
        return False

    threshold = params.get("value") or params.get("before", "")
    cutoff = _parse_relative_time(threshold, ctx.now)
    if cutoff is None:
        return False

    return completed_at < cutoff


def _evaluate_moved_before(
    params: dict, task: Task | None, ctx: EvaluationContext
) -> bool:
    """Check if task was moved to current location before a relative time."""
    if task is None:
        return False

    moved_at = getattr(task, "moved_at", None)
    if moved_at is None:
        return False

    threshold = params.get("value") or params.get("before", "")
    cutoff = _parse_relative_time(threshold, ctx.now)
    if cutoff is None:
        return False

    return moved_at < cutoff


def _parse_relative_time(spec: str, now: datetime) -> datetime | None:
    """Parse relative time like '-7d' into absolute datetime."""
    import re
    from datetime import timedelta

    if not isinstance(spec, str):
        return None

    spec = spec.strip()
    match = re.match(r"(-?\d+)([dhm])", spec)
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2)

    if unit == "d":
        return now + timedelta(days=amount)
    elif unit == "h":
        return now + timedelta(hours=amount)
    elif unit == "m":
        return now + timedelta(minutes=amount)

    return None


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
