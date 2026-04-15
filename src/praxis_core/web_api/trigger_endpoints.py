"""Trigger API endpoints for Practice-based trigger execution."""

from datetime import datetime, timedelta
import logging
import os

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse

from praxis_core.model import Practice, PriorityType, User
from praxis_core.dsl import PracticeConfig, PracticeAction, should_schedule_fire
from praxis_core.persistence import create_task, get_connection, PriorityGraph
from praxis_core.web_api.auth import get_current_user_optional


logger = logging.getLogger(__name__)
router = APIRouter()

# Cron API key from environment (set in Fly.io secrets or .env)
CRON_API_KEY = os.environ.get("CRON_API_KEY", "")


def _get_graph(entity_id: str | None = None):
    """Import here to avoid circular import."""
    from praxis_core.web_api.app import get_graph
    return get_graph(entity_id=entity_id)


def _serialize_task(t, render_markdown: bool = False, current_user=None, graph=None):
    """Import here to avoid circular import."""
    from praxis_core.web_api.app import serialize_task
    return serialize_task(t, render_markdown=render_markdown, current_user=current_user, graph=graph)


def _get_scheduled_actions(practice: Practice) -> list[PracticeAction]:
    """Get all schedule-triggered actions from a Practice's actions_config."""
    if not practice.actions_config:
        return []
    try:
        config = PracticeConfig.from_json(practice.actions_config)
    except (ValueError, KeyError):
        logger.warning(f"Invalid actions_config for practice {practice.id}")
        return []

    return [a for a in config.actions if a.trigger.schedule]


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

    For each Practice with scheduled actions:
    1. Check if the schedule should fire (time passed, not yet fired today)
    2. If so, execute the action via v2 engine
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
        if isinstance(p, Practice)
        and p.priority_type == PriorityType.PRACTICE
        and p.actions_config
    ]

    for practice in practices:
        actions = _get_scheduled_actions(practice)
        if not actions:
            continue

        fired = False
        for action in actions:
            schedule = action.trigger.schedule
            if not should_schedule_fire(schedule, now, practice.last_triggered_at):
                continue

            # Execute via v2 engine
            try:
                result = _execute_action(action, practice, entity_id, now, user.id)
                if result.get("error"):
                    if result["error"] != "Conditions not met":
                        logger.debug(f"Trigger for {practice.name} skipped: {result['error']}")
                    continue

                fired = True
                tasks_created = result.get("tasks", 0)
                if tasks_created > 0:
                    created_tasks.append({
                        "practice_id": practice.id,
                        "practice_name": practice.name,
                        "tasks_created": tasks_created,
                    })
                    logger.info(f"Created {tasks_created} task(s) from practice '{practice.name}'")

            except Exception as e:
                errors.append({
                    "practice_id": practice.id,
                    "practice_name": practice.name,
                    "error": str(e),
                })
                logger.error(f"Failed to execute trigger for practice {practice.id}: {e}")

        # Update last_triggered_at if any action fired
        if fired:
            practice.last_triggered_at = now
            practice.updated_at = now
            graph.save_priority(practice)

    return JSONResponse({
        "tasks_created": sum(t.get("tasks_created", 0) for t in created_tasks),
        "tasks": created_tasks,
        "errors": errors if errors else None,
    })


def _execute_action(
    action: PracticeAction,
    practice: Practice,
    entity_id: str,
    now: datetime,
    created_by: int | None = None,
) -> dict:
    """Execute a single practice action via v2 engine + executor."""
    from praxis_core.practices.engine_v2 import ExecutionContext
    from praxis_core.practices.executor_v2 import execute_and_persist

    ctx = ExecutionContext(
        now=now,
        entity_id=entity_id,
        practice={"id": practice.id, "name": practice.name},
    )

    return execute_and_persist(
        action, ctx,
        practice_id=practice.id,
        created_by=created_by,
    )


@router.post("/practices/{practice_id}/fire-trigger")
async def fire_practice_trigger(
    practice_id: str,
    user: User | None = Depends(get_current_user_optional),
):
    """
    Manually fire a Practice's trigger (for testing/debugging).

    Bypasses the schedule check and fires all actions immediately.
    """
    if not user:
        return JSONResponse({"error": "Authentication required"}, status_code=401)

    entity_id = user.entity_id
    graph = _get_graph(entity_id=entity_id)

    practice = graph.nodes.get(practice_id)
    if not practice:
        return JSONResponse({"error": "Practice not found"}, status_code=404)
    if not isinstance(practice, Practice):
        return JSONResponse({"error": "Not a practice"}, status_code=400)
    if practice.entity_id != entity_id:
        return JSONResponse({"error": "Permission denied"}, status_code=403)
    if not practice.actions_config:
        return JSONResponse({"error": "Practice has no actions configured"}, status_code=400)

    try:
        config = PracticeConfig.from_json(practice.actions_config)
    except (ValueError, KeyError):
        return JSONResponse({"error": "Invalid actions configuration"}, status_code=400)

    now = datetime.now()
    total_tasks = 0
    total_collations = 0
    errors = []

    for action in config.actions:
        try:
            result = _execute_action(action, practice, entity_id, now, user.id)
            if result.get("error"):
                errors.append(result["error"])
                continue
            total_tasks += result.get("tasks", 0)
            total_collations += result.get("collations", 0)
        except Exception as e:
            errors.append(str(e))

    # Update last_triggered_at
    practice.last_triggered_at = now
    practice.updated_at = now
    graph.save_priority(practice)

    return JSONResponse({
        "success": total_tasks > 0 or total_collations > 0 or not errors,
        "tasks_created": total_tasks,
        "collations_created": total_collations,
        "errors": errors if errors else None,
    })


# -----------------------------------------------------------------------------
# Midnight Cron Endpoint
# -----------------------------------------------------------------------------

def _get_entities_with_triggers() -> list[str]:
    """Get all entity IDs that have Practices with actions_config set."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT DISTINCT entity_id
            FROM priorities
            WHERE priority_type = 'practice'
            AND actions_config IS NOT NULL
            AND actions_config != ''
            AND entity_id IS NOT NULL
        """).fetchall()
        return [row["entity_id"] for row in rows]


@router.post("/cron/midnight")
async def midnight_cron(
    x_cron_key: str | None = Header(None, alias="X-Cron-Key"),
):
    """
    Midnight cron endpoint for firing missed triggers.

    Called by external cron job (Fly.io scheduled machine, GitHub Actions, etc.)
    at midnight to ensure triggers fire for users who weren't active.

    Authentication: Requires X-Cron-Key header matching CRON_API_KEY env var.
    """
    if not CRON_API_KEY:
        logger.warning("Cron endpoint called but CRON_API_KEY not configured")
        return JSONResponse({"error": "Cron endpoint not configured"}, status_code=503)

    if x_cron_key != CRON_API_KEY:
        logger.warning("Cron endpoint called with invalid key")
        return JSONResponse({"error": "Invalid cron key"}, status_code=401)

    now = datetime.now()
    logger.info(f"Midnight cron started at {now.isoformat()}")

    entity_ids = _get_entities_with_triggers()
    logger.info(f"Found {len(entity_ids)} entities with triggers")

    results = {
        "timestamp": now.isoformat(),
        "entities_processed": 0,
        "triggers_fired": 0,
        "tasks_created": 0,
        "errors": [],
    }

    for entity_id in entity_ids:
        try:
            graph = PriorityGraph(get_connection, entity_id=entity_id)
            graph.load()

            practices = [
                p for p in graph.nodes.values()
                if isinstance(p, Practice)
                and p.priority_type == PriorityType.PRACTICE
                and p.actions_config
            ]

            for practice in practices:
                actions = _get_scheduled_actions(practice)
                fired = False

                for action in actions:
                    schedule = action.trigger.schedule
                    if not should_schedule_fire(schedule, now, practice.last_triggered_at):
                        continue

                    try:
                        result = _execute_action(action, practice, entity_id, now)
                        if result.get("error"):
                            continue

                        fired = True
                        results["tasks_created"] += result.get("tasks", 0)

                    except Exception as e:
                        results["errors"].append({
                            "entity_id": entity_id,
                            "practice_id": practice.id,
                            "error": str(e),
                        })

                if fired:
                    results["triggers_fired"] += 1
                    practice.last_triggered_at = now
                    practice.updated_at = now
                    graph.save_priority(practice)

            results["entities_processed"] += 1

        except Exception as e:
            logger.error(f"Cron: Error processing entity {entity_id}: {e}")
            results["errors"].append({
                "entity_id": entity_id,
                "error": str(e),
            })

    # Outbox cleanup: hard-delete tasks in outbox for > 7 days
    from praxis_core.persistence.task_repo import purge_old_outbox_tasks
    try:
        purged = purge_old_outbox_tasks(days=7)
        results["outbox_purged"] = purged
        if purged > 0:
            logger.info(f"Cron: Purged {purged} outbox task(s) older than 7 days")
    except Exception as e:
        logger.error(f"Cron: Outbox purge failed: {e}")
        results["errors"].append({"step": "outbox_purge", "error": str(e)})

    logger.info(
        f"Midnight cron completed: {results['entities_processed']} entities, "
        f"{results['triggers_fired']} triggers, {results['tasks_created']} tasks"
    )

    return JSONResponse(results)
