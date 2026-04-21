"""Tag routes — search, add, and remove tags on tasks and priorities."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from praxis_web.rendering import templates, SESSION_COOKIE_NAME
from praxis_core.persistence import validate_session
from praxis_core.persistence.tag_persistence import (
    get_tags_by_entity,
    get_or_create_tag,
    search_tags,
    get_tags_for_task,
    add_tag_to_task,
    remove_tag_from_task,
    get_tags_for_priority,
    add_tag_to_priority,
    remove_tag_from_priority,
)

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


def _serialize_tag(tag) -> dict:
    """Serialize a Tag for API response."""
    return {
        "id": tag.id,
        "name": tag.name,
        "color": tag.color,
        "created_at": tag.created_at.isoformat() if tag.created_at else None,
    }


@router.get("/tags/search", response_class=HTMLResponse)
async def tag_search(request: Request, q: str = ""):
    """Search tags for autocomplete. Returns HTML suggestions."""
    user = _get_user(request)
    entity_id = user.entity_id if user else None

    if not entity_id:
        tags = []
    elif not q.strip():
        tags = get_tags_by_entity(entity_id)
    else:
        tags = search_tags(entity_id, q.strip())

    return templates.TemplateResponse(
        request,
        "partials/components/tag_suggestions.html",
        {"tags": [_serialize_tag(t) for t in tags], "query": q}
    )


# ---------------------------------------------------------------------------
# Task tags
# ---------------------------------------------------------------------------

@router.get("/tasks/{task_id}/tags", response_class=HTMLResponse)
async def get_task_tags(request: Request, task_id: str):
    """Get tags HTML for a task."""
    tags = get_tags_for_task(task_id)

    return templates.TemplateResponse(
        request,
        "partials/components/task_tags_list.html",
        {"tags": [_serialize_tag(t) for t in tags], "task_id": task_id, "removable": True}
    )


@router.post("/tasks/{task_id}/tags", response_class=HTMLResponse)
async def add_task_tag(request: Request, task_id: str):
    """Add a tag to a task. Creates the tag if it doesn't exist."""
    form_data = await request.form()
    name = form_data.get("name", "").strip()

    if not name:
        return HTMLResponse(content="", status_code=400)

    user = _get_user(request)
    if not user or not user.entity_id:
        return HTMLResponse(content="", status_code=401)

    # Get or create the tag, then attach it
    tag = get_or_create_tag(entity_id=user.entity_id, name=name)
    add_tag_to_task(task_id, tag.id)

    # Return updated tags list with trigger to refresh filter dropdown
    tags = get_tags_for_task(task_id)
    html_response = templates.TemplateResponse(
        request,
        "partials/components/task_tags_list.html",
        {"tags": [_serialize_tag(t) for t in tags], "task_id": task_id, "removable": True}
    )
    html_response.headers["HX-Trigger"] = "tagCreated"
    return html_response


@router.delete("/tasks/{task_id}/tags/{tag_id}", response_class=HTMLResponse)
async def remove_task_tag(request: Request, task_id: str, tag_id: str):
    """Remove a tag from a task."""
    remove_tag_from_task(task_id, tag_id)

    # Return updated tags list
    tags = get_tags_for_task(task_id)
    return templates.TemplateResponse(
        request,
        "partials/components/task_tags_list.html",
        {"tags": [_serialize_tag(t) for t in tags], "task_id": task_id, "removable": True}
    )


# ---------------------------------------------------------------------------
# Priority tags
# ---------------------------------------------------------------------------

@router.post("/priorities/{priority_id}/tags", response_class=HTMLResponse)
async def add_priority_tag(request: Request, priority_id: str):
    """Add a tag to a priority."""
    form_data = await request.form()
    name = form_data.get("name", "").strip()

    if not name:
        return HTMLResponse(content="", status_code=400)

    user = _get_user(request)
    if not user or not user.entity_id:
        return HTMLResponse(content="", status_code=401)

    # Get or create the tag, then attach it
    tag = get_or_create_tag(entity_id=user.entity_id, name=name)
    add_tag_to_priority(priority_id, tag.id)

    # Return updated tags list with trigger to refresh filter dropdown
    tags = get_tags_for_priority(priority_id)
    html_response = templates.TemplateResponse(
        request,
        "partials/components/priority_tags_list.html",
        {"tags": [_serialize_tag(t) for t in tags], "priority_id": priority_id, "removable": True}
    )
    html_response.headers["HX-Trigger"] = "tagCreated"
    return html_response


@router.delete("/priorities/{priority_id}/tags/{tag_id}", response_class=HTMLResponse)
async def remove_priority_tag(request: Request, priority_id: str, tag_id: str):
    """Remove a tag from a priority."""
    remove_tag_from_priority(priority_id, tag_id)

    # Return updated tags list
    tags = get_tags_for_priority(priority_id)
    return templates.TemplateResponse(
        request,
        "partials/components/priority_tags_list.html",
        {"tags": [_serialize_tag(t) for t in tags], "priority_id": priority_id, "removable": True}
    )
