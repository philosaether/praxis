"""
Task-related web routes (HTMX partials and full-page views).

Extracted from app.py to keep the main module manageable.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from praxis_web.rendering import templates as _templates, api_client as _api_client, is_htmx_request as _is_htmx_request, render_full_page as _render_full_page

router = APIRouter()


# -----------------------------------------------------------------------------
# Routes: HTMX Partials - Tasks
# -----------------------------------------------------------------------------

@router.get("/tasks/list", response_class=HTMLResponse)
async def tasks_list_partial(
    request: Request,
    priority: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    q: str | None = None,
):
    """HTMX partial: filtered list of tasks."""
    async with _api_client(request) as client:
        params = {}
        if priority:
            params["priority"] = priority
        if status:
            params["status"] = status
        if tag:
            params["tag"] = tag
        if q:
            params["q"] = q
        response = await client.get("/api/tasks", params=params)
        data = response.json()

    return _templates.TemplateResponse(
        request,
        "partials/task_rows.html",
        {
            "tasks": data["tasks"],
            "priorities": data.get("priorities", []),
            "current_tag": tag,
            "current_status": status,
            "current_search": q,
        }
    )



@router.get("/tasks/new", response_class=HTMLResponse)
async def new_task_form(request: Request):
    """Show empty form for creating a new task."""
    async with _api_client(request) as client:
        response = await client.get("/api/priorities")
        data = response.json()

    from praxis_core.model import TaskStatus
    return _templates.TemplateResponse(
        request,
        "partials/task_new_form.html",
        {
            "priorities": data["priorities"],
            "task_statuses": [s.value for s in TaskStatus],
        }
    )


@router.post("/tasks/create", response_class=HTMLResponse)
async def create_task_submit(request: Request):
    """Create a new task and return the view mode (read-only display)."""
    form_data = await request.form()

    async with _api_client(request) as client:
        response = await client.post("/api/tasks", data=dict(form_data))
        if response.status_code == 400:
            error_data = response.json()
            return HTMLResponse(
                content=f"<div class='error'>{error_data.get('error', 'Name is required')}</div>",
                status_code=400
            )
        data = response.json()

    task = data["task"]

    # Return task view mode and trigger list refresh
    async with _api_client(request) as client:
        detail_response = await client.get(f"/api/tasks/{task['id']}")
        detail_data = detail_response.json()

    # Include HX-Trigger to refresh the task list
    html_response = _templates.TemplateResponse(
        request,
        "partials/task_view.html",
        detail_data
    )
    html_response.headers["HX-Trigger"] = "taskCreated"
    html_response.headers["HX-Push-Url"] = f"/tasks/{task['id']}"
    html_response.headers["X-New-Item-Id"] = str(task["id"])
    return html_response


@router.post("/tasks/quick-add", response_class=HTMLResponse)
async def quick_add_task(request: Request):
    """Create a task via quick-add modal and return the row HTML."""
    form_data = await request.form()

    async with _api_client(request) as client:
        response = await client.post("/api/tasks", data=dict(form_data))
        if response.status_code == 400:
            error_data = response.json()
            return HTMLResponse(
                content=f"<div class='error'>{error_data.get('error', 'Name is required')}</div>",
                status_code=400
            )
        data = response.json()

    task = data["task"]
    html_response = _templates.TemplateResponse(
        request,
        "partials/task_row_single.html",
        {"task": task}
    )
    # Trigger event to close modal
    html_response.headers["HX-Trigger"] = "taskCreated"
    return html_response

@router.get("/tasks/quick-add/priorities", response_class=HTMLResponse)
async def quick_add_priorities(request: Request):
    """Return fresh priority options for the quick-add modal dropdown."""
    async with _api_client(request) as client:
        response = await client.get("/api/priorities")
        data = response.json()

    # Build options HTML with type prefix for scannability
    options = ['<option value="">Inbox (no priority)</option>']
    for p in data["priorities"]:
        type_prefix = p["priority_type"][:3].upper()
        options.append(f'<option value="{p["id"]}">[{type_prefix}] {p["name"]}</option>')

    return HTMLResponse(content="\n".join(options))


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: str):
    """Task detail - full page or HTMX partial."""
    async with _api_client(request) as client:
        response = await client.get(f"/api/tasks/{task_id}")
        if response.status_code == 404:
            return HTMLResponse(
                content="<div class='error'>Task not found</div>",
                status_code=404
            )
        data = response.json()

    # HTMX request - return partial
    if _is_htmx_request(request):
        return _templates.TemplateResponse(
            request,
            "partials/task_view.html",
            data
        )

    # Full page request - render with task detail pre-loaded
    detail_html = _templates.get_template("partials/task_view.html").render(
        request=request, **data
    )
    return await _render_full_page(
        request,
        mode="tasks",
        initial_detail_html=detail_html
    )


@router.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
async def task_edit(request: Request, task_id: str):
    """HTMX partial: edit mode for a single task."""
    async with _api_client(request) as client:
        response = await client.get(f"/api/tasks/{task_id}/edit")
        if response.status_code == 404:
            return HTMLResponse(
                content="<div class='error'>Task not found</div>",
                status_code=404
            )
        data = response.json()

    return _templates.TemplateResponse(
        request,
        "partials/task_edit.html",
        data
    )


@router.post("/tasks/{task_id}/properties", response_class=HTMLResponse)
async def task_save_properties(request: Request, task_id: str):
    """Save task properties and return view mode + OOB row update."""
    form_data = await request.form()

    async with _api_client(request) as client:
        response = await client.post(
            f"/api/tasks/{task_id}/properties",
            data=dict(form_data)
        )
        if response.status_code == 404:
            return HTMLResponse(
                content="<div class='error'>Task not found</div>",
                status_code=404
            )
        if response.status_code == 400:
            error_data = response.json()
            return HTMLResponse(
                content=f"<div class='error'>{error_data.get('error', 'Validation error')}</div>",
                status_code=400
            )
        data = response.json()

    # Check if the task left the current user's queue (reassigned to someone else)
    task = data["task"]
    task_assigned_away = False
    if task.get("assigned_to"):
        async with _api_client(request) as client:
            me_response = await client.get("/api/auth/me")
            if me_response.status_code == 200:
                current_user_id = me_response.json().get("id")
                if current_user_id and task["assigned_to"] != current_user_id:
                    task_assigned_away = True

    # Render view mode (confirms save was successful)
    view_html = _templates.TemplateResponse(
        request,
        "partials/task_view.html",
        data
    ).body.decode()

    if task_assigned_away:
        # Remove the row from the list via empty OOB swap
        row_html = f'<div id="task-row-{task["id"]}" hx-swap-oob="true"></div>'
    else:
        # Render OOB row update
        row_html = _templates.TemplateResponse(
            request,
            "partials/task_row_single.html",
            {"task": task, "oob": True}
        ).body.decode()

    return HTMLResponse(content=view_html + row_html)


@router.post("/tasks/{task_id}/notes", response_class=HTMLResponse)
async def task_save_notes(request: Request, task_id: str):
    """Save task notes and return updated notes section."""
    form_data = await request.form()

    async with _api_client(request) as client:
        response = await client.post(
            f"/api/tasks/{task_id}/notes",
            data=dict(form_data)
        )
        if response.status_code == 404:
            return HTMLResponse(
                content="<div class='error'>Task not found</div>",
                status_code=404
            )
        data = response.json()

    return _templates.TemplateResponse(
        request,
        "partials/item_notes.html",
        data
    )


@router.post("/tasks/{task_id}/toggle", response_class=HTMLResponse)
async def task_toggle_done(request: Request, task_id: str):
    """Toggle task between done and queued."""
    async with _api_client(request) as client:
        response = await client.post(f"/api/tasks/{task_id}/toggle")
        if response.status_code == 404:
            return HTMLResponse(content="", status_code=404)
        data = response.json()

    task = data["task"]

    # Task moved to outbox — remove row from list immediately
    if task.get("is_in_outbox"):
        return HTMLResponse(content="")

    return _templates.TemplateResponse(
        request,
        "partials/task_row_single.html",
        {"task": task}
    )


@router.delete("/tasks/{task_id}", response_class=HTMLResponse)
async def delete_task(request: Request, task_id: str):
    """Delete a task and return empty content."""
    async with _api_client(request) as client:
        response = await client.delete(f"/api/tasks/{task_id}")
        if response.status_code == 404:
            return HTMLResponse(content="", status_code=404)

    # Return empty response - HTMX will remove the row
    return HTMLResponse(content="")


# -----------------------------------------------------------------------------
# Misplaced route: belongs with priority routes, extracted here for now
# -----------------------------------------------------------------------------

@router.delete("/priorities/{priority_id}", response_class=HTMLResponse)
async def delete_priority(request: Request, priority_id: str):
    """Delete a priority and return empty content."""
    async with _api_client(request) as client:
        response = await client.delete(f"/api/priorities/{priority_id}")
        if response.status_code == 404:
            return HTMLResponse(content="", status_code=404)

    # Return empty response - HTMX will remove the node
    return HTMLResponse(content="")
