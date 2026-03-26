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

@app.get("/", response_class=RedirectResponse)
async def root():
    return RedirectResponse(url="/priorities", status_code=302)


@app.get("/priorities", response_class=HTMLResponse)
async def priorities_page(request: Request):
    """Full page: two-pane layout with list on left."""
    async with api_client() as client:
        response = await client.get("/api/priorities")
        data = response.json()

    return templates.TemplateResponse(
        request,
        "priority_list.html",
        {
            "priorities": data["priorities"],
            "priority_types": data["priority_types"],
            "selected_type": None,
            "active_only": False,
        }
    )

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

    return templates.TemplateResponse(
        request,
        "partials/priority_detail.html",
        data
    )

@app.get("/priorities/{priority_id}/edit", response_class=HTMLResponse)
async def priority_edit_form(request: Request, priority_id: str):
    """HTMX partial: edit form for a priority."""
    async with api_client() as client:
        response = await client.get(f"/api/priorities/{priority_id}/edit")
        if response.status_code == 404:
            return HTMLResponse(
                content="<div class='error'>Priority not found</div>",
                status_code=404
            )
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/priority_edit.html",
        data
    )

@app.post("/priorities/{priority_id}", response_class=HTMLResponse)
async def priority_save(
    request: Request,
    priority_id: str,
):
    """Save edits to a priority and return updated detail view."""
    form_data = await request.form()

    async with api_client() as client:
        response = await client.post(
            f"/api/priorities/{priority_id}",
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
        "partials/priority_detail.html",
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

    return templates.TemplateResponse(
        request,
        "partials/task_detail.html",
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