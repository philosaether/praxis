"""Task API endpoints."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse

from praxis_core.model import TaskStatus
from praxis_core.persistence import (
    create_task,
    get_task,
    list_tasks,
    update_task,
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


def _serialize_task(t, render_markdown: bool = False):
    """Import here to avoid circular import."""
    from praxis_core.api.app import serialize_task
    return serialize_task(t, render_markdown=render_markdown)


@router.post("")
async def create_task_endpoint():
    """Create a new task with default values."""
    task = create_task(title="New Task")
    return {"task": _serialize_task(task)}


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
        "task": _serialize_task(task, render_markdown=True),
        "priorities": [_serialize_priority(p) for p in priorities],
        "task_statuses": [s.value for s in TaskStatus],
    }


@router.get("/{task_id}/edit")
async def get_task_for_edit(task_id: int):
    """Get task data for edit form (raw, no markdown rendering)."""
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    graph = _get_graph()
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    return {
        "task": _serialize_task(task, render_markdown=False),
        "priorities": [_serialize_priority(p) for p in priorities],
        "task_statuses": [s.value for s in TaskStatus],
        "edit_mode": True,
    }


@router.post("/{task_id}")
async def update_task_endpoint(
    task_id: int,
    title: Annotated[str, Form()],
    status: Annotated[str, Form()],
    priority_id: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
    due_date: Annotated[str | None, Form()] = None,
):
    """Update a task and return updated data."""
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    # Parse due_date if provided
    parsed_due_date = None
    if due_date:
        try:
            parsed_due_date = datetime.fromisoformat(due_date)
        except ValueError:
            pass

    update_task(
        task_id,
        title=title.strip(),
        status=TaskStatus(status),
        priority_id=priority_id.strip() if priority_id else "",
        notes=notes.strip() if notes else "",
        due_date=parsed_due_date,
    )

    # Return updated data
    return await get_task_endpoint(task_id)


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


@router.post("/{task_id}/properties")
async def update_task_properties(
    task_id: int,
    title: Annotated[str, Form()],
    status: Annotated[str, Form()],
    priority_id: Annotated[str | None, Form()] = None,
    due_date: Annotated[str | None, Form()] = None,
):
    """Update task properties (everything except notes)."""
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    # Validate title
    if not title.strip():
        return JSONResponse({"error": "Title is required"}, status_code=400)

    # Parse due_date if provided
    parsed_due_date = None
    if due_date:
        try:
            parsed_due_date = datetime.fromisoformat(due_date)
        except ValueError:
            pass

    update_task(
        task_id,
        title=title.strip(),
        status=TaskStatus(status),
        priority_id=priority_id.strip() if priority_id else "",
        notes=task.notes or "",  # Preserve existing notes
        due_date=parsed_due_date,
    )

    # Return updated task with both raw and rendered notes
    task = get_task(task_id)
    graph = _get_graph()
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    task_data = _serialize_task(task, render_markdown=True)
    task_data["notes_raw"] = task.notes or ""

    return {
        "task": task_data,
        "priorities": [_serialize_priority(p) for p in priorities],
        "task_statuses": [s.value for s in TaskStatus],
    }


@router.post("/{task_id}/notes")
async def update_task_notes(
    task_id: int,
    notes: Annotated[str | None, Form()] = None,
):
    """Update task notes independently."""
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    update_task(
        task_id,
        title=task.title,
        status=task.status,
        priority_id=task.priority_id or "",
        notes=notes.strip() if notes else "",
        due_date=task.due_date,
    )

    task = get_task(task_id)
    task_data = _serialize_task(task, render_markdown=True)
    task_data["notes_raw"] = task.notes or ""

    return {
        "task": task_data,
        "item_type": "task",
        "item_id": task.id,
        "notes": task_data.get("notes", ""),
        "notes_raw": task.notes or "",
    }
