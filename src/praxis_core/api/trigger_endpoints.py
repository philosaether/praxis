"""Trigger API endpoints for Practice-based trigger execution."""

from datetime import datetime, timedelta
import logging
import os

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse

from praxis_core.model import Practice, PriorityType, User
from praxis_core.model.practice_triggers import PracticeTrigger, TriggerEventType
from praxis_core.triggers import (
    TriggerContext,
    should_practice_trigger_fire,
    execute_practice_trigger,
)
from praxis_core.persistence import create_task, get_connection, PriorityGraph
from praxis_core.api.auth import get_current_user_optional


logger = logging.getLogger(__name__)
router = APIRouter()

# Cron API key from environment (set in Fly.io secrets or .env)
CRON_API_KEY = os.environ.get("CRON_API_KEY", "")


def _get_graph(entity_id: str | None = None):
    """Import here to avoid circular import."""
    from praxis_core.api.app import get_graph
    return get_graph(entity_id=entity_id)


def _serialize_task(t, render_markdown: bool = False, current_user=None, graph=None):
    """Import here to avoid circular import."""
    from praxis_core.api.app import serialize_task
    return serialize_task(t, render_markdown=render_markdown, current_user=current_user, graph=graph)


@router.post("/practices/check-triggers")
async def check_practice_triggers(
    user: User | None = Depends(get_current_user_optional),
):
    """
    Check and execute scheduled Practice triggers.

    Called by:
    - Browser polling (every 60s when tab is visible)
    - App launch catch-up
    - Midnight cron job

    For each Practice with a scheduled trigger:
    1. Check if the trigger should fire (time passed, not yet fired today)
    2. If so, create task from template
    3. Update last_triggered_at on the Practice
    4. Return list of created tasks
    """
    if not user:
        return JSONResponse({"error": "Authentication required"}, status_code=401)

    entity_id = user.entity_id
    graph = _get_graph(entity_id=entity_id)
    now = datetime.now()

    created_tasks = []
    errors = []

    # Get all Practices for this entity
    practices = [
        p for p in graph.nodes.values()
        if isinstance(p, Practice) and p.priority_type == PriorityType.PRACTICE
    ]

    for practice in practices:
        # Skip practices without trigger config
        if not practice.trigger_config:
            continue

        # Parse trigger config
        trigger = PracticeTrigger.from_json_or_none(practice.trigger_config)
        if not trigger:
            logger.warning(f"Invalid trigger config for practice {practice.id}")
            continue

        # Only process scheduled triggers (event triggers handled elsewhere)
        if trigger.event.type != TriggerEventType.SCHEDULE:
            continue

        # Check if trigger should fire
        if not should_practice_trigger_fire(trigger, practice.last_triggered_at, now):
            continue

        # Build context for execution
        ctx = TriggerContext(
            now=now,
            entity_id=entity_id,
            practice={
                "id": practice.id,
                "name": practice.name,
            },
        )

        # Execute trigger to get action parameters
        result = execute_practice_trigger(trigger, practice.id, ctx)

        if not result.success:
            if result.error_message != "Conditions not met":
                logger.debug(f"Trigger for {practice.name} skipped: {result.error_message}")
            continue

        # Process actions
        for action in result.actions_taken:
            if action["type"] == "create_task":
                params = action["params"]
                try:
                    task = create_task(
                        name=params["name"],
                        notes=params.get("notes"),
                        due_date=params.get("due_date"),
                        priority_id=params.get("priority_id"),
                        entity_id=entity_id,
                        created_by=user.id,
                    )
                    created_tasks.append(task)
                    logger.info(f"Created task '{task.name}' from practice '{practice.name}'")
                except Exception as e:
                    errors.append({
                        "practice_id": practice.id,
                        "practice_name": practice.name,
                        "error": str(e),
                    })
                    logger.error(f"Failed to create task for practice {practice.id}: {e}")

            elif action["type"] == "collate_tasks":
                # TODO: Implement collate_tasks action
                # This batches existing tasks into a single task with subtasks
                logger.debug(f"collate_tasks action not yet implemented for practice {practice.id}")

        # Update last_triggered_at on the Practice
        practice.last_triggered_at = now
        practice.updated_at = now
        graph.save_priority(practice)

    # Serialize created tasks for response
    serialized_tasks = [
        _serialize_task(t, current_user=user, graph=graph)
        for t in created_tasks
    ]

    return JSONResponse({
        "tasks_created": len(created_tasks),
        "tasks": serialized_tasks,
        "errors": errors if errors else None,
    })


@router.post("/practices/{practice_id}/fire-trigger")
async def fire_practice_trigger(
    practice_id: str,
    user: User | None = Depends(get_current_user_optional),
):
    """
    Manually fire a Practice's trigger (for testing/debugging).

    This bypasses the schedule check and fires the trigger immediately.
    """
    if not user:
        return JSONResponse({"error": "Authentication required"}, status_code=401)

    entity_id = user.entity_id
    graph = _get_graph(entity_id=entity_id)

    # Get the practice
    practice = graph.nodes.get(practice_id)
    if not practice:
        return JSONResponse({"error": "Practice not found"}, status_code=404)

    if not isinstance(practice, Practice):
        return JSONResponse({"error": "Not a practice"}, status_code=400)

    # Check permission (must be owner)
    if practice.entity_id != entity_id:
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    if not practice.trigger_config:
        return JSONResponse({"error": "Practice has no trigger configured"}, status_code=400)

    trigger = PracticeTrigger.from_json_or_none(practice.trigger_config)
    if not trigger:
        return JSONResponse({"error": "Invalid trigger configuration"}, status_code=400)

    now = datetime.now()

    # Build context
    ctx = TriggerContext(
        now=now,
        entity_id=entity_id,
        practice={
            "id": practice.id,
            "name": practice.name,
        },
    )

    # Execute trigger (bypassing schedule check)
    result = execute_practice_trigger(trigger, practice.id, ctx)

    if not result.success:
        return JSONResponse({
            "success": False,
            "error": result.error_message,
        })

    created_tasks = []
    errors = []

    for action in result.actions_taken:
        if action["type"] == "create_task":
            params = action["params"]
            try:
                task = create_task(
                    name=params["name"],
                    notes=params.get("notes"),
                    due_date=params.get("due_date"),
                    priority_id=params.get("priority_id"),
                    entity_id=entity_id,
                    created_by=user.id,
                )
                created_tasks.append(task)
            except Exception as e:
                errors.append(str(e))

    # Update last_triggered_at
    practice.last_triggered_at = now
    practice.updated_at = now
    graph.save_priority(practice)

    serialized_tasks = [
        _serialize_task(t, current_user=user, graph=graph)
        for t in created_tasks
    ]

    return JSONResponse({
        "success": True,
        "tasks_created": len(created_tasks),
        "tasks": serialized_tasks,
        "errors": errors if errors else None,
    })


# -----------------------------------------------------------------------------
# Midnight Cron Endpoint
# -----------------------------------------------------------------------------

def _get_entities_with_triggers() -> list[str]:
    """Get all entity IDs that have Practices with trigger_config set."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT DISTINCT entity_id
            FROM priorities
            WHERE priority_type = 'practice'
            AND trigger_config IS NOT NULL
            AND trigger_config != ''
            AND entity_id IS NOT NULL
        """).fetchall()
        return [row["entity_id"] for row in rows]


def _calculate_missed_days(
    trigger: PracticeTrigger,
    last_triggered_at: datetime | None,
    now: datetime,
) -> int:
    """Calculate how many days a trigger was missed."""
    if not last_triggered_at:
        return 1  # First time firing, no catch-up needed

    params = trigger.event.params
    interval = params.get("interval", "daily")

    if interval == "daily" or interval == "weekdays":
        # Count days since last trigger
        days_missed = (now.date() - last_triggered_at.date()).days - 1
        if interval == "weekdays":
            # Subtract weekend days
            current = last_triggered_at.date() + timedelta(days=1)
            while current < now.date():
                if current.weekday() < 5:  # Monday-Friday
                    pass  # Count this day
                else:
                    days_missed -= 1
                current += timedelta(days=1)
        return max(0, days_missed)

    elif interval == "weekly":
        # Count weeks since last trigger
        weeks_missed = ((now.date() - last_triggered_at.date()).days // 7) - 1
        return max(0, weeks_missed)

    return 0


def _fire_trigger_with_catchup(
    practice: Practice,
    trigger: PracticeTrigger,
    entity_id: str,
    now: datetime,
    graph: PriorityGraph,
) -> dict:
    """Fire a trigger with catch-up logic for missed days."""
    missed_days = _calculate_missed_days(trigger, practice.last_triggered_at, now)

    # Build context
    ctx = TriggerContext(
        now=now,
        entity_id=entity_id,
        practice={
            "id": practice.id,
            "name": practice.name,
        },
    )

    # Execute trigger
    result = execute_practice_trigger(trigger, practice.id, ctx)

    if not result.success:
        return {
            "practice_id": practice.id,
            "practice_name": practice.name,
            "success": False,
            "error": result.error_message,
        }

    created_tasks = []

    for action in result.actions_taken:
        if action["type"] == "create_task":
            params = action["params"]
            task_name = params["name"]
            task_notes = params.get("notes") or ""

            # Add catch-up note if days were missed
            if missed_days > 0:
                catchup_note = f"\n\n---\nCatch-up: {missed_days} day(s) missed while offline."
                task_notes = task_notes + catchup_note

            try:
                task = create_task(
                    name=task_name,
                    notes=task_notes if task_notes else None,
                    due_date=params.get("due_date"),
                    priority_id=params.get("priority_id"),
                    entity_id=entity_id,
                )
                created_tasks.append({
                    "id": task.id,
                    "name": task.name,
                })
                logger.info(f"Cron: Created task '{task.name}' for entity {entity_id}")
            except Exception as e:
                logger.error(f"Cron: Failed to create task: {e}")

    # Update last_triggered_at
    practice.last_triggered_at = now
    practice.updated_at = now
    graph.save_priority(practice)

    return {
        "practice_id": practice.id,
        "practice_name": practice.name,
        "success": True,
        "tasks_created": len(created_tasks),
        "missed_days": missed_days,
    }


@router.post("/cron/midnight")
async def midnight_cron(
    x_cron_key: str | None = Header(None, alias="X-Cron-Key"),
):
    """
    Midnight cron endpoint for firing missed triggers.

    Called by external cron job (Fly.io scheduled machine, GitHub Actions, etc.)
    at midnight to ensure triggers fire for users who weren't active.

    Authentication: Requires X-Cron-Key header matching CRON_API_KEY env var.

    For each entity with scheduled triggers:
    1. Check which triggers should have fired today but didn't
    2. Fire them with catch-up logic (notes include missed day count)
    3. Update last_triggered_at
    """
    # Validate cron key
    if not CRON_API_KEY:
        logger.warning("Cron endpoint called but CRON_API_KEY not configured")
        return JSONResponse(
            {"error": "Cron endpoint not configured"},
            status_code=503,
        )

    if x_cron_key != CRON_API_KEY:
        logger.warning("Cron endpoint called with invalid key")
        return JSONResponse(
            {"error": "Invalid cron key"},
            status_code=401,
        )

    now = datetime.now()
    logger.info(f"Midnight cron started at {now.isoformat()}")

    # Get all entities with triggers
    entity_ids = _get_entities_with_triggers()
    logger.info(f"Found {len(entity_ids)} entities with triggers")

    results = {
        "timestamp": now.isoformat(),
        "entities_processed": 0,
        "triggers_fired": 0,
        "tasks_created": 0,
        "errors": [],
        "details": [],
    }

    for entity_id in entity_ids:
        try:
            # Load graph for this entity
            graph = PriorityGraph(get_connection, entity_id=entity_id)
            graph.load()

            # Get all Practices with triggers
            practices = [
                p for p in graph.nodes.values()
                if isinstance(p, Practice)
                and p.priority_type == PriorityType.PRACTICE
                and p.trigger_config
            ]

            for practice in practices:
                trigger = PracticeTrigger.from_json_or_none(practice.trigger_config)
                if not trigger or not trigger.enabled:
                    continue

                # Only process scheduled triggers
                if trigger.event.type != TriggerEventType.SCHEDULE:
                    continue

                # Check if trigger should fire
                if not should_practice_trigger_fire(trigger, practice.last_triggered_at, now):
                    continue

                # Fire trigger with catch-up
                result = _fire_trigger_with_catchup(
                    practice, trigger, entity_id, now, graph
                )

                results["details"].append(result)

                if result.get("success"):
                    results["triggers_fired"] += 1
                    results["tasks_created"] += result.get("tasks_created", 0)
                else:
                    results["errors"].append({
                        "entity_id": entity_id,
                        "practice_id": practice.id,
                        "error": result.get("error"),
                    })

            results["entities_processed"] += 1

        except Exception as e:
            logger.error(f"Cron: Error processing entity {entity_id}: {e}")
            results["errors"].append({
                "entity_id": entity_id,
                "error": str(e),
            })

    logger.info(
        f"Midnight cron completed: {results['entities_processed']} entities, "
        f"{results['triggers_fired']} triggers, {results['tasks_created']} tasks"
    )

    return JSONResponse(results)
