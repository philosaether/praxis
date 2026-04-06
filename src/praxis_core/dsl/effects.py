"""
Scoring effects for Rules.

Effects modify task scores during the ranking pass:
- aptness: multiplicative (0.0 - 1.0)
- urgency: additive (0 - 15)
- importance: additive (0 - 10)

Effects are pure — they don't modify database state.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from simpleeval import EvalWithCompoundTypes


class EffectTarget(StrEnum):
    """What part of the score the effect modifies."""

    APTNESS = "aptness"
    URGENCY = "urgency"
    IMPORTANCE = "importance"


class EffectOperator(StrEnum):
    """How the effect modifies the target."""

    MULTIPLY = "multiply"  # value is multiplier (e.g., 1.5 = +50%)
    ADD = "add"  # value is addend (e.g., 3 = +3)
    SET = "set"  # value replaces current (e.g., 10 = set to 10)
    FORMULA = "formula"  # formula string evaluated with variables


@dataclass
class Effect:
    """
    A scoring effect applied when rule conditions match.

    Attributes:
        target: Which score component to modify
        operator: How to modify it
        value: Numeric value for multiply/add/set
        formula: Expression string for formula operator
    """

    target: EffectTarget
    operator: EffectOperator
    value: float | None = None
    formula: str | None = None

    def to_dict(self) -> dict:
        result = {"target": self.target.value, "operator": self.operator.value}
        if self.operator == EffectOperator.FORMULA:
            result["formula"] = self.formula
        else:
            result["value"] = self.value
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "Effect":
        return cls(
            target=EffectTarget(data["target"]),
            operator=EffectOperator(data["operator"]),
            value=data.get("value"),
            formula=data.get("formula"),
        )


@dataclass
class EffectContext:
    """
    Context for effect evaluation.

    Provides variables available for formula evaluation.
    """

    # Base scores (before effects)
    base_aptness: float = 1.0
    base_urgency: float = 0.0
    base_importance: float = 0.0

    # Task-derived variables
    days_until_due: float | None = None
    hours_until_due: float | None = None
    days_overdue: float = 0.0
    days_since_touched: float = 0.0
    days_since_created: float = 0.0
    priority_depth: int = 0

    def get_formula_variables(self) -> dict[str, Any]:
        """Return variables available for formula evaluation."""
        return {
            "base_aptness": self.base_aptness,
            "base_urgency": self.base_urgency,
            "base_importance": self.base_importance,
            "days_until_due": self.days_until_due or 0,
            "hours_until_due": self.hours_until_due or 0,
            "days_overdue": self.days_overdue,
            "days_since_touched": self.days_since_touched,
            "days_since_created": self.days_since_created,
            "priority_depth": self.priority_depth,
        }


@dataclass
class EffectResult:
    """
    Accumulated result of applying effects.

    Aptness is multiplicative (starts at 1.0).
    Urgency/importance are additive modifiers (start at 0.0).
    """

    aptness: float = 1.0
    urgency_modifier: float = 0.0
    importance_modifier: float = 0.0
    matched_rules: list[str] = field(default_factory=list)

    def final_urgency(self, base: float) -> float:
        """Calculate final urgency from base + modifier."""
        return base + self.urgency_modifier

    def final_importance(self, base: float) -> float:
        """Calculate final importance from base + modifier."""
        return base + self.importance_modifier


def apply_effect(
    effect: Effect,
    result: EffectResult,
    ctx: EffectContext,
) -> None:
    """
    Apply a single effect to the result.

    Modifies result in place.
    """
    # Get the value to apply
    if effect.operator == EffectOperator.FORMULA:
        if not effect.formula:
            return
        try:
            evaluator = EvalWithCompoundTypes(
                names=ctx.get_formula_variables(),
                functions={
                    "min": min,
                    "max": max,
                    "abs": abs,
                },
            )
            value = evaluator.eval(effect.formula)
        except Exception:
            # If formula evaluation fails, skip this effect
            return
    else:
        value = effect.value
        if value is None:
            return

    # Apply the value based on target and operator
    match effect.target:
        case EffectTarget.APTNESS:
            match effect.operator:
                case EffectOperator.MULTIPLY:
                    result.aptness *= value
                case EffectOperator.ADD:
                    result.aptness += value
                case EffectOperator.SET:
                    result.aptness = value
                case EffectOperator.FORMULA:
                    # Formula result treated as aptness multiplier
                    result.aptness *= max(0, value / 10) if value > 0 else 0

        case EffectTarget.URGENCY:
            match effect.operator:
                case EffectOperator.MULTIPLY:
                    # Multiply applies to base urgency
                    result.urgency_modifier += ctx.base_urgency * (value - 1)
                case EffectOperator.ADD:
                    result.urgency_modifier += value
                case EffectOperator.SET:
                    # Set means replace base urgency
                    result.urgency_modifier = value - ctx.base_urgency
                case EffectOperator.FORMULA:
                    # Formula result is additive urgency
                    result.urgency_modifier += value

        case EffectTarget.IMPORTANCE:
            match effect.operator:
                case EffectOperator.MULTIPLY:
                    result.importance_modifier += ctx.base_importance * (value - 1)
                case EffectOperator.ADD:
                    result.importance_modifier += value
                case EffectOperator.SET:
                    result.importance_modifier = value - ctx.base_importance
                case EffectOperator.FORMULA:
                    result.importance_modifier += value


def apply_effects(
    effects: list[Effect],
    ctx: EffectContext,
    result: EffectResult | None = None,
) -> EffectResult:
    """
    Apply multiple effects to a result.

    Args:
        effects: List of effects to apply
        ctx: Context with base scores and formula variables
        result: Existing result to modify (creates new if None)

    Returns:
        EffectResult with accumulated modifications
    """
    if result is None:
        result = EffectResult()

    for effect in effects:
        apply_effect(effect, result, ctx)

    # Floor aptness at 0
    result.aptness = max(0.0, result.aptness)

    return result
