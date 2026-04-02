"""
Trigger Event Dispatcher.

Handles firing triggers when entity events occur:
- task_completed: When a task is marked done
- task_created: When a new task is created
- priority_completed: When a priority is marked complete
- priority_status_changed: When a priority status changes
"""

import asyncio
import logging
from datetime import datetime

from praxis_core.model.triggers import TriggerEventType, TriggerActionType
from praxis_core.persistence import (
    list_triggers_by_event_type,
    record_trigger_fire,
    create_task,
    get_task,
)
from praxis_core.triggers.engine import (
    TriggerContext,
    execute_trigger,
    execute_create_task,
    execute_collate_tasks,
)
from praxis_core.api.sse import (
    get_sse_manager,
    task_created_event,
    trigger_fired_event,
)


logger = logging.getLogger(__name__)


def on_task_completed(task_id: str, entity_id: str) -> None:
    """
    Handle task completion event.

    Called when a task is marked as done. Finds and executes any triggers
    listening for task_completed events that match the task.
    """
    try:
        task = get_task(task_id)
        if not task:
            logger.warning(f"on_task_completed: Task {task_id} not found")
            return

        # Get task data for context
        task_data = {
            "id": task.id,
            "name": task.name,
            "priority_id": task.priority_id,
            "tags": [],  # TODO: Load tags if needed
        }

        # Find triggers listening for task_completed
        triggers = list_triggers_by_event_type(
            event_type="task_completed",
            entity_id=entity_id,
            enabled_only=True,
        )

        now = datetime.now()
        for trigger in triggers:
            _try_fire_trigger(trigger, entity_id, now, event_task=task_data)

    except Exception as e:
        logger.error(f"Error in on_task_completed: {e}", exc_info=True)


def on_task_created(task_id: str, entity_id: str) -> None:
    """
    Handle task creation event.

    Called when a new task is created. Finds and executes any triggers
    listening for task_created events that match the task.
    """
    try:
        task = get_task(task_id)
        if not task:
            return

        task_data = {
            "id": task.id,
            "name": task.name,
            "priority_id": task.priority_id,
            "tags": [],
        }

        triggers = list_triggers_by_event_type(
            event_type="task_created",
            entity_id=entity_id,
            enabled_only=True,
        )

        now = datetime.now()
        for trigger in triggers:
            _try_fire_trigger(trigger, entity_id, now, event_task=task_data)

    except Exception as e:
        logger.error(f"Error in on_task_created: {e}", exc_info=True)


def on_priority_completed(priority_id: str, entity_id: str, priority_data: dict | None = None) -> None:
    """
    Handle priority completion event.

    Called when a priority is marked complete. Finds and executes any triggers
    listening for priority_completed events that match.
    """
    try:
        if not priority_data:
            from praxis_core.persistence.priority_persistence import get_priority
            priority = get_priority(priority_id)
            if not priority:
                return
            priority_data = {
                "id": priority.id,
                "name": priority.name,
                "priority_type": priority.priority_type.value if hasattr(priority.priority_type, 'value') else priority.priority_type,
            }

        triggers = list_triggers_by_event_type(
            event_type="priority_completed",
            entity_id=entity_id,
            enabled_only=True,
        )

        now = datetime.now()
        for trigger in triggers:
            _try_fire_trigger(trigger, entity_id, now, event_priority=priority_data)

    except Exception as e:
        logger.error(f"Error in on_priority_completed: {e}", exc_info=True)


def on_priority_status_changed(priority_id: str, entity_id: str, new_status: str, priority_data: dict | None = None) -> None:
    """
    Handle priority status change event.

    Called when a priority's status changes. Finds and executes any triggers
    listening for priority_status_changed events.
    """
    try:
        if not priority_data:
            from praxis_core.persistence.priority_persistence import get_priority
            priority = get_priority(priority_id)
            if not priority:
                return
            priority_data = {
                "id": priority.id,
                "name": priority.name,
                "priority_type": priority.priority_type.value if hasattr(priority.priority_type, 'value') else priority.priority_type,
                "status": new_status,
            }

        triggers = list_triggers_by_event_type(
            event_type="priority_status_changed",
            entity_id=entity_id,
            enabled_only=True,
        )

        now = datetime.now()
        for trigger in triggers:
            # Check if trigger cares about this specific status
            event_params = trigger.event.params
            if "status" in event_params and event_params["status"] != new_status:
                continue

            _try_fire_trigger(trigger, entity_id, now, event_priority=priority_data)

    except Exception as e:
        logger.error(f"Error in on_priority_status_changed: {e}", exc_info=True)


def _try_fire_trigger(
    trigger,
    entity_id: str,
    now: datetime,
    event_task: dict | None = None,
    event_priority: dict | None = None,
) -> bool:
    """
    Try to fire a single trigger.

    Returns True if the trigger was fired, False otherwise.
    """
    try:
        # Build context
        ctx = TriggerContext(
            now=now,
            entity_id=entity_id,
            event_task=event_task,
            event_priority=event_priority,
        )

        # If trigger is attached to a practice, load practice data
        if trigger.practice_id:
            from praxis_core.persistence.priority_persistence import get_priority
            practice = get_priority(trigger.practice_id)
            if practice:
                ctx.practice = {
                    "id": practice.id,
                    "name": practice.name,
                    "priority_type": practice.priority_type.value if hasattr(practice.priority_type, 'value') else practice.priority_type,
                }

        # Execute trigger
        result = execute_trigger(trigger, ctx)

        if not result.success:
            logger.debug(f"Trigger {trigger.name} conditions not met")
            return False

        # Process actions
        tasks_created = []
        for action in result.actions_taken:
            if action["type"] == "create_task":
                params = action["params"]
                task = create_task(
                    name=params["name"],
                    notes=params.get("notes"),
                    due_date=params.get("due_date"),
                    priority_id=params.get("priority_id"),
                    entity_id=entity_id,
                )
                tasks_created.append(task)
                logger.info(f"Trigger {trigger.name} created task: {task.name}")

            elif action["type"] == "collate_tasks":
                # TODO: Implement collation
                logger.info(f"Trigger {trigger.name} collation: {action['params'].get('batch_name')}")

        # Record that trigger fired
        record_trigger_fire(trigger.id, now)

        # Send SSE events
        _send_sse_events(trigger, entity_id, tasks_created)

        return True

    except Exception as e:
        logger.error(f"Error firing trigger {trigger.id}: {e}", exc_info=True)
        return False


def _send_sse_events(trigger, entity_id: str, tasks_created: list) -> None:
    """Send SSE events for trigger execution."""
    try:
        sse_manager = get_sse_manager()

        # Get or create event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, create one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # Send task_created events
        for task in tasks_created:
            event = task_created_event(task.id, task.priority_id)
            asyncio.ensure_future(sse_manager.broadcast(entity_id, event))

        # Send trigger_fired event
        action_type = "create_task" if tasks_created else "unknown"
        result_id = tasks_created[0].id if tasks_created else None
        event = trigger_fired_event(
            trigger_id=trigger.id,
            trigger_name=trigger.name,
            action_type=action_type,
            result_id=result_id,
        )
        asyncio.ensure_future(sse_manager.broadcast(entity_id, event))

    except Exception as e:
        logger.error(f"Error sending SSE events: {e}")
