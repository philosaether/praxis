"""
Triggers DSL: Human-readable YAML format for Practice triggers.

Practice trigger DSL is inline within a Practice definition:

    practice:
      name: Daily LeetCode
      on:
        schedule:
          interval: daily
          at: "17:00"
      create:
        name: "LeetCode practice for {{date}}"
        due: end_of_day
        tags: [practice, coding]
    ---
    practice:
      name: Weekday Standup
      on:
        schedule:
          interval: weekdays
          at: "09:00"
      when:
        - day: monday, tuesday, wednesday, thursday, friday
      create:
        name: "Daily standup"
        due: "+2h"
    ---
    practice:
      name: Weekly Errands Batch
      on:
        schedule:
          interval: weekly
          day: sunday
          at: "09:00"
      collate:
        source_tag: errand
        batch_name: "Errands for week of {{date}}"

Event types:
    - schedule: {interval: daily|weekly|weekdays|2x_daily, at: "HH:MM", day: monday}
    - task_completed: {tag: errand} or {priority_id: xyz}
    - priority_completed: {priority_type: goal}

Action syntax:
    create:
      name: "Task name with {{variables}}"
      notes: "Optional notes"
      due: "+1d" or "end_of_day" or "end_of_week"
      tags: [tag1, tag2]

    collate:
      source_tag: errand
      batch_name: "Batch name with {{date}}"
      mark_source_done: false
"""

import re
import yaml
from typing import Any

from praxis_core.model.practice_triggers import (
    PracticeTrigger,
    TriggerEvent,
    TriggerEventType,
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
# Condition Parsing
# -----------------------------------------------------------------------------

def _parse_condition(key: str, value: Any) -> dict:
    """Parse a single condition from DSL format to dict."""

    # time: 08:00 to 12:00
    if key == "time":
        if isinstance(value, str) and " to " in value:
            start, end = value.split(" to ", 1)
            return {
                "type": "time_window",
                "params": {"start": start.strip(), "end": end.strip()}
            }
        raise DSLParseError(f"Invalid time format: {value}. Expected 'HH:MM to HH:MM'")

    # day: monday, wednesday, friday
    if key == "day":
        if isinstance(value, str):
            days = [d.strip().lower() for d in value.split(",")]
        elif isinstance(value, list):
            days = [d.lower() for d in value]
        else:
            raise DSLParseError(f"Invalid day format: {value}")
        return {"type": "day_of_week", "params": {"days": days}}

    # tagged: deep-work
    if key == "tagged":
        return {"type": "tag_match", "params": {"tag": str(value), "operator": "has"}}

    # not_tagged: work
    if key == "not_tagged":
        return {"type": "tag_match", "params": {"tag": str(value), "operator": "missing"}}

    raise DSLParseError(f"Unknown condition type: {key}")


def _parse_conditions(when_list: list) -> list[dict]:
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


# -----------------------------------------------------------------------------
# Practice Trigger Parsing
# -----------------------------------------------------------------------------

def parse_practice_trigger(yaml_content: str) -> PracticeTrigger:
    """
    Parse a Practice trigger configuration from YAML.

    The YAML should contain the trigger-related fields from a Practice:
    - on: event configuration
    - when: optional conditions
    - create: task template (or collate: for batching)
    """
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        raise DSLParseError(f"Invalid YAML: {e}")

    if not isinstance(data, dict):
        raise DSLParseError(f"Content must be a mapping, got: {type(data)}")

    # Handle 'practice:' wrapper if present
    if "practice" in data:
        data = data["practice"]

    # YAML parses 'on' as boolean True, so check both
    on_block = data.get("on") or data.get(True)
    if on_block is None:
        raise DSLParseError("Trigger must have an 'on' block specifying the event")

    # Parse event
    event = _parse_event(on_block)

    # Parse conditions (optional)
    when_block = data.get("when", [])
    if not isinstance(when_block, list):
        raise DSLParseError("'when' must be a list of conditions")
    conditions = _parse_conditions(when_block)

    # Parse actions
    task_template = None
    collate_config = None

    if "create" in data:
        task_template = _parse_task_template(data["create"])
    if "collate" in data:
        collate_config = _parse_collate_config(data["collate"])

    if task_template is None and collate_config is None:
        raise DSLParseError("Trigger must have a 'create' or 'collate' action")

    enabled = data.get("enabled", True)

    return PracticeTrigger(
        event=event,
        task_template=task_template,
        collate_config=collate_config,
        conditions=conditions,
        enabled=enabled,
    )


# -----------------------------------------------------------------------------
# Condition Serialization
# -----------------------------------------------------------------------------

def _serialize_condition(condition: dict) -> dict:
    """Serialize a condition dict to DSL format."""
    cond_type = condition.get("type", "")
    params = condition.get("params", {})

    if cond_type == "time_window":
        start = params.get("start", "00:00")
        end = params.get("end", "23:59")
        return {"time": f"{start} to {end}"}

    if cond_type == "day_of_week":
        days = params.get("days", [])
        return {"day": ", ".join(days)}

    if cond_type == "tag_match":
        tag = params.get("tag", "")
        operator = params.get("operator", "has")
        if operator == "missing":
            return {"not_tagged": tag}
        return {"tagged": tag}

    # Fallback: return as-is
    return {cond_type: params}


# -----------------------------------------------------------------------------
# Event Serialization
# -----------------------------------------------------------------------------

def _serialize_event(event: TriggerEvent) -> dict:
    """Serialize an event to DSL format."""
    event_type_map = {
        TriggerEventType.SCHEDULE: "schedule",
        TriggerEventType.PRIORITY_COMPLETED: "priority_completed",
        TriggerEventType.TASK_COMPLETED: "task_completed",
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
# Practice Trigger Serialization
# -----------------------------------------------------------------------------

def serialize_practice_trigger(trigger: PracticeTrigger) -> str:
    """
    Serialize a PracticeTrigger to YAML content.

    Returns YAML that can be embedded in a Practice definition.
    """
    trigger_dict = {}

    # Event
    trigger_dict["on"] = _serialize_event(trigger.event)

    # Conditions
    if trigger.conditions:
        trigger_dict["when"] = [_serialize_condition(c) for c in trigger.conditions]

    # Actions
    if trigger.task_template:
        trigger_dict["create"] = _serialize_task_template(trigger.task_template)
    if trigger.collate_config:
        trigger_dict["collate"] = _serialize_collate_config(trigger.collate_config)

    if not trigger.enabled:
        trigger_dict["enabled"] = False

    # Serialize to YAML
    yaml_str = yaml.dump(trigger_dict, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Replace 'on:' with '"on":' to prevent YAML boolean interpretation on re-parse
    yaml_str = yaml_str.replace("\non:", '\n"on":')
    if yaml_str.startswith("on:"):
        yaml_str = '"on":' + yaml_str[3:]

    return yaml_str.rstrip()
