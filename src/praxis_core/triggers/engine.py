"""
Trigger execution engine.

Handles:
- Evaluating trigger conditions (reuses Rules engine)
- Expanding template variables ({{date}}, {{practice.name}}, etc.)
- Executing trigger actions (create_task, collate_tasks)
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from praxis_core.model.rules import RuleCondition
from praxis_core.model.triggers import (
    Trigger,
    TriggerEvent,
    TriggerEventType,
    TriggerAction,
    TriggerActionType,
    TaskTemplate,
    CollateConfig,
)


# -----------------------------------------------------------------------------
# Trigger Context
# -----------------------------------------------------------------------------

@dataclass
class TriggerContext:
    """Context for trigger evaluation and execution."""
    now: datetime
    entity_id: str | None = None

    # Event data (populated based on event type)
    event_priority: dict | None = None  # For priority_completed
    event_task: dict | None = None  # For task_completed

    # Practice data (if trigger is attached to a practice)
    practice: dict | None = None

    def get_template_variables(self) -> dict[str, Any]:
        """Get variables available for template expansion."""
        variables = {
            "date": self.now.strftime("%Y-%m-%d"),
            "time": self.now.strftime("%H:%M"),
            "day_of_week": self.now.strftime("%A").lower(),
            "year": self.now.year,
            "month": self.now.month,
            "day": self.now.day,
            "hour": self.now.hour,
            "minute": self.now.minute,
        }

        # Add practice variables
        if self.practice:
            variables["practice"] = self.practice
            variables["practice.name"] = self.practice.get("name", "")
            variables["practice.id"] = self.practice.get("id", "")

        # Add event variables
        if self.event_priority:
            variables["event"] = {"priority": self.event_priority}
            variables["event.priority.name"] = self.event_priority.get("name", "")
            variables["event.priority.id"] = self.event_priority.get("id", "")
            variables["event.priority.type"] = self.event_priority.get("priority_type", "")

        if self.event_task:
            if "event" not in variables:
                variables["event"] = {}
            variables["event"]["task"] = self.event_task
            variables["event.task.name"] = self.event_task.get("name", "")
            variables["event.task.id"] = self.event_task.get("id", "")

        return variables


# -----------------------------------------------------------------------------
# Template Expansion
# -----------------------------------------------------------------------------

# Pattern for template variables: {{variable.path}}
_TEMPLATE_PATTERN = re.compile(r"\{\{([^}]+)\}\}")


def expand_template(template: str, ctx: TriggerContext) -> str:
    """
    Expand template variables in a string.

    Supported variables:
        {{date}}              → 2026-04-02
        {{time}}              → 14:30
        {{day_of_week}}       → wednesday
        {{practice.name}}     → "Morning Routine"
        {{event.priority.name}} → "Ship Project X"
        {{event.task.name}}   → "Review PR"
    """
    if not template:
        return ""

    variables = ctx.get_template_variables()

    def replace_var(match: re.Match) -> str:
        var_path = match.group(1).strip()

        # Direct lookup first
        if var_path in variables:
            value = variables[var_path]
            if isinstance(value, dict):
                return str(value)
            return str(value)

        # Try nested lookup (e.g., "practice.name")
        parts = var_path.split(".")
        value = variables
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                # Variable not found, return original
                return match.group(0)

        return str(value)

    return _TEMPLATE_PATTERN.sub(replace_var, template)


# -----------------------------------------------------------------------------
# Due Date Offset Parsing
# -----------------------------------------------------------------------------

def parse_due_date_offset(offset: str | None, now: datetime) -> datetime | None:
    """
    Parse a due date offset string into a datetime.

    Supported formats:
        +1d, +2d       → add N days
        +1h, +8h       → add N hours
        +30m           → add N minutes
        end_of_day     → 23:59 today
        end_of_week    → Sunday 23:59
        tomorrow       → tomorrow at 23:59
        next_monday    → next Monday at 09:00
    """
    if not offset:
        return None

    offset = offset.strip().lower()

    # Relative offsets: +1d, +8h, +30m
    match = re.match(r"\+(\d+)([dhm])", offset)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if unit == "d":
            return now + timedelta(days=amount)
        elif unit == "h":
            return now + timedelta(hours=amount)
        elif unit == "m":
            return now + timedelta(minutes=amount)

    # Special keywords
    if offset == "end_of_day":
        return now.replace(hour=23, minute=59, second=59, microsecond=0)

    if offset == "end_of_week":
        # End of week = Sunday 23:59
        days_until_sunday = (6 - now.weekday()) % 7
        if days_until_sunday == 0:
            days_until_sunday = 7  # Next Sunday if today is Sunday
        end_of_week = now + timedelta(days=days_until_sunday)
        return end_of_week.replace(hour=23, minute=59, second=59, microsecond=0)

    if offset == "tomorrow":
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=23, minute=59, second=59, microsecond=0)

    # next_monday, next_tuesday, etc.
    match = re.match(r"next_(\w+)", offset)
    if match:
        day_name = match.group(1)
        day_map = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6
        }
        if day_name in day_map:
            target_day = day_map[day_name]
            days_ahead = (target_day - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            next_day = now + timedelta(days=days_ahead)
            return next_day.replace(hour=9, minute=0, second=0, microsecond=0)

    return None


# -----------------------------------------------------------------------------
# Condition Evaluation (reuse from Rules engine)
# -----------------------------------------------------------------------------

def evaluate_condition(condition: RuleCondition, ctx: TriggerContext) -> bool:
    """
    Evaluate a single condition.

    Note: This is a simplified version for triggers. For task-based conditions,
    we defer to the Rules engine. Triggers mainly use time-based conditions.
    """
    from praxis_core.model.rules import ConditionType

    params = condition.params

    match condition.type:
        case ConditionType.TIME_WINDOW:
            start_str = params.get("start", "00:00")
            end_str = params.get("end", "23:59")
            try:
                start_h, start_m = map(int, start_str.split(":"))
                end_h, end_m = map(int, end_str.split(":"))
                start_minutes = start_h * 60 + start_m
                end_minutes = end_h * 60 + end_m
                now_minutes = ctx.now.hour * 60 + ctx.now.minute

                # Handle overnight windows (e.g., 22:00 to 06:00)
                if start_minutes <= end_minutes:
                    return start_minutes <= now_minutes <= end_minutes
                else:
                    return now_minutes >= start_minutes or now_minutes <= end_minutes
            except (ValueError, AttributeError):
                return False

        case ConditionType.DAY_OF_WEEK:
            days = params.get("days", [])
            current_day = ctx.now.strftime("%A").lower()
            return current_day in [d.lower() for d in days]

        case ConditionType.TAG_MATCH:
            # For triggers, tag conditions apply to the event task if present
            if ctx.event_task:
                task_tags = set(t.lower() for t in ctx.event_task.get("tags", []))
                tag = params.get("tag", "").lower()
                operator = params.get("operator", "has")
                if operator == "has":
                    return tag in task_tags
                else:  # missing
                    return tag not in task_tags
            return True  # No task context, condition passes

        case ConditionType.PRIORITY_MATCH:
            # For triggers, priority conditions apply to the event priority
            if ctx.event_priority:
                if "priority_id" in params:
                    return ctx.event_priority.get("id") == params["priority_id"]
                if "priority_type" in params:
                    return ctx.event_priority.get("priority_type") == params["priority_type"]
            return True  # No priority context, condition passes

        case _:
            # Other conditions not typically used in triggers
            return True


def evaluate_conditions(conditions: list[RuleCondition], ctx: TriggerContext) -> bool:
    """Evaluate all conditions (AND logic). All must pass."""
    for condition in conditions:
        if not evaluate_condition(condition, ctx):
            return False
    return True


# -----------------------------------------------------------------------------
# Action Execution
# -----------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    """Result of executing a trigger."""
    success: bool
    actions_taken: list[dict] = field(default_factory=list)
    error_message: str | None = None


def execute_create_task(
    template: TaskTemplate,
    trigger: Trigger,
    ctx: TriggerContext,
) -> dict:
    """
    Execute a create_task action.

    Returns the task creation parameters (not the actual task - that's done
    by the caller with access to persistence layer).
    """
    # Expand template variables
    name = expand_template(template.name_pattern, ctx)
    notes = expand_template(template.notes_pattern, ctx) if template.notes_pattern else None

    # Parse due date
    due_date = parse_due_date_offset(template.due_date_offset, ctx.now)

    # Determine priority_id
    priority_id = template.priority_id or trigger.practice_id

    return {
        "name": name,
        "notes": notes,
        "due_date": due_date,
        "priority_id": priority_id,
        "entity_id": ctx.entity_id,
        "tags": template.tags,
    }


def execute_collate_tasks(
    config: CollateConfig,
    trigger: Trigger,
    ctx: TriggerContext,
) -> dict:
    """
    Execute a collate_tasks action.

    Returns the collation parameters (the actual task gathering and creation
    is done by the caller with access to persistence layer).
    """
    batch_name = expand_template(config.batch_name_pattern, ctx)

    return {
        "batch_name": batch_name,
        "source_tag": config.source_tag,
        "source_priority_id": config.source_priority_id or trigger.practice_id,
        "include_completed": config.include_completed,
        "mark_source_done": config.mark_source_done,
        "entity_id": ctx.entity_id,
    }


def execute_trigger(trigger: Trigger, ctx: TriggerContext) -> ExecutionResult:
    """
    Execute a trigger's actions.

    Note: This doesn't actually create tasks - it returns the parameters
    needed to create them. The actual persistence is handled by the scheduler
    which has access to the persistence layer.
    """
    # Check conditions first
    if not evaluate_conditions(trigger.conditions, ctx):
        return ExecutionResult(
            success=False,
            error_message="Conditions not met",
        )

    actions_taken = []

    for action in trigger.actions:
        match action.type:
            case TriggerActionType.CREATE_TASK:
                if action.task_template:
                    params = execute_create_task(action.task_template, trigger, ctx)
                    actions_taken.append({
                        "type": "create_task",
                        "params": params,
                    })

            case TriggerActionType.COLLATE_TASKS:
                if action.collate_config:
                    params = execute_collate_tasks(action.collate_config, trigger, ctx)
                    actions_taken.append({
                        "type": "collate_tasks",
                        "params": params,
                    })

    return ExecutionResult(
        success=True,
        actions_taken=actions_taken,
    )


# -----------------------------------------------------------------------------
# Schedule Checking
# -----------------------------------------------------------------------------

def should_trigger_fire(trigger: Trigger, now: datetime) -> bool:
    """
    Check if a scheduled trigger should fire based on its schedule and last_fired_at.

    This is used by the scheduler to determine which triggers are due.
    """
    if trigger.event.type != TriggerEventType.SCHEDULE:
        return False

    params = trigger.event.params
    interval = params.get("interval", "daily")
    scheduled_time = params.get("at", "00:00")
    scheduled_day = params.get("day")  # For weekly triggers

    # Parse scheduled time
    try:
        hour, minute = map(int, scheduled_time.split(":"))
    except (ValueError, AttributeError):
        hour, minute = 0, 0

    # Check if we're past the scheduled time today
    scheduled_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # For weekly triggers, check if today is the scheduled day
    if interval == "weekly" and scheduled_day:
        day_map = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6
        }
        if now.weekday() != day_map.get(scheduled_day.lower(), 0):
            return False

    # For weekday triggers, check if today is a weekday
    if interval == "weekdays" and now.weekday() >= 5:
        return False

    # Check if we've already fired today (or at this interval)
    if trigger.last_fired_at:
        last_fired = trigger.last_fired_at

        if interval == "daily" or interval == "weekdays":
            # Should fire once per day
            if last_fired.date() >= now.date():
                return False
        elif interval == "weekly":
            # Should fire once per week
            days_since = (now.date() - last_fired.date()).days
            if days_since < 7:
                return False
        elif interval == "2x_daily":
            # Should fire twice per day - check if at least 8 hours since last fire
            hours_since = (now - last_fired).total_seconds() / 3600
            if hours_since < 8:
                return False

    # Check if we're past the scheduled time
    if now < scheduled_today:
        return False

    return True
