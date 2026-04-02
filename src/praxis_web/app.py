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
PRAXIS_ENV = os.getenv("PRAXIS_ENV", "local")  # local, staging, production

# Static files and templates
STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Make environment available in all templates
templates.env.globals["praxis_env"] = PRAXIS_ENV

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


def is_htmx_request(request: Request) -> bool:
    """Check if this is an HTMX request (partial) vs full page load."""
    return request.headers.get("HX-Request") == "true"


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
async def signup_page(request: Request, error: str | None = None, invite_token: str | None = None):
    """Display signup page."""
    # If already logged in, redirect to home
    if request.cookies.get(SESSION_COOKIE_NAME):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(
        request,
        "signup.html",
        {"error": error, "invite_token": invite_token}
    )


@app.post("/signup")
async def signup_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()],
    invite_token: Annotated[str | None, Form()] = None,
):
    """Handle signup form submission."""
    # Validate passwords match
    if password != password_confirm:
        return templates.TemplateResponse(
            request,
            "signup.html",
            {"error": "Passwords do not match", "invite_token": invite_token},
            status_code=400
        )

    async with httpx.AsyncClient(base_url=API_URL, timeout=30.0) as client:
        register_data = {"username": username, "password": password}
        if invite_token:
            register_data["invite_token"] = invite_token
        response = await client.post(
            "/api/auth/register",
            json=register_data
        )

        if response.status_code != 200:
            error_data = response.json()
            error_msg = error_data.get("detail", "Registration failed")
            return templates.TemplateResponse(
                request,
                "signup.html",
                {"error": error_msg, "invite_token": invite_token},
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
# Routes: Invite Acceptance
# -----------------------------------------------------------------------------

@app.get("/invite/{token}", response_class=HTMLResponse)
async def invite_page(request: Request, token: str):
    """Display invite acceptance page."""
    # Validate the token
    async with httpx.AsyncClient(base_url=API_URL, timeout=30.0) as client:
        response = await client.get(f"/api/invites/validate/{token}")
        data = response.json()

    if not data.get("valid"):
        return templates.TemplateResponse(
            request,
            "invite.html",
            {"valid": False, "error": "This invitation is invalid or has expired."}
        )

    # Check if user is already logged in
    if request.cookies.get(SESSION_COOKIE_NAME):
        # Could add "accept while logged in" flow here
        # For now, redirect to home with a message
        return templates.TemplateResponse(
            request,
            "invite.html",
            {
                "valid": True,
                "logged_in": True,
                "inviter_username": data.get("inviter_username"),
                "token": token,
            }
        )

    # Show signup form with invite context
    return templates.TemplateResponse(
        request,
        "invite.html",
        {
            "valid": True,
            "logged_in": False,
            "inviter_username": data.get("inviter_username"),
            "email": data.get("email"),
            "token": token,
        }
    )


# -----------------------------------------------------------------------------
# Routes: Pages
# -----------------------------------------------------------------------------

async def render_full_page(
    request: Request,
    mode: str = "tasks",
    initial_list_html: str | None = None,
    initial_detail_html: str | None = None,
):
    """Render full home page with specific mode and optional pre-rendered content."""
    # Check if user is logged in
    if not request.cookies.get(SESSION_COOKIE_NAME):
        return RedirectResponse(url="/login", status_code=302)

    async with api_client(request) as client:
        # Fetch user info
        me_response = await client.get("/api/auth/me")
        if me_response.status_code != 200:
            response = RedirectResponse(url="/login", status_code=302)
            response.delete_cookie(key=SESSION_COOKIE_NAME)
            return response
        user = me_response.json()

        # Always fetch priorities for dropdowns
        priorities_response = await client.get("/api/priorities")
        priorities_data = priorities_response.json()

        # Fetch user's tags for filter dropdown
        tags_response = await client.get("/api/tags")
        tags_data = tags_response.json() if tags_response.status_code == 200 else {"tags": []}

        # Fetch tasks for task modes (needed for default list if no initial_list_html)
        tasks_data = {"tasks": []}
        if mode in ["tasks", "inbox"] and not initial_list_html:
            if mode == "inbox":
                tasks_response = await client.get("/api/tasks/inbox")
            else:
                tasks_response = await client.get("/api/tasks")
            tasks_data = tasks_response.json()

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "user": user,
            "tasks": tasks_data.get("tasks", []),
            "priorities": priorities_data["priorities"],
            "priority_types": priorities_data["priority_types"],
            "user_tags": tags_data.get("tags", []),
            "default_mode": mode,
            "initial_list_html": initial_list_html,
            "initial_detail_html": initial_detail_html,
        }
    )


@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    """Full page: two-pane layout with tasks as default view."""
    return await render_full_page(request, mode="tasks")


@app.get("/tasks", response_class=HTMLResponse)
async def tasks_page(
    request: Request,
    priority: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    q: str | None = None,
):
    """Tasks queue view - full page or HTMX partial."""
    if is_htmx_request(request):
        # Return just the task list partial with filters
        return await tasks_list_partial(request, priority=priority, status=status, tag=tag, q=q)
    return await render_full_page(request, mode="tasks")


@app.get("/tasks/inbox", response_class=HTMLResponse)
async def tasks_inbox_page(request: Request):
    """Inbox view - full page or HTMX partial."""
    if is_htmx_request(request):
        # Return just the inbox list partial
        async with api_client(request) as client:
            response = await client.get("/api/tasks", params={"inbox": "true"})
            data = response.json()
        return templates.TemplateResponse(
            request,
            "partials/task_rows.html",
            {"tasks": data["tasks"], "priorities": data.get("priorities", [])}
        )
    return await render_full_page(request, mode="inbox")


@app.get("/priorities", response_class=HTMLResponse)
async def priorities_page(request: Request):
    """Priorities view - full page or HTMX partial."""
    if is_htmx_request(request):
        return await priorities_list_partial(request)

    # For full page, render the priority list
    async with api_client(request) as client:
        response = await client.get("/api/priorities")
        data = response.json()

    list_html = templates.get_template("partials/priority_rows.html").render(
        priorities=data["priorities"]
    )

    return await render_full_page(request, mode="priorities", initial_list_html=list_html)

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
async def priority_type_fields(request: Request, priority_type: str = "initiative"):
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
    html_response.headers["HX-Push-Url"] = f"/priorities/{priority['id']}"
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
async def quick_add_priority_fields(request: Request, priority_type: str = "initiative"):
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
    """Priority detail - full page or HTMX partial."""
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

    # HTMX request - return partial
    if is_htmx_request(request):
        return templates.TemplateResponse(
            request,
            "partials/priority_view.html",
            data
        )

    # Full page request - render with priority detail and list pre-loaded
    detail_html = templates.get_template("partials/priority_view.html").render(
        request=request, **data
    )

    # Also get priority list for left pane
    async with api_client(request) as client:
        list_response = await client.get("/api/priorities")
        list_data = list_response.json()

    list_html = templates.get_template("partials/priority_rows.html").render(
        priorities=list_data["priorities"]
    )

    return await render_full_page(
        request,
        mode="priorities",
        initial_list_html=list_html,
        initial_detail_html=detail_html
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
    tag: str | None = None,
    q: str | None = None,
):
    """HTMX partial: filtered list of tasks."""
    async with api_client(request) as client:
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

    return templates.TemplateResponse(
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
    html_response.headers["HX-Push-Url"] = f"/tasks/{task['id']}"
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

@app.get("/tasks/quick-add/priorities", response_class=HTMLResponse)
async def quick_add_priorities(request: Request):
    """Return fresh priority options for the quick-add modal dropdown."""
    async with api_client(request) as client:
        response = await client.get("/api/priorities")
        data = response.json()

    # Build options HTML
    options = ['<option value="">Inbox (no priority)</option>']
    for p in data["priorities"]:
        options.append(f'<option value="{p["id"]}">{p["name"]}</option>')

    return HTMLResponse(content="\n".join(options))


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: str):
    """Task detail - full page or HTMX partial."""
    async with api_client(request) as client:
        response = await client.get(f"/api/tasks/{task_id}")
        if response.status_code == 404:
            return HTMLResponse(
                content="<div class='error'>Task not found</div>",
                status_code=404
            )
        data = response.json()

    # HTMX request - return partial
    if is_htmx_request(request):
        return templates.TemplateResponse(
            request,
            "partials/task_view.html",
            data
        )

    # Full page request - render with task detail pre-loaded
    detail_html = templates.get_template("partials/task_view.html").render(
        request=request, **data
    )
    return await render_full_page(
        request,
        mode="tasks",
        initial_detail_html=detail_html
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

# -----------------------------------------------------------------------------
# Routes: Friends
# -----------------------------------------------------------------------------

@app.get("/friends", response_class=HTMLResponse)
async def friends_page(request: Request):
    """Friends view - full page or HTMX partial."""
    if is_htmx_request(request):
        return await friends_list_partial(request)

    # For full page, render the friends list
    async with api_client(request) as client:
        response = await client.get("/api/friends")
        friends = response.json() if response.status_code == 200 else []

    list_html = templates.get_template("partials/friends_list.html").render(
        friends=friends
    )

    return await render_full_page(request, mode="friends", initial_list_html=list_html)


@app.get("/friends/list", response_class=HTMLResponse)
async def friends_list_partial(request: Request):
    """HTMX partial: list of friends."""
    async with api_client(request) as client:
        response = await client.get("/api/friends")
        friends = response.json() if response.status_code == 200 else []

    return templates.TemplateResponse(
        request,
        "partials/friends_list.html",
        {"friends": friends}
    )


@app.delete("/friends/{friend_id}", response_class=HTMLResponse)
async def remove_friend(request: Request, friend_id: int):
    """Remove a friend."""
    async with api_client(request) as client:
        response = await client.delete(f"/api/friends/{friend_id}")
        if response.status_code != 200:
            return HTMLResponse(content="<div class='error'>Failed to remove friend</div>")

    # Return empty content to remove the row
    return HTMLResponse(content="")


@app.post("/invites")
async def create_invite(request: Request):
    """Create an invite and return the token."""
    async with api_client(request) as client:
        response = await client.post("/api/invites", json={})

        if response.status_code != 200:
            error_data = response.json() if response.content else {}
            return Response(
                content=json.dumps({"error": error_data.get("detail", "Failed to create invite")}),
                media_type="application/json",
                status_code=response.status_code
            )

        return Response(
            content=response.content,
            media_type="application/json"
        )


@app.get("/users", response_class=HTMLResponse)
async def get_users_for_share(request: Request):
    """Get list of friends for share dropdown (only friends can be shared with)."""
    async with api_client(request) as client:
        response = await client.get("/api/friends")
        if response.status_code != 200:
            return HTMLResponse(content="[]")
        friends = response.json()
    return Response(content=json.dumps(friends), media_type="application/json")


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


# -----------------------------------------------------------------------------
# Routes: Tags
# -----------------------------------------------------------------------------

@app.get("/tags/search", response_class=HTMLResponse)
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


@app.get("/tasks/{task_id}/tags", response_class=HTMLResponse)
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


@app.post("/tasks/{task_id}/tags", response_class=HTMLResponse)
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


@app.delete("/tasks/{task_id}/tags/{tag_id}", response_class=HTMLResponse)
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


@app.post("/priorities/{priority_id}/tags", response_class=HTMLResponse)
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


@app.delete("/priorities/{priority_id}/tags/{tag_id}", response_class=HTMLResponse)
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


# -----------------------------------------------------------------------------
# Filter Options (for dynamic dropdown refresh)
# -----------------------------------------------------------------------------

@app.get("/filters/priorities", response_class=HTMLResponse)
async def filter_priority_options(request: Request, selected: str | None = None):
    """Return priority filter options for dropdown refresh."""
    async with api_client(request) as client:
        response = await client.get("/api/priorities")
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/components/filter_priority_options.html",
        {"priorities": data.get("priorities", []), "selected": selected}
    )


@app.get("/filters/tags", response_class=HTMLResponse)
async def filter_tag_options(request: Request, selected: str | None = None):
    """Return tag filter options for dropdown refresh."""
    async with api_client(request) as client:
        response = await client.get("/api/tags")
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/components/filter_tag_options.html",
        {"user_tags": data.get("tags", []), "selected": selected}
    )


# -----------------------------------------------------------------------------
# Routes: Rules
# -----------------------------------------------------------------------------

@app.get("/rules", response_class=HTMLResponse)
async def rules_page(request: Request):
    """Rules view - full page or HTMX partial."""
    if is_htmx_request(request):
        return await rules_list_partial(request)

    async with api_client(request) as client:
        response = await client.get("/api/rules")
        data = response.json() if response.status_code == 200 else {}
        rules = data.get("rules", [])

    list_html = templates.get_template("partials/rules_list.html").render(rules=rules)
    return await render_full_page(request, mode="rules", initial_list_html=list_html)


@app.get("/rules/list", response_class=HTMLResponse)
async def rules_list_partial(request: Request):
    """HTMX partial: list of rules."""
    async with api_client(request) as client:
        response = await client.get("/api/rules")
        data = response.json() if response.status_code == 200 else {}
        rules = data.get("rules", [])

    return templates.TemplateResponse(
        request,
        "partials/rules_list.html",
        {"rules": rules}
    )


@app.get("/rules/{rule_id}", response_class=HTMLResponse)
async def rule_detail(request: Request, rule_id: str):
    """HTMX partial: rule detail view."""
    async with api_client(request) as client:
        response = await client.get(f"/api/rules/{rule_id}")
        if response.status_code != 200:
            return HTMLResponse("<div class='error'>Rule not found</div>", status_code=404)
        data = response.json()
        rule = data.get("rule")

    return templates.TemplateResponse(
        request,
        "partials/rule_view.html",
        {"rule": rule}
    )


@app.post("/rules/{rule_id}/toggle", response_class=HTMLResponse)
async def toggle_rule_web(request: Request, rule_id: str):
    """Toggle a rule's enabled state."""
    async with api_client(request) as client:
        response = await client.post(f"/api/rules/{rule_id}/toggle")
        if response.status_code != 200:
            return HTMLResponse("<div class='error'>Failed to toggle rule</div>")
    return HTMLResponse("")


@app.post("/rules/restore-defaults", response_class=HTMLResponse)
async def restore_defaults_web(request: Request):
    """Restore user's rules to defaults and return updated list."""
    async with api_client(request) as client:
        response = await client.post("/api/rules/restore-defaults")
        if response.status_code != 200:
            return HTMLResponse("<div class='error'>Failed to restore defaults</div>")
        data = response.json()
        rules = data.get("rules", [])

    return templates.TemplateResponse(
        request,
        "partials/rules_list.html",
        {"rules": rules}
    )


@app.get("/rules/new", response_class=HTMLResponse)
async def new_rule_form(request: Request):
    """Show new rule form (placeholder for now)."""
    return HTMLResponse("""
        <div class="empty-state">
            <h3>New Rule</h3>
            <p>Rule creation wizard coming soon</p>
        </div>
    """)