"""
Render and assemble Practice actions.

Converts between DSL PracticeAction objects, chip-compatible dicts for
templates, and form field values from HTMX submissions.
"""

import json
import re
from datetime import datetime, timedelta
from typing import Any

from praxis_core.dsl import (
    PracticeAction,
    PracticeConfig,
    Schedule,
    Cadence,
    TaskTemplate,
    PriorityTemplate,
)

_ACTION_FIELD_RE = re.compile(r"^action_(\d+)_(.+)$")


def render_schedule_phrase(schedule: Schedule) -> dict:
    """Render a schedule as a phrase with editable chip data.

    Returns:
        dict with 'text' and 'chips' keys
    """
    interval = schedule.interval
    at = schedule.at
    day = schedule.day

    # Handle cadence (custom interval)
    if isinstance(interval, Cadence):
        freq = interval.frequency
        # Build day suffix from stored day value (fallback: derive for weekly)
        day_suffix = ""
        effective_day = day
        if not effective_day and freq.endswith('w') and interval.beginning:
            try:
                dt = datetime.fromisoformat(interval.beginning)
                day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                effective_day = day_names[dt.weekday()]
            except ValueError:
                pass
        if effective_day:
            first_day = effective_day.split(",")[0].strip()
            if first_day == "last":
                day_suffix = " on the last day"
            elif first_day.isdigit():
                n = int(first_day)
                ordinal = f"{n}{'st' if n == 1 else 'nd' if n == 2 else 'rd' if n == 3 else 'th'}"
                day_suffix = f" on the {ordinal}"
            else:
                day_suffix = f" on {first_day.title()}"
        # Parse frequency like "14d" or "2w"
        if freq.endswith('d'):
            num = freq[:-1]
            return {
                "text": f"Every {num} days",
                "chips": [
                    {"type": "cadence", "value": freq, "label": f"every {num} days"}
                ]
            }
        elif freq.endswith('w'):
            num = freq[:-1]
            return {
                "text": f"Every {num} weeks{day_suffix}",
                "chips": [
                    {"type": "cadence", "value": freq, "label": f"every {num} weeks{day_suffix.lower()}"}
                ]
            }
        elif freq.endswith('m'):
            num = freq[:-1]
            return {
                "text": f"Every {num} months{day_suffix}",
                "chips": [
                    {"type": "cadence", "value": freq, "label": f"every {num} months{day_suffix.lower()}"}
                ]
            }
        return {
            "text": f"On cadence ({freq}){day_suffix}",
            "chips": [{"type": "cadence", "value": freq, "label": f"{freq}{day_suffix.lower()}"}]
        }

    # Handle named intervals
    interval_phrases = {
        "daily": "Daily",
        "weekdays": "On weekdays",
        "weekly": "Weekly",
        "2x_daily": "Twice daily",
        # Day names
        "monday": "On Mondays",
        "tuesday": "On Tuesdays",
        "wednesday": "On Wednesdays",
        "thursday": "On Thursdays",
        "friday": "On Fridays",
        "saturday": "On Saturdays",
        "sunday": "On Sundays",
    }

    phrase = interval_phrases.get(interval, f"On {interval}")
    chips = [{"type": "schedule", "value": interval, "label": phrase.lower()}]

    # Add day if specified (for weekly)
    if day and interval == "weekly":
        phrase = f"Weekly on {day.title()}"
        chips[0]["day"] = day

    # Add time if specified
    if at:
        if isinstance(at, list):
            time_str = " and ".join(at)
            phrase += f" at {time_str}"
        else:
            phrase += f" at {at}"
        chips.append({"type": "time", "value": at, "label": f"at {at}"})

    return {"text": phrase, "chips": chips}


def render_due_phrase(due: str | dict | None) -> dict | None:
    """Render a due date specification as a phrase.

    Returns:
        dict with 'text' and 'chip' keys, or None if no due
    """
    if not due:
        return None

    if isinstance(due, str):
        due_phrases = {
            "end_of_day": "due at end of day",
            "end_of_week": "due at end of week",
            "tomorrow": "due tomorrow",
        }
        # Handle offset notation like "+1d", "+2h"
        if due.startswith("+"):
            offset = due[1:]
            if offset.endswith("d"):
                num = offset[:-1]
                phrase = f"due in {num} day{'s' if num != '1' else ''}"
            elif offset.endswith("h"):
                num = offset[:-1]
                phrase = f"due in {num} hour{'s' if num != '1' else ''}"
            else:
                phrase = f"due {due}"
        else:
            phrase = due_phrases.get(due, f"due {due}")

        return {
            "text": phrase,
            "chip": {"type": "due", "value": due, "label": phrase}
        }

    # Complex due spec: {"day": "friday", "time": "17:00"}
    if isinstance(due, dict):
        day = due.get("day", "")
        time = due.get("time", "")
        phrase = f"due {day}"
        if time:
            phrase += f" at {time}"
        return {
            "text": phrase,
            "chip": {"type": "due", "value": due, "label": phrase}
        }

    return None


def render_task_template_phrase(template: TaskTemplate) -> dict:
    """Render a task template as a phrase.

    Returns:
        dict with 'text' and 'chips' keys
    """
    parts = []
    chips = []

    # Task name
    parts.append(f'create a task named "{template.name}"')
    chips.append({"type": "name", "value": template.name, "label": template.name})

    # Notes
    if template.description:
        # Truncate long notes
        notes_preview = template.description[:50] + "..." if len(template.description) > 50 else template.description
        parts.append(f'with notes "{notes_preview}"')
        chips.append({"type": "notes", "value": template.description, "label": notes_preview})

    # Due
    due_info = render_due_phrase(template.due)
    if due_info:
        parts.append(due_info["text"])
        chips.append(due_info["chip"])

    # Tags
    if template.tags:
        tags_str = ", ".join(template.tags)
        parts.append(f"tagged [{tags_str}]")
        chips.append({"type": "tags", "value": template.tags, "label": tags_str})

    return {
        "text": " ".join(parts),
        "chips": chips
    }


def render_collate_phrase(target: Any, as_template: TaskTemplate) -> dict:
    """Render a collate action as a phrase."""
    # Determine target description
    if hasattr(target, 'shorthand') and target.shorthand:
        target_text = target.shorthand
        if target_text.startswith("tagged:"):
            tag = target_text.split(":", 1)[1].strip()
            target_phrase = f"tasks tagged [{tag}]"
        elif target_text == "children":
            target_phrase = "child tasks"
        elif target_text == "descendants":
            target_phrase = "all descendant tasks"
        else:
            target_phrase = target_text
    else:
        target_phrase = "matching tasks"

    return {
        "text": f'batch {target_phrase} into "{as_template.name}"',
        "chips": [
            {"type": "collate_target", "value": str(target), "label": target_phrase},
            {"type": "collate_name", "value": as_template.name, "label": as_template.name}
        ]
    }


def render_action_sentence(action: PracticeAction | dict) -> dict:
    """Render a complete action as a human-readable sentence.

    Args:
        action: PracticeAction object or dict from JSON

    Returns:
        dict with:
            - text: Full sentence text
            - parts: List of sentence parts with chip metadata
            - chips: Flat list of all editable chips
    """
    # Parse dict to PracticeAction if needed
    if isinstance(action, dict):
        action = PracticeAction.from_dict(action)

    parts = []
    all_chips = []

    # Schedule/trigger phrase
    if action.trigger.schedule:
        schedule_info = render_schedule_phrase(action.trigger.schedule)
        parts.append({"text": schedule_info["text"], "type": "schedule"})
        all_chips.extend(schedule_info["chips"])
    elif action.trigger.event:
        event_type = action.trigger.event.type.value
        event_phrases = {
            "task_completion": "When a task is completed",
            "priority_completion": "When a priority is completed",
        }
        phrase = event_phrases.get(event_type, f"On {event_type}")
        parts.append({"text": phrase, "type": "event"})
        all_chips.append({"type": "event", "value": event_type, "label": phrase.lower()})

    # Conditions (when:)
    if action.conditions:
        cond_parts = []
        for cond in action.conditions:
            cond_parts.append(f"{cond.type}")
            all_chips.append({"type": "condition", "value": cond.to_dict(), "label": cond.type})
        if cond_parts:
            parts.append({"text": f"when {', '.join(cond_parts)}", "type": "conditions"})

    # Create action
    if action.create and action.create.items:
        for item in action.create.items:
            if isinstance(item, TaskTemplate):
                task_info = render_task_template_phrase(item)
                parts.append({"text": task_info["text"], "type": "create_task"})
                all_chips.extend(task_info["chips"])
            elif isinstance(item, PriorityTemplate):
                parts.append({
                    "text": f'create a {item.type} named "{item.name}"',
                    "type": "create_priority"
                })
                all_chips.append({"type": "priority_name", "value": item.name, "label": item.name})

    # Collate action
    if action.collate:
        collate_info = render_collate_phrase(action.collate.target, action.collate.as_template)
        parts.append({"text": collate_info["text"], "type": "collate"})
        all_chips.extend(collate_info["chips"])

    # Build full sentence
    full_text = ", ".join(p["text"] for p in parts)
    if full_text and not full_text.endswith("."):
        full_text += "."

    return {
        "text": full_text,
        "parts": parts,
        "chips": all_chips
    }


def render_actions_from_config(actions_config: str | None) -> list[dict]:
    """Parse actions_config JSON and render all actions as sentences.

    Args:
        actions_config: JSON string from Practice.actions_config field

    Returns:
        List of rendered action dicts, each with text/parts/chips
    """
    if not actions_config:
        return []

    try:
        config = PracticeConfig.from_json(actions_config)
        return [render_action_sentence(action) for action in config.actions]
    except (json.JSONDecodeError, KeyError, AttributeError):
        return []


def render_action_summary(action: PracticeAction | dict) -> str:
    """Render an action as a simple human-readable summary for view mode.

    Only includes: trigger condition, task name, and due date.
    Example: 'On weekdays, create a task called "Practice Leetcode," due at end of day.'

    Args:
        action: PracticeAction object or dict from JSON

    Returns:
        Simple summary string
    """
    if isinstance(action, dict):
        action = PracticeAction.from_dict(action)

    parts = []

    # Trigger phrase
    if action.trigger.schedule:
        schedule_info = render_schedule_phrase(action.trigger.schedule)
        parts.append(schedule_info["text"])
    elif action.trigger.event:
        event_type = action.trigger.event.type.value
        event_phrases = {
            "task_completion": "When a task is completed",
            "priority_completion": "When a priority is completed",
        }
        parts.append(event_phrases.get(event_type, f"On {event_type}"))

    # Task creation (simplified)
    if action.create and action.create.items:
        for item in action.create.items:
            if isinstance(item, TaskTemplate):
                task_part = f'create a task called "{item.name}"'
                # Add due if present
                due_info = render_due_phrase(item.due)
                if due_info:
                    task_part += f", {due_info['text']}"
                parts.append(task_part)

    # Collate (simplified)
    if action.collate:
        target = action.collate.target
        if hasattr(target, 'shorthand') and target.shorthand:
            if target.shorthand == "children":
                target_phrase = "child tasks"
            elif target.shorthand == "descendants":
                target_phrase = "descendant tasks"
            else:
                target_phrase = target.shorthand
        else:
            target_phrase = "matching tasks"
        parts.append(f'batch {target_phrase} into "{action.collate.as_template.name}"')

    # Build sentence
    summary = ", ".join(parts)
    if summary and not summary.endswith("."):
        summary += "."

    return summary


def action_to_card_data(action: PracticeAction | dict) -> dict:
    """Extract chip-compatible field values from a PracticeAction for the
    action card template.

    Returns a flat dict with trigger_type, action_type, and all chip field
    values that the action_card.html template expects.
    """
    if isinstance(action, dict):
        action = PracticeAction.from_dict(action)

    data = {
        "trigger_type": "schedule" if action.trigger.schedule else "event",
        "action_type": "collate" if action.collate else "create",
    }

    # Schedule fields
    if action.trigger.schedule:
        sched = action.trigger.schedule
        if isinstance(sched.interval, str):
            data["interval"] = sched.interval
        elif hasattr(sched.interval, 'frequency'):
            # Preserve cadence data for round-tripping
            data["interval"] = "custom"
            data["cadence_frequency"] = sched.interval.frequency
            data["cadence_beginning"] = sched.interval.beginning
            # Decompose for chip rendering
            freq = sched.interval.frequency
            m = re.match(r"(\d+)([dwmqy])", freq)
            if m:
                data["cadence_count"] = m.group(1)
                unit_map = {"d": "days", "w": "weeks", "m": "months", "q": "quarters", "y": "years"}
                data["cadence_period"] = unit_map.get(m.group(2), "weeks")
            # Use stored day value (works for all period types)
            if sched.day:
                data["cadence_day"] = sched.day
            elif data.get("cadence_period") == "weeks" and sched.interval.beginning:
                # Fallback for old data without stored day: derive from beginning
                try:
                    dt = datetime.fromisoformat(sched.interval.beginning)
                    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                    data["cadence_day"] = day_names[dt.weekday()]
                except ValueError:
                    pass
        if sched.at:
            data["time"] = sched.at if isinstance(sched.at, str) else sched.at[0]

    # Event fields
    if action.trigger.event:
        evt = action.trigger.event
        event_type = evt.event_type.value
        if "task" in event_type:
            if evt.params.get("entity_type") == "goal":
                data["event_subject"] = "goal"
            else:
                data["event_subject"] = "task"
        else:
            entity_type = evt.params.get("entity_type", "any")
            data["event_subject"] = entity_type

        if "completion" in event_type:
            data["event_outcome"] = "completed"
        elif "status_change" in event_type:
            data["event_outcome"] = f"status_change:{evt.to}" if evt.to else "status_change:active"
        else:
            data["event_outcome"] = "created"

        if evt.params.get("under"):
            data["event_ancestor"] = evt.params["under"]

    # Create fields
    if action.create and action.create.items:
        item = action.create.items[0]
        if isinstance(item, TaskTemplate):
            data["task_name"] = item.name
            if item.due:
                data["due"] = item.due if isinstance(item.due, str) else "end_of_day"
            if item.tags:
                data["tags"] = ",".join(item.tags)
            if item.description:
                data["description"] = item.description

    # Collate fields
    if action.collate:
        target = action.collate.target
        if hasattr(target, 'shorthand') and target.shorthand:
            data["collate_target"] = target.shorthand
        if action.collate.as_template:
            data["collate_name"] = action.collate.as_template.name

    return data


def actions_to_card_data(actions_config: str | None) -> list[dict]:
    """Parse actions_config and return card data for all actions."""
    if not actions_config:
        return []

    try:
        config = PracticeConfig.from_json(actions_config)
        return [action_to_card_data(action) for action in config.actions]
    except (json.JSONDecodeError, KeyError, AttributeError):
        return []


def render_action_summaries(actions_config: str | None) -> list[str]:
    """Parse actions_config and render simple summaries for view mode.

    Args:
        actions_config: JSON string from Practice.actions_config field

    Returns:
        List of simple summary strings
    """
    if not actions_config:
        return []

    try:
        config = PracticeConfig.from_json(actions_config)
        return [render_action_summary(action) for action in config.actions]
    except (json.JSONDecodeError, KeyError, AttributeError):
        return []


def actions_to_yaml(actions_config: str | None) -> str:
    """Convert actions_config JSON to YAML for editing.

    Args:
        actions_config: JSON string from Practice.actions_config field

    Returns:
        YAML string representation
    """
    import yaml

    if not actions_config:
        return "# No actions configured\nactions: []\n"

    try:
        config = PracticeConfig.from_json(actions_config)
        # Return just the actions list, not the full practice wrapper
        yaml_data = {"actions": [a.to_dict() for a in config.actions]}
        return yaml.dump(yaml_data, default_flow_style=False, sort_keys=False)
    except (json.JSONDecodeError, KeyError):
        return f"# Error parsing actions\n# Raw: {actions_config}\nactions: []\n"


def yaml_to_actions_config(yaml_str: str, practice_name: str = "") -> str:
    """Parse YAML and convert to actions_config JSON.

    Args:
        yaml_str: YAML string with actions list
        practice_name: Name of the practice (for PracticeConfig wrapper)

    Returns:
        JSON string for storage in actions_config field

    Raises:
        ValueError: If YAML is invalid
    """
    import yaml

    try:
        data = yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML: {e}")

    if not data:
        data = {"actions": []}

    # Ensure we have actions list
    if "actions" not in data:
        if isinstance(data, list):
            data = {"actions": data}
        else:
            raise ValueError("YAML must contain 'actions' list")

    # Wrap in practice config
    data["name"] = practice_name
    config = PracticeConfig.from_dict(data)
    return config.to_json()


def _offset_beginning(base: datetime, period: str, n: int) -> str:
    """Offset a date by N periods, calendar-aware for months+."""
    if period == "weeks":
        return (base + timedelta(weeks=n)).strftime("%Y-%m-%d")
    elif period == "days":
        return (base + timedelta(days=n)).strftime("%Y-%m-%d")
    elif period == "months":
        import calendar
        month = base.month - 1 + n
        year = base.year + month // 12
        month = month % 12 + 1
        max_day = calendar.monthrange(year, month)[1]
        day = min(base.day, max_day)
        return base.replace(year=year, month=month, day=day).strftime("%Y-%m-%d")
    elif period == "quarters":
        return _offset_beginning(base, "months", n * 3)
    elif period == "years":
        return base.replace(year=base.year + n).strftime("%Y-%m-%d")
    return (base + timedelta(days=n * 7)).strftime("%Y-%m-%d")


def _align_beginning_to_day(beginning: str, days_selected: str, period: str, start: str) -> str:
    """Align a beginning date to the selected day value.

    For weeks: days_selected is a weekday name like "tuesday"
    For months+: days_selected is a date like "15" or "first monday"
    """
    first_day = days_selected.split(",")[0].strip().lower()
    begin_dt = datetime.fromisoformat(beginning)

    if period == "weeks":
        day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        if first_day in day_names:
            target_weekday = day_names.index(first_day)
            current_weekday = begin_dt.weekday()
            delta = (target_weekday - current_weekday) % 7
            if delta == 0 and start and start != "immediately":
                delta = 7
            return (begin_dt + timedelta(days=delta)).strftime("%Y-%m-%d")
    elif period in ("months", "quarters", "years"):
        # Date-of-month: "15", "1", "last"
        if first_day == "last":
            # Set to last day of the month
            if begin_dt.month == 12:
                next_month = begin_dt.replace(year=begin_dt.year + 1, month=1, day=1)
            else:
                next_month = begin_dt.replace(month=begin_dt.month + 1, day=1)
            return (next_month - timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            target_day = int(first_day)
            # Clamp to valid day for this month
            import calendar
            max_day = calendar.monthrange(begin_dt.year, begin_dt.month)[1]
            target_day = min(target_day, max_day)
            return begin_dt.replace(day=target_day).strftime("%Y-%m-%d")
        except ValueError:
            pass  # "first monday" etc. — leave beginning as-is for now

    return beginning


def assemble_actions_config(form_data: dict, practice_name: str = "") -> str | None:
    """Assemble actions_config JSON from flat form fields.

    Parses form fields like action_0_interval, action_0_task_name, etc.
    into a PracticeConfig JSON string for database storage.

    This is the inverse of action_to_card_data(): card_data → template →
    hidden inputs → form submit → this function → actions_config JSON.

    Args:
        form_data: dict of form field names to values
        practice_name: name of the practice (for PracticeConfig wrapper)

    Returns:
        JSON string for actions_config, or None if no action fields found
    """
    # Group form fields by action index
    action_fields: dict[int, dict[str, str]] = {}

    for key, value in form_data.items():
        m = _ACTION_FIELD_RE.match(key)
        if m:
            idx = int(m.group(1))
            field = m.group(2)
            if idx not in action_fields:
                action_fields[idx] = {}
            action_fields[idx][field] = value

    if not action_fields:
        return None

    actions = []
    for idx in sorted(action_fields):
        fields = action_fields[idx]
        trigger_type = fields.get("trigger_type", "schedule")
        action_type = fields.get("action_type", "create")

        action_data: dict[str, Any] = {"trigger": {}}

        # Build trigger
        if trigger_type == "schedule":
            interval = fields.get("interval") or "weekdays"
            if interval == "custom":
                # Reconstruct cadence from chip fields (count+period) or
                # hidden inputs (cadence_frequency) on re-save without edit
                count = fields.get("count", "")
                period = fields.get("period", "")
                if count and period:
                    period_unit = {"days": "d", "weeks": "w", "months": "m", "quarters": "q", "years": "y"}
                    freq = f"{count}{period_unit.get(period, 'w')}"
                else:
                    freq = fields.get("cadence_frequency", "2w")

                start = fields.get("start", "")
                days_selected = fields.get("days", "")
                if not start or start == "immediately":
                    beginning = fields.get("cadence_beginning") or datetime.now().strftime("%Y-%m-%d")
                elif start == "next":
                    # "next week/month/etc." — use calendar-aware offset
                    beginning = _offset_beginning(datetime.now(), period, 1)
                elif start.startswith("in "):
                    # "in 3 weeks" — parse number and period
                    parts = start.split()
                    try:
                        n = int(parts[1])
                        beginning = _offset_beginning(datetime.now(), period, n)
                    except (ValueError, IndexError):
                        beginning = datetime.now().strftime("%Y-%m-%d")
                else:
                    beginning = start

                # Align beginning to selected day (context-dependent)
                if days_selected and period != "days":
                    beginning = _align_beginning_to_day(
                        beginning, days_selected, period, start
                    )

                cadence: dict[str, str] = {"frequency": freq, "beginning": beginning}
                sched_data: dict[str, Any] = {"interval": {"cadence": cadence}}
                # Store day selection for round-tripping
                if days_selected:
                    sched_data["day"] = days_selected
                action_data["trigger"]["schedule"] = sched_data
            else:
                action_data["trigger"]["schedule"] = {"interval": interval}
            time = fields.get("time")
            if time:
                action_data["trigger"]["schedule"]["at"] = time
        else:
            subject = fields.get("event_subject") or "any"
            outcome = fields.get("event_outcome") or "created"

            if outcome == "completed":
                event_type = "task_completion" if subject == "task" else "priority_completion"
            elif outcome.startswith("status_change:"):
                event_type = "task_status_change" if subject == "task" else "priority_status_change"
            else:
                event_type = "task_status_change" if subject == "task" else "priority_status_change"

            event_dict: dict[str, str] = {"event": event_type}
            if outcome.startswith("status_change:"):
                event_dict["to"] = outcome.split(":", 1)[1]
            if subject not in ("any", "task"):
                event_dict["entity_type"] = subject

            ancestor = fields.get("event_ancestor")
            if ancestor:
                event_dict["under"] = ancestor

            action_data["trigger"]["event"] = event_dict

        # Build action
        if action_type == "collate":
            target = fields.get("collate_target") or "children"
            name = fields.get("collate_name") or "batch"
            action_data["collate"] = {"target": target, "as": {"name": name}}
        else:
            task_name = fields.get("task_name") or "new task"
            task: dict[str, Any] = {"name": task_name}

            due = fields.get("due")
            if due:
                task["due"] = due

            tags = fields.get("tags")
            if tags:
                tag_list = [t.strip() for t in tags.split(",") if t.strip()]
                if tag_list:
                    task["tags"] = tag_list

            description = fields.get("description")
            if description:
                task["description"] = description

            action_data["create"] = [{"task": task}]

        actions.append(action_data)

    config = {"practice": {"name": practice_name, "actions": actions}}
    return json.dumps(config)
