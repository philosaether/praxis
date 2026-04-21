"""
Priority detail/edit routes: viewing, editing, and saving individual priorities.

Direct persistence — no httpx proxy.
"""

import json
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from praxis_core.model import PriorityType, PriorityStatus, Goal, Practice
from praxis_core.serialization import get_graph, clear_graph_cache, serialize_priority, serialize_task
from praxis_core.persistence import validate_session, list_tasks
from praxis_core.practices import on_priority_status_changed
from praxis_web.rendering import (
    templates,
    is_htmx_request,
    render_full_page,
    SESSION_COOKIE_NAME,
)

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


def _ser_task(t, current_user=None, graph=None):
    return serialize_task(t, render_markdown=True, current_user=current_user, graph=graph)


def _get_priority_tasks(priority_id: str):
    return list_tasks(priority_id=priority_id, include_done=True)


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


def _build_detail_data(graph, priority_id, entity_id, user):
    """Build the standard detail response dict for a priority."""
    priority = graph.get(priority_id)
    parent_ids = graph.parents.get(priority_id, set())
    child_ids = graph.children.get(priority_id, set())

    shares = graph.get_shares(priority_id) if priority.entity_id == entity_id else []
    tasks = _get_priority_tasks(priority_id)

    return {
        "priority": _ser(
            priority,
            render_markdown=True,
            current_entity_id=entity_id,
            shares=shares,
            include_action_cards=True,
        ),
        "parents": [_ser(graph.get(pid), current_entity_id=entity_id) for pid in sorted(parent_ids) if graph.get(pid)],
        "children": [_ser(graph.get(cid), current_entity_id=entity_id) for cid in sorted(child_ids) if graph.get(cid)],
        "tasks": [_ser_task(t, current_user=user, graph=graph) for t in tasks],
    }


# -----------------------------------------------------------------------------
# Priority Detail View
# -----------------------------------------------------------------------------

@router.get("/priorities/{priority_id}", response_class=HTMLResponse)
async def priority_detail(request: Request, priority_id: str, from_task: str | None = None):
    """Priority detail - full page or HTMX partial."""
    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = get_graph(entity_id=entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return HTMLResponse(
            content="<div class='error'>Priority not found</div>",
            status_code=404
        )

    data = _build_detail_data(graph, priority_id, entity_id, user)
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
    priorities = sorted(graph.nodes.values(), key=lambda p: (p.priority_type.value, p.name))
    list_html = templates.get_template("partials/priority_rows.html").render(
        priorities=[_ser(p, current_entity_id=entity_id) for p in priorities]
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
    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = get_graph(entity_id=entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return HTMLResponse(
            content="<div class='error'>Priority not found</div>",
            status_code=404
        )

    parent_ids = graph.parents.get(priority_id, set())
    all_priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    shares = graph.get_shares(priority_id) if priority.entity_id == entity_id else []

    priority_data = _ser(priority, current_entity_id=entity_id, shares=shares)
    priority_data["notes_raw"] = priority.description or ""

    # Fetch friends and groups for assignee picker
    friends = []
    groups = []
    if user and user.id:
        from praxis_core.persistence.friend_repo import list_friends
        from praxis_core.persistence.user_repo import list_user_groups
        friends = list_friends(user.id)
        friends.insert(0, {"id": user.id, "username": user.username, "entity_id": user.entity_id})
        groups = list_user_groups(user.id)

    data = {
        "priority": priority_data,
        "parents": [_ser(graph.get(pid), current_entity_id=entity_id) for pid in sorted(parent_ids) if graph.get(pid)],
        "all_priorities": [_ser(p, current_entity_id=entity_id) for p in all_priorities],
        "priority_types": [t.value for t in PriorityType],
        "priority_statuses": [s.value for s in PriorityStatus],
        "friends": friends,
        "groups": groups,
        "edit_mode": True,
    }

    # For Practice priorities, render action cards for the editor
    if priority_data.get("priority_type") == "practice":
        from praxis_web.helpers.action_renderer import actions_to_card_data
        actions_config = priority_data.get("actions_config")
        data["action_cards"] = actions_to_card_data(actions_config) if actions_config else []
        data["priority_name"] = priority_data.get("name", "")
        data["editable"] = True
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
    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = get_graph(entity_id=entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return HTMLResponse(content="", status_code=404)

    tasks = _get_priority_tasks(priority_id)

    return templates.TemplateResponse(
        request,
        "partials/priority_tasks_panel.html",
        {
            "priority": _ser(priority, render_markdown=True, current_entity_id=entity_id, include_action_cards=True),
            "tasks": [_ser_task(t, current_user=user, graph=graph) for t in tasks],
        }
    )


# -----------------------------------------------------------------------------
# Change Type
# -----------------------------------------------------------------------------

@router.post("/priorities/{priority_id}/change-type", response_class=HTMLResponse)
async def priority_change_type(request: Request, priority_id: str):
    """Change priority type and return updated edit form."""
    form_data = await request.form()
    new_priority_type = form_data.get("new_priority_type", "initiative")

    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = get_graph(entity_id=entity_id)
    old_priority = graph.get(priority_id)

    if not old_priority:
        return HTMLResponse(content="<div class='error'>Priority not found</div>", status_code=404)

    if old_priority.priority_type.value != new_priority_type:
        # Create new priority of new type, preserving common fields
        from praxis_core.model import Value, Goal as GoalModel, Practice as PracticeModel, Initiative, Org
        now = datetime.now()
        constructors = {
            "value": Value, "goal": GoalModel, "practice": PracticeModel,
            "initiative": Initiative, "org": Org,
        }
        cls = constructors.get(new_priority_type, Initiative)
        new_priority = cls(id=priority_id, name=old_priority.name, entity_id=entity_id, created_at=old_priority.created_at, updated_at=now)

        # Copy common fields
        new_priority.status = old_priority.status
        new_priority.agent_context = old_priority.agent_context
        new_priority.description = old_priority.description
        new_priority.rank = old_priority.rank

        # Replace in graph
        graph.nodes[priority_id] = new_priority
        graph.save_priority(new_priority)

    # Return edit data for (possibly new) type
    parent_ids = graph.parents.get(priority_id, set())
    all_priorities = sorted(graph.nodes.values(), key=lambda p: p.name)
    current_priority = graph.get(priority_id)
    shares = graph.get_shares(priority_id) if current_priority.entity_id == entity_id else []

    priority_data = _ser(current_priority, current_entity_id=entity_id, shares=shares)
    priority_data["notes_raw"] = current_priority.description or ""

    # Fetch friends and groups for assignee picker
    friends = []
    groups = []
    if user and user.id:
        from praxis_core.persistence.friend_repo import list_friends
        from praxis_core.persistence.user_repo import list_user_groups
        friends = list_friends(user.id)
        friends.insert(0, {"id": user.id, "username": user.username, "entity_id": user.entity_id})
        groups = list_user_groups(user.id)

    data = {
        "priority": priority_data,
        "parents": [_ser(graph.get(pid), current_entity_id=entity_id) for pid in sorted(parent_ids) if graph.get(pid)],
        "all_priorities": [_ser(p, current_entity_id=entity_id) for p in all_priorities],
        "priority_types": [t.value for t in PriorityType],
        "priority_statuses": [s.value for s in PriorityStatus],
        "friends": friends,
        "groups": groups,
        "edit_mode": True,
    }

    return templates.TemplateResponse(request, "partials/priority_edit.html", data)


# -----------------------------------------------------------------------------
# Save Properties
# -----------------------------------------------------------------------------

@router.post("/priorities/{priority_id}/properties", response_class=HTMLResponse)
async def priority_save_properties(request: Request, priority_id: str):
    """Save priority properties and return view mode + OOB row update."""
    form_data = await request.form()
    form = dict(form_data)

    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = get_graph(entity_id=entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return HTMLResponse(
            content="<div class='error'>Priority not found</div>",
            status_code=404
        )

    name = form.get("name", "").strip()
    if not name:
        return HTMLResponse(
            content="<div class='error'>Name is required</div>",
            status_code=400
        )

    # Assemble actions_config JSON from chip form fields
    from praxis_web.helpers.action_renderer import assemble_actions_config
    actions_config = assemble_actions_config(form, form.get("name", ""))
    if not actions_config:
        actions_config = '{"practice": {"name": "", "actions": []}}'

    # Track old status for event trigger
    old_status = priority.status

    # Update common fields
    status = form.get("status", "active")
    priority.name = name
    priority.status = PriorityStatus(status)
    priority.agent_context = form.get("agent_context", "").strip() or None
    priority.description = form.get("notes", "").strip() or None
    priority.updated_at = datetime.now()

    # Update priority assignment
    assigned_to_entity_id = form.get("assigned_to_entity_id", "").strip() or None
    old_assignee = priority.assigned_to_entity_id
    priority.assigned_to_entity_id = assigned_to_entity_id

    # Auto-share with group members if assignment changed to a group
    if assigned_to_entity_id and assigned_to_entity_id != old_assignee and user:
        _auto_share_with_group(priority_id, assigned_to_entity_id, graph, user.id)

    # Update type-specific fields
    if isinstance(priority, Goal):
        priority.complete_when = form.get("complete_when", "").strip() or None
        priority.progress = form.get("progress", "").strip() or None
        due_date = form.get("due_date", "").strip()
        if due_date:
            try:
                priority.due_date = datetime.fromisoformat(due_date)
            except ValueError:
                priority.due_date = None
        else:
            priority.due_date = None

    # For Practice priorities, update actions_config
    if isinstance(priority, Practice):
        stripped = actions_config.strip() if actions_config else ""
        if stripped:
            try:
                parsed = json.loads(stripped)
                actions = parsed.get("practice", {}).get("actions", [])
                priority.actions_config = stripped if actions else None
            except (json.JSONDecodeError, AttributeError):
                priority.actions_config = stripped
        else:
            priority.actions_config = None

    graph.save_priority(priority)

    # Fire event trigger if status changed
    if priority.status != old_status and entity_id:
        priority_data_evt = {
            "id": priority.id,
            "name": priority.name,
            "priority_type": priority.priority_type.value,
        }
        on_priority_status_changed(
            priority_id=priority.id,
            entity_id=entity_id,
            new_status=priority.status.value,
            priority_data=priority_data_evt,
            created_by=user.id if user else None,
        )

    # Handle parent link changes
    parent_id = form.get("parent_id", "").strip() or None
    current_parents = graph.parents.get(priority_id, set())

    for old_parent in list(current_parents):
        if old_parent != parent_id:
            graph.unlink(priority_id, old_parent)

    if parent_id and parent_id not in current_parents and parent_id != priority_id:
        try:
            graph.link(priority_id, parent_id)
        except ValueError:
            pass

    # Build response data
    parent_ids = graph.parents.get(priority_id, set())
    child_ids = graph.children.get(priority_id, set())
    all_priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    priority_data = _ser(priority, render_markdown=True, current_entity_id=entity_id, include_action_cards=True)
    priority_data["notes_raw"] = priority.description or ""

    data = {
        "priority": priority_data,
        "parents": [_ser(graph.get(pid), current_entity_id=entity_id) for pid in sorted(parent_ids) if graph.get(pid)],
        "children": [_ser(graph.get(cid), current_entity_id=entity_id) for cid in sorted(child_ids) if graph.get(cid)],
        "all_priorities": [_ser(p, current_entity_id=entity_id) for p in all_priorities],
        "priority_statuses": [s.value for s in PriorityStatus],
        "priority_types": [t.value for t in PriorityType],
    }

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

    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = get_graph(entity_id=entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return HTMLResponse(
            content="<div class='error'>Priority not found</div>",
            status_code=404
        )

    notes = form_data.get("notes")
    priority.description = notes.strip() if notes else None
    priority.updated_at = datetime.now()
    graph.save_priority(priority)

    priority_data = _ser(priority, render_markdown=True)

    data = {
        "priority": priority_data,
        "item_type": "priority",
        "item_id": priority.id,
        "notes": priority_data.get("notes", ""),
        "notes_raw": priority.description or "",
    }

    return templates.TemplateResponse(
        request,
        "partials/item_notes.html",
        data
    )
