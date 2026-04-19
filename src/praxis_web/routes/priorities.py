"""
Priority list/create routes: browsing, filtering, and creating priorities.
"""

import json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from praxis_web.rendering import templates, api_client

router = APIRouter()


# -----------------------------------------------------------------------------
# Priority List
# -----------------------------------------------------------------------------

@router.get("/priorities/list", response_class=HTMLResponse)
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


# -----------------------------------------------------------------------------
# New Priority Form
# -----------------------------------------------------------------------------

@router.get("/priorities/new", response_class=HTMLResponse)
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


@router.get("/priorities/new/fields", response_class=HTMLResponse)
async def priority_type_fields(request: Request, priority_type: str = "initiative"):
    """Return type-specific fields for the selected priority type."""
    template_name = f"partials/type_fields/{priority_type}_fields.html"
    return templates.TemplateResponse(request, template_name, {})


# -----------------------------------------------------------------------------
# Create Priority
# -----------------------------------------------------------------------------

@router.post("/priorities/create", response_class=HTMLResponse)
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


# -----------------------------------------------------------------------------
# Quick Add
# -----------------------------------------------------------------------------

@router.post("/priorities/quick-add", response_class=HTMLResponse)
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


@router.get("/priorities/quick-add/fields", response_class=HTMLResponse)
async def quick_add_priority_fields(request: Request, priority_type: str = "initiative"):
    """Return type-specific fields for quick-add modal."""
    template_name = f"partials/type_fields/{priority_type}_fields.html"
    return templates.TemplateResponse(request, template_name, {})


# -----------------------------------------------------------------------------
# Parent Options
# -----------------------------------------------------------------------------

@router.get("/priorities/parent-options", response_class=HTMLResponse)
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
