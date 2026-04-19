"""
Priority detail/edit routes: viewing, editing, and saving individual priorities.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from praxis_web.rendering import (
    templates,
    api_client,
    is_htmx_request,
    render_full_page,
    SESSION_COOKIE_NAME,
)

router = APIRouter()


def _build_priority_tree(graph) -> list[dict]:
    """Build a nested priority tree for the priority picker chip."""
    roots = graph.roots()

    def build_node(priority):
        child_ids = graph.children.get(priority.id, set())
        children = []
        for cid in sorted(child_ids):
            child = graph.nodes.get(cid)
            if child:
                children.append(build_node(child))
        return {"name": priority.name, "children": children}

    return [build_node(r) for r in sorted(roots, key=lambda p: p.name)]


# -----------------------------------------------------------------------------
# Priority Detail View
# -----------------------------------------------------------------------------

@router.get("/priorities/{priority_id}", response_class=HTMLResponse)
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


# -----------------------------------------------------------------------------
# Priority Edit
# -----------------------------------------------------------------------------

@router.get("/priorities/{priority_id}/edit", response_class=HTMLResponse)
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

    # For Practice priorities, render action cards for the editor
    if data["priority"].get("priority_type") == "practice":
        from praxis_web.helpers.action_renderer import actions_to_card_data
        from praxis_core.persistence import get_connection, PriorityGraph, validate_session
        actions_config = data["priority"].get("actions_config")
        data["action_cards"] = actions_to_card_data(actions_config) if actions_config else []
        data["priority_name"] = data["priority"].get("name", "")
        data["editable"] = True
        # Build priority tree for the ancestor picker chip
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        if session_token:
            result = validate_session(session_token)
            if result:
                _, user = result
                graph = PriorityGraph(get_connection, entity_id=user.entity_id)
                graph.load()
                data["priority_tree"] = _build_priority_tree(graph)

    return templates.TemplateResponse(
        request,
        "partials/priority_edit.html",
        data
    )


# -----------------------------------------------------------------------------
# Tasks Panel
# -----------------------------------------------------------------------------

@router.get("/priorities/{priority_id}/tasks-panel", response_class=HTMLResponse)
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


# -----------------------------------------------------------------------------
# Change Type
# -----------------------------------------------------------------------------

@router.post("/priorities/{priority_id}/change-type", response_class=HTMLResponse)
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


# -----------------------------------------------------------------------------
# Save Properties
# -----------------------------------------------------------------------------

@router.post("/priorities/{priority_id}/properties", response_class=HTMLResponse)
async def priority_save_properties(request: Request, priority_id: str):
    """Save priority properties and return view mode + OOB row update."""
    form_data = await request.form()
    data = dict(form_data)

    # Assemble actions_config JSON from chip form fields (action_N_field).
    # This replaces the old client-side serializeActionCards() approach.
    # Always send actions_config so deletions persist (empty string clears).
    from praxis_web.helpers.action_renderer import assemble_actions_config
    actions_config = assemble_actions_config(data, data.get("name", ""))
    # Send valid empty JSON when no actions (empty string gets swallowed by FastAPI)
    data["actions_config"] = actions_config or '{"practice": {"name": "", "actions": []}}'

    async with api_client(request) as client:
        response = await client.post(
            f"/api/priorities/{priority_id}/properties",
            data=data
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


# -----------------------------------------------------------------------------
# Save Notes
# -----------------------------------------------------------------------------

@router.post("/priorities/{priority_id}/notes", response_class=HTMLResponse)
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
