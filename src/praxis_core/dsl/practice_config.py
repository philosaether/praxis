"""
Practice configuration — how actions are bundled with triggers and conditions.

PracticeAction: one trigger + conditions + one or more actions.
PracticeConfig: the full config for a Practice priority.

Single source of truth — consolidates what was previously split between
dsl/actions.py and triggers/models_v2.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .conditions import Condition, ConditionType
from .triggers import Trigger
from .actions import CreateAction, CollateAction


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
    conditions: list[Condition] = field(default_factory=list)
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
    def from_dict(cls, data: dict) -> PracticeAction:
        trigger_data = data.get("trigger") or {}

        trigger = Trigger.from_dict(trigger_data)

        # Parse conditions (when:) - can be in trigger: or at top level
        conditions: list[Condition] = []
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

        return cls(
            trigger=trigger,
            conditions=conditions,
            create=create,
            collate=collate,
        )


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
    def from_dict(cls, data: dict) -> PracticeConfig:
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
    def from_json(cls, json_str: str) -> PracticeConfig:
        """Deserialize from JSON."""
        return cls.from_dict(json.loads(json_str))
