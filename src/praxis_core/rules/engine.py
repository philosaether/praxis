"""Rules engine: evaluates rules and modifies task scores."""

from dataclasses import dataclass
from datetime import datetime, time

from simpleeval import simple_eval, EvalWithCompoundTypes

from praxis_core.model.rules import (
    Rule,
    RuleCondition,
    RuleEffect,
    ConditionType,
    EffectTarget,
    EffectOperator,
)
from praxis_core.model import Task


@dataclass
class RuleContext:
    """
    Context for rule evaluation.

    Contains all the variables available for conditions and formulas.
    """
    task: Task
    now: datetime

    # Computed variables (populated during evaluation)
    days_until_due: float | None = None
    hours_until_due: float | None = None
    days_overdue: float = 0.0
    days_since_touched: float = 0.0
    days_since_created: float = 0.0
    days_since_tag_completion: float | None = None  # For recency conditions
    priority_depth: int = 0
    task_tags: set[str] | None = None

    # Base scores (set by scoring algorithm before rule evaluation)
    base_importance: float = 0.0
    base_urgency: float = 0.0

    def __post_init__(self):
        """Compute derived variables from task and timestamp."""
        # Due date calculations
        if self.task.due_date:
            delta = self.task.due_date - self.now
            total_hours = delta.total_seconds() / 3600
            self.hours_until_due = total_hours
            self.days_until_due = total_hours / 24

            if self.days_until_due < 0:
                self.days_overdue = abs(self.days_until_due)
                self.days_until_due = 0
                self.hours_until_due = 0

        # Staleness: days since last update (use created_at as proxy for now)
        # TODO: Add updated_at to Task model for accurate staleness
        if self.task.created_at:
            delta = self.now - self.task.created_at
            self.days_since_created = delta.total_seconds() / 86400
            # Use created_at as proxy for touched until we have updated_at
            self.days_since_touched = self.days_since_created

    def get_formula_variables(self) -> dict:
        """Return variables available for formula evaluation."""
        return {
            "days_until_due": self.days_until_due or 0,
            "hours_until_due": self.hours_until_due or 0,
            "days_overdue": self.days_overdue,
            "days_since_touched": self.days_since_touched,
            "days_since_created": self.days_since_created,
            "days_since_tag_completion": self.days_since_tag_completion or 0,
            "priority_depth": self.priority_depth,
            "base_importance": self.base_importance,
            "base_urgency": self.base_urgency,
        }


@dataclass
class RuleResult:
    """Result of applying rules to a task."""
    aptness: float = 1.0
    urgency_modifier: float = 0.0
    importance_modifier: float = 0.0
    matched_rules: list[str] | None = None  # Rule IDs that matched

    def __post_init__(self):
        if self.matched_rules is None:
            self.matched_rules = []


def evaluate_condition(condition: RuleCondition, ctx: RuleContext) -> bool:
    """
    Evaluate a single condition against the context.

    Returns True if the condition matches, False otherwise.
    """
    params = condition.params

    match condition.type:
        case ConditionType.TIME_WINDOW:
            start_str = params.get("start", "00:00")
            end_str = params.get("end", "23:59")
            start = time.fromisoformat(start_str)
            end = time.fromisoformat(end_str)
            current_time = ctx.now.time()

            # Handle overnight windows (e.g., 22:00 to 06:00)
            if start <= end:
                return start <= current_time <= end
            else:
                return current_time >= start or current_time <= end

        case ConditionType.DAY_OF_WEEK:
            days = params.get("days", [])
            current_day = ctx.now.strftime("%A").lower()
            return current_day in [d.lower() for d in days]

        case ConditionType.TAG_MATCH:
            tag = params.get("tag", "")
            operator = params.get("operator", "has")
            task_tags = ctx.task_tags or set()

            if operator == "has":
                return tag.lower() in {t.lower() for t in task_tags}
            elif operator == "missing":
                return tag.lower() not in {t.lower() for t in task_tags}
            return False

        case ConditionType.PRIORITY_MATCH:
            priority_id = params.get("priority_id")
            priority_type = params.get("priority_type")

            if priority_id:
                return ctx.task.priority_id == priority_id
            if priority_type:
                return ctx.task.priority_type == priority_type
            return False

        case ConditionType.PRIORITY_ANCESTOR:
            # TODO: Implement with graph traversal
            # For now, just check direct parent
            ancestor_id = params.get("ancestor_id")
            return ctx.task.priority_id == ancestor_id

        case ConditionType.DUE_DATE_PROXIMITY:
            has_due_date = params.get("has_due_date")
            within_hours = params.get("within_hours")
            overdue = params.get("overdue")

            if has_due_date is not None:
                if has_due_date and ctx.task.due_date is None:
                    return False
                if not has_due_date and ctx.task.due_date is not None:
                    return False

            if overdue is not None:
                if overdue and ctx.days_overdue <= 0:
                    return False
                if not overdue and ctx.days_overdue > 0:
                    return False

            if within_hours is not None:
                if ctx.hours_until_due is None:
                    return False
                return ctx.hours_until_due <= within_hours

            return True  # If we get here, all specified conditions passed

        case ConditionType.STALENESS:
            days_untouched = params.get("days_untouched", 0)
            operator = params.get("operator", "gte")

            match operator:
                case "gte":
                    return ctx.days_since_touched >= days_untouched
                case "lte":
                    return ctx.days_since_touched <= days_untouched
                case "eq":
                    return abs(ctx.days_since_touched - days_untouched) < 0.5
                case _:
                    return False

        case ConditionType.RECENCY:
            # TODO: Implement with completion history lookup
            # For now, return False (condition doesn't match)
            return False

        case ConditionType.TASK_PROPERTY:
            prop = params.get("property")
            value = params.get("value")

            if prop == "assigned_to":
                if value == "me":
                    # TODO: Need current user context
                    return ctx.task.assigned_to is not None
                return str(ctx.task.assigned_to) == str(value)
            elif prop == "status":
                return ctx.task.status.value == value
            return False

        case _:
            return False


def apply_effect(effect: RuleEffect, result: RuleResult, ctx: RuleContext) -> None:
    """
    Apply a single effect to the result.

    Modifies result in place.
    """
    # Get the value to apply
    if effect.operator == EffectOperator.FORMULA:
        if not effect.formula:
            return
        try:
            # Use simpleeval for safe formula evaluation
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
                    # For formulas, treat result as absolute aptness modifier
                    result.aptness *= max(0, value / 10) if value > 0 else 0

        case EffectTarget.URGENCY:
            match effect.operator:
                case EffectOperator.MULTIPLY:
                    # Multiply applies to base urgency conceptually
                    result.urgency_modifier += ctx.base_urgency * (value - 1)
                case EffectOperator.ADD:
                    result.urgency_modifier += value
                case EffectOperator.SET:
                    # Set means replace base urgency
                    result.urgency_modifier = value - ctx.base_urgency
                case EffectOperator.FORMULA:
                    # Formula result is treated as additive urgency
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


def evaluate_rules(
    rules: list[Rule],
    task: Task,
    task_tags: set[str] | None = None,
    base_importance: float = 0.0,
    base_urgency: float = 0.0,
    priority_depth: int = 0,
    now: datetime | None = None,
) -> RuleResult:
    """
    Evaluate all rules against a task and return combined result.

    Args:
        rules: List of rules to evaluate, in priority order (highest first)
        task: The task to evaluate
        task_tags: Set of tag names on the task
        base_importance: Pre-rule importance score
        base_urgency: Pre-rule urgency score
        priority_depth: Depth of task's priority in the tree
        now: Current timestamp (defaults to now)

    Returns:
        RuleResult with combined aptness modifier and urgency/importance adjustments
    """
    if now is None:
        now = datetime.now()

    ctx = RuleContext(
        task=task,
        now=now,
        task_tags=task_tags or set(),
        base_importance=base_importance,
        base_urgency=base_urgency,
        priority_depth=priority_depth,
    )

    result = RuleResult()

    for rule in rules:
        if not rule.enabled:
            continue

        # Check if all conditions match (AND logic)
        if not all(evaluate_condition(c, ctx) for c in rule.conditions):
            continue

        # All conditions matched - apply effects
        result.matched_rules.append(rule.id)

        for effect in rule.effects:
            apply_effect(effect, result, ctx)

    # Floor aptness at 0
    result.aptness = max(0.0, result.aptness)

    return result
