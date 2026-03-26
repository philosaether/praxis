"""Task API endpoints."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from praxis_core.model import TaskStatus
from praxis_core.persistence import (
    get_task,
    list_tasks,
    update_task_status,
)


router = APIRouter()


def _get_graph():
    """Import here to avoid circular import."""
    from praxis_core.api.app import get_graph
    return get_graph()


def _serialize_priority(p):
    """Import here to avoid circular import."""
    from praxis_core.api.app import serialize_priority
    return serialize_priority(p)


def _serialize_task(t):
    """Import here to avoid circular import."""
    from praxis_core.api.app import serialize_task
    return serialize_task(t)


@router.get("")
async def list_tasks_endpoint(
    priority: str | None = None,
    status: str | None = None,
):
    """List tasks with optional filters."""
    task_status = None
    if status:
        try:
            task_status = TaskStatus(status)
        except ValueError:
            pass

    tasks = list_tasks(priority_id=priority, status=task_status)
    graph = _get_graph()
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    return {
        "tasks": [_serialize_task(t) for t in tasks],
        "priorities": [_serialize_priority(p) for p in priorities],
    }


@router.get("/{task_id}")
async def get_task_endpoint(task_id: int):
    """Get a single task."""
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    graph = _get_graph()
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    return {
        "task": _serialize_task(task),
        "priorities": [_serialize_priority(p) for p in priorities],
        "task_statuses": [s.value for s in TaskStatus],
    }


@router.post("/{task_id}/toggle")
async def toggle_task(task_id: int):
    """Toggle task between done and queued."""
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    new_status = TaskStatus.QUEUED if task.status == TaskStatus.DONE else TaskStatus.DONE
    update_task_status(task_id, new_status)

    task = get_task(task_id)
    return {"task": _serialize_task(task)}
