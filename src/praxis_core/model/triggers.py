"""Trigger models for automated task generation."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from .rules import RuleCondition  # Reuse conditions from Rules


class TriggerEventType(StrEnum):
    """Types of events that can fire a trigger."""
    # Time events
    SCHEDULE = "schedule"  # {interval: "daily", at: "08:00", day: "monday"}

    # Entity events
    PRIORITY_COMPLETED = "priority_completed"  # {priority_id: "x"} or {priority_type: "goal"}
    TASK_COMPLETED = "task_completed"  # {priority_id: "x"} or {tag: "errand"}
    TASK_CREATED = "task_created"  # {priority_id: "x"} or {tag: "x"}
    PRIORITY_STATUS_CHANGED = "priority_status_changed"  # {to_status: "active"}


class TriggerActionType(StrEnum):
    """Types of actions a trigger can perform."""
    CREATE_TASK = "create_task"  # Create a single task from template
    COLLATE_TASKS = "collate_tasks"  # Gather matching tasks into batch task


class ScheduleInterval(StrEnum):
    """Common schedule intervals."""
    DAILY = "daily"
    WEEKLY = "weekly"
    WEEKDAYS = "weekdays"  # Mon-Fri
    TWICE_DAILY = "2x_daily"
    EVERY_OTHER_DAY = "every_other_day"


@dataclass
class TriggerEvent:
    """The event that fires a trigger."""
    type: TriggerEventType
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": self.type.value, "params": self.params}

    @classmethod
    def from_dict(cls, data: dict) -> "TriggerEvent":
        return cls(
            type=TriggerEventType(data["type"]),
            params=data.get("params", {}),
        )


@dataclass
class TaskTemplate:
    """Template for generating a task."""
    name_pattern: str  # "Daily {{practice.name}}" or "Errands for {{date}}"
    notes_pattern: str | None = None
    due_date_offset: str | None = None  # "+1d", "+8h", "end_of_day", "end_of_week"
    tags: list[str] = field(default_factory=list)
    priority_id: str | None = None  # Override; defaults to trigger's practice
    assign_to_creator: bool = False

    def to_dict(self) -> dict:
        return {
            "name_pattern": self.name_pattern,
            "notes_pattern": self.notes_pattern,
            "due_date_offset": self.due_date_offset,
            "tags": self.tags,
            "priority_id": self.priority_id,
            "assign_to_creator": self.assign_to_creator,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskTemplate":
        return cls(
            name_pattern=data.get("name_pattern", ""),
            notes_pattern=data.get("notes_pattern"),
            due_date_offset=data.get("due_date_offset"),
            tags=data.get("tags", []),
            priority_id=data.get("priority_id"),
            assign_to_creator=data.get("assign_to_creator", False),
        )


@dataclass
class CollateConfig:
    """Configuration for collating tasks into a batch."""
    source_tag: str | None = None  # Tasks with this tag
    source_priority_id: str | None = None  # Tasks under this priority
    batch_name_pattern: str = "{{source_tag}} batch for {{date}}"
    include_completed: bool = False
    mark_source_done: bool = False  # Mark collated tasks as done

    def to_dict(self) -> dict:
        return {
            "source_tag": self.source_tag,
            "source_priority_id": self.source_priority_id,
            "batch_name_pattern": self.batch_name_pattern,
            "include_completed": self.include_completed,
            "mark_source_done": self.mark_source_done,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CollateConfig":
        return cls(
            source_tag=data.get("source_tag"),
            source_priority_id=data.get("source_priority_id"),
            batch_name_pattern=data.get("batch_name_pattern", ""),
            include_completed=data.get("include_completed", False),
            mark_source_done=data.get("mark_source_done", False),
        )


@dataclass
class TriggerAction:
    """An action performed when a trigger fires."""
    type: TriggerActionType
    task_template: TaskTemplate | None = None
    collate_config: CollateConfig | None = None

    def to_dict(self) -> dict:
        d = {"type": self.type.value}
        if self.task_template:
            d["task_template"] = self.task_template.to_dict()
        if self.collate_config:
            d["collate_config"] = self.collate_config.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "TriggerAction":
        return cls(
            type=TriggerActionType(data["type"]),
            task_template=TaskTemplate.from_dict(data["task_template"]) if data.get("task_template") else None,
            collate_config=CollateConfig.from_dict(data["collate_config"]) if data.get("collate_config") else None,
        )


@dataclass
class Trigger:
    """
    A trigger that performs actions when events occur.

    Triggers can be attached to Practices (via practice_id) or standalone.
    Conditions use the same syntax as Rules (reuse RuleCondition).
    """
    id: str
    name: str
    event: TriggerEvent  # What fires this trigger
    conditions: list[RuleCondition]  # Additional filters (reuse from Rules)
    actions: list[TriggerAction]  # What to do when fired

    entity_id: str | None = None  # Owner entity
    practice_id: str | None = None  # If attached to a Practice
    description: str | None = None
    enabled: bool = True
    priority: int = 0  # For ordering when multiple triggers match

    # Execution tracking
    last_fired_at: datetime | None = None
    fire_count: int = 0

    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "practice_id": self.practice_id,
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "priority": self.priority,
            "event": self.event.to_dict(),
            "conditions": [c.to_dict() for c in self.conditions],
            "actions": [a.to_dict() for a in self.actions],
            "last_fired_at": self.last_fired_at.isoformat() if self.last_fired_at else None,
            "fire_count": self.fire_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Trigger":
        return cls(
            id=data["id"],
            entity_id=data.get("entity_id"),
            practice_id=data.get("practice_id"),
            name=data["name"],
            description=data.get("description"),
            enabled=data.get("enabled", True),
            priority=data.get("priority", 0),
            event=TriggerEvent.from_dict(data["event"]),
            conditions=[RuleCondition.from_dict(c) for c in data.get("conditions", [])],
            actions=[TriggerAction.from_dict(a) for a in data.get("actions", [])],
            last_fired_at=datetime.fromisoformat(data["last_fired_at"]) if data.get("last_fired_at") else None,
            fire_count=data.get("fire_count", 0),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
        )
