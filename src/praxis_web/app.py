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
from starlette.responses import StreamingResponse
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
# Dev/Demo Routes
# -----------------------------------------------------------------------------

@app.get("/demo/chips", response_class=HTMLResponse)
async def chip_demo(request: Request):
    """Demo page for chip components."""
    return templates.TemplateResponse(request, "chip_demo.html", {})


# -----------------------------------------------------------------------------
# Chip Partials (HTMX endpoints for dynamic chip spawning)
# -----------------------------------------------------------------------------

@app.get("/partials/chips/day", response_class=HTMLResponse)
async def chip_day_partial(
    request: Request,
    name: str = "days",
    value: str = "",
    period: str = "weeks"
):
    """Return day chip HTML fragment for HTMX spawning."""
    return templates.TemplateResponse(
        request,
        "partials/chips/chip_day.html",
        {"name": name, "value": value, "period": period}
    )


@app.get("/partials/chips/number", response_class=HTMLResponse)
async def chip_number_partial(
    request: Request,
    name: str = "count",
    value: str = "2"
):
    """Return number chip HTML fragment for HTMX spawning."""
    return templates.TemplateResponse(
        request,
        "partials/chips/chip_number.html",
        {"name": name, "value": value}
    )


@app.get("/partials/chips/period", response_class=HTMLResponse)
async def chip_period_partial(
    request: Request,
    name: str = "period",
    value: str = "weeks"
):
    """Return period chip HTML fragment for HTMX spawning."""
    return templates.TemplateResponse(
        request,
        "partials/chips/chip_period.html",
        {"name": name, "value": value}
    )


@app.get("/partials/chips/month", response_class=HTMLResponse)
async def chip_month_partial(
    request: Request,
    name: str = "month",
    value: str = "",
    mode: str = "year"
):
    """Return month chip HTML fragment for HTMX spawning."""
    return templates.TemplateResponse(
        request,
        "partials/chips/chip_month.html",
        {"name": name, "value": value, "mode": mode}
    )


@app.get("/partials/chips/time", response_class=HTMLResponse)
async def chip_time_partial(
    request: Request,
    name: str = "time",
    value: str = ""
):
    """Return time-of-day chip HTML fragment for HTMX spawning."""
    return templates.TemplateResponse(
        request,
        "partials/chips/chip_time.html",
        {"name": name, "value": value}
    )


@app.get("/partials/chips/start", response_class=HTMLResponse)
async def chip_start_partial(
    request: Request,
    name: str = "start",
    value: str = "immediately",
    period: str = "weeks"
):
    """Return start date chip HTML fragment for HTMX spawning."""
    return templates.TemplateResponse(
        request,
        "partials/chips/chip_start.html",
        {"name": name, "value": value, "period": period}
    )


@app.get("/partials/chips/description", response_class=HTMLResponse)
async def chip_description_partial(
    request: Request,
    name: str = "description",
    value: str = "",
    practice_name: str = ""
):
    """Return description chip HTML fragment for HTMX spawning."""
    return templates.TemplateResponse(
        request,
        "partials/chips/chip_description.html",
        {"name": name, "value": value, "practice_name": practice_name}
    )


@app.get("/partials/chips/tags", response_class=HTMLResponse)
async def chip_tags_partial(
    request: Request,
    name: str = "tags",
    value: str = ""
):
    """Return tags chip HTML fragment for HTMX spawning."""
    return templates.TemplateResponse(
        request,
        "partials/chips/chip_tags.html",
        {"name": name, "value": value}
    )


@app.get("/partials/chips/due", response_class=HTMLResponse)
async def chip_due_partial(
    request: Request,
    name: str = "due",
    value: str = "end_of_day"
):
    """Return due date chip HTML fragment for HTMX spawning."""
    return templates.TemplateResponse(
        request,
        "partials/chips/chip_due.html",
        {"name": name, "value": value}
    )


@app.get("/partials/chips/task_name", response_class=HTMLResponse)
async def chip_task_name_partial(
    request: Request,
    name: str = "task_name",
    value: str = ""
):
    """Return task name chip HTML fragment for HTMX spawning."""
    return templates.TemplateResponse(
        request,
        "partials/chips/chip_task_name.html",
        {"name": name, "value": value}
    )


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

    # For full page, render the priority list and tree pane
    async with api_client(request) as client:
        response = await client.get("/api/priorities")
        data = response.json()

        # Also get tree data for detail pane
        tree_response = await client.get("/api/priorities/tree")
        tree_data = tree_response.json()

    list_html = templates.get_template("partials/priority_rows.html").render(
        priorities=data["priorities"]
    )

    # Build nested tree structure for recursive rendering
    children_map = tree_data["children_map"]

    def nest_children(node):
        node_id = node["id"]
        node["children"] = children_map.get(node_id, [])
        for child in node["children"]:
            nest_children(child)
        return node

    roots = [nest_children(root) for root in tree_data["roots"]]

    detail_html = templates.get_template("partials/priority_tree_pane.html").render(
        roots=roots
    )

    return await render_full_page(request, mode="priorities", initial_list_html=list_html, initial_detail_html=detail_html)

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


@app.get("/priorities/parent-options", response_class=HTMLResponse)
async def priority_parent_options(request: Request, exclude: str | None = None):
    """Return fresh parent priority options for dropdowns."""
    async with api_client(request) as client:
        response = await client.get("/api/priorities")
        data = response.json()

    options = ['<option value="">None</option>']
    for p in data["priorities"]:
        if exclude and p["id"] == exclude:
            continue
        options.append(f'<option value="{p["id"]}">{p["name"]} ({p["priority_type"]})</option>')

    return HTMLResponse(content="\n".join(options))


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

    # For Practice priorities, render actions for the editor
    if data["priority"].get("priority_type") == "practice":
        from praxis_web.helpers.action_renderer import render_actions_from_config
        actions_config = data["priority"].get("actions_config")
        data["actions"] = render_actions_from_config(actions_config) if actions_config else []
        data["editable"] = True

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


@app.get("/priorities/{priority_id}/trigger/edit", response_class=HTMLResponse)
async def priority_trigger_edit(request: Request, priority_id: str):
    """Show trigger editor form for a Practice."""
    async with api_client(request) as client:
        response = await client.get(f"/api/priorities/{priority_id}")
        if response.status_code == 404:
            return HTMLResponse(
                content="<div class='error'>Priority not found</div>",
                status_code=404
            )
        data = response.json()

    priority = data["priority"]

    # Parse existing trigger config if present
    trigger = None
    if priority.get("trigger_config"):
        import json
        try:
            from praxis_core.model.practice_triggers import PracticeTrigger
            pt = PracticeTrigger.from_json(priority["trigger_config"])
            # Flatten to simple dict for template
            trigger = {
                "interval": pt.event.params.get("interval"),
                "at": pt.event.params.get("at", "09:00"),
                "day": pt.event.params.get("day"),
                "task_name": pt.task_template.name_pattern if pt.task_template else "",
                "task_notes": pt.task_template.notes_pattern if pt.task_template else "",
                "due": pt.task_template.due_date_offset if pt.task_template else "",
                "enabled": pt.enabled,
            }
        except Exception:
            trigger = None

    return templates.TemplateResponse(
        request,
        "partials/trigger_editor.html",
        {"priority": priority, "trigger": trigger}
    )


@app.post("/priorities/{priority_id}/trigger", response_class=HTMLResponse)
async def priority_trigger_save(request: Request, priority_id: str):
    """Save trigger configuration for a Practice."""
    form_data = await request.form()

    # Build trigger config from form data
    interval = form_data.get("interval")
    at_time = form_data.get("at", "09:00")
    day = form_data.get("day")
    task_name = form_data.get("task_name", "")
    task_notes = form_data.get("task_notes", "")
    due = form_data.get("due", "")
    enabled = form_data.get("enabled") == "on"

    if not interval:
        return HTMLResponse(
            content="<div class='error'>Please select a schedule</div>",
            status_code=400
        )

    if not task_name.strip():
        return HTMLResponse(
            content="<div class='error'>Task name is required</div>",
            status_code=400
        )

    # Build PracticeTrigger
    from praxis_core.model.practice_triggers import (
        PracticeTrigger, TriggerEvent, TriggerEventType, TaskTemplate
    )

    event_params = {"interval": interval, "at": at_time}
    if interval == "weekly" and day:
        event_params["day"] = day

    trigger = PracticeTrigger(
        event=TriggerEvent(type=TriggerEventType.SCHEDULE, params=event_params),
        task_template=TaskTemplate(
            name_pattern=task_name.strip(),
            notes_pattern=task_notes.strip() if task_notes.strip() else None,
            due_date_offset=due if due else None,
        ),
        enabled=enabled,
    )

    # Save to database via direct update
    from praxis_core.persistence import get_connection, PriorityGraph, validate_session

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return HTMLResponse(content="<div class='error'>Authentication required</div>", status_code=401)
    result = validate_session(session_token)
    if not result:
        return HTMLResponse(content="<div class='error'>Invalid session</div>", status_code=401)
    _, user = result

    graph = PriorityGraph(get_connection, entity_id=user.entity_id)
    graph.load()

    priority = graph.get(priority_id)
    if not priority:
        return HTMLResponse(content="<div class='error'>Priority not found</div>", status_code=404)

    if priority.entity_id != user.entity_id:
        return HTMLResponse(content="<div class='error'>Permission denied</div>", status_code=403)

    # Update trigger config
    priority.trigger_config = trigger.to_json()
    from datetime import datetime
    priority.updated_at = datetime.now()
    graph.save_priority(priority)

    # Return updated priority view
    async with api_client(request) as client:
        response = await client.get(f"/api/priorities/{priority_id}")
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/priority_view.html",
        data
    )


@app.delete("/priorities/{priority_id}/trigger", response_class=HTMLResponse)
async def priority_trigger_delete(request: Request, priority_id: str):
    """Remove trigger configuration from a Practice."""
    from praxis_core.persistence import get_connection, PriorityGraph, validate_session

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return HTMLResponse(content="<div class='error'>Authentication required</div>", status_code=401)
    result = validate_session(session_token)
    if not result:
        return HTMLResponse(content="<div class='error'>Invalid session</div>", status_code=401)
    _, user = result

    graph = PriorityGraph(get_connection, entity_id=user.entity_id)
    graph.load()

    priority = graph.get(priority_id)
    if not priority:
        return HTMLResponse(content="<div class='error'>Priority not found</div>", status_code=404)

    if priority.entity_id != user.entity_id:
        return HTMLResponse(content="<div class='error'>Permission denied</div>", status_code=403)

    # Clear trigger config
    priority.trigger_config = None
    priority.last_triggered_at = None
    from datetime import datetime
    priority.updated_at = datetime.now()
    graph.save_priority(priority)

    # Return updated priority view
    async with api_client(request) as client:
        response = await client.get(f"/api/priorities/{priority_id}")
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/priority_view.html",
        data
    )


# -----------------------------------------------------------------------------
# Routes: Practice Actions (DSL v2)
# -----------------------------------------------------------------------------

@app.get("/priorities/{priority_id}/actions", response_class=HTMLResponse)
async def priority_actions_editor(request: Request, priority_id: str):
    """HTMX partial: Actions editor for a Practice."""
    from praxis_core.persistence import get_connection, PriorityGraph, validate_session
    from praxis_web.helpers.action_renderer import render_actions_from_config, actions_to_yaml

    # Authenticate via session cookie
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return HTMLResponse(content="<div class='error'>Authentication required</div>", status_code=401)

    result = validate_session(session_token)
    if not result:
        return HTMLResponse(content="<div class='error'>Invalid session</div>", status_code=401)

    _, user = result

    graph = PriorityGraph(get_connection, entity_id=user.entity_id)
    graph.load()

    priority = graph.get(priority_id)
    if not priority:
        return HTMLResponse(content="<div class='error'>Priority not found</div>", status_code=404)

    actions = render_actions_from_config(priority.actions_config)
    actions_yaml = actions_to_yaml(priority.actions_config)
    editable = priority.entity_id == user.entity_id

    return templates.TemplateResponse(
        request,
        "partials/actions/actions_editor.html",
        {
            "priority": {"id": priority_id, "actions_config": priority.actions_config},
            "actions": actions,
            "actions_yaml": actions_yaml,
            "editable": editable,
        }
    )


@app.get("/priorities/{priority_id}/actions/wizard", response_class=HTMLResponse)
async def priority_actions_wizard(
    request: Request,
    priority_id: str,
    page: str = "start",
):
    """HTMX partial: Actions wizard modal with DAG navigation."""
    from praxis_core.persistence import get_connection, PriorityGraph, validate_session

    # Authenticate
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return HTMLResponse(content="<div class='error'>Authentication required</div>", status_code=401)

    result = validate_session(session_token)
    if not result:
        return HTMLResponse(content="<div class='error'>Invalid session</div>", status_code=401)

    _, user = result

    graph = PriorityGraph(get_connection, entity_id=user.entity_id)
    graph.load()

    priority = graph.get(priority_id)
    if not priority:
        return HTMLResponse(content="<div class='error'>Priority not found</div>", status_code=404)

    # Accumulate wizard data from query params
    params = dict(request.query_params)
    wizard_data = {
        "action_type": params.get("action_type", "create"),
        "trigger_type": params.get("trigger_type", "schedule"),
        # Collation fields
        "collate_under_practice": params.get("collate_under_practice"),
        "collate_under_priority": params.get("collate_under_priority"),
        "collate_priority_id": params.get("collate_priority_id"),
        "collate_with_tag": params.get("collate_with_tag"),
        "collate_tag": params.get("collate_tag"),
        "collate_due_day": params.get("collate_due_day"),
        "collate_due_value": params.get("collate_due_value"),
        # Schedule fields
        "schedule": {
            "interval": params.get("schedule_interval", "weekdays"),
            "days": params.get("schedule_days", "").split(",") if params.get("schedule_days") else [],
            "cadence_value": int(params.get("schedule_cadence_value", 2)),
            "cadence_unit": params.get("schedule_cadence_unit", "w"),
            "cadence_anchor": params.get("schedule_cadence_anchor"),
            "at": params.get("schedule_at") if params.get("schedule_has_time") else None,
        },
        # Event fields
        "event": {
            "entity": params.get("event_entity", "task"),
            "lifecycle": params.get("event_lifecycle", "completed"),
            "filter": {
                "type": params.get("event_filter_type", "any"),
                "priority_id": params.get("event_filter_priority_id"),
                "tag": params.get("event_filter_tag"),
            }
        },
        # Task details
        "task_name": params.get("task_name", ""),
        "task_description": params.get("task_description", ""),
        "task_due": params.get("task_due", "end_of_day"),
        "task_tags": params.get("task_tags", ""),
    }

    # DAG navigation logic
    action_type = wizard_data["action_type"]
    trigger_type = wizard_data["trigger_type"]

    # Calculate next_page based on current page and state
    if page == "start":
        next_page = "collation" if action_type == "collate" else "trigger"
        back_page = None
    elif page == "collation":
        next_page = "trigger"
        back_page = "start"
    elif page == "trigger":
        next_page = "schedule" if trigger_type == "schedule" else "event"
        back_page = "collation" if action_type == "collate" else "start"
    elif page == "schedule":
        next_page = "details"
        back_page = "trigger"
    elif page == "event":
        next_page = "details"
        back_page = "trigger"
    elif page == "details":
        next_page = "confirm"
        back_page = "schedule" if trigger_type == "schedule" else "event"
    elif page == "confirm":
        next_page = None
        back_page = "details"
    else:
        next_page = "start"
        back_page = None

    # Progress percentage
    page_order = ["start", "collation", "trigger", "schedule", "event", "details", "confirm"]
    progress_pct = 20
    if page in page_order:
        idx = page_order.index(page)
        progress_pct = min(100, (idx + 1) * 20)

    # Build preview sentence for confirmation page
    preview_sentence = ""
    if page == "confirm":
        preview_sentence = _build_action_preview(wizard_data)

    # Get all priorities for selectors (from graph.nodes dict)
    priorities = [p for p in graph.nodes.values() if p.id != priority_id]

    return templates.TemplateResponse(
        request,
        "partials/actions/action_wizard_modal.html",
        {
            "priority_id": priority_id,
            "practice_name": priority.name,
            "page": page,
            "next_page": next_page,
            "back_page": back_page,
            "progress_pct": progress_pct,
            "wizard_data": wizard_data,
            "priorities": priorities,
            "preview_sentence": preview_sentence,
        }
    )


def _build_action_preview(wizard_data: dict) -> str:
    """Build human-readable preview sentence for action."""
    parts = []

    # Trigger part
    if wizard_data["trigger_type"] == "schedule":
        sched = wizard_data.get("schedule", {})
        interval = sched.get("interval", "weekdays")

        if interval == "daily":
            parts.append("Every day")
        elif interval == "weekdays":
            parts.append("On weekdays")
        elif interval in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
            days = sched.get("days", [])
            if days and len(days) > 1:
                day_names = [d.capitalize() for d in days]
                parts.append(f"Every {', '.join(day_names[:-1])} and {day_names[-1]}")
            else:
                parts.append(f"Every {interval.capitalize()}")
        elif interval in ["custom_days", "custom_weeks"]:
            val = sched.get("cadence_value", 2)
            unit = sched.get("cadence_unit", "w")
            unit_word = "days" if unit == "d" else "weeks"
            parts.append(f"Every {val} {unit_word}")

        if sched.get("at"):
            parts[-1] += f" at {sched['at']}"
    else:
        # Event trigger
        event = wizard_data.get("event", {})
        entity = event.get("entity", "task")
        lifecycle = event.get("lifecycle", "completed")
        filter_info = event.get("filter", {})
        filter_type = filter_info.get("type", "any")

        parts.append(f"When a {entity} is {lifecycle}")
        if filter_type == "under_practice":
            parts[-1] += " under this Practice"
        elif filter_type == "tagged" and filter_info.get("tag"):
            parts[-1] += f" tagged [{filter_info['tag']}]"

    # Action part
    action_type = wizard_data.get("action_type", "create")
    task_name = wizard_data.get("task_name", "Untitled task")

    if action_type == "collate":
        parts.append(f"batch tasks into '{task_name}'")
    else:
        parts.append(f"create a task called '{task_name}'")

    # Due part
    due = wizard_data.get("task_due")
    if due:
        due_text = {
            "end_of_day": "due at end of day",
            "+1d": "due tomorrow",
            "+2d": "due in 2 days",
            "+3d": "due in 3 days",
            "+7d": "due in 1 week",
            "end_of_week": "due at end of week",
        }.get(due, "")
        if due_text:
            parts[-1] += f", {due_text}"

    return ", ".join(parts) + "."


@app.post("/priorities/{priority_id}/actions", response_class=HTMLResponse)
async def priority_actions_create(request: Request, priority_id: str):
    """Create a new action from wizard data."""
    from praxis_core.persistence import get_connection, PriorityGraph, validate_session
    from praxis_core.dsl import (
        PracticeConfig, PracticeAction, Trigger, Schedule, Cadence,
        CreateAction, CollateAction, TaskTemplate, CollateTarget,
        Event, EventType,
    )
    from praxis_web.helpers.action_renderer import render_actions_from_config, actions_to_yaml
    from datetime import datetime, date

    # Authenticate via session cookie
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return HTMLResponse(content="<div class='error'>Authentication required</div>", status_code=401)

    result = validate_session(session_token)
    if not result:
        return HTMLResponse(content="<div class='error'>Invalid session</div>", status_code=401)

    _, user = result

    # Parse form data
    form = await request.form()
    action_type = form.get("action_type", "create")
    trigger_type = form.get("trigger_type", "schedule")

    # Schedule fields
    schedule_interval = form.get("schedule_interval", "weekdays")
    schedule_days = form.get("schedule_days", "")
    schedule_cadence_value = int(form.get("schedule_cadence_value", 2))
    schedule_cadence_unit = form.get("schedule_cadence_unit", "w")
    schedule_cadence_anchor = form.get("schedule_cadence_anchor", "")
    schedule_at = form.get("schedule_at") if form.get("schedule_has_time") else None

    # Event fields
    event_entity = form.get("event_entity", "task")
    event_lifecycle = form.get("event_lifecycle", "completed")
    event_filter_type = form.get("event_filter_type", "any")
    event_filter_priority_id = form.get("event_filter_priority_id")
    event_filter_tag = form.get("event_filter_tag")

    # Task details
    task_name = form.get("task_name", "").strip() or "Untitled task"
    task_description = form.get("task_description", "").strip()
    task_due = form.get("task_due", "")
    task_tags = form.get("task_tags", "")

    # Collation fields
    collate_under_practice = form.get("collate_under_practice")
    collate_with_tag = form.get("collate_with_tag")
    collate_tag = form.get("collate_tag", "")

    graph = PriorityGraph(get_connection, entity_id=user.entity_id)
    graph.load()

    priority = graph.get(priority_id)
    if not priority:
        return HTMLResponse(content="<div class='error'>Priority not found</div>", status_code=404)

    if priority.entity_id != user.entity_id:
        return HTMLResponse(content="<div class='error'>Permission denied</div>", status_code=403)

    # Parse existing config or create new
    if priority.actions_config:
        try:
            config = PracticeConfig.from_json(priority.actions_config)
        except:
            config = PracticeConfig(name=priority.name)
    else:
        config = PracticeConfig(name=priority.name)

    # Build trigger
    trigger = None
    if trigger_type == "schedule":
        # Build schedule based on interval type
        if schedule_interval in ["custom_days", "custom_weeks"]:
            freq = f"{schedule_cadence_value}{'d' if schedule_cadence_unit == 'd' else 'w'}"
            schedule = Schedule(
                interval=Cadence(
                    frequency=freq,
                    beginning=schedule_cadence_anchor or date.today().isoformat(),
                )
            )
        elif schedule_interval in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
            # Check for multi-day
            days = [d.strip() for d in schedule_days.split(",") if d.strip()] if schedule_days else []
            if len(days) > 1:
                # Multi-day - use first day and note others (simplified for now)
                schedule = Schedule(interval="weekly", day=days[0])
            else:
                schedule = Schedule(interval="weekly", day=schedule_interval)
        else:
            schedule = Schedule(interval=schedule_interval)

        if schedule_at:
            schedule.at = schedule_at

        trigger = Trigger(schedule=schedule)
    else:
        # Event trigger - map entity+lifecycle to EventType
        if event_entity == "task" and event_lifecycle == "completed":
            event_type = EventType.TASK_COMPLETION
        elif event_entity == "task":
            event_type = EventType.TASK_STATUS_CHANGE
        elif event_lifecycle == "completed":
            event_type = EventType.PRIORITY_COMPLETION
        else:
            event_type = EventType.PRIORITY_STATUS_CHANGE

        # Build params for filtering
        params = {}
        if event_filter_type == "under_practice":
            params["under"] = "practice"
        elif event_filter_type == "under_priority" and event_filter_priority_id:
            params["under"] = event_filter_priority_id
        elif event_filter_type == "tagged" and event_filter_tag:
            params["tagged"] = event_filter_tag

        # For goals, add entity type filter
        if event_entity == "goal":
            params["entity_type"] = "goal"

        event = Event(event_type=event_type, params=params)
        trigger = Trigger(event=event)

    # Build action
    if action_type == "collate":
        # Build collate target
        target_parts = []
        if collate_under_practice:
            target_parts.append("children")
        if collate_with_tag and collate_tag:
            target_parts.append(f"tagged:{collate_tag}")

        collate = CollateAction(
            target=CollateTarget(shorthand=target_parts[0] if target_parts else "children"),
            as_template=TaskTemplate(
                name=task_name,
                description=task_description if task_description else None,
                due=task_due if task_due else None,
            )
        )
        action = PracticeAction(trigger=trigger, collate=collate)
    else:
        # Create task action
        tags = [t.strip() for t in task_tags.split(",") if t.strip()]
        create = CreateAction(items=[
            TaskTemplate(
                name=task_name,
                description=task_description if task_description else None,
                due=task_due if task_due else None,
                tags=tags,
            )
        ])
        action = PracticeAction(trigger=trigger, create=create)

    # Add to config and save
    config.actions.append(action)
    priority.actions_config = config.to_json()
    priority.updated_at = datetime.now()

    graph.save_priority(priority)

    # Clear the API's graph cache so it reloads from DB
    # Must call the API endpoint since API runs in a separate process
    async with api_client(request) as client:
        await client.post("/api/cache/invalidate", params={"entity_id": user.entity_id})

    # Return updated editor
    actions = render_actions_from_config(priority.actions_config)
    actions_yaml = actions_to_yaml(priority.actions_config)

    return templates.TemplateResponse(
        request,
        "partials/actions/actions_editor.html",
        {
            "priority": {"id": priority_id, "actions_config": priority.actions_config},
            "actions": actions,
            "actions_yaml": actions_yaml,
            "editable": True,
        }
    )


@app.delete("/priorities/{priority_id}/actions/{action_idx}")
async def priority_actions_delete(request: Request, priority_id: str, action_idx: int):
    """Delete an action by index."""
    from praxis_core.persistence import get_connection, PriorityGraph, validate_session
    from praxis_core.dsl import PracticeConfig
    from datetime import datetime

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return {"success": False, "error": "Authentication required"}
    result = validate_session(session_token)
    if not result:
        return {"success": False, "error": "Invalid session"}
    _, user = result

    graph = PriorityGraph(get_connection, entity_id=user.entity_id)
    graph.load()

    priority = graph.get(priority_id)
    if not priority:
        return {"success": False, "error": "Priority not found"}

    if priority.entity_id != user.entity_id:
        return {"success": False, "error": "Permission denied"}

    if not priority.actions_config:
        return {"success": False, "error": "No actions to delete"}

    try:
        config = PracticeConfig.from_json(priority.actions_config)
        if 0 <= action_idx < len(config.actions):
            config.actions.pop(action_idx)
            priority.actions_config = config.to_json() if config.actions else None
            priority.updated_at = datetime.now()
            graph.save_priority(priority)

            # Clear the API's graph cache so it reloads from DB
            async with api_client(request) as client:
                await client.post("/api/cache/invalidate", params={"entity_id": user.entity_id})

            return {"success": True}
        else:
            return {"success": False, "error": "Invalid action index"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/priorities/{priority_id}/actions/yaml", response_class=HTMLResponse)
async def priority_actions_yaml_get(request: Request, priority_id: str):
    """Get actions as YAML editor HTML."""
    from praxis_core.persistence import get_connection, PriorityGraph, validate_session
    from praxis_web.helpers.action_renderer import actions_to_yaml

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return HTMLResponse("<p class='error'>Authentication required</p>")
    result = validate_session(session_token)
    if not result:
        return HTMLResponse("<p class='error'>Invalid session</p>")
    _, user = result

    graph = PriorityGraph(get_connection, entity_id=user.entity_id)
    graph.load()

    priority = graph.get(priority_id)
    if not priority:
        return HTMLResponse("<p class='error'>Priority not found</p>")

    yaml_content = actions_to_yaml(priority.actions_config)

    # Return HTML with textarea for editing
    # Note: The "edit as code" / "edit as plain english" toggle is managed by priority_edit.html
    html = f'''
    <div class="actions-editor-yaml" id="actions-editor-{priority_id}">
        <form hx-post="/priorities/{priority_id}/actions/yaml"
              hx-target="#actions-editor-container"
              hx-swap="innerHTML"
              hx-on::afterRequest="if(event.detail.successful) {{ actionsYamlMode = false; document.getElementById('actions-mode-toggle').textContent = 'edit as code'; }}">
            <textarea name="yaml" rows="12" class="property-input yaml-input">{yaml_content}</textarea>
            <div class="yaml-actions">
                <button type="submit" class="btn btn-sm btn-primary">Save</button>
                <span id="yaml-status-{priority_id}" class="yaml-status"></span>
            </div>
        </form>
    </div>
    '''
    return HTMLResponse(html)


@app.post("/priorities/{priority_id}/actions/yaml", response_class=HTMLResponse)
async def priority_actions_yaml_save(
    request: Request,
    priority_id: str,
    yaml_content: str = Form(..., alias="yaml"),
):
    """Save actions from YAML text."""
    from praxis_core.persistence import get_connection, PriorityGraph, validate_session
    from praxis_web.helpers.action_renderer import yaml_to_actions_config, actions_to_yaml
    from datetime import datetime

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return HTMLResponse("<p class='error'>Authentication required</p>")
    result = validate_session(session_token)
    if not result:
        return HTMLResponse("<p class='error'>Invalid session</p>")
    _, user = result

    graph = PriorityGraph(get_connection, entity_id=user.entity_id)
    graph.load()

    priority = graph.get(priority_id)
    if not priority:
        return HTMLResponse("<p class='error'>Priority not found</p>")

    if priority.entity_id != user.entity_id:
        return HTMLResponse("<p class='error'>Permission denied</p>")

    try:
        actions_config = yaml_to_actions_config(yaml_content, priority.name)
        priority.actions_config = actions_config
        priority.updated_at = datetime.now()
        graph.save_priority(priority)

        # Clear the API's graph cache so it reloads from DB
        from praxis_core.api.app import clear_graph_cache
        clear_graph_cache(user.entity_id)

        # Return visual editor on success (switches back from YAML mode)
        from praxis_web.helpers.action_renderer import render_actions_from_config
        actions = render_actions_from_config(priority.actions_config)

        return templates.TemplateResponse(
            request,
            "partials/actions/actions_editor.html",
            {
                "priority": {"id": priority_id, "actions_config": priority.actions_config},
                "actions": actions,
                "editable": True,
            }
        )
    except ValueError as e:
        # Return error with the original YAML so user can fix it
        html = f'''
        <div class="actions-editor-yaml" id="actions-editor-{priority_id}">
            <p class="error-msg">Error: {str(e)}</p>
            <form hx-post="/priorities/{priority_id}/actions/yaml"
                  hx-target="#actions-editor-container"
                  hx-swap="innerHTML">
                <textarea name="yaml" rows="12" class="property-input yaml-input">{yaml_content}</textarea>
                <div class="yaml-actions">
                    <button type="submit" class="btn btn-sm btn-primary">Save</button>
                </div>
            </form>
        </div>
        '''
        return HTMLResponse(html)


@app.post("/priorities/{priority_id}/actions/validate")
async def priority_actions_yaml_validate(
    request: Request,
    priority_id: str,
    yaml: str = Form(...),
):
    """Validate YAML without saving."""
    from praxis_web.helpers.action_renderer import yaml_to_actions_config
    from praxis_core.dsl import PracticeConfig

    try:
        actions_config = yaml_to_actions_config(yaml, "test")
        config = PracticeConfig.from_json(actions_config)
        return {"valid": True, "action_count": len(config.actions)}
    except ValueError as e:
        return {"valid": False, "error": str(e)}


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

    # Build options HTML with type prefix for scannability
    options = ['<option value="">Inbox (no priority)</option>']
    for p in data["priorities"]:
        type_prefix = p["priority_type"][:3].upper()
        options.append(f'<option value="{p["id"]}">[{type_prefix}] {p["name"]}</option>')

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


# Rule templates for the wizard
RULE_TEMPLATES = [
    {
        "id": "morning_boost",
        "name": "Morning Boost",
        "icon": "🌅",
        "description": "Increase aptness for tasks during morning hours when focus is high.",
        "conditions": [{"type": "time_window", "params": {"start": "06:00", "end": "12:00"}}],
        "effects": [{"target": "aptness", "operator": "multiply", "value": 1.5}],
    },
    {
        "id": "evening_wind_down",
        "name": "Evening Wind-down",
        "icon": "🌙",
        "description": "Reduce aptness in the evening to favor lighter tasks.",
        "conditions": [{"type": "time_window", "params": {"start": "20:00", "end": "23:59"}}],
        "effects": [{"target": "aptness", "operator": "multiply", "value": 0.5}],
    },
    {
        "id": "weekend_rest",
        "name": "Weekend Rest",
        "icon": "🛋️",
        "description": "Lower task urgency on weekends to encourage rest.",
        "conditions": [{"type": "day_of_week", "params": {"days": ["saturday", "sunday"]}}],
        "effects": [{"target": "aptness", "operator": "multiply", "value": 0.3}],
    },
    {
        "id": "deadline_crunch",
        "name": "Deadline Crunch",
        "icon": "⏰",
        "description": "Boost urgency when a task's due date is approaching.",
        "conditions": [{"type": "due_date_proximity", "params": {"due_type": "within_hours", "hours": 24}}],
        "effects": [{"target": "urgency", "operator": "add", "value": 5}],
    },
    {
        "id": "overdue_penalty",
        "name": "Overdue Penalty",
        "icon": "🚨",
        "description": "Significantly boost urgency for overdue tasks.",
        "conditions": [{"type": "due_date_proximity", "params": {"due_type": "overdue"}}],
        "effects": [{"target": "urgency", "operator": "set", "value": 10}],
    },
    {
        "id": "stale_nudge",
        "name": "Stale Task Nudge",
        "icon": "🧹",
        "description": "Increase urgency for tasks untouched for several days.",
        "conditions": [{"type": "staleness", "params": {"days": 7}}],
        "effects": [{"target": "urgency", "operator": "add", "value": 3}],
    },
    {
        "id": "deep_work",
        "name": "Deep Work Focus",
        "icon": "🎯",
        "description": "Boost aptness for tasks tagged with 'deep-work'.",
        "conditions": [{"type": "tag_match", "params": {"tag": "deep-work"}}],
        "effects": [{"target": "aptness", "operator": "multiply", "value": 2.0}],
    },
    {
        "id": "custom",
        "name": "Custom Rule",
        "icon": "✨",
        "description": "Start from scratch with a blank rule.",
        "conditions": [],
        "effects": [],
    },
]


# Specific routes MUST come before /{rule_id} catch-all
@app.get("/rules/new", response_class=HTMLResponse)
async def new_rule_wizard(request: Request):
    """Show rule template wizard."""
    return templates.TemplateResponse(
        request,
        "partials/rule_new_wizard.html",
        {"templates": RULE_TEMPLATES}
    )


@app.post("/rules/new/from-template", response_class=HTMLResponse)
async def new_rule_from_template(request: Request):
    """Create a new rule from a template and open the editor."""
    form_data = await request.form()
    template_id = form_data.get("template_id", "custom")

    # Find the template
    template = next((t for t in RULE_TEMPLATES if t["id"] == template_id), RULE_TEMPLATES[-1])

    # Create the rule via API
    async with api_client(request) as client:
        response = await client.post("/api/rules", json={
            "name": template["name"] if template_id != "custom" else "New Rule",
            "description": template["description"] if template_id != "custom" else "",
            "conditions": template["conditions"],
            "effects": template["effects"],
        })

        if response.status_code != 200:
            return HTMLResponse("<div class='error'>Failed to create rule</div>", status_code=400)

        data = response.json()
        rule = data.get("rule")

        # Get YAML representation for the editor
        yaml_response = await client.get(f"/api/rules/export/{rule['id']}")
        rule_yaml = yaml_response.text if yaml_response.status_code == 200 else ""

    # Return the edit form for the new rule
    html_response = templates.TemplateResponse(
        request,
        "partials/rule_edit.html",
        {"rule": rule, "rule_yaml": rule_yaml}
    )
    html_response.headers["HX-Trigger"] = "ruleCreated"
    return html_response


@app.get("/rules/export")
async def export_rules_web(request: Request):
    """Export all rules as YAML file."""
    async with api_client(request) as client:
        response = await client.get("/api/rules/export")
        if response.status_code != 200:
            return HTMLResponse("<div class='error'>Failed to export rules</div>")

        return Response(
            content=response.content,
            media_type="text/yaml",
            headers={"Content-Disposition": "attachment; filename=praxis-rules.yml"}
        )


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


@app.post("/rules/import/preview")
async def import_preview_web(request: Request):
    """Preview rules from YAML content."""
    body = await request.body()
    async with api_client(request) as client:
        response = await client.post(
            "/api/rules/import/preview",
            content=body.decode('utf-8'),
            headers={"Content-Type": "text/plain"}
        )
        return Response(
            content=response.content,
            media_type="application/json",
            status_code=response.status_code
        )


@app.post("/rules/import")
async def import_rules_web(request: Request):
    """Import selected rules from YAML."""
    data = await request.json()
    async with api_client(request) as client:
        response = await client.post("/api/rules/import", json=data)
        return Response(
            content=response.content,
            media_type="application/json",
            status_code=response.status_code
        )


# Catch-all routes MUST come after specific routes
@app.get("/rules/{rule_id}", response_class=HTMLResponse)
async def rule_detail(request: Request, rule_id: str):
    """Rule detail - full page or HTMX partial."""
    async with api_client(request) as client:
        response = await client.get(f"/api/rules/{rule_id}")
        if response.status_code != 200:
            return HTMLResponse("<div class='error'>Rule not found</div>", status_code=404)
        data = response.json()
        rule = data.get("rule")

    # HTMX request - return partial
    if is_htmx_request(request):
        return templates.TemplateResponse(
            request,
            "partials/rule_view.html",
            {"rule": rule}
        )

    # Full page request - render with rule detail pre-loaded
    detail_html = templates.get_template("partials/rule_view.html").render(
        request=request, rule=rule
    )

    # Get rules list for left pane
    async with api_client(request) as client:
        list_response = await client.get("/api/rules")
        list_data = list_response.json() if list_response.status_code == 200 else {}
        rules = list_data.get("rules", [])

    list_html = templates.get_template("partials/rules_list.html").render(rules=rules)

    return await render_full_page(
        request,
        mode="rules",
        initial_list_html=list_html,
        initial_detail_html=detail_html
    )


@app.get("/rules/{rule_id}/edit", response_class=HTMLResponse)
async def rule_edit(request: Request, rule_id: str):
    """HTMX partial: rule edit mode with block editor."""
    async with api_client(request) as client:
        response = await client.get(f"/api/rules/{rule_id}")
        if response.status_code != 200:
            return HTMLResponse("<div class='error'>Rule not found</div>", status_code=404)
        data = response.json()
        rule = data.get("rule")

        # Get YAML representation for toggle view
        yaml_response = await client.get(f"/api/rules/export/{rule_id}")
        rule_yaml = yaml_response.text if yaml_response.status_code == 200 else ""

    return templates.TemplateResponse(
        request,
        "partials/rule_edit.html",
        {"rule": rule, "rule_yaml": rule_yaml}
    )


@app.post("/rules/{rule_id}", response_class=HTMLResponse)
async def rule_save(request: Request, rule_id: str):
    """Save rule edits and return view mode."""
    form_data = await request.form()

    # Check if we're in YAML mode
    yaml_content = form_data.get("yaml_content")

    if yaml_content:
        # YAML mode: parse and update via API
        async with api_client(request) as client:
            response = await client.put(
                f"/api/rules/{rule_id}/yaml",
                content=yaml_content,
                headers={"Content-Type": "text/plain"}
            )
            if response.status_code != 200:
                error = response.json().get("error", "Failed to save rule")
                return HTMLResponse(f"<div class='error'>{error}</div>", status_code=400)
            data = response.json()
            rule = data.get("rule")
    else:
        # Block mode: build rule data from form
        rule_data = {
            "name": form_data.get("name", ""),
            "description": form_data.get("description", ""),
            "priority": int(form_data.get("priority", 0)),
            "conditions": [],
            "effects": [],
        }

        # Parse conditions from form (conditions[0][type], conditions[0][start], etc.)
        condition_indices = set()
        for key in form_data.keys():
            if key.startswith("conditions["):
                idx = key.split("[")[1].split("]")[0]
                condition_indices.add(int(idx))

        for idx in sorted(condition_indices):
            cond_type = form_data.get(f"conditions[{idx}][type]")
            if not cond_type:
                continue

            condition = {"type": cond_type, "params": {}}

            if cond_type == "time_window":
                condition["params"]["start"] = form_data.get(f"conditions[{idx}][start]", "08:00")
                condition["params"]["end"] = form_data.get(f"conditions[{idx}][end]", "17:00")
            elif cond_type == "day_of_week":
                days = form_data.getlist(f"conditions[{idx}][days][]")
                condition["params"]["days"] = days
            elif cond_type in ("tag_match", "tag_missing"):
                condition["params"]["tag"] = form_data.get(f"conditions[{idx}][tag]", "")
            elif cond_type == "due_date_proximity":
                condition["params"]["due_type"] = form_data.get(f"conditions[{idx}][due_type]", "has_due_date")
                hours = form_data.get(f"conditions[{idx}][hours]")
                if hours:
                    condition["params"]["hours"] = int(hours)
            elif cond_type == "staleness":
                days = form_data.get(f"conditions[{idx}][days]")
                if days:
                    condition["params"]["days"] = int(days)

            rule_data["conditions"].append(condition)

        # Parse effects from form
        effect_indices = set()
        for key in form_data.keys():
            if key.startswith("effects["):
                idx = key.split("[")[1].split("]")[0]
                effect_indices.add(int(idx))

        for idx in sorted(effect_indices):
            target = form_data.get(f"effects[{idx}][target]")
            operator = form_data.get(f"effects[{idx}][operator]")
            value = form_data.get(f"effects[{idx}][value]", "")

            if target and operator:
                rule_data["effects"].append({
                    "target": target,
                    "operator": operator,
                    "value": value,
                })

        async with api_client(request) as client:
            response = await client.put(f"/api/rules/{rule_id}", json=rule_data)
            if response.status_code != 200:
                error = response.json().get("error", "Failed to save rule")
                return HTMLResponse(f"<div class='error'>{error}</div>", status_code=400)
            data = response.json()
            rule = data.get("rule")

    # Return view mode with trigger to refresh list
    html_response = templates.TemplateResponse(
        request,
        "partials/rule_view.html",
        {"rule": rule}
    )
    html_response.headers["HX-Trigger"] = "ruleUpdated"
    return html_response


@app.post("/rules/{rule_id}/toggle", response_class=HTMLResponse)
async def toggle_rule_web(request: Request, rule_id: str):
    """Toggle a rule's enabled state."""
    async with api_client(request) as client:
        response = await client.post(f"/api/rules/{rule_id}/toggle")
        if response.status_code != 200:
            return HTMLResponse("<div class='error'>Failed to toggle rule</div>")
    return HTMLResponse("")


@app.delete("/rules/{rule_id}", response_class=HTMLResponse)
async def delete_rule_web(request: Request, rule_id: str):
    """Delete a rule."""
    async with api_client(request) as client:
        response = await client.delete(f"/api/rules/{rule_id}")
        if response.status_code != 200:
            return HTMLResponse("<div class='error'>Failed to delete rule</div>")
    return HTMLResponse("")


# -----------------------------------------------------------------------------
# Trigger Routes (proxy to API)
# -----------------------------------------------------------------------------

@app.post("/api/practices/check-triggers")
async def check_triggers_proxy(request: Request):
    """Proxy trigger check to API backend."""
    async with api_client(request) as client:
        response = await client.post("/api/practices/check-triggers")
        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type="application/json",
        )