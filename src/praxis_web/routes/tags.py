"""Tag routes — search, add, and remove tags on tasks and priorities."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from praxis_web.rendering import templates, api_client

router = APIRouter()


@router.get("/tags/search", response_class=HTMLResponse)
async def tag_search(request: Request, q: str = ""):
    """Search tags for autocomplete. Returns HTML suggestions."""
    async with api_client(request) as client:
        response = await client.get("/api/tags/search", params={"q": q})
        data = response.json()
        tags = data.get("tags", [])

    return templates.TemplateResponse(
        request,
        "partials/components/tag_suggestions.html",
        {"tags": tags, "query": q}
    )


# ---------------------------------------------------------------------------
# Task tags
# ---------------------------------------------------------------------------

@router.get("/tasks/{task_id}/tags", response_class=HTMLResponse)
async def get_task_tags(request: Request, task_id: str):
    """Get tags HTML for a task."""
    async with api_client(request) as client:
        response = await client.get(f"/api/tags/tasks/{task_id}")
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/components/task_tags_list.html",
        {"tags": data.get("tags", []), "task_id": task_id, "removable": True}
    )


@router.post("/tasks/{task_id}/tags", response_class=HTMLResponse)
async def add_task_tag(request: Request, task_id: str):
    """Add a tag to a task. Creates the tag if it doesn't exist."""
    form_data = await request.form()
    name = form_data.get("name", "").strip()

    if not name:
        return HTMLResponse(content="", status_code=400)

    async with api_client(request) as client:
        response = await client.post(
            f"/api/tags/tasks/{task_id}",
            data={"name": name}
        )
        data = response.json()

    # Return updated tags list with trigger to refresh filter dropdown
    html_response = templates.TemplateResponse(
        request,
        "partials/components/task_tags_list.html",
        {"tags": data.get("tags", []), "task_id": task_id, "removable": True}
    )
    html_response.headers["HX-Trigger"] = "tagCreated"
    return html_response


@router.delete("/tasks/{task_id}/tags/{tag_id}", response_class=HTMLResponse)
async def remove_task_tag(request: Request, task_id: str, tag_id: str):
    """Remove a tag from a task."""
    async with api_client(request) as client:
        response = await client.delete(f"/api/tags/tasks/{task_id}/{tag_id}")
        data = response.json()

    # Return updated tags list
    return templates.TemplateResponse(
        request,
        "partials/components/task_tags_list.html",
        {"tags": data.get("tags", []), "task_id": task_id, "removable": True}
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

    async with api_client(request) as client:
        response = await client.post(
            f"/api/tags/priorities/{priority_id}",
            data={"name": name}
        )
        data = response.json()

    # Return updated tags list with trigger to refresh filter dropdown
    html_response = templates.TemplateResponse(
        request,
        "partials/components/priority_tags_list.html",
        {"tags": data.get("tags", []), "priority_id": priority_id, "removable": True}
    )
    html_response.headers["HX-Trigger"] = "tagCreated"
    return html_response


@router.delete("/priorities/{priority_id}/tags/{tag_id}", response_class=HTMLResponse)
async def remove_priority_tag(request: Request, priority_id: str, tag_id: str):
    """Remove a tag from a priority."""
    async with api_client(request) as client:
        response = await client.delete(f"/api/tags/priorities/{priority_id}/{tag_id}")
        data = response.json()

    # Return updated tags list
    return templates.TemplateResponse(
        request,
        "partials/components/priority_tags_list.html",
        {"tags": data.get("tags", []), "priority_id": priority_id, "removable": True}
    )
