"""
Priority list/create routes: browsing, filtering, and creating priorities.

Direct persistence — no httpx proxy.
"""

import json
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from praxis_core.model import PriorityType, PriorityStatus, Value, Goal, Practice, Initiative, Org
from praxis_core.serialization import get_graph, clear_graph_cache, serialize_priority, serialize_task
from praxis_core.persistence import validate_session, list_tasks
from praxis_core.practices import on_priority_created
from praxis_web.rendering import SESSION_COOKIE_NAME, templates

router = APIRouter()

# Shared cache for entity name resolution within a request
_entity_name_cache: dict = {}


def _get_user(request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    result = validate_session(token)
    if result is None:
        return None
    session, user = result
    return user


def _ser(p, render_markdown=False, current_entity_id=None, shares=None, share_counts=None, include_action_cards=False):
    return serialize_priority(
        p,
        render_markdown=render_markdown,
        current_entity_id=current_entity_id,
        shares=shares,
        share_counts=share_counts,
        include_action_cards=include_action_cards,
        entity_name_cache=_entity_name_cache,
    )


def _generate_priority_id():
    from ulid import ULID
    return str(ULID())


def _create_priority_by_type(priority_type: str, id: str, name: str, entity_id: str | None = None):
    now = datetime.now()
    constructors = {
        "value": Value, "goal": Goal, "practice": Practice,
        "initiative": Initiative, "org": Org,
    }
    cls = constructors.get(priority_type, Initiative)
    return cls(id=id, name=name, entity_id=entity_id, created_at=now, updated_at=now)


def _auto_share_with_group(priority_id: str, entity_id: str, graph, owner_user_id: int):
    from praxis_core.persistence.database import get_connection
    with get_connection() as conn:
        entity = conn.execute("SELECT type FROM entities WHERE id = ?", (entity_id,)).fetchone()
        if not entity or entity["type"] != "group":
            return
        members = conn.execute(
            """SELECT em.user_id, u.entity_id as user_entity_id
               FROM entity_members em
               JOIN users u ON em.user_id = u.id
               WHERE em.entity_id = ?""",
            (entity_id,)
        ).fetchall()
        for member in members:
            if member["user_id"] != owner_user_id:
                graph.share_with_user(priority_id, member["user_id"], "contributor", allow_adoption=False)
            if member["user_entity_id"]:
                clear_graph_cache(member["user_entity_id"])


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
    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = get_graph(entity_id=entity_id)

    if type:
        try:
            priority_type = PriorityType(type)
            priorities = graph.by_type(priority_type)
        except ValueError:
            priorities = list(graph.nodes.values())
    else:
        priorities = list(graph.nodes.values())

    if active:
        priorities = [p for p in priorities if p.status == PriorityStatus.ACTIVE]

    priorities = sorted(priorities, key=lambda p: (p.priority_type.value, p.name))

    return templates.TemplateResponse(
        request,
        "partials/priority_rows.html",
        {"priorities": [_ser(p, current_entity_id=entity_id) for p in priorities]}
    )


# -----------------------------------------------------------------------------
# New Priority Form
# -----------------------------------------------------------------------------

@router.get("/priorities/new", response_class=HTMLResponse)
async def new_priority_form(request: Request):
    """Show empty form for creating a new priority."""
    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = get_graph(entity_id=entity_id)

    priorities = sorted(graph.nodes.values(), key=lambda p: (p.priority_type.value, p.name))

    return templates.TemplateResponse(
        request,
        "partials/priority_new_form.html",
        {
            "all_priorities": [_ser(p, current_entity_id=entity_id) for p in priorities],
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
    if parent_id and not parent_id.strip():
        parent_id = None

    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = get_graph(entity_id=entity_id)

    # Extract form fields
    priority_type = form_data.get("priority_type", "initiative")
    name = form_data.get("name", "").strip()
    status = form_data.get("status", "active")
    agent_context = form_data.get("agent_context")
    notes = form_data.get("notes")
    assigned_to_entity_id = form_data.get("assigned_to_entity_id")
    complete_when = form_data.get("complete_when")
    progress = form_data.get("progress")
    due_date = form_data.get("due_date")

    if not name:
        return HTMLResponse(
            content="<div class='error'>Name is required</div>",
            status_code=400
        )

    priority_id = _generate_priority_id()
    priority = _create_priority_by_type(priority_type, priority_id, name, entity_id)

    # Set common fields
    priority.status = PriorityStatus(status)
    priority.agent_context = agent_context.strip() if agent_context else None
    priority.description = notes.strip() if notes else None
    priority.assigned_to_entity_id = assigned_to_entity_id.strip() if assigned_to_entity_id else None

    # Set type-specific fields
    if isinstance(priority, Goal):
        priority.complete_when = complete_when.strip() if complete_when else None
        priority.progress = progress.strip() if progress else None
        if due_date:
            try:
                priority.due_date = datetime.fromisoformat(due_date)
            except ValueError:
                priority.due_date = None

    graph.add(priority)

    # Auto-share with group members if assigned to a group
    if priority.assigned_to_entity_id and user:
        _auto_share_with_group(priority.id, priority.assigned_to_entity_id, graph, user.id)

    # Handle parent link
    if parent_id and parent_id.strip():
        try:
            graph.link(priority.id, parent_id.strip())
        except ValueError:
            pass

    # Fire creation event
    if entity_id:
        on_priority_created(
            priority_id=priority.id,
            entity_id=entity_id,
            priority_data={
                "id": priority.id,
                "name": priority.name,
                "priority_type": priority.priority_type.value,
            },
            created_by=user.id if user else None,
        )

    # Build response data
    parent_ids = graph.parents.get(priority.id, set())
    child_ids = graph.children.get(priority.id, set())
    all_priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    data = {
        "priority": _ser(priority, render_markdown=True, current_entity_id=entity_id),
        "parents": [_ser(graph.get(pid), current_entity_id=entity_id) for pid in sorted(parent_ids) if graph.get(pid)],
        "children": [_ser(graph.get(cid), current_entity_id=entity_id) for cid in sorted(child_ids) if graph.get(cid)],
        "all_priorities": [_ser(p, current_entity_id=entity_id) for p in all_priorities],
        "priority_statuses": [s.value for s in PriorityStatus],
    }

    priority_dict = data["priority"]

    # Return priority view mode and trigger list refresh
    html_response = templates.TemplateResponse(
        request,
        "partials/priority_view.html",
        data
    )
    # Include priority data in trigger for tree update
    trigger_data = {
        "priorityCreated": {
            "id": priority_dict["id"],
            "parent_id": parent_id
        }
    }
    html_response.headers["HX-Trigger"] = json.dumps(trigger_data)
    html_response.headers["HX-Push-Url"] = f"/priorities/{priority_dict['id']}"
    html_response.headers["X-New-Item-Id"] = priority_dict["id"]
    return html_response


# -----------------------------------------------------------------------------
# Quick Add
# -----------------------------------------------------------------------------

@router.post("/priorities/quick-add", response_class=HTMLResponse)
async def quick_add_priority(request: Request):
    """Create a priority via quick-add modal and return the row HTML."""
    form_data = await request.form()
    parent_id = form_data.get("parent_id")
    if parent_id and not parent_id.strip():
        parent_id = None

    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = get_graph(entity_id=entity_id)

    # Extract form fields
    priority_type = form_data.get("priority_type", "initiative")
    name = form_data.get("name", "").strip()
    status = form_data.get("status", "active")
    agent_context = form_data.get("agent_context")
    notes = form_data.get("notes")
    assigned_to_entity_id = form_data.get("assigned_to_entity_id")
    complete_when = form_data.get("complete_when")
    progress = form_data.get("progress")
    due_date = form_data.get("due_date")

    if not name:
        return HTMLResponse(
            content="<div class='error'>Name is required</div>",
            status_code=400
        )

    priority_id = _generate_priority_id()
    priority = _create_priority_by_type(priority_type, priority_id, name, entity_id)

    # Set common fields
    priority.status = PriorityStatus(status)
    priority.agent_context = agent_context.strip() if agent_context else None
    priority.description = notes.strip() if notes else None
    priority.assigned_to_entity_id = assigned_to_entity_id.strip() if assigned_to_entity_id else None

    # Set type-specific fields
    if isinstance(priority, Goal):
        priority.complete_when = complete_when.strip() if complete_when else None
        priority.progress = progress.strip() if progress else None
        if due_date:
            try:
                priority.due_date = datetime.fromisoformat(due_date)
            except ValueError:
                priority.due_date = None

    graph.add(priority)

    # Auto-share with group members if assigned to a group
    if priority.assigned_to_entity_id and user:
        _auto_share_with_group(priority.id, priority.assigned_to_entity_id, graph, user.id)

    # Handle parent link
    if parent_id and parent_id.strip():
        try:
            graph.link(priority.id, parent_id.strip())
        except ValueError:
            pass

    # Fire creation event
    if entity_id:
        on_priority_created(
            priority_id=priority.id,
            entity_id=entity_id,
            priority_data={
                "id": priority.id,
                "name": priority.name,
                "priority_type": priority.priority_type.value,
            },
            created_by=user.id if user else None,
        )

    priority_dict = _ser(priority, render_markdown=True, current_entity_id=entity_id)

    html_response = templates.TemplateResponse(
        request,
        "partials/priority_row_single.html",
        {"priority": priority_dict}
    )
    trigger_data = {
        "priorityCreated": {
            "id": priority_dict["id"],
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
    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = get_graph(entity_id=entity_id)

    priorities = sorted(graph.nodes.values(), key=lambda p: (p.priority_type.value, p.name))

    options = ['<option value="">None</option>']
    for p in priorities:
        if exclude and p.id == exclude:
            continue
        options.append(f'<option value="{p.id}">{p.name} ({p.priority_type.value})</option>')

    return HTMLResponse(content="\n".join(options))
