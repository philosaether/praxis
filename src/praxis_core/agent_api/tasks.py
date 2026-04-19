"""Agent API — Task operations."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from praxis_core.model import User
from praxis_core.model.tasks import TaskStatus
from praxis_core.persistence import (
    create_task,
    get_task,
    list_tasks,
    update_task,
    update_task_status,
    delete_task,
    get_tags_for_task,
    get_tags_for_tasks,
)
from praxis_core.web_api.auth import get_current_user


def _get_graph(entity_id):
    from praxis_core.web_api.app import get_graph
    return get_graph(entity_id)

router = APIRouter()


# -- Request/Response models --------------------------------------------------

class CreateTaskRequest(BaseModel):
    name: str
    priority_id: str | None = None
    due_date: str | None = None  # ISO format
    description: str | None = None


class UpdateTaskRequest(BaseModel):
    name: str | None = None
    priority_id: str | None = None
    due_date: str | None = None
    description: str | None = None
    status: str | None = None


# -- Serialization ------------------------------------------------------------

def _serialize(t, tags: set[str] | None = None, score_data: dict | None = None) -> dict:
    """Minimal task serialization for agents."""
    data = {
        "id": t.id,
        "name": t.name,
        "status": t.status.value,
        "description": t.description,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "priority_id": t.priority_id,
        "priority_name": t.priority_name,
        "entity_id": t.entity_id,
        "created_by": t.created_by,
        "is_in_outbox": t.is_in_outbox,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
    if tags is not None:
        data["tags"] = sorted(tags)
    if score_data:
        data.update(score_data)
    return data


# -- Endpoints ----------------------------------------------------------------

@router.post("")
async def create_task_endpoint(body: CreateTaskRequest, user: User = Depends(get_current_user)):
    """Create a task."""
    parsed_due = None
    if body.due_date:
        try:
            parsed_due = datetime.fromisoformat(body.due_date)
        except ValueError:
            pass

    # Determine entity_id from priority or user
    entity_id = user.entity_id
    if body.priority_id:
        graph = _get_graph(user.entity_id)
        priority = graph.get(body.priority_id)
        if priority:
            entity_id = priority.entity_id

    task = create_task(
        name=body.name,
        description=body.description,
        due_date=parsed_due,
        priority_id=body.priority_id,
        entity_id=entity_id,
        created_by=user.id,
    )
    return _serialize(task)


@router.get("")
async def list_tasks_endpoint(
    priority_id: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    inbox: bool = False,
    outbox: bool = False,
    include_done: bool = False,
    user: User = Depends(get_current_user),
):
    """List tasks. Returns ranked queue by default (no filters)."""
    status_filter = None
    if status:
        try:
            status_filter = TaskStatus(status)
        except ValueError:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": f"Invalid status: {status}"}, status_code=400)
    tag_names = [t.strip() for t in tag.split(",")] if tag else None

    tasks = list_tasks(
        priority_id=priority_id,
        status=status_filter,
        include_done=include_done,
        entity_id=user.entity_id,
        inbox_only=inbox,
        outbox_only=outbox,
        tag_names=tag_names,
        search_query=q,
    )

    # Score and rank
    from praxis_core.prioritization import rank_tasks
    from praxis_core.persistence.rule_persistence import list_rules

    graph = _get_graph(user.entity_id)
    rules = list_rules(entity_id=user.entity_id, enabled_only=True)
    task_ids = [t.id for t in tasks]
    tags_map = get_tags_for_tasks(task_ids) if task_ids else {}

    scored = rank_tasks(tasks, graph, rules, tags_map)

    return [
        _serialize(
            st.task,
            tags=tags_map.get(st.task.id, set()),
            score_data={
                "score": round(st.score, 2),
                "importance": round(st.importance, 2),
                "urgency": round(st.urgency, 2),
                "aptness": round(st.aptness, 2),
                "matched_rules": st.matched_rules,
            },
        )
        for st in scored
    ]


def _check_task_access(task, user: User):
    """Return 403 response if user doesn't own the task, else None."""
    if task.entity_id != user.entity_id:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Permission denied"}, status_code=403)
    return None


@router.get("/{task_id}")
async def get_task_endpoint(task_id: str, user: User = Depends(get_current_user)):
    """Get a single task."""
    task = get_task(task_id)
    if not task:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Task not found"}, status_code=404)
    if err := _check_task_access(task, user):
        return err

    tags = get_tags_for_task(task_id)
    return _serialize(task, tags=tags)


@router.put("/{task_id}")
async def update_task_endpoint(
    task_id: str,
    body: UpdateTaskRequest,
    user: User = Depends(get_current_user),
):
    """Update a task."""
    task = get_task(task_id)
    if not task:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Task not found"}, status_code=404)
    if err := _check_task_access(task, user):
        return err

    updates = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if body.priority_id is not None:
        updates["priority_id"] = body.priority_id
    if body.due_date is not None:
        try:
            updates["due_date"] = datetime.fromisoformat(body.due_date)
        except ValueError:
            pass
    if body.status is not None:
        try:
            updates["status"] = TaskStatus(body.status)
        except ValueError:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": f"Invalid status: {body.status}"}, status_code=400)

    if updates:
        updated = update_task(task_id, **updates)
        return _serialize(updated)
    return _serialize(task)


@router.post("/{task_id}/complete")
async def complete_task(task_id: str, user: User = Depends(get_current_user)):
    """Mark a task as done."""
    task = get_task(task_id)
    if not task:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Task not found"}, status_code=404)
    if err := _check_task_access(task, user):
        return err

    updated = update_task_status(task_id, TaskStatus.DONE)

    # Fire event triggers
    from praxis_core.practices import on_task_completed
    if task.entity_id:
        on_task_completed(
            task_id=task_id,
            entity_id=task.entity_id,
            task_data={
                "id": task.id,
                "name": task.name,
                "status": "done",
                "priority_id": task.priority_id,
                "entity_id": task.entity_id,
            },
            created_by=user.id,
        )

    return _serialize(updated)


@router.delete("/{task_id}")
async def delete_task_endpoint(task_id: str, user: User = Depends(get_current_user)):
    """Delete a task."""
    task = get_task(task_id)
    if not task:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Task not found"}, status_code=404)
    if err := _check_task_access(task, user):
        return err

    delete_task(task_id)
    return {"deleted": task_id}
