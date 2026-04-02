"""
Triggers DSL: Human-readable YAML format for triggers.

File format uses YAML documents (separated by ---) to allow multiple triggers:

    trigger:
      name: Daily Morning Routine
      practice: practice-123

      on:
        schedule:
          interval: daily
          at: "06:00"

      create:
        name: "Morning routine for {{date}}"
        due: end_of_day
        tags: [routine, morning]
    ---
    trigger:
      name: Weekday Standup

      on:
        schedule:
          interval: daily
          at: "09:00"

      when:
        - day: monday, tuesday, wednesday, thursday, friday

      create:
        name: "Daily standup"
        due: "+2h"
    ---
    trigger:
      name: Weekly Errands Batch

      on:
        schedule:
          interval: weekly
          day: sunday
          at: "09:00"

      collate:
        source_tag: errand
        batch_name: "Errands for week of {{date}}"
    ---
    trigger:
      name: Goal Celebration

      on:
        priority_completed:
          priority_type: goal

      create:
        name: "Write case study: {{event.priority.name}}"
        tags: [case-study, writing]

Event types:
    - schedule: {interval: daily|weekly|weekdays|2x_daily, at: "HH:MM", day: monday}
    - priority_completed: {priority_type: goal} or {priority_id: xyz}
    - task_completed: {tag: errand} or {priority_id: xyz}
    - task_created: {tag: errand} or {priority_id: xyz}

Condition syntax (same as Rules):
    - time: 08:00 to 12:00           → TIME_WINDOW
    - day: monday, wednesday, friday  → DAY_OF_WEEK
    - tagged: deep-work               → TAG_MATCH (has)
    - not_tagged: work                → TAG_MATCH (missing)
    - etc.

Action syntax:
    create:
      name: "Task name with {{variables}}"
      notes: "Optional notes"
      due: "+1d" or "end_of_day" or "end_of_week"
      tags: [tag1, tag2]
      priority_id: optional-override

    collate:
      source_tag: errand
      source_priority_id: optional
      batch_name: "Batch name with {{date}}"
      mark_source_done: false
"""

import re
import yaml
from typing import Any

from praxis_core.model.rules import RuleCondition, ConditionType
from praxis_core.model.triggers import (
    Trigger,
    TriggerEvent,
    TriggerEventType,
    TriggerAction,
    TriggerActionType,
    TaskTemplate,
    CollateConfig,
)


class DSLParseError(Exception):
    """Error parsing trigger DSL."""
    pass


# -----------------------------------------------------------------------------
# Event Parsing
# -----------------------------------------------------------------------------

def _parse_event(on_block: dict) -> TriggerEvent:
    """Parse the 'on' block into a TriggerEvent."""
    if not isinstance(on_block, dict):
        raise DSLParseError(f"'on' must be a mapping, got: {type(on_block)}")

    if len(on_block) != 1:
        raise DSLParseError("'on' must have exactly one event type")

    event_type_str, params = next(iter(on_block.items()))

    # Map DSL event names to TriggerEventType
    event_type_map = {
        "schedule": TriggerEventType.SCHEDULE,
        "priority_completed": TriggerEventType.PRIORITY_COMPLETED,
        "task_completed": TriggerEventType.TASK_COMPLETED,
        "task_created": TriggerEventType.TASK_CREATED,
        "priority_status_changed": TriggerEventType.PRIORITY_STATUS_CHANGED,
    }

    if event_type_str not in event_type_map:
        raise DSLParseError(
            f"Unknown event type: {event_type_str}. "
            f"Expected one of: {', '.join(event_type_map.keys())}"
        )

    event_type = event_type_map[event_type_str]

    # Parse event parameters
    if params is None:
        params = {}
    elif not isinstance(params, dict):
        raise DSLParseError(f"Event parameters must be a mapping, got: {type(params)}")

    return TriggerEvent(type=event_type, params=params)


# -----------------------------------------------------------------------------
# Condition Parsing (reuse from Rules DSL)
# -----------------------------------------------------------------------------

def _parse_condition(key: str, value: Any) -> RuleCondition:
    """Parse a single condition from DSL format (same as Rules)."""

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
# Action Parsing
# -----------------------------------------------------------------------------

def _parse_task_template(create_block: dict) -> TaskTemplate:
    """Parse a 'create' block into a TaskTemplate."""
    if not isinstance(create_block, dict):
        raise DSLParseError(f"'create' must be a mapping, got: {type(create_block)}")

    name_pattern = create_block.get("name", "")
    if not name_pattern:
        raise DSLParseError("'create' block must have a 'name' field")

    return TaskTemplate(
        name_pattern=name_pattern,
        notes_pattern=create_block.get("notes"),
        due_date_offset=create_block.get("due"),
        tags=create_block.get("tags", []),
        priority_id=create_block.get("priority_id"),
        assign_to_creator=create_block.get("assign_to_creator", False),
    )


def _parse_collate_config(collate_block: dict) -> CollateConfig:
    """Parse a 'collate' block into a CollateConfig."""
    if not isinstance(collate_block, dict):
        raise DSLParseError(f"'collate' must be a mapping, got: {type(collate_block)}")

    return CollateConfig(
        source_tag=collate_block.get("source_tag"),
        source_priority_id=collate_block.get("source_priority_id"),
        batch_name_pattern=collate_block.get("batch_name", "Batch for {{date}}"),
        include_completed=collate_block.get("include_completed", False),
        mark_source_done=collate_block.get("mark_source_done", False),
    )


def _parse_actions(trigger_dict: dict) -> list[TriggerAction]:
    """Parse actions from the trigger dict (create and/or collate blocks)."""
    actions = []

    if "create" in trigger_dict:
        template = _parse_task_template(trigger_dict["create"])
        actions.append(TriggerAction(
            type=TriggerActionType.CREATE_TASK,
            task_template=template,
        ))

    if "collate" in trigger_dict:
        config = _parse_collate_config(trigger_dict["collate"])
        actions.append(TriggerAction(
            type=TriggerActionType.COLLATE_TASKS,
            collate_config=config,
        ))

    return actions


# -----------------------------------------------------------------------------
# Trigger Parsing
# -----------------------------------------------------------------------------

def _parse_trigger_dict(trigger_dict: dict) -> Trigger:
    """Parse a single trigger from its dict representation."""
    if "name" not in trigger_dict:
        raise DSLParseError("Trigger must have a 'name' field")

    # YAML parses 'on' as boolean True, so check both
    on_block = trigger_dict.get("on") or trigger_dict.get(True)
    if on_block is None:
        raise DSLParseError("Trigger must have an 'on' block specifying the event")

    name = trigger_dict["name"]
    description = trigger_dict.get("description")
    priority = trigger_dict.get("priority", 0)
    enabled = trigger_dict.get("enabled", True)
    practice_id = trigger_dict.get("practice")

    # Parse event
    event = _parse_event(on_block)

    # Parse conditions (optional)
    when_block = trigger_dict.get("when", [])
    if not isinstance(when_block, list):
        raise DSLParseError("'when' must be a list of conditions")
    conditions = _parse_conditions(when_block)

    # Parse actions
    actions = _parse_actions(trigger_dict)
    if not actions:
        raise DSLParseError("Trigger must have at least one action ('create' or 'collate')")

    return Trigger(
        id="",  # Will be assigned on import
        name=name,
        description=description,
        priority=priority,
        enabled=enabled,
        practice_id=practice_id,
        event=event,
        conditions=conditions,
        actions=actions,
    )


def parse_triggers(yaml_content: str) -> list[Trigger]:
    """
    Parse triggers from YAML content.

    Supports both single and multi-document YAML files.
    Each document should have a 'trigger:' key containing the trigger definition.
    """
    triggers = []

    try:
        documents = list(yaml.safe_load_all(yaml_content))
    except yaml.YAMLError as e:
        raise DSLParseError(f"Invalid YAML: {e}")

    for doc in documents:
        if doc is None:
            continue

        if not isinstance(doc, dict):
            raise DSLParseError(f"Document must be a mapping, got: {type(doc)}")

        if "trigger" not in doc:
            raise DSLParseError("Document must have a 'trigger' key")

        trigger_dict = doc["trigger"]
        if not isinstance(trigger_dict, dict):
            raise DSLParseError("'trigger' must be a mapping")

        triggers.append(_parse_trigger_dict(trigger_dict))

    return triggers


# -----------------------------------------------------------------------------
# Condition Serialization (same as Rules)
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
            return {condition.type.value: params}


# -----------------------------------------------------------------------------
# Event Serialization
# -----------------------------------------------------------------------------

def _serialize_event(event: TriggerEvent) -> dict:
    """Serialize an event to DSL format."""
    event_type_map = {
        TriggerEventType.SCHEDULE: "schedule",
        TriggerEventType.PRIORITY_COMPLETED: "priority_completed",
        TriggerEventType.TASK_COMPLETED: "task_completed",
        TriggerEventType.TASK_CREATED: "task_created",
        TriggerEventType.PRIORITY_STATUS_CHANGED: "priority_status_changed",
    }

    event_key = event_type_map.get(event.type, event.type.value)
    return {event_key: event.params if event.params else None}


# -----------------------------------------------------------------------------
# Action Serialization
# -----------------------------------------------------------------------------

def _serialize_task_template(template: TaskTemplate) -> dict:
    """Serialize a TaskTemplate to DSL format."""
    create_dict = {"name": template.name_pattern}

    if template.notes_pattern:
        create_dict["notes"] = template.notes_pattern
    if template.due_date_offset:
        create_dict["due"] = template.due_date_offset
    if template.tags:
        create_dict["tags"] = template.tags
    if template.priority_id:
        create_dict["priority_id"] = template.priority_id
    if template.assign_to_creator:
        create_dict["assign_to_creator"] = True

    return create_dict


def _serialize_collate_config(config: CollateConfig) -> dict:
    """Serialize a CollateConfig to DSL format."""
    collate_dict = {}

    if config.source_tag:
        collate_dict["source_tag"] = config.source_tag
    if config.source_priority_id:
        collate_dict["source_priority_id"] = config.source_priority_id
    if config.batch_name_pattern:
        collate_dict["batch_name"] = config.batch_name_pattern
    if config.include_completed:
        collate_dict["include_completed"] = True
    if config.mark_source_done:
        collate_dict["mark_source_done"] = True

    return collate_dict


# -----------------------------------------------------------------------------
# Trigger Serialization
# -----------------------------------------------------------------------------

def serialize_triggers(triggers: list[Trigger]) -> str:
    """
    Serialize triggers to YAML content.

    Each trigger becomes a separate YAML document with a 'trigger:' key.
    """
    documents = []

    for trigger in triggers:
        trigger_dict = {
            "name": trigger.name,
        }

        if trigger.description:
            trigger_dict["description"] = trigger.description

        if trigger.priority != 0:
            trigger_dict["priority"] = trigger.priority

        if not trigger.enabled:
            trigger_dict["enabled"] = False

        if trigger.practice_id:
            trigger_dict["practice"] = trigger.practice_id

        # Event
        trigger_dict["on"] = _serialize_event(trigger.event)

        # Conditions
        if trigger.conditions:
            trigger_dict["when"] = [_serialize_condition(c) for c in trigger.conditions]

        # Actions
        for action in trigger.actions:
            if action.type == TriggerActionType.CREATE_TASK and action.task_template:
                trigger_dict["create"] = _serialize_task_template(action.task_template)
            elif action.type == TriggerActionType.COLLATE_TASKS and action.collate_config:
                trigger_dict["collate"] = _serialize_collate_config(action.collate_config)

        documents.append({"trigger": trigger_dict})

    # Serialize each document separately and join with ---
    # Note: We need to quote 'on' as it's a YAML reserved word (parsed as True)
    yaml_parts = []
    for doc in documents:
        yaml_str = yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)
        # Replace 'on:' with '"on":' to prevent YAML boolean interpretation
        yaml_str = yaml_str.replace("\n  on:", '\n  "on":')
        yaml_parts.append(yaml_str.rstrip())

    return "\n---\n".join(yaml_parts)


def serialize_trigger(trigger: Trigger) -> str:
    """Serialize a single trigger to YAML."""
    return serialize_triggers([trigger])
