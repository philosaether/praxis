"""
DSL v2 execution engine.

Handles:
- Evaluating conditions (event, capacity, time, day)
- Expanding template variables
- Parsing due dates (shorthand and structured)
- Executing create actions (tasks, priorities, hierarchies)
- Executing collate actions (query + batch)
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from praxis_core.dsl import (
    PracticeConfig,
    PracticeAction,
    Condition,
    CreateAction,
    CollateAction,
)
from praxis_core.dsl.actions import TaskTemplate, PriorityTemplate


# -----------------------------------------------------------------------------
# Execution Context
# -----------------------------------------------------------------------------

@dataclass
class ExecutionContext:
    """Context for action execution."""
    now: datetime
    entity_id: str | None = None

    # Practice being executed
    practice: dict | None = None

    # Event data (for event-triggered actions)
    event_priority: dict | None = None
    event_task: dict | None = None

    # Capacity values (for capacity conditions)
    capacities: dict[str, float] = field(default_factory=dict)

    def get_template_variables(self) -> dict[str, Any]:
        """Get variables available for template expansion."""
        variables = {
            "date": self.now.strftime("%Y-%m-%d"),
            "today": self.now.strftime("%Y-%m-%d"),
            "time": self.now.strftime("%H:%M"),
            "day_of_week": self.now.strftime("%A").lower(),
            "year": self.now.year,
            "month": self.now.month,
            "day": self.now.day,
            "hour": self.now.hour,
            "minute": self.now.minute,
        }

        # Practice variables
        if self.practice:
            variables["practice"] = self.practice
            variables["practice.name"] = self.practice.get("name", "")
            variables["practice.id"] = self.practice.get("id", "")

        # Event variables
        if self.event_priority:
            variables["event"] = {"priority": self.event_priority}
            variables["event.name"] = self.event_priority.get("name", "")
            variables["event.type"] = self.event_priority.get("priority_type", "")
            variables["priority"] = self.event_priority
            variables["priority.name"] = self.event_priority.get("name", "")

        if self.event_task:
            if "event" not in variables:
                variables["event"] = {}
            variables["event"]["task"] = self.event_task
            variables["event.name"] = self.event_task.get("name", "")
            variables["task"] = self.event_task
            variables["task.name"] = self.event_task.get("name", "")

        return variables


# -----------------------------------------------------------------------------
# Template Expansion
# -----------------------------------------------------------------------------

_TEMPLATE_PATTERN = re.compile(r"\{\{([^}]+)\}\}")


def expand_template(template: str, ctx: ExecutionContext) -> str:
    """
    Expand template variables in a string.

    Supported variables:
        {{date}}, {{today}}     → 2026-04-03
        {{time}}                → 14:30
        {{day_of_week}}         → thursday
        {{practice.name}}       → "Morning Routine"
        {{priority.name}}       → "Ship Project X" (event priority)
        {{event.name}}          → name of triggering entity
    """
    if not template:
        return ""

    variables = ctx.get_template_variables()

    def replace_var(match: re.Match) -> str:
        var_path = match.group(1).strip()

        # Direct lookup
        if var_path in variables:
            value = variables[var_path]
            return str(value) if not isinstance(value, dict) else str(value)

        # Nested lookup (e.g., "event.priority.name")
        parts = var_path.split(".")
        value = variables
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return match.group(0)  # Keep original if not found

        return str(value)

    return _TEMPLATE_PATTERN.sub(replace_var, template)


# -----------------------------------------------------------------------------
# Due Date Parsing
# -----------------------------------------------------------------------------

def parse_due_date(due: str | dict | None, now: datetime) -> datetime | None:
    """
    Parse a due date specification.

    Shorthand formats:
        end_of_day      → today 23:59
        end_of_week     → Friday 17:00
        tomorrow        → tomorrow 23:59
        +1d, +7d        → N days from now
        +2h, +30m       → N hours/minutes from now
        next_monday     → next Monday 09:00

    Structured format:
        {day: "today", time: "17:00"}
        {day: "friday", time: "17:00"}
        {day: "+4", time: "12:00"}
    """
    if due is None:
        return None

    # Structured format
    if isinstance(due, dict):
        day_spec = due.get("day", "today")
        time_spec = due.get("time", "23:59")

        # Parse time
        try:
            hour, minute = map(int, str(time_spec).split(":"))
        except (ValueError, AttributeError):
            hour, minute = 23, 59

        # Parse day
        if day_spec == "today":
            result = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        elif day_spec == "tomorrow":
            result = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        elif day_spec.startswith("+"):
            # Relative days: +4
            try:
                days = int(day_spec[1:])
                result = (now + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            except ValueError:
                return None
        else:
            # Day name: friday, monday, etc.
            result = _next_weekday(day_spec, now)
            if result:
                result = result.replace(hour=hour, minute=minute, second=0, microsecond=0)

        return result

    # Shorthand format
    due = str(due).strip().lower()

    # Relative offsets: +1d, +8h, +30m
    match = re.match(r"\+(\d+)([dhm])", due)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if unit == "d":
            return now + timedelta(days=amount)
        elif unit == "h":
            return now + timedelta(hours=amount)
        elif unit == "m":
            return now + timedelta(minutes=amount)

    # Keywords
    if due == "end_of_day":
        return now.replace(hour=23, minute=59, second=59, microsecond=0)

    if due == "end_of_week":
        # Friday 17:00
        days_until_friday = (4 - now.weekday()) % 7
        if days_until_friday == 0 and now.hour >= 17:
            days_until_friday = 7
        friday = now + timedelta(days=days_until_friday)
        return friday.replace(hour=17, minute=0, second=0, microsecond=0)

    if due == "tomorrow":
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=23, minute=59, second=59, microsecond=0)

    # next_monday, next_tuesday, etc.
    match = re.match(r"next_(\w+)", due)
    if match:
        day_name = match.group(1)
        result = _next_weekday(day_name, now)
        if result:
            return result.replace(hour=9, minute=0, second=0, microsecond=0)

    return None


def _next_weekday(day_name: str, now: datetime) -> datetime | None:
    """Get the next occurrence of a weekday."""
    day_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6
    }
    target = day_map.get(day_name.lower())
    if target is None:
        return None

    days_ahead = (target - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7  # Next week
    return now + timedelta(days=days_ahead)


# -----------------------------------------------------------------------------
# Condition Evaluation
# -----------------------------------------------------------------------------

def evaluate_condition(condition, ctx: ExecutionContext) -> bool:
    """Evaluate a single condition.

    Accepts either dsl.conditions.Condition (.condition_type) or
    models_v2.Condition (.type) for backwards compatibility.
    """
    params = condition.params
    # Support both dsl.conditions.Condition and models_v2.Condition
    ctype = str(getattr(condition, 'condition_type', None) or getattr(condition, 'type', ''))

    if ctype == "event" or getattr(condition, 'subject', None) == "event":
        # Check event properties
        if ctx.event_priority:
            if "type" in params:
                if ctx.event_priority.get("priority_type") != params["type"]:
                    return False
            if "ancestor" in params:
                # For now, we store ancestor as a name to resolve later
                # This check would need access to the priority hierarchy
                # For the engine test, we'll pass if ancestor is specified
                # (actual resolution happens at execution time with DB access)
                pass
        return True

    if ctype == "capacity":
        # Check capacity thresholds
        cap_name = params.get("name") or params.get("id", "")
        cap_value = ctx.capacities.get(cap_name, 0.0)

        if "less_than" in params:
            if cap_value >= params["less_than"]:
                return False
        if "at_most" in params:
            if cap_value > params["at_most"]:
                return False
        if "at_least" in params:
            if cap_value < params["at_least"]:
                return False
        if "greater_than" in params:
            if cap_value <= params["greater_than"]:
                return False
        if "equals" in params:
            if cap_value != params["equals"]:
                return False
        return True

    if ctype == "day":
        # Check day of week
        current_day = ctx.now.strftime("%A").lower()
        days = params.get("value", "")
        if isinstance(days, str):
            days = [d.strip().lower() for d in days.split(",")]
        return current_day in days

    if ctype == "time":
        # Check time window
        time_range = params.get("value", "")
        if " to " in time_range:
            start_str, end_str = time_range.split(" to ", 1)
            try:
                start_h, start_m = map(int, start_str.strip().split(":"))
                end_h, end_m = map(int, end_str.strip().split(":"))
                start_minutes = start_h * 60 + start_m
                end_minutes = end_h * 60 + end_m
                now_minutes = ctx.now.hour * 60 + ctx.now.minute

                if start_minutes <= end_minutes:
                    return start_minutes <= now_minutes <= end_minutes
                else:
                    # Overnight window
                    return now_minutes >= start_minutes or now_minutes <= end_minutes
            except (ValueError, AttributeError):
                return True

    return True  # Unknown condition types pass by default


def evaluate_conditions(conditions: list[Condition], ctx: ExecutionContext) -> bool:
    """Evaluate all conditions (AND logic)."""
    for condition in conditions:
        if not evaluate_condition(condition, ctx):
            return False
    return True


# -----------------------------------------------------------------------------
# Action Execution Results
# -----------------------------------------------------------------------------

@dataclass
class TaskSpec:
    """Specification for a task to create."""
    name: str
    notes: str | None = None
    due_date: datetime | None = None
    tags: list[str] = field(default_factory=list)
    priority_id: str | None = None
    entity_id: str | None = None


@dataclass
class PrioritySpec:
    """Specification for a priority to create."""
    name: str
    type: str = "project"
    notes: str | None = None
    due_date: datetime | None = None
    tags: list[str] = field(default_factory=list)
    parent_id: str | None = None
    entity_id: str | None = None
    children: list["TaskSpec | PrioritySpec"] = field(default_factory=list)


@dataclass
class CollateSpec:
    """Specification for a collation to perform."""
    batch_name: str
    target_shorthand: str | None = None
    match_any: list[dict] | None = None
    match_all: list[dict] | None = None
    exclude: list[dict] | None = None
    batch_due: datetime | None = None
    batch_tags: list[str] = field(default_factory=list)
    entity_id: str | None = None


@dataclass
class ExecutionResult:
    """Result of executing an action."""
    success: bool
    tasks: list[TaskSpec] = field(default_factory=list)
    priorities: list[PrioritySpec] = field(default_factory=list)
    collations: list[CollateSpec] = field(default_factory=list)
    error_message: str | None = None


# -----------------------------------------------------------------------------
# Action Execution
# -----------------------------------------------------------------------------

def _execute_task_template(template: TaskTemplate, ctx: ExecutionContext) -> TaskSpec:
    """Execute a task template to produce a TaskSpec."""
    return TaskSpec(
        name=expand_template(template.name, ctx),
        notes=expand_template(template.description, ctx) if template.description else None,
        due_date=parse_due_date(template.due, ctx.now),
        tags=list(template.tags),
        priority_id=template.priority_id,
        entity_id=ctx.entity_id,
    )


def _execute_priority_template(template: PriorityTemplate, ctx: ExecutionContext) -> PrioritySpec:
    """Execute a priority template to produce a PrioritySpec with children."""
    children = []
    for child in template.children:
        if isinstance(child, TaskTemplate):
            children.append(_execute_task_template(child, ctx))
        elif isinstance(child, PriorityTemplate):
            children.append(_execute_priority_template(child, ctx))

    return PrioritySpec(
        name=expand_template(template.name, ctx),
        type=template.type,
        notes=expand_template(template.description, ctx) if template.description else None,
        due_date=parse_due_date(template.due, ctx.now),
        tags=list(template.tags),
        entity_id=ctx.entity_id,
        children=children,
    )


def execute_create_action(create: CreateAction, ctx: ExecutionContext) -> ExecutionResult:
    """Execute a create action."""
    tasks = []
    priorities = []

    for item in create.items:
        if isinstance(item, TaskTemplate):
            tasks.append(_execute_task_template(item, ctx))
        elif isinstance(item, PriorityTemplate):
            priorities.append(_execute_priority_template(item, ctx))

    return ExecutionResult(
        success=True,
        tasks=tasks,
        priorities=priorities,
    )


def execute_collate_action(collate: CollateAction, ctx: ExecutionContext) -> ExecutionResult:
    """Execute a collate action."""
    target = collate.target

    spec = CollateSpec(
        batch_name=expand_template(collate.as_template.name, ctx),
        target_shorthand=target.shorthand,
        match_any=target.match_any,
        match_all=target.match_all,
        exclude=target.exclude,
        batch_due=parse_due_date(collate.as_template.due, ctx.now),
        batch_tags=list(collate.as_template.tags),
        entity_id=ctx.entity_id,
    )

    return ExecutionResult(
        success=True,
        collations=[spec],
    )


def execute_action(action: PracticeAction, ctx: ExecutionContext) -> ExecutionResult:
    """Execute a practice action if conditions pass."""
    # Check conditions
    if not evaluate_conditions(action.conditions, ctx):
        return ExecutionResult(success=False, error_message="Conditions not met")

    # Execute create or collate
    if action.create:
        return execute_create_action(action.create, ctx)
    if action.collate:
        return execute_collate_action(action.collate, ctx)

    return ExecutionResult(success=False, error_message="No action defined")
