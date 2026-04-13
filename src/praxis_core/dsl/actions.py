"""
Actions for Rules and Practices.

Actions perform database operations when automations fire:
- create: INSERT tasks/priorities
- move: UPDATE task location (outbox, inbox, priority)
- delete: DELETE tasks
- collate: batch existing tasks into one

Actions are impure — they modify database state.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
import re


class ActionType(StrEnum):
    """Types of actions that can be executed."""

    CREATE = "create"
    MOVE = "move"
    DELETE = "delete"
    COLLATE = "collate"


# Import Trigger-related types for PracticeAction
from .triggers import Trigger, Schedule, Cadence, Event


# -----------------------------------------------------------------------------
# Templates for Create Action
# -----------------------------------------------------------------------------


@dataclass
class TaskTemplate:
    """Template for creating a task."""

    name: str
    description: str | None = None
    due: str | dict | None = None  # "end_of_day" or {"day": "friday", "time": "17:00"}
    tags: list[str] = field(default_factory=list)
    priority_id: str | None = None  # Override parent priority

    def to_dict(self) -> dict:
        result = {"name": self.name}
        if self.description:
            result["description"] = self.description
        if self.due:
            result["due"] = self.due
        if self.tags:
            result["tags"] = self.tags
        if self.priority_id:
            result["priority_id"] = self.priority_id
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "TaskTemplate":
        return cls(
            name=data.get("name", ""),
            description=data.get("description") or data.get("notes"),
            due=data.get("due"),
            tags=data.get("tags", []),
            priority_id=data.get("priority_id"),
        )


@dataclass
class PriorityTemplate:
    """Template for creating a priority (with optional children)."""

    name: str
    priority_type: str = "goal"
    description: str | None = None
    due: str | dict | None = None
    tags: list[str] = field(default_factory=list)
    children: list["TaskTemplate | PriorityTemplate"] = field(default_factory=list)

    def to_dict(self) -> dict:
        result = {"name": self.name, "type": self.priority_type}
        if self.description:
            result["description"] = self.description
        if self.due:
            result["due"] = self.due
        if self.tags:
            result["tags"] = self.tags
        if self.children:
            result["children"] = [c.to_dict() for c in self.children]
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "PriorityTemplate":
        children = []
        for child_data in data.get("children", []):
            if "task" in child_data:
                children.append(TaskTemplate.from_dict(child_data["task"]))
            elif "priority" in child_data:
                children.append(PriorityTemplate.from_dict(child_data["priority"]))
            elif "name" in child_data:
                # Infer type from presence of 'type' or 'children'
                if "type" in child_data or "children" in child_data:
                    children.append(PriorityTemplate.from_dict(child_data))
                else:
                    children.append(TaskTemplate.from_dict(child_data))
        return cls(
            name=data.get("name", ""),
            priority_type=data.get("type", "goal"),
            description=data.get("description") or data.get("notes"),
            due=data.get("due"),
            tags=data.get("tags", []),
            children=children,
        )


# -----------------------------------------------------------------------------
# Action Specifications (output of template execution)
# -----------------------------------------------------------------------------


@dataclass
class TaskSpec:
    """Specification for a task to create."""

    name: str
    description: str | None = None
    due_date: datetime | None = None
    tags: list[str] = field(default_factory=list)
    priority_id: str | None = None
    entity_id: str | None = None  # Owner


@dataclass
class PrioritySpec:
    """Specification for a priority to create."""

    name: str
    priority_type: str = "goal"
    description: str | None = None
    due_date: datetime | None = None
    tags: list[str] = field(default_factory=list)
    parent_id: str | None = None
    entity_id: str | None = None
    children: list["TaskSpec | PrioritySpec"] = field(default_factory=list)


@dataclass
class MoveSpec:
    """Specification for a move operation."""

    destination: str  # "outbox", "inbox", or priority ID/name
    task_ids: list[str] = field(default_factory=list)  # Tasks to move


@dataclass
class DeleteSpec:
    """Specification for a delete operation."""

    task_ids: list[str] = field(default_factory=list)


@dataclass
class CollateSpec:
    """Specification for a collation operation."""

    batch_name: str
    batch_description: str | None = None
    batch_due: datetime | None = None
    batch_tags: list[str] = field(default_factory=list)

    # Target filtering
    target_shorthand: str | None = None  # "children", "descendants", "tagged: X"
    match_any: list[dict] | None = None
    match_all: list[dict] | None = None
    exclude: list[dict] | None = None

    entity_id: str | None = None
    priority_id: str | None = None  # Context priority for "children"


# -----------------------------------------------------------------------------
# Action Models
# -----------------------------------------------------------------------------


@dataclass
class CreateAction:
    """Action that creates tasks and/or priorities."""

    items: list[TaskTemplate | PriorityTemplate] = field(default_factory=list)

    def to_dict(self) -> list:
        result = []
        for item in self.items:
            if isinstance(item, TaskTemplate):
                result.append({"task": item.to_dict()})
            else:
                result.append({"priority": item.to_dict()})
        return result

    @classmethod
    def from_dict(cls, data: list | dict) -> "CreateAction":
        if isinstance(data, dict):
            data = [data]

        items = []
        for item_data in data:
            if "task" in item_data:
                items.append(TaskTemplate.from_dict(item_data["task"]))
            elif "priority" in item_data:
                items.append(PriorityTemplate.from_dict(item_data["priority"]))
            elif "name" in item_data:
                # Infer from structure
                if "type" in item_data or "children" in item_data:
                    items.append(PriorityTemplate.from_dict(item_data))
                else:
                    items.append(TaskTemplate.from_dict(item_data))
        return cls(items=items)


@dataclass
class MoveAction:
    """Action that moves tasks to a location."""

    destination: str  # "outbox", "inbox", or priority name

    def to_dict(self) -> dict:
        return {"move": self.destination}

    @classmethod
    def from_dict(cls, data: str | dict) -> "MoveAction":
        if isinstance(data, str):
            return cls(destination=data)
        return cls(destination=data.get("priority") or data.get("destination", ""))


@dataclass
class DeleteAction:
    """Action that deletes tasks."""

    # Future: could add conditions like "after: 7d"
    immediate: bool = True

    def to_dict(self) -> dict:
        return {"delete": True}

    @classmethod
    def from_dict(cls, data: bool | dict) -> "DeleteAction":
        if isinstance(data, bool):
            return cls(immediate=data)
        return cls(immediate=True)


@dataclass
class CollateTarget:
    """Target specification for collation."""

    shorthand: str | None = None  # "children", "descendants", "tagged: X"
    match_any: list[dict] | None = None
    match_all: list[dict] | None = None
    exclude: list[dict] | None = None

    def to_dict(self) -> dict | str:
        if self.shorthand:
            return self.shorthand
        result = {}
        if self.match_any:
            result["match_any"] = self.match_any
        if self.match_all:
            result["match_all"] = self.match_all
        if self.exclude:
            result["exclude"] = self.exclude
        return result

    @classmethod
    def from_dict(cls, data: dict | str | list) -> "CollateTarget":
        if isinstance(data, str):
            return cls(shorthand=data)

        if isinstance(data, list):
            match_any = []
            match_all = []
            exclude = []
            for item in data:
                if "match_any" in item:
                    ma = item["match_any"]
                    if isinstance(ma, dict):
                        match_any.extend([{k: v} for k, v in ma.items()])
                    else:
                        match_any.extend(ma)
                if "match_all" in item:
                    mall = item["match_all"]
                    if isinstance(mall, dict):
                        match_all.extend([{k: v} for k, v in mall.items()])
                    else:
                        match_all.extend(mall)
                if "exclude" in item:
                    ex = item["exclude"]
                    if isinstance(ex, dict):
                        exclude.extend([{k: v} for k, v in ex.items()])
                    else:
                        exclude.extend(ex)
            return cls(
                match_any=match_any if match_any else None,
                match_all=match_all if match_all else None,
                exclude=exclude if exclude else None,
            )

        return cls(
            match_any=data.get("match_any"),
            match_all=data.get("match_all"),
            exclude=data.get("exclude"),
        )


@dataclass
class CollateAction:
    """Action that collates existing tasks into a batch."""

    target: CollateTarget
    as_template: TaskTemplate

    def to_dict(self) -> dict:
        return {
            "target": self.target.to_dict(),
            "as": self.as_template.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CollateAction":
        return cls(
            target=CollateTarget.from_dict(data.get("target", "children")),
            as_template=TaskTemplate.from_dict(data.get("as", {})),
        )


# -----------------------------------------------------------------------------
# Execution Context
# -----------------------------------------------------------------------------


@dataclass
class ActionContext:
    """Context for action execution."""

    now: datetime
    entity_id: str | None = None  # Owner user ID
    priority_id: str | None = None  # Context priority (for Practices)

    # For template expansion
    practice: dict | None = None
    event_priority: dict | None = None
    event_task: dict | None = None

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

        if self.practice:
            variables["practice"] = self.practice
            variables["practice.name"] = self.practice.get("name", "")
            variables["practice.id"] = self.practice.get("id", "")

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


def expand_template(template: str, ctx: ActionContext) -> str:
    """
    Expand template variables in a string.

    Supported variables:
        {{date}}, {{today}}     → 2026-04-03
        {{time}}                → 14:30
        {{day_of_week}}         → thursday
        {{practice.name}}       → "Morning Routine"
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

        try:
            hour, minute = map(int, str(time_spec).split(":"))
        except (ValueError, AttributeError):
            hour, minute = 23, 59

        if day_spec == "today":
            result = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        elif day_spec == "tomorrow":
            result = (now + timedelta(days=1)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
        elif str(day_spec).startswith("+"):
            try:
                days = int(day_spec[1:])
                result = (now + timedelta(days=days)).replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
            except ValueError:
                return None
        else:
            # Day name: friday, monday, etc.
            result = _next_weekday(day_spec, now)
            if result:
                result = result.replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )

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
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    target = day_map.get(day_name.lower())
    if target is None:
        return None

    days_ahead = (target - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7  # Next week
    return now + timedelta(days=days_ahead)


# -----------------------------------------------------------------------------
# Action Execution (produces specs, not DB writes)
# -----------------------------------------------------------------------------


def execute_create_action(
    action: CreateAction, ctx: ActionContext
) -> tuple[list[TaskSpec], list[PrioritySpec]]:
    """
    Execute a create action, producing specs.

    Returns:
        Tuple of (task_specs, priority_specs) ready for persistence
    """
    tasks = []
    priorities = []

    for item in action.items:
        if isinstance(item, TaskTemplate):
            tasks.append(_execute_task_template(item, ctx))
        elif isinstance(item, PriorityTemplate):
            priorities.append(_execute_priority_template(item, ctx))

    return tasks, priorities


def _execute_task_template(template: TaskTemplate, ctx: ActionContext) -> TaskSpec:
    """Execute a task template to produce a TaskSpec."""
    return TaskSpec(
        name=expand_template(template.name, ctx),
        description=expand_template(template.description, ctx)
        if template.description
        else None,
        due_date=parse_due_date(template.due, ctx.now),
        tags=list(template.tags),
        priority_id=template.priority_id or ctx.priority_id,
        entity_id=ctx.entity_id,
    )


def _execute_priority_template(
    template: PriorityTemplate, ctx: ActionContext
) -> PrioritySpec:
    """Execute a priority template to produce a PrioritySpec with children."""
    children = []
    for child in template.children:
        if isinstance(child, TaskTemplate):
            children.append(_execute_task_template(child, ctx))
        elif isinstance(child, PriorityTemplate):
            children.append(_execute_priority_template(child, ctx))

    return PrioritySpec(
        name=expand_template(template.name, ctx),
        priority_type=template.priority_type,
        description=expand_template(template.description, ctx)
        if template.description
        else None,
        due_date=parse_due_date(template.due, ctx.now),
        tags=list(template.tags),
        parent_id=ctx.priority_id,
        entity_id=ctx.entity_id,
        children=children,
    )


def execute_move_action(
    action: MoveAction, task_ids: list[str], ctx: ActionContext
) -> MoveSpec:
    """
    Execute a move action, producing a spec.

    Args:
        action: The move action configuration
        task_ids: Tasks matched by the rule's conditions
        ctx: Action context

    Returns:
        MoveSpec ready for persistence
    """
    return MoveSpec(
        destination=action.destination,
        task_ids=task_ids,
    )


def execute_delete_action(
    action: DeleteAction, task_ids: list[str], ctx: ActionContext
) -> DeleteSpec:
    """
    Execute a delete action, producing a spec.

    Args:
        action: The delete action configuration
        task_ids: Tasks matched by the rule's conditions
        ctx: Action context

    Returns:
        DeleteSpec ready for persistence
    """
    return DeleteSpec(task_ids=task_ids)


def execute_collate_action(action: CollateAction, ctx: ActionContext) -> CollateSpec:
    """
    Execute a collate action, producing a spec.

    Returns:
        CollateSpec with query params for gathering tasks
    """
    target = action.target

    return CollateSpec(
        batch_name=expand_template(action.as_template.name, ctx),
        batch_description=expand_template(action.as_template.description, ctx)
        if action.as_template.description
        else None,
        batch_due=parse_due_date(action.as_template.due, ctx.now),
        batch_tags=list(action.as_template.tags),
        target_shorthand=target.shorthand,
        match_any=target.match_any,
        match_all=target.match_all,
        exclude=target.exclude,
        entity_id=ctx.entity_id,
        priority_id=ctx.priority_id,
    )


# -----------------------------------------------------------------------------
# Practice Action (wraps trigger + conditions + action)
# -----------------------------------------------------------------------------


@dataclass
class PracticeAction:
    """
    A single action block within a Practice.

    Combines: trigger (when) + conditions (if) + action (then).
    """

    trigger: Trigger
    conditions: list = field(default_factory=list)  # List of Condition objects
    create: CreateAction | None = None
    collate: CollateAction | None = None

    def to_dict(self) -> dict:
        result = {"trigger": self.trigger.to_dict()}
        if self.conditions:
            result["when"] = {c.condition_type: c.params for c in self.conditions}
        if self.create:
            result["create"] = self.create.to_dict()
        if self.collate:
            result["collate"] = self.collate.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "PracticeAction":
        from .conditions import Condition, ConditionType

        trigger_data = data.get("trigger") or {}

        trigger = Trigger.from_dict(trigger_data)

        # Parse conditions (when:) - can be in trigger: or at top level
        conditions = []
        when_data = trigger_data.get("when", data.get("when", {}))
        if isinstance(when_data, dict):
            for key, value in when_data.items():
                if "." in str(key):
                    # Dot notation: event.type -> subject="event", check type
                    parts = str(key).split(".", 1)
                    conditions.append(Condition(
                        condition_type=ConditionType(parts[1]) if parts[1] in [e.value for e in ConditionType] else ConditionType.STATUS,
                        params={"value": value},
                        subject=parts[0],
                    ))
                elif key in [e.value for e in ConditionType]:
                    conditions.append(Condition(
                        condition_type=ConditionType(key),
                        params=value if isinstance(value, dict) else {"value": value},
                    ))

        create = None
        collate = None

        create_data = trigger_data.get("create", data.get("create"))
        if create_data is not None:
            create = CreateAction.from_dict(create_data)

        collate_data = trigger_data.get("collate", data.get("collate"))
        if collate_data is not None:
            collate = CollateAction.from_dict(collate_data)

        return cls(trigger=trigger, conditions=conditions, create=create, collate=collate)


# -----------------------------------------------------------------------------
# Practice Config (container for actions_config JSON field)
# -----------------------------------------------------------------------------


@dataclass
class PracticeConfig:
    """
    Full Practice configuration with multiple actions.

    Used for serializing/deserializing the actions_config JSON field.
    """

    name: str
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    actions: list[PracticeAction] = field(default_factory=list)

    def to_dict(self) -> dict:
        result = {"name": self.name}
        if self.description:
            result["description"] = self.description
        if self.tags:
            result["tags"] = self.tags
        if self.actions:
            result["actions"] = [a.to_dict() for a in self.actions]
        return {"practice": result}

    def to_json(self) -> str:
        """Serialize to JSON for database storage."""
        import json
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict) -> "PracticeConfig":
        # Handle wrapper
        if "practice" in data:
            data = data["practice"]

        actions = []
        for action_data in data.get("actions", []):
            actions.append(PracticeAction.from_dict(action_data))

        return cls(
            name=data.get("name", ""),
            description=data.get("description"),
            tags=data.get("tags", []),
            actions=actions,
        )

    @classmethod
    def from_json(cls, json_str: str) -> "PracticeConfig":
        """Deserialize from JSON."""
        import json
        return cls.from_dict(json.loads(json_str))
