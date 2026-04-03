"""
DSL v2 models for Practice actions.

These models support the new multi-action Practice structure:
- Multiple actions per Practice
- Polymorphic create (task, priority, hierarchy)
- Enhanced collation with filtering
- Custom cadence intervals
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
import json


# -----------------------------------------------------------------------------
# Schedule / Event Types
# -----------------------------------------------------------------------------

class ScheduleInterval(StrEnum):
    """Named schedule intervals."""
    DAILY = "daily"
    WEEKDAYS = "weekdays"
    WEEKLY = "weekly"
    TWICE_DAILY = "2x_daily"
    # Day names are also valid (monday, tuesday, etc.) - handled in parser


class EventType(StrEnum):
    """Types of events that can trigger an action."""
    SCHEDULE = "schedule"
    TASK_COMPLETION = "task_completion"
    PRIORITY_COMPLETION = "priority_completion"


# -----------------------------------------------------------------------------
# Schedule Configuration
# -----------------------------------------------------------------------------

@dataclass
class Cadence:
    """Custom cadence for intervals like 'every 14 days'."""
    frequency: str  # e.g., "14d", "2w"
    beginning: str  # Anchor date, e.g., "2026-04-03"
    at: str = "00:00"  # Time of day

    def to_dict(self) -> dict:
        return {
            "frequency": self.frequency,
            "beginning": self.beginning,
            "at": self.at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Cadence":
        beginning = data["beginning"]
        # YAML may parse date as datetime.date object
        if hasattr(beginning, "isoformat"):
            beginning = beginning.isoformat()
        return cls(
            frequency=data["frequency"],
            beginning=str(beginning),
            at=str(data.get("at", "00:00")),
        )


@dataclass
class Schedule:
    """Schedule configuration for time-based triggers."""
    interval: str | Cadence  # "daily", "weekdays", "monday", or Cadence
    at: str | list[str] | None = None  # "09:00" or ["08:00", "14:00"]
    day: str | None = None  # For weekly: "monday", etc.

    def to_dict(self) -> dict:
        result = {}
        if isinstance(self.interval, Cadence):
            result["interval"] = {"cadence": self.interval.to_dict()}
        else:
            result["interval"] = self.interval
        if self.at:
            result["at"] = self.at
        if self.day:
            result["day"] = self.day
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "Schedule":
        interval_data = data.get("interval", "daily")
        if isinstance(interval_data, dict) and "cadence" in interval_data:
            interval = Cadence.from_dict(interval_data["cadence"])
        else:
            interval = interval_data
        return cls(
            interval=interval,
            at=data.get("at"),
            day=data.get("day"),
        )


# -----------------------------------------------------------------------------
# Event Configuration
# -----------------------------------------------------------------------------

@dataclass
class Event:
    """Event configuration (non-schedule triggers)."""
    type: EventType
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": self.type.value, **self.params}

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        if isinstance(data, str):
            # Shorthand: "priority_completion"
            return cls(type=EventType(data))
        type_val = data.pop("type", None)
        return cls(type=EventType(type_val), params=data)


# -----------------------------------------------------------------------------
# Trigger (on:)
# -----------------------------------------------------------------------------

@dataclass
class ActionTrigger:
    """What causes an action to fire (on: block)."""
    schedule: Schedule | None = None
    event: Event | None = None

    def to_dict(self) -> dict:
        if self.schedule:
            return {"schedule": self.schedule.to_dict()}
        if self.event:
            return {"event": self.event.to_dict()}
        return {}

    @classmethod
    def from_dict(cls, data: dict) -> "ActionTrigger":
        # Only extract schedule/event, ignore create/collate/when
        if "schedule" in data:
            return cls(schedule=Schedule.from_dict(data["schedule"]))
        if "event" in data:
            return cls(event=Event.from_dict(data["event"]))
        # Check if schedule data is at top level (without schedule: wrapper)
        if "interval" in data:
            return cls(schedule=Schedule.from_dict(data))
        return cls()


# -----------------------------------------------------------------------------
# Conditions (when:)
# -----------------------------------------------------------------------------

@dataclass
class Condition:
    """A condition that filters when an action executes."""
    type: str  # "event", "capacity", "day", "time"
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": self.type, "params": self.params}

    @classmethod
    def from_dict(cls, data: dict) -> "Condition":
        return cls(type=data["type"], params=data.get("params", {}))


# -----------------------------------------------------------------------------
# Create Templates
# -----------------------------------------------------------------------------

@dataclass
class TaskTemplate:
    """Template for creating a task."""
    name: str
    notes: str | None = None
    due: str | dict | None = None  # "end_of_day" or {"day": "friday", "time": "17:00"}
    tags: list[str] = field(default_factory=list)
    priority_id: str | None = None  # Override parent

    def to_dict(self) -> dict:
        result = {"name": self.name}
        if self.notes:
            result["notes"] = self.notes
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
            notes=data.get("notes"),
            due=data.get("due"),
            tags=data.get("tags", []),
            priority_id=data.get("priority_id"),
        )


@dataclass
class PriorityTemplate:
    """Template for creating a priority (with optional children)."""
    name: str
    type: str = "project"  # goal, project, area, practice
    notes: str | None = None
    due: str | dict | None = None
    tags: list[str] = field(default_factory=list)
    children: list["TaskTemplate | PriorityTemplate"] = field(default_factory=list)

    def to_dict(self) -> dict:
        result = {"name": self.name, "type": self.type}
        if self.notes:
            result["notes"] = self.notes
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
            type=data.get("type", "project"),
            notes=data.get("notes"),
            due=data.get("due"),
            tags=data.get("tags", []),
            children=children,
        )


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
        # Handle both list and single-item formats
        if isinstance(data, dict):
            data = [data]

        items = []
        for item_data in data:
            if "task" in item_data:
                items.append(TaskTemplate.from_dict(item_data["task"]))
            elif "priority" in item_data:
                items.append(PriorityTemplate.from_dict(item_data["priority"]))
            elif "name" in item_data:
                # Legacy/shorthand: infer from structure
                if "type" in item_data or "children" in item_data:
                    items.append(PriorityTemplate.from_dict(item_data))
                else:
                    items.append(TaskTemplate.from_dict(item_data))
        return cls(items=items)


# -----------------------------------------------------------------------------
# Collate Configuration
# -----------------------------------------------------------------------------

@dataclass
class CollateTarget:
    """Target specification for collation."""
    # Shorthand targets
    shorthand: str | None = None  # "children", "descendants", "tagged: X"

    # Complex filtering
    match_any: list[dict] | None = None  # OR conditions
    match_all: list[dict] | None = None  # AND conditions
    exclude: list[dict] | None = None  # NOT conditions

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

        # Handle list format: [{match_any: {...}}, {exclude: {...}}]
        if isinstance(data, list):
            match_any = []
            match_all = []
            exclude = []
            for item in data:
                if "match_any" in item:
                    # match_any value can be a dict (key: value pairs) or list
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

        # Handle dict format: {match_any: [...], exclude: [...]}
        return cls(
            match_any=data.get("match_any"),
            match_all=data.get("match_all"),
            exclude=data.get("exclude"),
        )


@dataclass
class CollateAction:
    """Action that collates existing tasks into a batch."""
    target: CollateTarget
    as_template: TaskTemplate  # The batch task to create

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
# Practice Action
# -----------------------------------------------------------------------------

@dataclass
class PracticeAction:
    """A single action block within a Practice."""
    trigger: ActionTrigger
    conditions: list[Condition] = field(default_factory=list)
    create: CreateAction | None = None
    collate: CollateAction | None = None

    def to_dict(self) -> dict:
        result = {"on": self.trigger.to_dict()}
        if self.conditions:
            result["when"] = {c.type: c.params for c in self.conditions}
        if self.create:
            result["create"] = self.create.to_dict()
        if self.collate:
            result["collate"] = self.collate.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "PracticeAction":
        # The structure is:
        # - on:
        #     schedule: ...
        #     create: ...      # create/collate/when can be inside on:
        #   when: ...          # or at the same level as on:
        #   create: ...

        # YAML parses 'on:' as boolean True, so check both
        on_data = data.get("on") or data.get(True) or {}

        # Parse trigger (schedule or event from on:)
        trigger = ActionTrigger.from_dict(on_data)

        # Parse conditions (when:) - can be in on: or at top level
        conditions = []
        when_data = on_data.get("when", data.get("when", {}))
        if isinstance(when_data, dict):
            for key, value in when_data.items():
                if "." in key:
                    # Dot notation: event.type -> type="event", params from value
                    parts = key.split(".", 1)
                    conditions.append(Condition(
                        type=parts[0],
                        params={parts[1]: value}
                    ))
                else:
                    conditions.append(Condition(type=key, params=value if isinstance(value, dict) else {"value": value}))

        # Parse actions - can be in on: or at top level
        create = None
        collate = None

        create_data = on_data.get("create", data.get("create"))
        if create_data is not None:
            create = CreateAction.from_dict(create_data)

        collate_data = on_data.get("collate", data.get("collate"))
        if collate_data is not None:
            collate = CollateAction.from_dict(collate_data)

        return cls(
            trigger=trigger,
            conditions=conditions,
            create=create,
            collate=collate,
        )


# -----------------------------------------------------------------------------
# Practice (top-level)
# -----------------------------------------------------------------------------

@dataclass
class PracticeConfig:
    """Full Practice configuration with multiple actions."""
    name: str
    description: str | None = None
    parent: str | None = None  # Name reference to parent priority
    tags: list[str] = field(default_factory=list)
    actions: list[PracticeAction] = field(default_factory=list)

    def to_dict(self) -> dict:
        result = {"name": self.name}
        if self.description:
            result["description"] = self.description
        if self.parent:
            result["parent"] = self.parent
        if self.tags:
            result["tags"] = self.tags
        if self.actions:
            result["actions"] = [a.to_dict() for a in self.actions]
        return {"practice": result}

    def to_json(self) -> str:
        """Serialize to JSON for database storage."""
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
            parent=data.get("parent"),
            tags=data.get("tags", []),
            actions=actions,
        )

    @classmethod
    def from_json(cls, json_str: str) -> "PracticeConfig":
        """Deserialize from JSON."""
        return cls.from_dict(json.loads(json_str))
