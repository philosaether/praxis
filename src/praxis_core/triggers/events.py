"""
Trigger Event Dispatcher.

Handles firing Practice triggers when entity events occur:
- task_completion: When a task is marked done
- task_created: When a new task is created (placeholder)
- priority_completion: When a priority is marked complete
- priority_status_change: When a priority's status changes

These handlers find Practices with matching event triggers in
actions_config and execute them via the v2 engine.
"""

import logging
from datetime import datetime

from praxis_core.dsl import PracticeConfig, PracticeAction, EventType
from praxis_core.dsl.actions import ActionContext, execute_create_action, execute_collate_action
from praxis_core.model.priorities import Practice, PriorityType

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


def _get_ancestors(graph, priority_id: str) -> list[dict]:
    """Get ancestor chain for a priority (for event condition matching)."""
    ancestors = []
    ancestor_ids = graph.ancestors(priority_id)
    for aid in ancestor_ids:
        node = graph.nodes.get(aid)
        if node:
            ancestors.append({
                "id": node.id,
                "name": node.name,
                "priority_type": node.priority_type.value,
            })
    return ancestors


def _find_practices_with_event_actions(
    graph,
    event_type: EventType,
) -> list[tuple[Practice, PracticeAction]]:
    """Find all Practice actions with event triggers matching the given type."""
    matches = []

    for priority in graph.nodes.values():
        if not isinstance(priority, Practice):
            continue
        if not priority.actions_config:
            continue

        try:
            config = PracticeConfig.from_json(priority.actions_config)
        except (ValueError, KeyError):
            logger.warning(f"Failed to parse actions_config for {priority.name}")
            continue

        for action in config.actions:
            if not action.trigger.event:
                continue
            if action.trigger.event.event_type != event_type:
                continue
            matches.append((priority, action))

    return matches


def _matches_event_params(
    action: PracticeAction,
    event_type: EventType,
    task_data: dict | None = None,
    priority_data: dict | None = None,
) -> bool:
    """Check if an action's event params match the event data."""
    event = action.trigger.event
    if not event:
        return False

    params = event.params

    if event_type in (EventType.TASK_COMPLETION, EventType.TASK_STATUS_CHANGE):
        if task_data:
            if "tag" in params:
                task_tags = set(t.lower() for t in task_data.get("tags", []))
                if params["tag"].lower() not in task_tags:
                    return False
            if "priority_id" in params:
                if task_data.get("priority_id") != params["priority_id"]:
                    return False
            if "entity_type" in params:
                # entity_type filter on task events — always matches "task"
                if params["entity_type"] not in ("task", "any"):
                    return False

    if event_type in (EventType.PRIORITY_COMPLETION, EventType.PRIORITY_STATUS_CHANGE):
        if priority_data:
            if "priority_type" in params:
                if priority_data.get("priority_type") != params["priority_type"]:
                    return False
            if "entity_type" in params:
                if priority_data.get("priority_type") != params["entity_type"]:
                    return False
            if "under" in params:
                # Ancestor matching — check if any ancestor name matches
                ancestors = priority_data.get("ancestors", [])
                target = params["under"]
                if not any(a.get("name") == target for a in ancestors):
                    return False

    # Status change: check target status
    if event.to:
        if event_type == EventType.TASK_STATUS_CHANGE:
            if task_data and task_data.get("status") != event.to:
                return False
        if event_type == EventType.PRIORITY_STATUS_CHANGE:
            if priority_data and priority_data.get("status") != event.to:
                return False

    return True


def _execute_event_actions(
    matches: list[tuple[Practice, PracticeAction]],
    event_type: EventType,
    entity_id: str,
    task_data: dict | None = None,
    priority_data: dict | None = None,
    created_by: int | None = None,
) -> list[dict]:
    """Execute matching event-triggered actions via v2 executor."""
    from .executor_v2 import execute_and_persist
    from .engine_v2 import ExecutionContext

    created_tasks = []
    now = datetime.now()

    for practice, action in matches:
        # Check event params
        if not _matches_event_params(action, event_type, task_data, priority_data):
            continue

        # Build execution context
        ctx = ExecutionContext(
            now=now,
            entity_id=entity_id,
            practice={"id": practice.id, "name": practice.name},
            event_task=task_data,
            event_priority=priority_data,
        )

        # Execute via v2 engine + executor
        try:
            result = execute_and_persist(
                action, ctx,
                practice_id=practice.id,
                created_by=created_by,
            )

            if result.get("error"):
                if result["error"] != "Conditions not met":
                    logger.debug(f"Event trigger for {practice.name} skipped: {result['error']}")
                continue

            task_count = result.get("tasks", 0)
            collation_count = result.get("collations", 0)

            if task_count > 0 or collation_count > 0:
                created_tasks.append({
                    "practice_id": practice.id,
                    "practice_name": practice.name,
                    "tasks_created": task_count,
                    "collations_created": collation_count,
                })
                logger.info(
                    f"Event trigger created {task_count} task(s), "
                    f"{collation_count} collation(s) from practice '{practice.name}'"
                )

        except Exception as e:
            logger.error(f"Failed to execute event trigger for {practice.name}: {e}")

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
    task_completion triggers and executes them if conditions match.

    Args:
        task_id: ID of the completed task
        entity_id: Entity that owns the task
        task_data: Optional pre-loaded task data (avoids extra DB query)
        created_by: User ID to set as creator for any generated tasks

    Returns:
        List of dicts describing created entities
    """
    logger.debug(f"on_task_completed: task={task_id}, entity={entity_id}")

    if task_data is None:
        task_data = _get_task(task_id)
    if not task_data:
        logger.warning(f"Task not found: {task_id}")
        return []

    graph = _get_graph(entity_id)
    matches = _find_practices_with_event_actions(graph, EventType.TASK_COMPLETION)
    if not matches:
        return []

    return _execute_event_actions(
        matches, EventType.TASK_COMPLETION,
        entity_id, task_data=task_data, created_by=created_by,
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

    Skipped if task was created by a trigger to prevent infinite recursion.
    """
    if from_trigger:
        return []

    logger.debug(f"on_task_created: task={task_id}, entity={entity_id}")

    if task_data is None:
        task_data = _get_task(task_id)
    if not task_data:
        return []

    graph = _get_graph(entity_id)
    matches = _find_practices_with_event_actions(graph, EventType.TASK_CREATION)
    if not matches:
        return []

    return _execute_event_actions(
        matches, EventType.TASK_CREATION,
        entity_id, task_data=task_data, created_by=created_by,
    )


def on_priority_created(
    priority_id: str,
    entity_id: str,
    priority_data: dict | None = None,
    created_by: int | None = None,
    from_trigger: bool = False,
) -> list[dict]:
    """
    Handle priority creation event.

    Skipped if priority was created by a trigger to prevent infinite recursion.
    """
    if from_trigger:
        return []

    logger.debug(f"on_priority_created: priority={priority_id}, entity={entity_id}")

    graph = _get_graph(entity_id)

    if priority_data is None:
        priority = graph.nodes.get(priority_id)
        if priority:
            priority_data = {
                "id": priority.id,
                "name": priority.name,
                "priority_type": priority.priority_type.value,
            }

    if not priority_data:
        return []

    if "ancestors" not in priority_data:
        priority_data["ancestors"] = _get_ancestors(graph, priority_id)

    matches = _find_practices_with_event_actions(graph, EventType.PRIORITY_CREATION)
    if not matches:
        return []

    return _execute_event_actions(
        matches, EventType.PRIORITY_CREATION,
        entity_id, priority_data=priority_data, created_by=created_by,
    )


def on_priority_completed(
    priority_id: str,
    entity_id: str,
    priority_data: dict | None = None,
    created_by: int | None = None,
) -> list[dict]:
    """
    Handle priority completion event.

    Called when a priority (typically a Goal) is marked complete.
    Finds Practices with priority_completion triggers and executes them.
    """
    logger.debug(f"on_priority_completed: priority={priority_id}, entity={entity_id}")

    graph = _get_graph(entity_id)

    # Build priority data with ancestors
    if priority_data is None:
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

    # Add ancestors for condition matching
    if "ancestors" not in priority_data:
        priority_data["ancestors"] = _get_ancestors(graph, priority_id)

    matches = _find_practices_with_event_actions(graph, EventType.PRIORITY_COMPLETION)
    if not matches:
        return []

    return _execute_event_actions(
        matches, EventType.PRIORITY_COMPLETION,
        entity_id, priority_data=priority_data, created_by=created_by,
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

    If new_status is 'completed', delegates to on_priority_completed.
    Otherwise checks for priority_status_change triggers.
    """
    logger.debug(f"on_priority_status_changed: priority={priority_id}, status={new_status}")

    if new_status == "completed":
        return on_priority_completed(
            priority_id, entity_id, priority_data, created_by
        )

    # For non-completion status changes, check status_change triggers
    graph = _get_graph(entity_id)

    if priority_data is None:
        priority = graph.nodes.get(priority_id)
        if priority:
            priority_data = {
                "id": priority.id,
                "name": priority.name,
                "priority_type": priority.priority_type.value,
                "status": new_status,
            }

    if not priority_data:
        return []

    if "ancestors" not in priority_data:
        priority_data["ancestors"] = _get_ancestors(graph, priority_id)

    matches = _find_practices_with_event_actions(graph, EventType.PRIORITY_STATUS_CHANGE)
    if not matches:
        return []

    return _execute_event_actions(
        matches, EventType.PRIORITY_STATUS_CHANGE,
        entity_id, priority_data=priority_data, created_by=created_by,
    )
