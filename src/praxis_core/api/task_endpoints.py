"""Task API endpoints."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Form, Depends
from fastapi.responses import JSONResponse

from praxis_core.model import TaskStatus, User
from praxis_core.persistence import (
    create_task,
    get_task,
    list_tasks,
    update_task,
    update_task_status,
    delete_task,
)
from praxis_core.prioritization import rank_tasks
from praxis_core.api.auth import get_current_user, get_current_user_optional


router = APIRouter()


def _get_graph(entity_id: str | None = None):
    """Import here to avoid circular import."""
    from praxis_core.api.app import get_graph
    return get_graph(entity_id=entity_id)


def _serialize_priority(p):
    """Import here to avoid circular import."""
    from praxis_core.api.app import serialize_priority
    return serialize_priority(p)


def _serialize_task(t, render_markdown: bool = False, current_user=None, graph=None):
    """Import here to avoid circular import."""
    from praxis_core.api.app import serialize_task
    return serialize_task(t, render_markdown=render_markdown, current_user=current_user, graph=graph)


def _get_owner_user_id(entity_id: str) -> int | None:
    """Look up the user_id for a personal entity."""
    from praxis_core.persistence import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE entity_id = ?", (entity_id,)
        ).fetchone()
        return row["id"] if row else None


# -----------------------------------------------------------------------------
# Task Permission Helpers
# -----------------------------------------------------------------------------

def get_task_permission(task, user: User | None, graph=None) -> str | None:
    """
    Determine a user's permission level on a task.

    Returns one of:
      - 'owner': User's entity owns the task
      - 'assignee': User is assigned to the task
      - 'creator': User created the task
      - 'contributor': User has contributor/editor permission on the priority
      - 'viewer': User has viewer permission on the priority
      - None: No access
    """
    if user is None:
        return None

    # Owner: task belongs to user's entity
    if task.entity_id == user.entity_id:
        return "owner"

    # Assignee: task is assigned to user
    if task.assigned_to == user.id:
        return "assignee"

    # Creator: user created the task
    if task.created_by == user.id:
        return "creator"

    # Check priority-level permissions
    if task.priority_id and graph:
        priority_perm = graph.get_permission(task.priority_id, user.entity_id)
        if priority_perm in ("contributor", "editor"):
            return "contributor"
        if priority_perm == "viewer":
            return "viewer"
        if priority_perm == "owner":
            # User owns the priority but not this specific task
            return "owner"

    return None


def can_view_task(permission: str | None) -> bool:
    """Check if user can view the task."""
    return permission is not None


def can_edit_task(permission: str | None) -> bool:
    """Check if user can edit task properties (name, notes, due date)."""
    return permission in ("owner", "assignee")


def can_toggle_task(permission: str | None) -> bool:
    """Check if user can toggle task done/undone."""
    return permission in ("owner", "assignee")


def can_delete_task(permission: str | None) -> bool:
    """Check if user can delete the task."""
    return permission == "owner"


def can_create_task_on_priority(priority_perm: str | None) -> bool:
    """Check if user can create tasks under a priority."""
    return priority_perm in ("owner", "contributor", "editor")


@router.post("")
async def create_task_endpoint(
    name: Annotated[str, Form()],
    priority_id: Annotated[str | None, Form()] = None,
    due_date: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
    user: User | None = Depends(get_current_user_optional),
):
    """Create a new task."""
    if not name.strip():
        return JSONResponse({"error": "Name is required"}, status_code=400)

    creator_entity_id = user.entity_id if user else None
    created_by = user.id if user else None

    # Parse due_date if provided
    parsed_due_date = None
    if due_date:
        try:
            parsed_due_date = datetime.fromisoformat(due_date)
        except ValueError:
            pass

    # Determine entity_id and assigned_to based on priority settings
    task_entity_id = creator_entity_id
    assigned_to = None

    clean_priority_id = priority_id.strip() if priority_id else None
    if clean_priority_id:
        # Look up priority to get assignment settings
        graph = _get_graph(creator_entity_id)
        priority = graph.get(clean_priority_id)
        if priority:
            # Task belongs to priority owner's entity
            task_entity_id = priority.entity_id

            # Determine assignment based on priority settings
            if priority.auto_assign_owner and priority.entity_id:
                # Assign to priority owner
                assigned_to = _get_owner_user_id(priority.entity_id)
            elif priority.auto_assign_creator:
                # Assign to task creator
                assigned_to = created_by
            # else: unassigned (manual claim)

    task = create_task(
        name=name.strip(),
        notes=notes.strip() if notes else None,
        due_date=parsed_due_date,
        priority_id=clean_priority_id,
        entity_id=task_entity_id,
        assigned_to=assigned_to,
        created_by=created_by,
    )

    # Get graph for serialization (may already be created above)
    if 'graph' not in locals():
        graph = _get_graph(creator_entity_id)

    return {"task": _serialize_task(task, current_user=user, graph=graph)}


@router.get("")
async def list_tasks_endpoint(
    priority: str | None = None,
    status: str | None = None,
    inbox: bool = False,
    user: User | None = Depends(get_current_user_optional),
):
    """List tasks with optional filters, ranked by priority score.

    For the main queue (no priority filter), shows:
    - Tasks assigned to current user (from any entity)
    - Unassigned tasks owned by user's entity
    """
    task_status = None
    if status:
        try:
            task_status = TaskStatus(status)
        except ValueError:
            pass

    entity_id = user.entity_id if user else None
    user_id = user.id if user else None

    # Pass both entity_id and user_id for combined queue filtering
    tasks = list_tasks(
        priority_id=priority,
        status=task_status,
        entity_id=entity_id,
        assigned_to=user_id,
        inbox_only=inbox,
    )
    graph = _get_graph(entity_id)
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    # Rank tasks by importance + urgency
    scored_tasks = rank_tasks(tasks, graph)

    # Serialize with score included
    serialized = []
    for st in scored_tasks:
        task_data = _serialize_task(st.task, current_user=user, graph=graph)
        task_data["score"] = round(st.score, 2)
        task_data["importance"] = round(st.importance, 1)
        task_data["urgency"] = round(st.urgency, 1)
        serialized.append(task_data)

    return {
        "tasks": serialized,
        "priorities": [_serialize_priority(p) for p in priorities],
    }


@router.get("/{task_id}")
async def get_task_endpoint(
    task_id: str,
    user: User | None = Depends(get_current_user_optional),
):
    """Get a single task."""
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    return {
        "task": _serialize_task(task, render_markdown=True, current_user=user, graph=graph),
        "priorities": [_serialize_priority(p) for p in priorities],
        "task_statuses": [s.value for s in TaskStatus],
    }


@router.get("/{task_id}/edit")
async def get_task_for_edit(
    task_id: str,
    user: User | None = Depends(get_current_user_optional),
):
    """Get task data for edit form (raw, no markdown rendering)."""
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    return {
        "task": _serialize_task(task, render_markdown=False, current_user=user, graph=graph),
        "priorities": [_serialize_priority(p) for p in priorities],
        "task_statuses": [s.value for s in TaskStatus],
        "edit_mode": True,
    }


@router.post("/{task_id}")
async def update_task_endpoint(
    task_id: str,
    name: Annotated[str, Form()],
    status: Annotated[str, Form()],
    priority_id: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
    due_date: Annotated[str | None, Form()] = None,
    user: User | None = Depends(get_current_user_optional),
):
    """Update a task and return updated data."""
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    # Permission check
    graph = _get_graph(user.entity_id if user else None)
    permission = get_task_permission(task, user, graph)
    if not can_edit_task(permission):
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    # Parse due_date if provided
    parsed_due_date = None
    if due_date:
        try:
            parsed_due_date = datetime.fromisoformat(due_date)
        except ValueError:
            pass

    update_task(
        task_id,
        name=name.strip(),
        status=TaskStatus(status),
        priority_id=priority_id.strip() if priority_id else "",
        notes=notes.strip() if notes else "",
        due_date=parsed_due_date,
    )

    # Return updated data
    return await get_task_endpoint(task_id, user)


@router.post("/{task_id}/toggle")
async def toggle_task(
    task_id: str,
    user: User | None = Depends(get_current_user_optional),
):
    """Toggle task between done and queued."""
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    # Permission check
    graph = _get_graph(user.entity_id if user else None)
    permission = get_task_permission(task, user, graph)
    if not can_toggle_task(permission):
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    new_status = TaskStatus.QUEUED if task.status == TaskStatus.DONE else TaskStatus.DONE
    update_task_status(task_id, new_status)

    task = get_task(task_id)
    task_data = _serialize_task(task, current_user=user, graph=graph)

    # Include score data for the row display
    scored_tasks = rank_tasks([task], graph)
    if scored_tasks:
        st = scored_tasks[0]
        task_data["score"] = round(st.score, 2)
        task_data["importance"] = round(st.importance, 1)
        task_data["urgency"] = round(st.urgency, 1)

    return {"task": task_data}


@router.post("/{task_id}/properties")
async def update_task_properties(
    task_id: str,
    name: Annotated[str, Form()],
    priority_id: Annotated[str | None, Form()] = None,
    due_date: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
    user: User | None = Depends(get_current_user_optional),
):
    """Update task properties and notes together."""
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    # Permission check
    graph = _get_graph(user.entity_id if user else None)
    permission = get_task_permission(task, user, graph)
    if not can_edit_task(permission):
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    # Validate name
    if not name.strip():
        return JSONResponse({"error": "Name is required"}, status_code=400)

    # Parse due_date if provided
    parsed_due_date = None
    if due_date:
        try:
            parsed_due_date = datetime.fromisoformat(due_date)
        except ValueError:
            pass

    update_task(
        task_id,
        name=name.strip(),
        status=task.status,  # Preserve existing status
        priority_id=priority_id.strip() if priority_id else "",
        notes=notes.strip() if notes else "",
        due_date=parsed_due_date,
    )

    # Return updated task with both raw and rendered notes
    task = get_task(task_id)
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    task_data = _serialize_task(task, render_markdown=True, current_user=user, graph=graph)
    task_data["notes_raw"] = task.notes or ""

    return {
        "task": task_data,
        "priorities": [_serialize_priority(p) for p in priorities],
        "task_statuses": [s.value for s in TaskStatus],
    }


@router.post("/{task_id}/notes")
async def update_task_notes(
    task_id: str,
    notes: Annotated[str | None, Form()] = None,
    user: User | None = Depends(get_current_user_optional),
):
    """Update task notes independently."""
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    # Permission check
    graph = _get_graph(user.entity_id if user else None)
    permission = get_task_permission(task, user, graph)
    if not can_edit_task(permission):
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    update_task(
        task_id,
        name=task.name,
        status=task.status,
        priority_id=task.priority_id or "",
        notes=notes.strip() if notes else "",
        due_date=task.due_date,
    )

    task = get_task(task_id)
    task_data = _serialize_task(task, render_markdown=True, current_user=user, graph=graph)
    task_data["notes_raw"] = task.notes or ""

    return {
        "task": task_data,
        "item_type": "task",
        "item_id": task.id,
        "notes": task_data.get("notes", ""),
        "notes_raw": task.notes or "",
    }


@router.delete("/{task_id}")
async def delete_task_endpoint(
    task_id: str,
    user: User | None = Depends(get_current_user_optional),
):
    """Delete a task."""
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    # Permission check - only owner can delete
    graph = _get_graph(user.entity_id if user else None)
    permission = get_task_permission(task, user, graph)
    if not can_delete_task(permission):
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    delete_task(task_id)
    return {"success": True, "deleted_id": task_id}
