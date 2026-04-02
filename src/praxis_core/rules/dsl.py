"""
Rules DSL: Human-readable YAML format for rules.

File format uses YAML documents (separated by ---) to allow multiple rules:

    rule:
      name: Overdue Penalty
      description: Overdue tasks have maximum urgency plus penalty
      priority: 110

      when:
        - due_date:
            overdue: true

      then:
        - urgency: min(15, 10 + days_overdue)
    ---
    rule:
      name: Morning Focus
      ...

Condition syntax (human-friendly):
    - time: 08:00 to 12:00           → TIME_WINDOW
    - day: monday, wednesday, friday  → DAY_OF_WEEK
    - tagged: deep-work               → TAG_MATCH (has)
    - not_tagged: work                → TAG_MATCH (missing)
    - priority: <id>                  → PRIORITY_MATCH
    - priority_type: value            → PRIORITY_MATCH
    - due_date:
        has_due_date: true
        overdue: true
        within_hours: 24
    - stale: 3 days                   → STALENESS (>= 3 days)
    - property:
        assigned_to: me
        status: queued

Effect syntax:
    - aptness: * 1.5                  → multiply
    - urgency: + 5                    → add
    - importance: = 10                → set
    - urgency: min(15, 10 + days)     → formula
"""

import re
import yaml
from typing import Any

from praxis_core.model.rules import (
    Rule,
    RuleCondition,
    RuleEffect,
    ConditionType,
    EffectTarget,
    EffectOperator,
)


class DSLParseError(Exception):
    """Error parsing rule DSL."""
    pass


# -----------------------------------------------------------------------------
# Condition Parsing
# -----------------------------------------------------------------------------

def _parse_condition(key: str, value: Any) -> RuleCondition:
    """Parse a single condition from DSL format."""

    # time: 08:00 to 12:00
    if key == "time":
        if isinstance(value, str) and " to " in value:
            start, end = value.split(" to ", 1)
            return RuleCondition(
                type=ConditionType.TIME_WINDOW,
                params={"start": start.strip(), "end": end.strip()}
            )
        raise DSLParseError(f"Invalid time format: {value}. Expected 'HH:MM to HH:MM'")

    # day: monday, wednesday, friday
    if key == "day":
        if isinstance(value, str):
            days = [d.strip().lower() for d in value.split(",")]
        elif isinstance(value, list):
            days = [d.lower() for d in value]
        else:
            raise DSLParseError(f"Invalid day format: {value}")
        return RuleCondition(
            type=ConditionType.DAY_OF_WEEK,
            params={"days": days}
        )

    # tagged: deep-work
    if key == "tagged":
        return RuleCondition(
            type=ConditionType.TAG_MATCH,
            params={"tag": str(value), "operator": "has"}
        )

    # not_tagged: work
    if key == "not_tagged":
        return RuleCondition(
            type=ConditionType.TAG_MATCH,
            params={"tag": str(value), "operator": "missing"}
        )

    # priority: <id>
    if key == "priority":
        return RuleCondition(
            type=ConditionType.PRIORITY_MATCH,
            params={"priority_id": str(value)}
        )

    # priority_type: value
    if key == "priority_type":
        return RuleCondition(
            type=ConditionType.PRIORITY_MATCH,
            params={"priority_type": str(value)}
        )

    # due_date: {overdue: true, ...}
    if key == "due_date":
        if not isinstance(value, dict):
            raise DSLParseError(f"due_date must be a mapping, got: {value}")
        params = {}
        if "has_due_date" in value:
            params["has_due_date"] = bool(value["has_due_date"])
        if "overdue" in value:
            params["overdue"] = bool(value["overdue"])
        if "within_hours" in value:
            params["within_hours"] = float(value["within_hours"])
        return RuleCondition(
            type=ConditionType.DUE_DATE_PROXIMITY,
            params=params
        )

    # stale: 3 days
    if key == "stale":
        if isinstance(value, str):
            match = re.match(r"(\d+)\s*days?", value)
            if match:
                days = int(match.group(1))
                return RuleCondition(
                    type=ConditionType.STALENESS,
                    params={"days_untouched": days, "operator": "gte"}
                )
        elif isinstance(value, (int, float)):
            return RuleCondition(
                type=ConditionType.STALENESS,
                params={"days_untouched": float(value), "operator": "gte"}
            )
        raise DSLParseError(f"Invalid stale format: {value}. Expected 'N days' or number")

    # property: {assigned_to: me, status: queued}
    if key == "property":
        if not isinstance(value, dict):
            raise DSLParseError(f"property must be a mapping, got: {value}")
        # Return first property as condition (multiple properties = multiple conditions)
        for prop, prop_value in value.items():
            return RuleCondition(
                type=ConditionType.TASK_PROPERTY,
                params={"property": prop, "value": prop_value}
            )
        raise DSLParseError("property condition requires at least one property")

    raise DSLParseError(f"Unknown condition type: {key}")


def _parse_conditions(when_list: list) -> list[RuleCondition]:
    """Parse the 'when' block into conditions."""
    conditions = []
    for item in when_list:
        if isinstance(item, dict):
            for key, value in item.items():
                conditions.append(_parse_condition(key, value))
        else:
            raise DSLParseError(f"Condition must be a mapping, got: {item}")
    return conditions


# -----------------------------------------------------------------------------
# Effect Parsing
# -----------------------------------------------------------------------------

# Pattern for operator shorthand: "* 1.5", "+ 5", "= 10"
_OPERATOR_PATTERN = re.compile(r"^([*+=])\s*(.+)$")


def _parse_effect(key: str, value: Any) -> RuleEffect:
    """Parse a single effect from DSL format."""

    # Validate target
    try:
        target = EffectTarget(key)
    except ValueError:
        raise DSLParseError(f"Unknown effect target: {key}. Expected: aptness, urgency, importance")

    value_str = str(value).strip()

    # Check for operator shorthand
    match = _OPERATOR_PATTERN.match(value_str)
    if match:
        op_char, operand = match.groups()
        operator = {
            "*": EffectOperator.MULTIPLY,
            "+": EffectOperator.ADD,
            "=": EffectOperator.SET,
        }[op_char]

        try:
            numeric_value = float(operand)
            return RuleEffect(
                target=target,
                operator=operator,
                value=numeric_value,
            )
        except ValueError:
            # If not numeric, treat as formula
            return RuleEffect(
                target=target,
                operator=EffectOperator.FORMULA,
                formula=operand,
            )

    # Otherwise, treat as formula
    return RuleEffect(
        target=target,
        operator=EffectOperator.FORMULA,
        formula=value_str,
    )


def _parse_effects(then_list: list) -> list[RuleEffect]:
    """Parse the 'then' block into effects."""
    effects = []
    for item in then_list:
        if isinstance(item, dict):
            for key, value in item.items():
                effects.append(_parse_effect(key, value))
        else:
            raise DSLParseError(f"Effect must be a mapping, got: {item}")
    return effects


# -----------------------------------------------------------------------------
# Rule Parsing
# -----------------------------------------------------------------------------

def _parse_rule_dict(rule_dict: dict) -> Rule:
    """Parse a single rule from its dict representation."""
    if "name" not in rule_dict:
        raise DSLParseError("Rule must have a 'name' field")

    name = rule_dict["name"]
    description = rule_dict.get("description")
    priority = rule_dict.get("priority", 0)
    enabled = rule_dict.get("enabled", True)

    # Parse conditions
    when_block = rule_dict.get("when", [])
    if not isinstance(when_block, list):
        raise DSLParseError("'when' must be a list of conditions")
    conditions = _parse_conditions(when_block)

    # Parse effects
    then_block = rule_dict.get("then", [])
    if not isinstance(then_block, list):
        raise DSLParseError("'then' must be a list of effects")
    effects = _parse_effects(then_block)

    if not effects:
        raise DSLParseError("Rule must have at least one effect in 'then' block")

    return Rule(
        id="",  # Will be assigned on import
        name=name,
        description=description,
        priority=priority,
        enabled=enabled,
        conditions=conditions,
        effects=effects,
    )


def parse_rules(yaml_content: str) -> list[Rule]:
    """
    Parse rules from YAML content.

    Supports both single and multi-document YAML files.
    Each document should have a 'rule:' key containing the rule definition.
    """
    rules = []

    try:
        documents = list(yaml.safe_load_all(yaml_content))
    except yaml.YAMLError as e:
        raise DSLParseError(f"Invalid YAML: {e}")

    for doc in documents:
        if doc is None:
            continue

        if not isinstance(doc, dict):
            raise DSLParseError(f"Document must be a mapping, got: {type(doc)}")

        if "rule" not in doc:
            raise DSLParseError("Document must have a 'rule' key")

        rule_dict = doc["rule"]
        if not isinstance(rule_dict, dict):
            raise DSLParseError("'rule' must be a mapping")

        rules.append(_parse_rule_dict(rule_dict))

    return rules


# -----------------------------------------------------------------------------
# Condition Serialization
# -----------------------------------------------------------------------------

def _serialize_condition(condition: RuleCondition) -> dict:
    """Serialize a condition to DSL format."""
    params = condition.params

    match condition.type:
        case ConditionType.TIME_WINDOW:
            start = params.get("start", "00:00")
            end = params.get("end", "23:59")
            return {"time": f"{start} to {end}"}

        case ConditionType.DAY_OF_WEEK:
            days = params.get("days", [])
            return {"day": ", ".join(days)}

        case ConditionType.TAG_MATCH:
            tag = params.get("tag", "")
            operator = params.get("operator", "has")
            if operator == "missing":
                return {"not_tagged": tag}
            return {"tagged": tag}

        case ConditionType.PRIORITY_MATCH:
            if "priority_id" in params:
                return {"priority": params["priority_id"]}
            if "priority_type" in params:
                return {"priority_type": params["priority_type"]}
            return {"priority": None}

        case ConditionType.DUE_DATE_PROXIMITY:
            # Only include non-None params
            due_params = {}
            if params.get("has_due_date") is not None:
                due_params["has_due_date"] = params["has_due_date"]
            if params.get("overdue") is not None:
                due_params["overdue"] = params["overdue"]
            if params.get("within_hours") is not None:
                due_params["within_hours"] = params["within_hours"]
            return {"due_date": due_params}

        case ConditionType.STALENESS:
            days = params.get("days_untouched", 0)
            return {"stale": f"{int(days)} days"}

        case ConditionType.TASK_PROPERTY:
            prop = params.get("property", "")
            value = params.get("value", "")
            return {"property": {prop: value}}

        case _:
            # Fallback: use raw params
            return {condition.type.value: params}


# -----------------------------------------------------------------------------
# Effect Serialization
# -----------------------------------------------------------------------------

def _serialize_effect(effect: RuleEffect) -> dict:
    """Serialize an effect to DSL format."""
    target = effect.target.value

    if effect.operator == EffectOperator.FORMULA:
        return {target: effect.formula}

    # Use operator shorthand
    op_char = {
        EffectOperator.MULTIPLY: "*",
        EffectOperator.ADD: "+",
        EffectOperator.SET: "=",
    }.get(effect.operator, "=")

    return {target: f"{op_char} {effect.value}"}


# -----------------------------------------------------------------------------
# Rule Serialization
# -----------------------------------------------------------------------------

def serialize_rules(rules: list[Rule]) -> str:
    """
    Serialize rules to YAML content.

    Each rule becomes a separate YAML document with a 'rule:' key.
    """
    documents = []

    for rule in rules:
        rule_dict = {
            "name": rule.name,
        }

        if rule.description:
            rule_dict["description"] = rule.description

        if rule.priority != 0:
            rule_dict["priority"] = rule.priority

        if not rule.enabled:
            rule_dict["enabled"] = False

        if rule.conditions:
            rule_dict["when"] = [_serialize_condition(c) for c in rule.conditions]

        if rule.effects:
            rule_dict["then"] = [_serialize_effect(e) for e in rule.effects]

        documents.append({"rule": rule_dict})

    # Serialize each document separately and join with ---
    yaml_parts = []
    for doc in documents:
        yaml_str = yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)
        yaml_parts.append(yaml_str.rstrip())

    return "\n---\n".join(yaml_parts)


def serialize_rule(rule: Rule) -> str:
    """Serialize a single rule to YAML."""
    return serialize_rules([rule])
