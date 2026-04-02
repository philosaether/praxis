"""
Trigger API endpoints.

CRUD operations for triggers, plus import/export and manual firing.
"""

from datetime import datetime
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from praxis_core.model.rules import RuleCondition, ConditionType
from praxis_core.model.triggers import (
    TriggerEvent,
    TriggerEventType,
    TriggerAction,
    TriggerActionType,
    TaskTemplate,
    CollateConfig,
)
from praxis_core.persistence import (
    create_trigger,
    get_trigger,
    list_triggers,
    update_trigger,
    delete_trigger,
    toggle_trigger,
    record_trigger_fire,
)
from praxis_core.triggers import (
    parse_triggers,
    serialize_triggers,
    serialize_trigger,
    DSLParseError,
    TriggerContext,
    execute_trigger,
)
from praxis_core.api.auth_endpoints import get_current_user


router = APIRouter()


# -----------------------------------------------------------------------------
# Request/Response Models
# -----------------------------------------------------------------------------

class EventParams(BaseModel):
    """Event parameters for API."""
    type: str
    params: dict = {}


class ConditionParams(BaseModel):
    """Condition parameters for API."""
    type: str
    params: dict = {}


class TaskTemplateParams(BaseModel):
    """Task template parameters for API."""
    name_pattern: str
    notes_pattern: str | None = None
    due_date_offset: str | None = None
    tags: list[str] = []
    priority_id: str | None = None


class CollateConfigParams(BaseModel):
    """Collate config parameters for API."""
    source_tag: str | None = None
    source_priority_id: str | None = None
    batch_name_pattern: str = "Batch for {{date}}"
    include_completed: bool = False
    mark_source_done: bool = False


class ActionParams(BaseModel):
    """Action parameters for API."""
    type: str
    task_template: TaskTemplateParams | None = None
    collate_config: CollateConfigParams | None = None


class TriggerCreateRequest(BaseModel):
    """Request body for creating a trigger."""
    name: str
    description: str | None = None
    priority: int = 0
    enabled: bool = True
    practice_id: str | None = None
    event: EventParams
    conditions: list[ConditionParams] = []
    actions: list[ActionParams]


class TriggerUpdateRequest(BaseModel):
    """Request body for updating a trigger."""
    name: str | None = None
    description: str | None = None
    priority: int | None = None
    enabled: bool | None = None
    practice_id: str | None = None
    event: EventParams | None = None
    conditions: list[ConditionParams] | None = None
    actions: list[ActionParams] | None = None


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def _convert_event(params: EventParams) -> TriggerEvent:
    """Convert API event params to TriggerEvent."""
    try:
        event_type = TriggerEventType(params.type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid event type: {params.type}")
    return TriggerEvent(type=event_type, params=params.params)


def _convert_condition(params: ConditionParams) -> RuleCondition:
    """Convert API condition params to RuleCondition."""
    try:
        cond_type = ConditionType(params.type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid condition type: {params.type}")
    return RuleCondition(type=cond_type, params=params.params)


def _convert_action(params: ActionParams) -> TriggerAction:
    """Convert API action params to TriggerAction."""
    try:
        action_type = TriggerActionType(params.type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid action type: {params.type}")

    task_template = None
    collate_config = None

    if action_type == TriggerActionType.CREATE_TASK and params.task_template:
        task_template = TaskTemplate(
            name_pattern=params.task_template.name_pattern,
            notes_pattern=params.task_template.notes_pattern,
            due_date_offset=params.task_template.due_date_offset,
            tags=params.task_template.tags,
            priority_id=params.task_template.priority_id,
        )
    elif action_type == TriggerActionType.COLLATE_TASKS and params.collate_config:
        collate_config = CollateConfig(
            source_tag=params.collate_config.source_tag,
            source_priority_id=params.collate_config.source_priority_id,
            batch_name_pattern=params.collate_config.batch_name_pattern,
            include_completed=params.collate_config.include_completed,
            mark_source_done=params.collate_config.mark_source_done,
        )

    return TriggerAction(
        type=action_type,
        task_template=task_template,
        collate_config=collate_config,
    )


def _trigger_to_dict(trigger) -> dict:
    """Convert trigger to JSON-serializable dict."""
    return {
        "id": trigger.id,
        "entity_id": trigger.entity_id,
        "practice_id": trigger.practice_id,
        "name": trigger.name,
        "description": trigger.description,
        "enabled": trigger.enabled,
        "priority": trigger.priority,
        "event": trigger.event.to_dict(),
        "conditions": [c.to_dict() for c in trigger.conditions],
        "actions": [a.to_dict() for a in trigger.actions],
        "last_fired_at": trigger.last_fired_at.isoformat() if trigger.last_fired_at else None,
        "fire_count": trigger.fire_count,
        "created_at": trigger.created_at.isoformat() if trigger.created_at else None,
        "updated_at": trigger.updated_at.isoformat() if trigger.updated_at else None,
    }


# -----------------------------------------------------------------------------
# CRUD Endpoints
# -----------------------------------------------------------------------------

@router.get("")
async def list_user_triggers(
    request: Request,
    practice_id: str | None = None,
    enabled: bool | None = None,
):
    """List triggers for the current user."""
    user = await get_current_user(request)

    triggers = list_triggers(
        entity_id=user.id,
        practice_id=practice_id,
        enabled_only=enabled or False,
    )

    return {
        "triggers": [_trigger_to_dict(t) for t in triggers]
    }


@router.post("")
async def create_user_trigger(request: Request, body: TriggerCreateRequest):
    """Create a new trigger."""
    user = await get_current_user(request)

    # Convert to domain objects
    event = _convert_event(body.event)
    conditions = [_convert_condition(c) for c in body.conditions]
    actions = [_convert_action(a) for a in body.actions]

    if not actions:
        raise HTTPException(status_code=400, detail="At least one action is required")

    trigger = create_trigger(
        name=body.name,
        event=event,
        actions=actions,
        entity_id=user.id,
        practice_id=body.practice_id,
        conditions=conditions,
        description=body.description,
        enabled=body.enabled,
        priority=body.priority,
    )

    return {"trigger": _trigger_to_dict(trigger)}


@router.get("/{trigger_id}")
async def get_user_trigger(request: Request, trigger_id: str):
    """Get a specific trigger."""
    user = await get_current_user(request)

    trigger = get_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")

    # Verify ownership
    if trigger.entity_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    return {"trigger": _trigger_to_dict(trigger)}


@router.put("/{trigger_id}")
async def update_user_trigger(request: Request, trigger_id: str, body: TriggerUpdateRequest):
    """Update a trigger."""
    user = await get_current_user(request)

    trigger = get_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")

    if trigger.entity_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Convert to domain objects where provided
    event = _convert_event(body.event) if body.event else None
    conditions = [_convert_condition(c) for c in body.conditions] if body.conditions is not None else None
    actions = [_convert_action(a) for a in body.actions] if body.actions is not None else None

    updated = update_trigger(
        trigger_id=trigger_id,
        name=body.name,
        description=body.description,
        event=event,
        conditions=conditions,
        actions=actions,
        enabled=body.enabled,
        priority=body.priority,
        practice_id=body.practice_id,
    )

    return {"trigger": _trigger_to_dict(updated)}


@router.delete("/{trigger_id}")
async def delete_user_trigger(request: Request, trigger_id: str):
    """Delete a trigger."""
    user = await get_current_user(request)

    trigger = get_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")

    if trigger.entity_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    delete_trigger(trigger_id)
    return {"success": True}


@router.post("/{trigger_id}/toggle")
async def toggle_user_trigger(request: Request, trigger_id: str):
    """Toggle a trigger's enabled state."""
    user = await get_current_user(request)

    trigger = get_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")

    if trigger.entity_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    updated = toggle_trigger(trigger_id)
    return {"trigger": _trigger_to_dict(updated)}


# -----------------------------------------------------------------------------
# Import/Export Endpoints
# -----------------------------------------------------------------------------

@router.get("/export")
async def export_triggers(request: Request):
    """Export all triggers as YAML."""
    user = await get_current_user(request)

    triggers = list_triggers(entity_id=user.id)
    yaml_content = serialize_triggers(triggers)

    return Response(
        content=yaml_content,
        media_type="text/yaml",
        headers={"Content-Disposition": "attachment; filename=praxis-triggers.yml"}
    )


@router.get("/export/{trigger_id}")
async def export_single_trigger(request: Request, trigger_id: str):
    """Export a single trigger as YAML."""
    user = await get_current_user(request)

    trigger = get_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")

    if trigger.entity_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    yaml_content = serialize_trigger(trigger)
    return Response(content=yaml_content, media_type="text/yaml")


@router.put("/{trigger_id}/yaml")
async def update_trigger_from_yaml(request: Request, trigger_id: str):
    """Update a trigger from YAML content."""
    user = await get_current_user(request)

    trigger = get_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")

    if trigger.entity_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    body = await request.body()
    yaml_content = body.decode("utf-8")

    try:
        parsed = parse_triggers(yaml_content)
    except DSLParseError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")

    if not parsed:
        raise HTTPException(status_code=400, detail="No trigger found in YAML")

    parsed_trigger = parsed[0]

    # Update the trigger with parsed data
    updated = update_trigger(
        trigger_id=trigger_id,
        name=parsed_trigger.name,
        description=parsed_trigger.description,
        event=parsed_trigger.event,
        conditions=parsed_trigger.conditions,
        actions=parsed_trigger.actions,
        enabled=parsed_trigger.enabled,
        priority=parsed_trigger.priority,
        practice_id=parsed_trigger.practice_id,
    )

    return {"trigger": _trigger_to_dict(updated)}


@router.post("/import/preview")
async def preview_import(request: Request):
    """Preview triggers from YAML content before import."""
    body = await request.body()
    yaml_content = body.decode("utf-8")

    try:
        triggers = parse_triggers(yaml_content)
    except DSLParseError as e:
        raise HTTPException(status_code=400, detail=f"Parse error: {e}")

    return {
        "triggers": [
            {
                "name": t.name,
                "description": t.description,
                "event_type": t.event.type.value,
                "conditions_count": len(t.conditions),
                "actions_count": len(t.actions),
            }
            for t in triggers
        ]
    }


class ImportRequest(BaseModel):
    yaml_content: str
    selected_indices: list[int]


@router.post("/import")
async def import_triggers(request: Request, body: ImportRequest):
    """Import selected triggers from YAML."""
    user = await get_current_user(request)

    try:
        triggers = parse_triggers(body.yaml_content)
    except DSLParseError as e:
        raise HTTPException(status_code=400, detail=f"Parse error: {e}")

    imported = []
    for idx in body.selected_indices:
        if idx < 0 or idx >= len(triggers):
            continue

        parsed = triggers[idx]
        trigger = create_trigger(
            name=parsed.name,
            event=parsed.event,
            actions=parsed.actions,
            entity_id=user.id,
            practice_id=parsed.practice_id,
            conditions=parsed.conditions,
            description=parsed.description,
            enabled=parsed.enabled,
            priority=parsed.priority,
        )
        imported.append(_trigger_to_dict(trigger))

    return {"imported": imported, "count": len(imported)}


# -----------------------------------------------------------------------------
# Manual Fire Endpoint
# -----------------------------------------------------------------------------

@router.post("/{trigger_id}/fire")
async def fire_trigger(request: Request, trigger_id: str):
    """Manually fire a trigger."""
    user = await get_current_user(request)

    trigger = get_trigger(trigger_id)
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger not found")

    if trigger.entity_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Create execution context
    ctx = TriggerContext(
        now=datetime.now(),
        entity_id=user.id,
    )

    # Execute trigger (bypassing condition checks for manual fire)
    from praxis_core.triggers.engine import execute_create_task, execute_collate_tasks
    from praxis_core.persistence import create_task as persist_create_task

    actions_taken = []

    for action in trigger.actions:
        if action.type == TriggerActionType.CREATE_TASK and action.task_template:
            params = execute_create_task(action.task_template, trigger, ctx)
            # Actually create the task
            task = persist_create_task(
                name=params["name"],
                notes=params.get("notes"),
                due_date=params.get("due_date"),
                priority_id=params.get("priority_id"),
                entity_id=user.id,
            )
            actions_taken.append({
                "type": "create_task",
                "task_id": task.id,
                "task_name": task.name,
            })

        elif action.type == TriggerActionType.COLLATE_TASKS and action.collate_config:
            params = execute_collate_tasks(action.collate_config, trigger, ctx)
            actions_taken.append({
                "type": "collate_tasks",
                "batch_name": params["batch_name"],
            })

    # Record that trigger was fired
    record_trigger_fire(trigger_id)

    return {
        "success": True,
        "trigger_id": trigger_id,
        "actions_taken": actions_taken,
    }
