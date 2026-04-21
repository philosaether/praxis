"""Trigger routes — practice trigger check, calling core directly."""

import logging
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from praxis_web.rendering import SESSION_COOKIE_NAME
from praxis_core.persistence import validate_session
from praxis_core.model import Practice, PriorityType
from praxis_core.dsl import PracticeConfig, PracticeAction, should_schedule_fire
from praxis_core.serialization import get_graph

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_user(request):
    """Get authenticated user from session cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    result = validate_session(token)
    if result is None:
        return None
    session, user = result
    return user


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


@router.post("/api/practices/check-triggers")
async def check_triggers(request: Request):
    """Check and execute scheduled Practice triggers.

    Called by browser polling (every 60s when tab is visible).
    """
    user = _get_user(request)
    if not user:
        return JSONResponse({"error": "Authentication required"}, status_code=401)

    entity_id = user.entity_id
    graph = get_graph(entity_id=entity_id)
    now = datetime.now()

    created_tasks = []
    errors = []

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

        if fired:
            practice.last_triggered_at = now
            practice.updated_at = now
            graph.save_priority(practice)

    return JSONResponse({
        "tasks_created": sum(t.get("tasks_created", 0) for t in created_tasks),
        "tasks": created_tasks,
        "errors": errors if errors else None,
    })
