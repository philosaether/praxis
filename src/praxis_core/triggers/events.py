"""
Trigger Event Dispatcher.

Handles firing Practice triggers when entity events occur:
- task_completed: When a task is marked done
- task_created: When a new task is created
- priority_completed: When a priority is marked complete

These handlers find Practices with matching event triggers and execute them.
"""

import logging
from datetime import datetime

from praxis_core.model.priorities import Practice, PriorityType
from praxis_core.model.practice_triggers import PracticeTrigger, TriggerEventType
from praxis_core.triggers.engine import TriggerContext, execute_practice_trigger

logger = logging.getLogger(__name__)


def _get_graph(entity_id: str):
    """Get PriorityGraph for entity. Import here to avoid circular imports."""
    from praxis_core.persistence import get_connection, PriorityGraph
    graph = PriorityGraph(get_connection, entity_id=entity_id)
    graph.load()
    return graph


def _get_task(task_id: str) -> dict | None:
    """Get task data as dict. Import here to avoid circular imports."""
    from praxis_core.persistence import get_task
    task = get_task(task_id)
    if not task:
        return None
    return {
        "id": task.id,
        "name": task.name,
        "status": task.status.value if task.status else None,
        "priority_id": task.priority_id,
        "entity_id": task.entity_id,
        "tags": [],  # TODO: Load tags if needed for conditions
    }


def _create_task_from_action(params: dict, entity_id: str, created_by: int | None = None):
    """Create a task from trigger action parameters."""
    from praxis_core.persistence import create_task
    return create_task(
        name=params["name"],
        notes=params.get("notes"),
        due_date=params.get("due_date"),
        priority_id=params.get("priority_id"),
        entity_id=entity_id,
        created_by=created_by,
    )


def _find_practices_with_event_trigger(
    graph,
    event_type: TriggerEventType,
) -> list[tuple[Practice, PracticeTrigger]]:
    """Find all Practices with triggers matching the given event type."""
    matches = []

    for priority in graph.nodes.values():
        if not isinstance(priority, Practice):
            continue
        if priority.priority_type != PriorityType.PRACTICE:
            continue
        if not priority.trigger_config:
            continue

        trigger = PracticeTrigger.from_json_or_none(priority.trigger_config)
        if not trigger:
            continue
        if not trigger.enabled:
            continue
        if trigger.event.type != event_type:
            continue

        matches.append((priority, trigger))

    return matches


def _execute_event_triggers(
    practices_with_triggers: list[tuple[Practice, PracticeTrigger]],
    ctx: TriggerContext,
    entity_id: str,
    created_by: int | None = None,
) -> list[dict]:
    """Execute matching event triggers and create tasks."""
    created_tasks = []

    for practice, trigger in practices_with_triggers:
        # Check event params for additional filtering
        event_params = trigger.event.params

        # For task_completed: filter by tag or priority_id
        if trigger.event.type == TriggerEventType.TASK_COMPLETED:
            if ctx.event_task:
                # Filter by tag if specified
                if "tag" in event_params:
                    task_tags = set(t.lower() for t in ctx.event_task.get("tags", []))
                    if event_params["tag"].lower() not in task_tags:
                        continue
                # Filter by priority_id if specified
                if "priority_id" in event_params:
                    if ctx.event_task.get("priority_id") != event_params["priority_id"]:
                        continue

        # For priority_completed: filter by priority_type
        if trigger.event.type == TriggerEventType.PRIORITY_COMPLETED:
            if ctx.event_priority:
                if "priority_type" in event_params:
                    if ctx.event_priority.get("priority_type") != event_params["priority_type"]:
                        continue

        # Update context with practice data
        ctx.practice = {
            "id": practice.id,
            "name": practice.name,
        }

        # Execute trigger
        result = execute_practice_trigger(trigger, practice.id, ctx)

        if not result.success:
            if result.error_message != "Conditions not met":
                logger.debug(f"Event trigger for {practice.name} skipped: {result.error_message}")
            continue

        # Process actions
        for action in result.actions_taken:
            if action["type"] == "create_task":
                try:
                    task = _create_task_from_action(
                        action["params"],
                        entity_id,
                        created_by=created_by,
                    )
                    created_tasks.append({
                        "task_id": task.id,
                        "task_name": task.name,
                        "practice_id": practice.id,
                        "practice_name": practice.name,
                    })
                    logger.info(f"Event trigger created task '{task.name}' from practice '{practice.name}'")
                except Exception as e:
                    logger.error(f"Failed to create task for event trigger: {e}")

            elif action["type"] == "collate_tasks":
                # TODO: Implement collate_tasks action
                logger.debug(f"collate_tasks action not yet implemented")

    return created_tasks


def on_task_completed(
    task_id: str,
    entity_id: str,
    task_data: dict | None = None,
    created_by: int | None = None,
) -> list[dict]:
    """
    Handle task completion event.

    Called when a task is marked as done. Finds Practices with
    task_completed triggers and executes them if conditions match.

    Args:
        task_id: ID of the completed task
        entity_id: Entity that owns the task
        task_data: Optional pre-loaded task data (avoids extra DB query)
        created_by: User ID to set as creator for any generated tasks

    Returns:
        List of created tasks (each as dict with task_id, task_name, etc.)
    """
    logger.debug(f"on_task_completed: task={task_id}, entity={entity_id}")

    # Get task data if not provided
    if task_data is None:
        task_data = _get_task(task_id)

    if not task_data:
        logger.warning(f"Task not found: {task_id}")
        return []

    # Get practices with task_completed triggers
    graph = _get_graph(entity_id)
    practices_with_triggers = _find_practices_with_event_trigger(
        graph, TriggerEventType.TASK_COMPLETED
    )

    if not practices_with_triggers:
        return []

    # Build context
    now = datetime.now()
    ctx = TriggerContext(
        now=now,
        entity_id=entity_id,
        event_task=task_data,
    )

    # Execute triggers
    return _execute_event_triggers(
        practices_with_triggers, ctx, entity_id, created_by
    )


def on_task_created(
    task_id: str,
    entity_id: str,
    task_data: dict | None = None,
    created_by: int | None = None,
    from_trigger: bool = False,
) -> list[dict]:
    """
    Handle task creation event.

    Called when a new task is created. Skipped if task was created by a trigger
    to prevent infinite recursion.

    Args:
        task_id: ID of the created task
        entity_id: Entity that owns the task
        task_data: Optional pre-loaded task data
        created_by: User ID to set as creator for any generated tasks
        from_trigger: If True, skip processing (prevents recursion)

    Returns:
        List of created tasks
    """
    if from_trigger:
        logger.debug(f"on_task_created: skipping (from_trigger=True)")
        return []

    logger.debug(f"on_task_created: task={task_id}, entity={entity_id}")

    # Note: task_created triggers are less common than task_completed,
    # but could be used for things like "when a task is added to inbox,
    # automatically create a review task"

    # For now, this is a placeholder. We don't have task_created as a
    # supported event type in the DSL, so this will return early.
    return []


def on_priority_completed(
    priority_id: str,
    entity_id: str,
    priority_data: dict | None = None,
    created_by: int | None = None,
) -> list[dict]:
    """
    Handle priority completion event.

    Called when a priority (typically a Goal) is marked complete.
    Finds Practices with priority_completed triggers and executes them.

    Args:
        priority_id: ID of the completed priority
        entity_id: Entity that owns the priority
        priority_data: Optional pre-loaded priority data
        created_by: User ID to set as creator for any generated tasks

    Returns:
        List of created tasks
    """
    logger.debug(f"on_priority_completed: priority={priority_id}, entity={entity_id}")

    # Get priority data if not provided
    if priority_data is None:
        graph = _get_graph(entity_id)
        priority = graph.nodes.get(priority_id)
        if priority:
            priority_data = {
                "id": priority.id,
                "name": priority.name,
                "priority_type": priority.priority_type.value,
            }

    if not priority_data:
        logger.warning(f"Priority not found: {priority_id}")
        return []

    # Get practices with priority_completed triggers
    graph = _get_graph(entity_id)
    practices_with_triggers = _find_practices_with_event_trigger(
        graph, TriggerEventType.PRIORITY_COMPLETED
    )

    if not practices_with_triggers:
        return []

    # Build context
    now = datetime.now()
    ctx = TriggerContext(
        now=now,
        entity_id=entity_id,
        event_priority=priority_data,
    )

    # Execute triggers
    return _execute_event_triggers(
        practices_with_triggers, ctx, entity_id, created_by
    )


def on_priority_status_changed(
    priority_id: str,
    entity_id: str,
    new_status: str,
    priority_data: dict | None = None,
    created_by: int | None = None,
) -> list[dict]:
    """
    Handle priority status change event.

    Called when a priority's status changes (e.g., active -> completed).
    If new_status is 'completed', delegates to on_priority_completed.

    Args:
        priority_id: ID of the priority
        entity_id: Entity that owns the priority
        new_status: New status value
        priority_data: Optional pre-loaded priority data
        created_by: User ID to set as creator for any generated tasks

    Returns:
        List of created tasks
    """
    logger.debug(f"on_priority_status_changed: priority={priority_id}, status={new_status}, entity={entity_id}")

    # Currently we only handle completion events
    if new_status == "completed":
        return on_priority_completed(
            priority_id, entity_id, priority_data, created_by
        )

    return []
