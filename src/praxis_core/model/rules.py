"""Rule models for the aptness engine."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ConditionType(StrEnum):
    """Types of conditions that can trigger a rule."""
    TIME_WINDOW = "time_window"           # {start: "08:00", end: "12:00"}
    DAY_OF_WEEK = "day_of_week"           # {days: ["saturday", "sunday"]}
    TAG_MATCH = "tag_match"               # {tag: "deep-work", operator: "has|missing"}
    PRIORITY_MATCH = "priority_match"     # {priority_id: "x"} or {priority_type: "practice"}
    PRIORITY_ANCESTOR = "priority_ancestor"  # {ancestor_id: "x"} - task under this subtree
    DUE_DATE_PROXIMITY = "due_date_proximity"  # {within_hours: 24} or {overdue: true}
    STALENESS = "staleness"               # {days_untouched: 5, operator: "gte"}
    RECENCY = "recency"                   # {tag: "x", days_since: 2, operator: "gte"}
    ENGAGEMENT_RECENCY = "engagement_recency"  # {days: 7, operator: "gte"} - priority not engaged
    TASK_PROPERTY = "task_property"       # {property: "assigned_to", value: "me"}


class EffectTarget(StrEnum):
    """What part of the score the effect modifies."""
    APTNESS = "aptness"
    URGENCY = "urgency"
    IMPORTANCE = "importance"


class EffectOperator(StrEnum):
    """How the effect modifies the target."""
    MULTIPLY = "multiply"   # value is multiplier (e.g., 1.5 = +50%)
    ADD = "add"             # value is addend (e.g., 3 = +3)
    SET = "set"             # value replaces current (e.g., 10 = set to 10)
    FORMULA = "formula"     # formula string evaluated with variables


@dataclass
class RuleCondition:
    """A condition that must be met for a rule to fire."""
    type: ConditionType
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": self.type.value, "params": self.params}

    @classmethod
    def from_dict(cls, data: dict) -> "RuleCondition":
        return cls(
            type=ConditionType(data["type"]),
            params=data.get("params", {}),
        )


@dataclass
class RuleEffect:
    """An effect applied when a rule's conditions are met."""
    target: EffectTarget
    operator: EffectOperator
    value: float | None = None      # For multiply, add, set
    formula: str | None = None      # For formula operator

    def to_dict(self) -> dict:
        d = {"target": self.target.value, "operator": self.operator.value}
        if self.operator == EffectOperator.FORMULA:
            d["formula"] = self.formula
        else:
            d["value"] = self.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "RuleEffect":
        return cls(
            target=EffectTarget(data["target"]),
            operator=EffectOperator(data["operator"]),
            value=data.get("value"),
            formula=data.get("formula"),
        )


@dataclass
class Rule:
    """
    A rule that modifies task scoring based on conditions.

    Rules are evaluated in priority order (higher priority first).
    All conditions must match (AND logic) for effects to apply.
    Multiple rules can affect the same task - effects combine:
    - Aptness: multiplicative
    - Urgency/Importance: additive
    """
    id: str
    name: str
    conditions: list[RuleCondition]
    effects: list[RuleEffect]
    entity_id: str | None = None      # Owner entity (None = system rule)
    description: str | None = None
    enabled: bool = True
    priority: int = 0                  # Higher = evaluated first
    is_system: bool = False            # Built-in rule (not user-editable)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "priority": self.priority,
            "conditions": [c.to_dict() for c in self.conditions],
            "effects": [e.to_dict() for e in self.effects],
            "is_system": self.is_system,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Rule":
        return cls(
            id=data["id"],
            entity_id=data.get("entity_id"),
            name=data["name"],
            description=data.get("description"),
            enabled=data.get("enabled", True),
            priority=data.get("priority", 0),
            conditions=[RuleCondition.from_dict(c) for c in data.get("conditions", [])],
            effects=[RuleEffect.from_dict(e) for e in data.get("effects", [])],
            is_system=data.get("is_system", False),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
        )
