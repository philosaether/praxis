"""
Action wizard helpers: form-parsing and blank-action construction.

These functions build actions_config dicts (JSON-serializable) from wizard
form data.  They return DSL objects that the caller serialises via
PracticeConfig.to_json().
"""

from datetime import date

from praxis_core.dsl import (
    PracticeAction,
    Trigger,
    Schedule,
    Cadence,
    CreateAction,
    CollateAction,
    TaskTemplate,
    CollateTarget,
    Event,
    EventType,
)


def parse_wizard_form(form_data: dict, existing_config=None) -> PracticeAction:
    """Parse action wizard form submission into a PracticeAction.

    Parameters
    ----------
    form_data:
        Flat dict of form fields (from ``await request.form()``).
    existing_config:
        Unused for now; reserved for future edit-in-place support where the
        caller passes the current PracticeConfig so the function can merge.

    Returns a ``PracticeAction`` ready to be appended to a PracticeConfig.
    """

    action_type = form_data.get("action_type", "create")
    trigger_type = form_data.get("trigger_type", "schedule")

    # -- Schedule fields ------------------------------------------------------
    schedule_interval = form_data.get("schedule_interval", "weekdays")
    schedule_days = form_data.get("schedule_days", "")
    schedule_cadence_value = int(form_data.get("schedule_cadence_value", 2))
    schedule_cadence_unit = form_data.get("schedule_cadence_unit", "w")
    schedule_cadence_anchor = form_data.get("schedule_cadence_anchor", "")
    schedule_at = (
        form_data.get("schedule_at") if form_data.get("schedule_has_time") else None
    )

    # -- Event fields ---------------------------------------------------------
    event_entity = form_data.get("event_entity", "task")
    event_lifecycle = form_data.get("event_lifecycle", "completed")
    event_filter_type = form_data.get("event_filter_type", "any")
    event_filter_priority_id = form_data.get("event_filter_priority_id")
    event_filter_tag = form_data.get("event_filter_tag")

    # -- Task details ---------------------------------------------------------
    task_name = form_data.get("task_name", "").strip() or "Untitled task"
    task_description = form_data.get("task_description", "").strip()
    task_due = form_data.get("task_due", "")
    task_tags = form_data.get("task_tags", "")

    # -- Collation fields -----------------------------------------------------
    collate_under_practice = form_data.get("collate_under_practice")
    collate_with_tag = form_data.get("collate_with_tag")
    collate_tag = form_data.get("collate_tag", "")

    # ---- Build trigger ------------------------------------------------------
    trigger = _build_trigger(
        trigger_type,
        schedule_interval=schedule_interval,
        schedule_days=schedule_days,
        schedule_cadence_value=schedule_cadence_value,
        schedule_cadence_unit=schedule_cadence_unit,
        schedule_cadence_anchor=schedule_cadence_anchor,
        schedule_at=schedule_at,
        event_entity=event_entity,
        event_lifecycle=event_lifecycle,
        event_filter_type=event_filter_type,
        event_filter_priority_id=event_filter_priority_id,
        event_filter_tag=event_filter_tag,
    )

    # ---- Build action -------------------------------------------------------
    if action_type == "collate":
        target_parts = []
        if collate_under_practice:
            target_parts.append("children")
        if collate_with_tag and collate_tag:
            target_parts.append(f"tagged:{collate_tag}")

        collate = CollateAction(
            target=CollateTarget(
                shorthand=target_parts[0] if target_parts else "children"
            ),
            as_template=TaskTemplate(
                name=task_name,
                description=task_description if task_description else None,
                due=task_due if task_due else None,
            ),
        )
        return PracticeAction(trigger=trigger, collate=collate)
    else:
        tags = [t.strip() for t in task_tags.split(",") if t.strip()]
        create = CreateAction(
            items=[
                TaskTemplate(
                    name=task_name,
                    description=task_description if task_description else None,
                    due=task_due if task_due else None,
                    tags=tags,
                )
            ]
        )
        return PracticeAction(trigger=trigger, create=create)


def build_blank_action(
    trigger_type: str = "schedule", action_type: str = "create"
) -> PracticeAction:
    """Build a default PracticeAction for a new wizard entry.

    Returns a ``PracticeAction`` with sensible defaults that the user can
    then customise in the editor UI.
    """

    if trigger_type == "schedule":
        trigger = Trigger(schedule=Schedule(interval="weekdays"))
    else:
        trigger = Trigger(event=Event(event_type=EventType.PRIORITY_STATUS_CHANGE))

    if action_type == "collate":
        collate = CollateAction(
            target=CollateTarget(shorthand="children"),
            as_template=TaskTemplate(name="new task"),
        )
        return PracticeAction(trigger=trigger, collate=collate)
    else:
        create = CreateAction(items=[TaskTemplate(name="new task")])
        return PracticeAction(trigger=trigger, create=create)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DAY_NAMES = frozenset(
    ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
)


def _build_trigger(
    trigger_type: str,
    *,
    schedule_interval: str,
    schedule_days: str,
    schedule_cadence_value: int,
    schedule_cadence_unit: str,
    schedule_cadence_anchor: str,
    schedule_at: str | None,
    event_entity: str,
    event_lifecycle: str,
    event_filter_type: str,
    event_filter_priority_id: str | None,
    event_filter_tag: str | None,
) -> Trigger:
    """Construct a Trigger from parsed form values."""

    if trigger_type == "schedule":
        if schedule_interval in ("custom_days", "custom_weeks"):
            freq = f"{schedule_cadence_value}{'d' if schedule_cadence_unit == 'd' else 'w'}"
            schedule = Schedule(
                interval=Cadence(
                    frequency=freq,
                    beginning=schedule_cadence_anchor or date.today().isoformat(),
                )
            )
        elif schedule_interval in _DAY_NAMES:
            days = (
                [d.strip() for d in schedule_days.split(",") if d.strip()]
                if schedule_days
                else []
            )
            if len(days) > 1:
                schedule = Schedule(interval="weekly", day=days[0])
            else:
                schedule = Schedule(interval="weekly", day=schedule_interval)
        else:
            schedule = Schedule(interval=schedule_interval)

        if schedule_at:
            schedule.at = schedule_at

        return Trigger(schedule=schedule)

    # Event trigger
    if event_entity == "task" and event_lifecycle == "completed":
        event_type = EventType.TASK_COMPLETION
    elif event_entity == "task":
        event_type = EventType.TASK_STATUS_CHANGE
    elif event_lifecycle == "completed":
        event_type = EventType.PRIORITY_COMPLETION
    else:
        event_type = EventType.PRIORITY_STATUS_CHANGE

    params: dict = {}
    if event_filter_type == "under_practice":
        params["under"] = "practice"
    elif event_filter_type == "under_priority" and event_filter_priority_id:
        params["under"] = event_filter_priority_id
    elif event_filter_type == "tagged" and event_filter_tag:
        params["tagged"] = event_filter_tag

    if event_entity == "goal":
        params["entity_type"] = "goal"

    event = Event(event_type=event_type, params=params)
    return Trigger(event=event)
