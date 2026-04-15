"""Task-specific condition evaluators."""

from datetime import datetime

from praxis_core.dsl.conditions import EvaluationContext
from praxis_core.model import Task


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
