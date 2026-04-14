"""Agent API — Priority operations."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from praxis_core.model import (
    PriorityType,
    PriorityStatus,
    Value,
    Goal,
    Practice,
    Initiative,
    User,
)
from praxis_core.web_api.auth import get_current_user


def _get_graph(entity_id):
    from praxis_core.web_api.app import get_graph
    return get_graph(entity_id)


def _clear_cache(entity_id):
    from praxis_core.web_api.app import clear_graph_cache
    clear_graph_cache(entity_id)

router = APIRouter()


# -- Request/Response models --------------------------------------------------

class CreatePriorityRequest(BaseModel):
    name: str
    priority_type: str = "initiative"
    status: str = "active"
    parent_id: str | None = None
    description: str | None = None
    agent_context: str | None = None
    # Goal fields
    complete_when: str | None = None
    due_date: str | None = None  # ISO format
    progress: str | None = None


class UpdatePriorityRequest(BaseModel):
    name: str | None = None
    status: str | None = None
    description: str | None = None
    agent_context: str | None = None
    complete_when: str | None = None
    due_date: str | None = None
    progress: str | None = None


# -- Serialization ------------------------------------------------------------

def _serialize(p) -> dict:
    """Minimal priority serialization for agents."""
    data = {
        "id": p.id,
        "name": p.name,
        "priority_type": p.priority_type.value,
        "status": p.status.value,
        "substatus": p.substatus,
        "description": p.description,
        "agent_context": p.agent_context,
        "rank": p.rank,
        "last_engaged_at": p.last_engaged_at.isoformat() if p.last_engaged_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
    if isinstance(p, Goal):
        data["complete_when"] = p.complete_when
        data["due_date"] = p.due_date.isoformat() if p.due_date else None
        data["progress"] = p.progress
    elif isinstance(p, Practice):
        data["actions_config"] = p.actions_config
        data["last_triggered_at"] = p.last_triggered_at.isoformat() if p.last_triggered_at else None
    return data


def _generate_id(name: str, graph) -> str:
    """Generate a URL-friendly priority ID from name."""
    import re
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50]
    if not graph.get(base):
        return base
    for i in range(2, 100):
        candidate = f"{base}-{i}"
        if not graph.get(candidate):
            return candidate
    from ulid import ULID
    return str(ULID())


def _create_by_type(priority_type: str, id: str, name: str, entity_id: str | None):
    """Create a Priority subclass by type string."""
    match priority_type:
        case "value":
            return Value(id=id, name=name, entity_id=entity_id)
        case "goal":
            return Goal(id=id, name=name, entity_id=entity_id)
        case "practice":
            return Practice(id=id, name=name, entity_id=entity_id)
        case "initiative":
            return Initiative(id=id, name=name, entity_id=entity_id)
        case _:
            return Initiative(id=id, name=name, entity_id=entity_id)


# -- Endpoints ----------------------------------------------------------------

@router.post("")
async def create_priority(body: CreatePriorityRequest, user: User = Depends(get_current_user)):
    """Create a priority."""
    graph = _get_graph(user.entity_id)
    priority_id = _generate_id(body.name, graph)
    priority = _create_by_type(body.priority_type, priority_id, body.name, user.entity_id)

    try:
        priority.status = PriorityStatus(body.status)
    except ValueError:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": f"Invalid status: {body.status}"}, status_code=400)
    priority.description = body.description
    priority.agent_context = body.agent_context

    if isinstance(priority, Goal):
        priority.complete_when = body.complete_when
        priority.progress = body.progress
        if body.due_date:
            try:
                priority.due_date = datetime.fromisoformat(body.due_date)
            except ValueError:
                pass

    graph.add(priority)

    if body.parent_id:
        try:
            graph.link(priority_id, body.parent_id)
        except ValueError:
            pass  # circular ref or missing parent

    _clear_cache(user.entity_id)
    return _serialize(priority)


@router.get("")
async def list_priorities(
    priority_type: str | None = None,
    status: str | None = None,
    user: User = Depends(get_current_user),
):
    """List priorities, optionally filtered."""
    graph = _get_graph(user.entity_id)
    priorities = list(graph.nodes.values())

    if priority_type:
        priorities = [p for p in priorities if p.priority_type.value == priority_type]
    if status:
        priorities = [p for p in priorities if p.status.value == status]

    return [_serialize(p) for p in priorities]


@router.get("/{priority_id}")
async def get_priority(priority_id: str, user: User = Depends(get_current_user)):
    """Get a single priority."""
    graph = _get_graph(user.entity_id)
    priority = graph.get(priority_id)
    if not priority:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    data = _serialize(priority)
    data["parent_ids"] = list(graph.parents.get(priority_id, set()))
    data["child_ids"] = list(graph.children.get(priority_id, set()))
    return data


@router.put("/{priority_id}")
async def update_priority(
    priority_id: str,
    body: UpdatePriorityRequest,
    user: User = Depends(get_current_user),
):
    """Update a priority."""
    graph = _get_graph(user.entity_id)
    priority = graph.get(priority_id)
    if not priority:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    if body.name is not None:
        priority.name = body.name
    if body.status is not None:
        try:
            priority.status = PriorityStatus(body.status)
        except ValueError:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": f"Invalid status: {body.status}"}, status_code=400)
    if body.description is not None:
        priority.description = body.description
    if body.agent_context is not None:
        priority.agent_context = body.agent_context

    if isinstance(priority, Goal):
        if body.complete_when is not None:
            priority.complete_when = body.complete_when
        if body.progress is not None:
            priority.progress = body.progress
        if body.due_date is not None:
            try:
                priority.due_date = datetime.fromisoformat(body.due_date)
            except ValueError:
                pass

    graph.save_priority(priority)
    _clear_cache(user.entity_id)
    return _serialize(priority)


@router.delete("/{priority_id}")
async def delete_priority(priority_id: str, user: User = Depends(get_current_user)):
    """Delete a priority."""
    from praxis_core.persistence.task_repo import unlink_tasks_from_priority

    graph = _get_graph(user.entity_id)
    if not graph.get(priority_id):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    unlink_tasks_from_priority(priority_id)
    graph.delete(priority_id)
    _clear_cache(user.entity_id)
    return {"deleted": priority_id}
