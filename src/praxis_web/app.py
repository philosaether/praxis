"""
Praxis Web UI server.

Run with: uvicorn praxis_web.app:app --port 8080
Requires: PRAXIS_API_URL environment variable (default: http://localhost:8000)
"""

import os
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
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

# Static files and templates
STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# -----------------------------------------------------------------------------
# API Client Helper
# -----------------------------------------------------------------------------

def api_client():
    return httpx.AsyncClient(base_url=API_URL, timeout=30.0)

# -----------------------------------------------------------------------------
# Routes: Pages
# -----------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    """Full page: two-pane layout with tasks as default view."""
    async with api_client() as client:
        # Fetch both tasks and priorities for initial load
        tasks_response = await client.get("/api/tasks")
        priorities_response = await client.get("/api/priorities")
        tasks_data = tasks_response.json()
        priorities_data = priorities_response.json()

    return templates.TemplateResponse(
        request,
        "home.html",
        {
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
    async with api_client() as client:
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


@app.post("/priorities/new", response_class=HTMLResponse)
async def create_new_priority(request: Request):
    """Create a new priority and return the row HTML."""
    form_data = await request.form()

    async with api_client() as client:
        response = await client.post("/api/priorities", data=dict(form_data))
        data = response.json()

    priority = data["priority"]
    html_response = templates.TemplateResponse(
        request,
        "partials/priority_row_single.html",
        {"priority": priority}
    )
    html_response.headers["X-New-Item-Id"] = priority["id"]
    return html_response


@app.get("/priorities/tree", response_class=HTMLResponse)
async def priority_tree(request: Request):
    """HTMX partial: tree view of priority hierarchy."""
    async with api_client() as client:
        response = await client.get("/api/priorities/tree")
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/priority_tree.html",
        {"roots": data["roots"], "children_map": data["children_map"]}
    )

# -----------------------------------------------------------------------------
# Routes: HTMX Partials - Priority Detail
# -----------------------------------------------------------------------------

@app.get("/priorities/{priority_id}", response_class=HTMLResponse)
async def priority_detail(request: Request, priority_id: str):
    """HTMX partial: detail view for a single priority."""
    async with api_client() as client:
        response = await client.get(f"/api/priorities/{priority_id}")
        if response.status_code == 404:
            return HTMLResponse(
                content="<div class='error'>Priority not found</div>",
                status_code=404
            )
        data = response.json()

    # Also fetch edit data to get raw notes and all_priorities
    async with api_client() as client:
        edit_response = await client.get(f"/api/priorities/{priority_id}/edit")
        if edit_response.status_code == 200:
            edit_data = edit_response.json()
            data["priority"]["notes_raw"] = edit_data["priority"].get("notes", "")
            data["all_priorities"] = edit_data.get("all_priorities", [])
            data["priority_statuses"] = edit_data.get("priority_statuses", [])

    return templates.TemplateResponse(
        request,
        "partials/item_detail.html",
        data
    )


@app.post("/priorities/{priority_id}/properties", response_class=HTMLResponse)
async def priority_save_properties(request: Request, priority_id: str):
    """Save priority properties and return updated properties section."""
    form_data = await request.form()

    async with api_client() as client:
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

    # Determine which properties template to use based on priority type
    priority_type = data["priority"]["priority_type"]
    template_name = f"partials/properties/{priority_type}_properties.html"

    return templates.TemplateResponse(
        request,
        template_name,
        data
    )


@app.post("/priorities/{priority_id}/notes", response_class=HTMLResponse)
async def priority_save_notes(request: Request, priority_id: str):
    """Save priority notes and return updated notes section."""
    form_data = await request.form()

    async with api_client() as client:
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
    async with api_client() as client:
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


@app.post("/tasks/new", response_class=HTMLResponse)
async def create_new_task(request: Request):
    """Create a new task and return the row HTML."""
    async with api_client() as client:
        response = await client.post("/api/tasks")
        data = response.json()

    task = data["task"]
    html_response = templates.TemplateResponse(
        request,
        "partials/task_row_single.html",
        {"task": task}
    )
    html_response.headers["X-New-Item-Id"] = str(task["id"])
    return html_response

@app.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: int):
    """HTMX partial: detail view for a single task."""
    async with api_client() as client:
        response = await client.get(f"/api/tasks/{task_id}")
        if response.status_code == 404:
            return HTMLResponse(
                content="<div class='error'>Task not found</div>",
                status_code=404
            )
        data = response.json()

    # Add notes_raw for the edit form
    task = data["task"]
    notes = task.get("notes") or ""
    task["notes_raw"] = notes if not notes.startswith("<") else ""
    # For proper raw notes, we need to fetch from edit endpoint
    async with api_client() as client:
        edit_response = await client.get(f"/api/tasks/{task_id}/edit")
        if edit_response.status_code == 200:
            edit_data = edit_response.json()
            task["notes_raw"] = edit_data["task"].get("notes", "")

    return templates.TemplateResponse(
        request,
        "partials/item_detail.html",
        data
    )


@app.post("/tasks/{task_id}/properties", response_class=HTMLResponse)
async def task_save_properties(request: Request, task_id: int):
    """Save task properties and return updated properties section."""
    form_data = await request.form()

    async with api_client() as client:
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

    return templates.TemplateResponse(
        request,
        "partials/properties/task_properties.html",
        data
    )


@app.post("/tasks/{task_id}/notes", response_class=HTMLResponse)
async def task_save_notes(request: Request, task_id: int):
    """Save task notes and return updated notes section."""
    form_data = await request.form()

    async with api_client() as client:
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
async def task_toggle_done(request: Request, task_id: int):
    """Toggle task between done and queued."""
    async with api_client() as client:
        response = await client.post(f"/api/tasks/{task_id}/toggle")
        if response.status_code == 404:
            return HTMLResponse(content="", status_code=404)
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/task_row_single.html",
        {"task": data["task"]}
    )