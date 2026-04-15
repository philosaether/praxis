"""Entity condition evaluators (task or event properties)."""

from praxis_core.dsl.conditions import EvaluationContext
from praxis_core.model import Task


def _evaluate_tagged(
    params: dict, task: Task | None, event: dict | None, ctx: EvaluationContext
) -> bool:
    """Check if entity has a specific tag."""
    tag = params.get("value") or params.get("tag", "")
    tag = tag.lower()

    if task is not None:
        tags = ctx.task_tags or set()
        return tag in {t.lower() for t in tags}

    if event is not None:
        event_tags = event.get("tags", [])
        return tag in {t.lower() for t in event_tags}

    return False


def _evaluate_not_tagged(
    params: dict, task: Task | None, event: dict | None, ctx: EvaluationContext
) -> bool:
    """Check if entity does not have a specific tag."""
    return not _evaluate_tagged(params, task, event, ctx)


def _evaluate_priority_type(
    params: dict, task: Task | None, event: dict | None
) -> bool:
    """Check entity's priority type."""
    expected_type = params.get("value") or params.get("type", "")

    if task is not None:
        # Task's priority type would need to be looked up
        # For now, check if task has priority_type attribute
        task_type = getattr(task, "priority_type", None)
        return str(task_type) == expected_type if task_type else False

    if event is not None:
        return event.get("priority_type") == expected_type

    return False


def _evaluate_priority_ancestor(
    params: dict, task: Task | None, event: dict | None, ctx: EvaluationContext
) -> bool:
    """Check if entity is under a specific priority ancestor."""
    ancestor = params.get("value") or params.get("ancestor", "")

    if task is not None:
        ancestors = ctx.task_ancestors or set()
        # ancestor could be a name or ID
        return ancestor in ancestors

    if event is not None:
        event_ancestors = event.get("ancestors", [])
        return ancestor in event_ancestors

    return False


def _evaluate_status(params: dict, task: Task | None, event: dict | None) -> bool:
    """Check entity status."""
    expected_status = params.get("value") or params.get("status", "")

    if task is not None:
        return task.status.value == expected_status

    if event is not None:
        return event.get("status") == expected_status

    return False


def _evaluate_in_location(params: dict, task: Task | None) -> bool:
    """Check if task is in inbox or outbox."""
    location = params.get("value") or params.get("location", "")

    if task is None:
        return False

    if location == "inbox":
        # Inbox = no priority assigned
        return task.priority_id is None

    if location == "outbox":
        # Outbox = marked for deletion (needs outbox field on Task)
        return getattr(task, "in_outbox", False)

    return False
