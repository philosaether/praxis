"""
Action types and execution for the automation system.

Action types define what can happen (create, move, delete, collate).
Specs are the resolved output ready for persistence.
Execute functions convert templates + context into specs.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from .triggers import Trigger, Schedule, Cadence, Event
from .templates import (
    TaskTemplate,
    PriorityTemplate,
    TaskSpec,
    PrioritySpec,
    ActionContext,
    expand_template,
)
from .date_parsing import parse_due_date


class ActionType(StrEnum):
    """Types of actions that can be executed."""

    CREATE = "create"
    MOVE = "move"
    DELETE = "delete"
    COLLATE = "collate"


# -----------------------------------------------------------------------------
# Specs (output of action execution)
# -----------------------------------------------------------------------------


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
    """Execute a move action, producing a spec."""
    return MoveSpec(
        destination=action.destination,
        task_ids=task_ids,
    )


def execute_delete_action(
    action: DeleteAction, task_ids: list[str], ctx: ActionContext
) -> DeleteSpec:
    """Execute a delete action, producing a spec."""
    return DeleteSpec(task_ids=task_ids)


def execute_collate_action(action: CollateAction, ctx: ActionContext) -> CollateSpec:
    """Execute a collate action, producing a spec."""
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
