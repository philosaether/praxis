"""
Templates and template expansion for action execution.

Templates define what to create (TaskTemplate, PriorityTemplate).
Specs are the resolved output (TaskSpec, PrioritySpec).
ActionContext provides variables for template expansion.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import re


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
