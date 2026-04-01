"""Tag API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Form, Depends
from fastapi.responses import JSONResponse

from praxis_core.model import User
from praxis_core.persistence.tag_persistence import (
    create_tag,
    get_tag,
    get_tags_by_entity,
    get_or_create_tag,
    search_tags,
    update_tag,
    delete_tag,
    add_tag_to_task,
    remove_tag_from_task,
    get_tags_for_task,
    add_tag_to_priority,
    remove_tag_from_priority,
    get_tags_for_priority,
)
from praxis_core.api.auth import get_current_user, get_current_user_optional


router = APIRouter()


def _serialize_tag(tag) -> dict:
    """Serialize a Tag for API response."""
    return {
        "id": tag.id,
        "name": tag.name,
        "color": tag.color,
        "created_at": tag.created_at.isoformat() if tag.created_at else None,
    }


# -----------------------------------------------------------------------------
# Tag CRUD Endpoints
# -----------------------------------------------------------------------------

@router.get("")
async def list_tags(
    user: User = Depends(get_current_user),
):
    """List all tags for the current user."""
    tags = get_tags_by_entity(user.entity_id)
    return {"tags": [_serialize_tag(t) for t in tags]}


@router.get("/search")
async def search_tags_endpoint(
    q: str = "",
    user: User = Depends(get_current_user),
):
    """Search tags by name prefix for autocomplete."""
    if not q.strip():
        tags = get_tags_by_entity(user.entity_id)
    else:
        tags = search_tags(user.entity_id, q.strip())
    return {"tags": [_serialize_tag(t) for t in tags]}


@router.post("")
async def create_tag_endpoint(
    name: Annotated[str, Form()],
    color: Annotated[str | None, Form()] = None,
    user: User = Depends(get_current_user),
):
    """Create a new tag."""
    if not name.strip():
        return JSONResponse({"error": "Name is required"}, status_code=400)

    tag = create_tag(
        entity_id=user.entity_id,
        name=name.strip(),
        color=color.strip() if color else None,
    )
    return {"tag": _serialize_tag(tag)}


@router.put("/{tag_id}")
async def update_tag_endpoint(
    tag_id: str,
    name: Annotated[str | None, Form()] = None,
    color: Annotated[str | None, Form()] = None,
    user: User = Depends(get_current_user),
):
    """Update a tag."""
    tag = get_tag(tag_id)
    if not tag:
        return JSONResponse({"error": "Tag not found"}, status_code=404)

    # Verify ownership
    if tag.entity_id != user.entity_id:
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    updated = update_tag(
        tag_id,
        name=name.strip() if name else None,
        color=color.strip() if color else None,
    )
    return {"tag": _serialize_tag(updated)}


@router.delete("/{tag_id}")
async def delete_tag_endpoint(
    tag_id: str,
    user: User = Depends(get_current_user),
):
    """Delete a tag."""
    tag = get_tag(tag_id)
    if not tag:
        return JSONResponse({"error": "Tag not found"}, status_code=404)

    # Verify ownership
    if tag.entity_id != user.entity_id:
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    delete_tag(tag_id)
    return {"success": True, "deleted_id": tag_id}


# -----------------------------------------------------------------------------
# Task <-> Tag Endpoints
# -----------------------------------------------------------------------------

@router.get("/tasks/{task_id}")
async def get_task_tags(
    task_id: str,
    user: User | None = Depends(get_current_user_optional),
):
    """Get all tags for a task."""
    tags = get_tags_for_task(task_id)
    return {"tags": [_serialize_tag(t) for t in tags]}


@router.post("/tasks/{task_id}")
async def add_tag_to_task_endpoint(
    task_id: str,
    name: Annotated[str, Form()],
    color: Annotated[str | None, Form()] = None,
    user: User = Depends(get_current_user),
):
    """Add a tag to a task. Creates the tag if it doesn't exist."""
    if not name.strip():
        return JSONResponse({"error": "Tag name is required"}, status_code=400)

    # Get or create the tag
    tag = get_or_create_tag(
        entity_id=user.entity_id,
        name=name.strip(),
        color=color.strip() if color else None,
    )

    # Add to task
    add_tag_to_task(task_id, tag.id)

    # Return all tags for the task
    tags = get_tags_for_task(task_id)
    return {"tags": [_serialize_tag(t) for t in tags], "added": _serialize_tag(tag)}


@router.delete("/tasks/{task_id}/{tag_id}")
async def remove_tag_from_task_endpoint(
    task_id: str,
    tag_id: str,
    user: User = Depends(get_current_user),
):
    """Remove a tag from a task."""
    tag = get_tag(tag_id)
    if not tag:
        return JSONResponse({"error": "Tag not found"}, status_code=404)

    # Verify ownership
    if tag.entity_id != user.entity_id:
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    remove_tag_from_task(task_id, tag_id)

    # Return remaining tags for the task
    tags = get_tags_for_task(task_id)
    return {"tags": [_serialize_tag(t) for t in tags], "removed_id": tag_id}


# -----------------------------------------------------------------------------
# Priority <-> Tag Endpoints
# -----------------------------------------------------------------------------

@router.get("/priorities/{priority_id}")
async def get_priority_tags(
    priority_id: str,
    user: User | None = Depends(get_current_user_optional),
):
    """Get all tags for a priority."""
    tags = get_tags_for_priority(priority_id)
    return {"tags": [_serialize_tag(t) for t in tags]}


@router.post("/priorities/{priority_id}")
async def add_tag_to_priority_endpoint(
    priority_id: str,
    name: Annotated[str, Form()],
    color: Annotated[str | None, Form()] = None,
    user: User = Depends(get_current_user),
):
    """Add a tag to a priority. Creates the tag if it doesn't exist."""
    if not name.strip():
        return JSONResponse({"error": "Tag name is required"}, status_code=400)

    # Get or create the tag
    tag = get_or_create_tag(
        entity_id=user.entity_id,
        name=name.strip(),
        color=color.strip() if color else None,
    )

    # Add to priority
    add_tag_to_priority(priority_id, tag.id)

    # Return all tags for the priority
    tags = get_tags_for_priority(priority_id)
    return {"tags": [_serialize_tag(t) for t in tags], "added": _serialize_tag(tag)}


@router.delete("/priorities/{priority_id}/{tag_id}")
async def remove_tag_from_priority_endpoint(
    priority_id: str,
    tag_id: str,
    user: User = Depends(get_current_user),
):
    """Remove a tag from a priority."""
    tag = get_tag(tag_id)
    if not tag:
        return JSONResponse({"error": "Tag not found"}, status_code=404)

    # Verify ownership
    if tag.entity_id != user.entity_id:
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    remove_tag_from_priority(priority_id, tag_id)

    # Return remaining tags for the priority
    tags = get_tags_for_priority(priority_id)
    return {"tags": [_serialize_tag(t) for t in tags], "removed_id": tag_id}
