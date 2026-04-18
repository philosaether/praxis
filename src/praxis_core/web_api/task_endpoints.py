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
    list_rules,
    get_tags_for_tasks,
)
from praxis_core.prioritization import rank_tasks
from praxis_core.web_api.auth import get_current_user, get_current_user_optional
from praxis_core.practices import on_task_completed


def _get_active_rules(entity_id: str | None):
    """Get active rules for scoring (system + user rules)."""
    return list_rules(entity_id=entity_id, include_system=True, enabled_only=True)


router = APIRouter()


def _get_graph(entity_id: str | None = None):
    """Import here to avoid circular import."""
    from praxis_core.web_api.app import get_graph
    return get_graph(entity_id=entity_id)


def _serialize_priority(p):
    """Import here to avoid circular import."""
    from praxis_core.web_api.app import serialize_priority
    return serialize_priority(p)


def _serialize_task(t, render_markdown: bool = False, current_user=None, graph=None):
    """Import here to avoid circular import."""
    from praxis_core.web_api.app import serialize_task
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
            return "owner"

    return None


def can_view_task(permission: str | None) -> bool:
    """Check if user can view the task."""
    return permission is not None


def can_edit_task(permission: str | None) -> bool:
    """Check if user can edit task properties (name, notes, due date)."""
    return permission in ("owner", "creator")


def can_toggle_task(permission: str | None) -> bool:
    """Check if user can toggle task done/undone."""
    return permission in ("owner", "creator")


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

    # Task belongs to priority owner's entity (or creator's if no priority)
    task_entity_id = creator_entity_id

    clean_priority_id = priority_id.strip() if priority_id else None
    if clean_priority_id:
        graph = _get_graph(creator_entity_id)
        priority = graph.get(clean_priority_id)
        if priority:
            task_entity_id = priority.entity_id

    task = create_task(
        name=name.strip(),
        notes=notes.strip() if notes else None,
        due_date=parsed_due_date,
        priority_id=clean_priority_id,
        entity_id=task_entity_id,
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
    tag: str | None = None,
    q: str | None = None,
    inbox: bool = False,
    outbox: bool = False,
    user: User | None = Depends(get_current_user_optional),
):
    """List tasks with optional filters, ranked by priority score.

    For the main queue (no priority filter), shows:
    - Tasks assigned to current user (from any entity)
    - Unassigned tasks owned by user's entity

    Query params:
    - priority: Filter by priority ID
    - status: Filter by status (queued, done, etc.)
    - tag: Filter by tag name
    - q: Search query (searches name and notes)
    - inbox: If true, show only tasks without a priority
    """
    task_status = None
    if status:
        try:
            task_status = TaskStatus(status)
        except ValueError:
            pass

    # Parse tag filter (could be single tag or comma-separated)
    tag_names = None
    if tag:
        tag_names = [t.strip() for t in tag.split(",") if t.strip()]

    # Clean search query
    search_query = q.strip() if q else None

    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)

    # For inbox: find Org-type priorities assigned to groups the user belongs to
    org_priority_ids = None
    if inbox and user:
        from praxis_core.persistence.user_repo import list_user_groups
        user_groups = list_user_groups(user.id)
        group_entity_ids = {g["entity_id"] for g in user_groups}
        if group_entity_ids:
            org_priority_ids = [
                p.id for p in graph.nodes.values()
                if p.priority_type.value == "org"
                and p.assigned_to_entity_id in group_entity_ids
            ]

    tasks = list_tasks(
        priority_id=priority,
        status=task_status,
        entity_id=entity_id,
        inbox_only=inbox,
        outbox_only=outbox,
        tag_names=tag_names,
        search_query=search_query,
        org_priority_ids=org_priority_ids,
    )
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    # Load rules and tags for rule-based scoring
    rules = _get_active_rules(entity_id)
    task_ids = [t.id for t in tasks]
    task_tags_map = get_tags_for_tasks(task_ids) if task_ids else {}

    # Rank tasks by (importance + urgency) × aptness
    scored_tasks = rank_tasks(tasks, graph, rules, task_tags_map)

    # Serialize with score included
    serialized = []
    for st in scored_tasks:
        task_data = _serialize_task(st.task, current_user=user, graph=graph)
        task_data["score"] = round(st.score, 2)
        task_data["importance"] = round(st.importance, 1)
        task_data["urgency"] = round(st.urgency, 1)
        task_data["aptness"] = round(st.aptness, 2)
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

    task_data = _serialize_task(task, render_markdown=False, current_user=user, graph=graph)
    task_data["notes_raw"] = task.description or ""

    return {
        "task": task_data,
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
    if new_status == TaskStatus.QUEUED and task.is_in_outbox:
        from praxis_core.persistence.task_repo import restore_from_outbox
        restore_from_outbox(task_id)
    else:
        update_task_status(task_id, new_status)

    # Fire event triggers if task was marked done
    if new_status == TaskStatus.DONE and task.entity_id:
        task_data_for_trigger = {
            "id": task.id,
            "name": task.name,
            "priority_id": task.priority_id,
            "entity_id": task.entity_id,
            "tags": [],  # TODO: Load tags if needed
        }
        on_task_completed(
            task_id=task.id,
            entity_id=task.entity_id,
            task_data=task_data_for_trigger,
            created_by=user.id if user else None,
        )

    task = get_task(task_id)
    task_data = _serialize_task(task, current_user=user, graph=graph)

    # Include score data for the row display
    entity_id = user.entity_id if user else None
    rules = _get_active_rules(entity_id)
    task_tags_map = get_tags_for_tasks([task_id])
    scored_tasks = rank_tasks([task], graph, rules, task_tags_map)
    if scored_tasks:
        st = scored_tasks[0]
        task_data["score"] = round(st.score, 2)
        task_data["importance"] = round(st.importance, 1)
        task_data["urgency"] = round(st.urgency, 1)
        task_data["aptness"] = round(st.aptness, 2)

    return {"task": task_data}


@router.post("/{task_id}/restore")
async def restore_task(
    task_id: str,
    user: User | None = Depends(get_current_user_optional),
):
    """Restore a task from the outbox back to the queue."""
    from praxis_core.persistence.task_repo import restore_from_outbox
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)
    if not task.is_in_outbox:
        return JSONResponse({"error": "Task is not in outbox"}, status_code=400)

    graph = _get_graph(user.entity_id if user else None)
    permission = get_task_permission(task, user, graph)
    if not can_toggle_task(permission):
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    restored = restore_from_outbox(task_id)
    return {"task": _serialize_task(restored, current_user=user)}


@router.post("/{task_id}/reassign")
async def reassign_task(
    task_id: str,
    priority_id: Annotated[str, Form()],
    user: User | None = Depends(get_current_user_optional),
):
    """Reassign a task to a different priority."""
    task = get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    graph = _get_graph(user.entity_id if user else None)
    permission = get_task_permission(task, user, graph)
    if not can_edit_task(permission):
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    update_task(task_id, priority_id=priority_id.strip())
    return await get_task_endpoint(task_id, user)


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
        status=task.status,
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
    task_data["notes_raw"] = task.description or ""

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
    task_data["notes_raw"] = task.description or ""

    return {
        "task": task_data,
        "item_type": "task",
        "item_id": task.id,
        "notes": task_data.get("notes", ""),
        "notes_raw": task.description or "",
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
