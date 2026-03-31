"""
Praxis Web UI server.

Run with: uvicorn praxis_web.app:app --port 8080
Requires: PRAXIS_API_URL environment variable (default: http://localhost:8000)
"""

import json
import os
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Annotated

# -----------------------------------------------------------------------------
# App Setup
# -----------------------------------------------------------------------------

app = FastAPI(title="Praxis Web")

# Config
API_URL = os.getenv("PRAXIS_API_URL", "http://localhost:8000")
SESSION_COOKIE_NAME = "praxis_session"

# Static files and templates
STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# -----------------------------------------------------------------------------
# API Client Helper
# -----------------------------------------------------------------------------

def api_client(request: Request | None = None):
    """Create an API client, optionally with auth from session cookie."""
    headers = {}
    if request:
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        if session_token:
            headers["Authorization"] = f"Bearer {session_token}"
    return httpx.AsyncClient(base_url=API_URL, timeout=30.0, headers=headers)


# -----------------------------------------------------------------------------
# Auth Routes
# -----------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    """Display login page."""
    # If already logged in, redirect to home
    if request.cookies.get(SESSION_COOKIE_NAME):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": error}
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    """Handle login form submission."""
    async with httpx.AsyncClient(base_url=API_URL, timeout=30.0) as client:
        response = await client.post(
            "/api/auth/login",
            json={"username": username, "password": password}
        )

        if response.status_code != 200:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Invalid username or password"},
                status_code=401
            )

        data = response.json()
        session_id = data["session_id"]

        # Set session cookie and redirect to home
        redirect = RedirectResponse(url="/", status_code=302)
        redirect.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            samesite="lax",
            # secure=True,  # Enable in production with HTTPS
            max_age=7 * 24 * 60 * 60,  # 7 days
        )
        return redirect


@app.get("/logout")
@app.post("/logout")
async def logout(request: Request):
    """Log out and clear session."""
    session_token = request.cookies.get(SESSION_COOKIE_NAME)

    # Call API to invalidate session
    if session_token:
        async with api_client(request) as client:
            await client.post("/api/auth/logout")

    # Clear cookie and redirect to login
    redirect = RedirectResponse(url="/login", status_code=302)
    redirect.delete_cookie(key=SESSION_COOKIE_NAME)
    return redirect


@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request, error: str | None = None):
    """Display signup page."""
    # If already logged in, redirect to home
    if request.cookies.get(SESSION_COOKIE_NAME):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(
        request,
        "signup.html",
        {"error": error}
    )


@app.post("/signup")
async def signup_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()],
):
    """Handle signup form submission."""
    # Validate passwords match
    if password != password_confirm:
        return templates.TemplateResponse(
            request,
            "signup.html",
            {"error": "Passwords do not match"},
            status_code=400
        )

    async with httpx.AsyncClient(base_url=API_URL, timeout=30.0) as client:
        response = await client.post(
            "/api/auth/register",
            json={"username": username, "password": password}
        )

        if response.status_code != 200:
            error_data = response.json()
            error_msg = error_data.get("detail", "Registration failed")
            return templates.TemplateResponse(
                request,
                "signup.html",
                {"error": error_msg},
                status_code=400
            )

        # Registration successful - log them in automatically
        login_response = await client.post(
            "/api/auth/login",
            json={"username": username, "password": password}
        )

        if login_response.status_code == 200:
            data = login_response.json()
            session_id = data["session_id"]

            redirect = RedirectResponse(url="/", status_code=302)
            redirect.set_cookie(
                key=SESSION_COOKIE_NAME,
                value=session_id,
                httponly=True,
                samesite="lax",
                max_age=7 * 24 * 60 * 60,
            )
            return redirect

        # Fallback: redirect to login page
        return RedirectResponse(url="/login", status_code=302)


# -----------------------------------------------------------------------------
# Routes: Pages
# -----------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    """Full page: two-pane layout with tasks as default view."""
    # Check if user is logged in
    if not request.cookies.get(SESSION_COOKIE_NAME):
        return RedirectResponse(url="/login", status_code=302)

    async with api_client(request) as client:
        # Fetch user info
        me_response = await client.get("/api/auth/me")
        if me_response.status_code != 200:
            # Session invalid, redirect to login
            response = RedirectResponse(url="/login", status_code=302)
            response.delete_cookie(key=SESSION_COOKIE_NAME)
            return response
        user = me_response.json()

        # Fetch both tasks and priorities for initial load
        tasks_response = await client.get("/api/tasks")
        priorities_response = await client.get("/api/priorities")
        tasks_data = tasks_response.json()
        priorities_data = priorities_response.json()

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "user": user,
            "tasks": tasks_data["tasks"],
            "priorities": priorities_data["priorities"],
            "priority_types": priorities_data["priority_types"],
            "default_mode": "tasks",
        }
    )


@app.get("/priorities", response_class=RedirectResponse)
async def priorities_redirect():
    """Redirect to home page."""
    return RedirectResponse(url="/", status_code=302)

# -----------------------------------------------------------------------------
# Routes: HTMX Partials - Priority List
# -----------------------------------------------------------------------------

@app.get("/priorities/list", response_class=HTMLResponse)
async def priorities_list_partial(
    request: Request,
    type: str | None = None,
    active: bool = False,
):
    """HTMX partial: filtered list of priorities."""
    async with api_client(request) as client:
        params = {}
        if type:
            params["type"] = type
        if active:
            params["active"] = "true"
        response = await client.get("/api/priorities", params=params)
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/priority_rows.html",
        {"priorities": data["priorities"]}
    )


@app.get("/priorities/new", response_class=HTMLResponse)
async def new_priority_form(request: Request):
    """Show empty form for creating a new priority."""
    async with api_client(request) as client:
        response = await client.get("/api/priorities")
        data = response.json()

    from praxis_core.model import PriorityType, PriorityStatus
    return templates.TemplateResponse(
        request,
        "partials/priority_new_form.html",
        {
            "all_priorities": data["priorities"],
            "priority_types": [t.value for t in PriorityType],
            "priority_statuses": [s.value for s in PriorityStatus],
        }
    )


@app.get("/priorities/new/fields", response_class=HTMLResponse)
async def priority_type_fields(request: Request, priority_type: str = "goal"):
    """Return type-specific fields for the selected priority type."""
    template_name = f"partials/type_fields/{priority_type}_fields.html"
    return templates.TemplateResponse(request, template_name, {})


@app.post("/priorities/create", response_class=HTMLResponse)
async def create_priority_submit(request: Request):
    """Create a new priority and return the detail view."""
    form_data = await request.form()
    parent_id = form_data.get("parent_id")
    # Normalize empty string to None
    if parent_id and not parent_id.strip():
        parent_id = None

    async with api_client(request) as client:
        response = await client.post("/api/priorities/create", data=dict(form_data))
        if response.status_code == 400:
            error_data = response.json()
            return HTMLResponse(
                content=f"<div class='error'>{error_data.get('error', 'Name is required')}</div>",
                status_code=400
            )
        data = response.json()

    priority = data["priority"]

    # Return priority view mode and trigger list refresh
    html_response = templates.TemplateResponse(
        request,
        "partials/priority_view.html",
        data
    )
    # Include priority data in trigger for tree update
    trigger_data = {
        "priorityCreated": {
            "id": priority["id"],
            "parent_id": parent_id
        }
    }
    html_response.headers["HX-Trigger"] = json.dumps(trigger_data)
    html_response.headers["X-New-Item-Id"] = priority["id"]
    return html_response


@app.post("/priorities/quick-add", response_class=HTMLResponse)
async def quick_add_priority(request: Request):
    """Create a priority via quick-add modal and return the row HTML."""
    form_data = await request.form()
    parent_id = form_data.get("parent_id")
    # Normalize empty string to None
    if parent_id and not parent_id.strip():
        parent_id = None

    async with api_client(request) as client:
        response = await client.post("/api/priorities/create", data=dict(form_data))
        if response.status_code == 400:
            error_data = response.json()
            return HTMLResponse(
                content=f"<div class='error'>{error_data.get('error', 'Name is required')}</div>",
                status_code=400
            )
        data = response.json()

    priority = data["priority"]
    html_response = templates.TemplateResponse(
        request,
        "partials/priority_row_single.html",
        {"priority": priority}
    )
    # Include priority data in trigger for tree update
    trigger_data = {
        "priorityCreated": {
            "id": priority["id"],
            "parent_id": parent_id
        }
    }
    html_response.headers["HX-Trigger"] = json.dumps(trigger_data)
    return html_response


@app.get("/priorities/quick-add/fields", response_class=HTMLResponse)
async def quick_add_priority_fields(request: Request, priority_type: str = "goal"):
    """Return type-specific fields for quick-add modal."""
    template_name = f"partials/type_fields/{priority_type}_fields.html"
    return templates.TemplateResponse(request, template_name, {})


@app.get("/priorities/tree", response_class=HTMLResponse)
async def priority_tree(request: Request):
    """HTMX partial: tree view of priority hierarchy."""
    async with api_client(request) as client:
        response = await client.get("/api/priorities/tree")
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/priority_tree.html",
        {"roots": data["roots"], "children_map": data["children_map"]}
    )


@app.get("/priorities/tree-pane", response_class=HTMLResponse)
async def priority_tree_pane(request: Request):
    """HTMX partial: full tree view for right pane."""
    async with api_client(request) as client:
        response = await client.get("/api/priorities/tree")
        data = response.json()

    # Build nested tree structure for recursive rendering
    children_map = data["children_map"]

    def nest_children(node):
        """Recursively attach children to nodes."""
        node_id = node["id"]
        node["children"] = children_map.get(node_id, [])
        for child in node["children"]:
            nest_children(child)
        return node

    roots = [nest_children(root) for root in data["roots"]]

    return templates.TemplateResponse(
        request,
        "partials/priority_tree_pane.html",
        {"roots": roots}
    )


@app.get("/priorities/{priority_id}/tree-node", response_class=HTMLResponse)
async def priority_tree_node(request: Request, priority_id: str):
    """Return a single tree node HTML for inserting into the tree."""
    async with api_client(request) as client:
        response = await client.get(f"/api/priorities/{priority_id}")
        if response.status_code == 404:
            return HTMLResponse(content="", status_code=404)
        data = response.json()

    priority = data["priority"]
    # New priorities have no children yet
    priority["children"] = []

    return templates.TemplateResponse(
        request,
        "partials/priority_tree_node.html",
        {"node": priority, "depth": 0}
    )


@app.post("/priorities/{priority_id}/move", response_class=HTMLResponse)
async def priority_move(request: Request, priority_id: str):
    """Handle drag-and-drop move of a priority in the tree."""
    data = await request.json()
    new_parent_id = data.get("new_parent_id")
    sibling_ids = data.get("sibling_ids", [])
    new_index = data.get("new_index", 0)

    async with api_client(request) as client:
        # Update parent relationship
        response = await client.post(
            f"/api/priorities/{priority_id}/move",
            json={
                "new_parent_id": new_parent_id,
                "sibling_ids": sibling_ids,
                "new_index": new_index
            }
        )

        if response.status_code != 200:
            return HTMLResponse(
                content="Failed to move priority",
                status_code=response.status_code
            )

    return HTMLResponse(content="OK", status_code=200)


@app.post("/priorities/{priority_id}/delete", response_class=HTMLResponse)
async def priority_delete(request: Request, priority_id: str):
    """Delete a priority, handling children and linked tasks."""
    data = await request.json()
    delete_mode = data.get("delete_mode", "orphan")

    async with api_client(request) as client:
        response = await client.post(
            f"/api/priorities/{priority_id}/delete",
            json={"delete_mode": delete_mode}
        )

        if response.status_code != 200:
            return HTMLResponse(
                content="Failed to delete priority",
                status_code=response.status_code
            )

    return HTMLResponse(content="OK", status_code=200)


# -----------------------------------------------------------------------------
# Routes: HTMX Partials - Priority Detail
# -----------------------------------------------------------------------------

@app.get("/priorities/{priority_id}", response_class=HTMLResponse)
async def priority_detail(request: Request, priority_id: str, from_task: str | None = None):
    """HTMX partial: view mode for a single priority."""
    async with api_client(request) as client:
        response = await client.get(f"/api/priorities/{priority_id}")
        if response.status_code == 404:
            return HTMLResponse(
                content="<div class='error'>Priority not found</div>",
                status_code=404
            )
        data = response.json()

    # Pass from_task for back navigation
    data["from_task"] = from_task

    return templates.TemplateResponse(
        request,
        "partials/priority_view.html",
        data
    )


@app.get("/priorities/{priority_id}/edit", response_class=HTMLResponse)
async def priority_edit(request: Request, priority_id: str):
    """HTMX partial: edit mode for a single priority."""
    async with api_client(request) as client:
        response = await client.get(f"/api/priorities/{priority_id}/edit")
        if response.status_code == 404:
            return HTMLResponse(
                content="<div class='error'>Priority not found</div>",
                status_code=404
            )
        data = response.json()

    from praxis_core.model import PriorityType
    data["priority_types"] = [t.value for t in PriorityType]

    return templates.TemplateResponse(
        request,
        "partials/priority_edit.html",
        data
    )


@app.get("/priorities/{priority_id}/tasks-panel", response_class=HTMLResponse)
async def priority_tasks_panel(request: Request, priority_id: str):
    """HTMX partial: just the tasks panel for a priority."""
    async with api_client(request) as client:
        response = await client.get(f"/api/priorities/{priority_id}")
        if response.status_code == 404:
            return HTMLResponse(content="", status_code=404)
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/priority_tasks_panel.html",
        {"priority": data["priority"], "tasks": data.get("tasks", [])}
    )


@app.post("/priorities/{priority_id}/change-type", response_class=HTMLResponse)
async def priority_change_type(request: Request, priority_id: str):
    """Change priority type and return updated edit form."""
    form_data = await request.form()

    async with api_client(request) as client:
        response = await client.post(
            f"/api/priorities/{priority_id}/change-type",
            data=dict(form_data)
        )
        if response.status_code != 200:
            return HTMLResponse(content="<div class='error'>Failed to change type</div>", status_code=400)
        data = response.json()

    # Add notes_raw for editing
    data["priority"]["notes_raw"] = data["priority"].get("notes") or ""

    # Add priority_types to the data for the dropdown
    from praxis_core.model import PriorityType
    data["priority_types"] = [t.value for t in PriorityType]

    return templates.TemplateResponse(request, "partials/priority_edit.html", data)


@app.post("/priorities/{priority_id}/properties", response_class=HTMLResponse)
async def priority_save_properties(request: Request, priority_id: str):
    """Save priority properties and return view mode + OOB row update."""
    form_data = await request.form()

    async with api_client(request) as client:
        response = await client.post(
            f"/api/priorities/{priority_id}/properties",
            data=dict(form_data)
        )
        if response.status_code == 404:
            return HTMLResponse(
                content="<div class='error'>Priority not found</div>",
                status_code=404
            )
        if response.status_code == 400:
            error_data = response.json()
            return HTMLResponse(
                content=f"<div class='error'>{error_data.get('error', 'Validation error')}</div>",
                status_code=400
            )
        data = response.json()

    # Render view mode (confirms save was successful)
    view_html = templates.TemplateResponse(
        request,
        "partials/priority_view.html",
        data
    ).body.decode()

    # Render OOB row update
    row_html = templates.TemplateResponse(
        request,
        "partials/priority_row_single.html",
        {"priority": data["priority"], "oob": True}
    ).body.decode()

    return HTMLResponse(content=view_html + row_html)


@app.post("/priorities/{priority_id}/notes", response_class=HTMLResponse)
async def priority_save_notes(request: Request, priority_id: str):
    """Save priority notes and return updated notes section."""
    form_data = await request.form()

    async with api_client(request) as client:
        response = await client.post(
            f"/api/priorities/{priority_id}/notes",
            data=dict(form_data)
        )
        if response.status_code == 404:
            return HTMLResponse(
                content="<div class='error'>Priority not found</div>",
                status_code=404
            )
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/item_notes.html",
        data
    )

# -----------------------------------------------------------------------------
# Routes: HTMX Partials - Tasks
# -----------------------------------------------------------------------------

@app.get("/tasks/list", response_class=HTMLResponse)
async def tasks_list_partial(
    request: Request,
    priority: str | None = None,
    status: str | None = None,
):
    """HTMX partial: filtered list of tasks."""
    async with api_client(request) as client:
        params = {}
        if priority:
            params["priority"] = priority
        if status:
            params["status"] = status
        response = await client.get("/api/tasks", params=params)
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/task_rows.html",
        {"tasks": data["tasks"], "priorities": data.get("priorities", [])}
    )


@app.get("/tasks/inbox", response_class=HTMLResponse)
async def tasks_inbox_partial(request: Request):
    """HTMX partial: inbox tasks (no priority assigned)."""
    async with api_client(request) as client:
        response = await client.get("/api/tasks", params={"inbox": "true"})
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/task_rows.html",
        {"tasks": data["tasks"], "priorities": data.get("priorities", [])}
    )


@app.get("/tasks/new", response_class=HTMLResponse)
async def new_task_form(request: Request):
    """Show empty form for creating a new task."""
    async with api_client(request) as client:
        response = await client.get("/api/priorities")
        data = response.json()

    from praxis_core.model import TaskStatus
    return templates.TemplateResponse(
        request,
        "partials/task_new_form.html",
        {
            "priorities": data["priorities"],
            "task_statuses": [s.value for s in TaskStatus],
        }
    )


@app.post("/tasks/create", response_class=HTMLResponse)
async def create_task_submit(request: Request):
    """Create a new task and return the view mode (read-only display)."""
    form_data = await request.form()

    async with api_client(request) as client:
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
    async with api_client(request) as client:
        detail_response = await client.get(f"/api/tasks/{task['id']}")
        detail_data = detail_response.json()

    # Include HX-Trigger to refresh the task list
    html_response = templates.TemplateResponse(
        request,
        "partials/task_view.html",
        detail_data
    )
    html_response.headers["HX-Trigger"] = "taskCreated"
    html_response.headers["X-New-Item-Id"] = str(task["id"])
    return html_response


@app.post("/tasks/quick-add", response_class=HTMLResponse)
async def quick_add_task(request: Request):
    """Create a task via quick-add modal and return the row HTML."""
    form_data = await request.form()

    async with api_client(request) as client:
        response = await client.post("/api/tasks", data=dict(form_data))
        if response.status_code == 400:
            error_data = response.json()
            return HTMLResponse(
                content=f"<div class='error'>{error_data.get('error', 'Name is required')}</div>",
                status_code=400
            )
        data = response.json()

    task = data["task"]
    html_response = templates.TemplateResponse(
        request,
        "partials/task_row_single.html",
        {"task": task}
    )
    # Trigger event to close modal
    html_response.headers["HX-Trigger"] = "taskCreated"
    return html_response

@app.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: str):
    """HTMX partial: view mode for a single task."""
    async with api_client(request) as client:
        response = await client.get(f"/api/tasks/{task_id}")
        if response.status_code == 404:
            return HTMLResponse(
                content="<div class='error'>Task not found</div>",
                status_code=404
            )
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/task_view.html",
        data
    )


@app.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
async def task_edit(request: Request, task_id: str):
    """HTMX partial: edit mode for a single task."""
    async with api_client(request) as client:
        response = await client.get(f"/api/tasks/{task_id}/edit")
        if response.status_code == 404:
            return HTMLResponse(
                content="<div class='error'>Task not found</div>",
                status_code=404
            )
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/task_edit.html",
        data
    )


@app.post("/tasks/{task_id}/properties", response_class=HTMLResponse)
async def task_save_properties(request: Request, task_id: str):
    """Save task properties and return view mode + OOB row update."""
    form_data = await request.form()

    async with api_client(request) as client:
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

    # Render view mode (confirms save was successful)
    view_html = templates.TemplateResponse(
        request,
        "partials/task_view.html",
        data
    ).body.decode()

    # Render OOB row update
    row_html = templates.TemplateResponse(
        request,
        "partials/task_row_single.html",
        {"task": data["task"], "oob": True}
    ).body.decode()

    return HTMLResponse(content=view_html + row_html)


@app.post("/tasks/{task_id}/notes", response_class=HTMLResponse)
async def task_save_notes(request: Request, task_id: str):
    """Save task notes and return updated notes section."""
    form_data = await request.form()

    async with api_client(request) as client:
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

    return templates.TemplateResponse(
        request,
        "partials/item_notes.html",
        data
    )


@app.post("/tasks/{task_id}/toggle", response_class=HTMLResponse)
async def task_toggle_done(request: Request, task_id: str):
    """Toggle task between done and queued."""
    async with api_client(request) as client:
        response = await client.post(f"/api/tasks/{task_id}/toggle")
        if response.status_code == 404:
            return HTMLResponse(content="", status_code=404)
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/task_row_single.html",
        {"task": data["task"]}
    )


@app.delete("/tasks/{task_id}", response_class=HTMLResponse)
async def delete_task(request: Request, task_id: str):
    """Delete a task and return empty content."""
    async with api_client(request) as client:
        response = await client.delete(f"/api/tasks/{task_id}")
        if response.status_code == 404:
            return HTMLResponse(content="", status_code=404)

    # Return empty response - HTMX will remove the row
    return HTMLResponse(content="")


@app.delete("/priorities/{priority_id}", response_class=HTMLResponse)
async def delete_priority(request: Request, priority_id: str):
    """Delete a priority and return empty content."""
    async with api_client(request) as client:
        response = await client.delete(f"/api/priorities/{priority_id}")
        if response.status_code == 404:
            return HTMLResponse(content="", status_code=404)

    # Return empty response - HTMX will remove the node
    return HTMLResponse(content="")


# -----------------------------------------------------------------------------
# Routes: Sharing
# -----------------------------------------------------------------------------

@app.get("/users", response_class=HTMLResponse)
async def get_users_for_share(request: Request):
    """Get list of users for share dropdown (as partial HTML)."""
    async with api_client(request) as client:
        response = await client.get("/api/auth/users")
        if response.status_code != 200:
            return HTMLResponse(content="[]")
        users = response.json()
    return Response(content=json.dumps(users), media_type="application/json")


@app.post("/priorities/{priority_id}/share")
async def share_priority(request: Request, priority_id: str):
    """Share a priority with another user."""
    data = await request.json()
    user_id = data.get("user_id")
    permission = data.get("permission", "contributor")

    if not user_id:
        return Response(
            content=json.dumps({"success": False, "error": "User ID required"}),
            media_type="application/json",
            status_code=400
        )

    async with api_client(request) as client:
        response = await client.post(
            f"/api/priorities/{priority_id}/share",
            json={"user_id": user_id, "permission": permission}
        )

        if response.status_code != 200:
            error_data = response.json() if response.content else {}
            return Response(
                content=json.dumps({
                    "success": False,
                    "error": error_data.get("detail", "Failed to share")
                }),
                media_type="application/json",
                status_code=response.status_code
            )

        return Response(
            content=json.dumps({"success": True}),
            media_type="application/json"
        )