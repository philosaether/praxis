"""
Task-related web routes (HTMX partials and full-page views).

Extracted from app.py to keep the main module manageable.
Direct persistence calls — no httpx proxy.
"""

from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from praxis_core.model import TaskStatus
from praxis_core.persistence import (
    create_task as _create_task,
    get_task as _get_task,
    list_tasks as _list_tasks,
    update_task as _update_task,
    update_task_status as _update_task_status,
    delete_task as _delete_task,
    get_tags_for_tasks,
    validate_session,
)
from praxis_core.persistence.rule_persistence import list_rules
from praxis_core.persistence.task_repo import (
    unlink_tasks_from_priority,
    restore_from_outbox,
)
from praxis_core.prioritization import rank_tasks
from praxis_core.practices import on_task_completed
from praxis_core.serialization import (
    get_graph as _get_graph_impl,
    serialize_task as _serialize_task_fn,
    serialize_priority as _serialize_priority_fn,
    get_task_permission,
    can_edit_task,
    can_toggle_task,
    can_delete_task,
    clear_graph_cache,
)
from praxis_web.rendering import (
    SESSION_COOKIE_NAME,
    templates as _templates,
    is_htmx_request as _is_htmx_request,
    render_full_page as _render_full_page,
)

router = APIRouter()


# -- helpers ------------------------------------------------------------------

def _get_user(request: Request):
    """Resolve the current user from session cookie, or None."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    result = validate_session(token)
    if result is None:
        return None
    _session, user = result
    return user


def _get_graph(entity_id: str | None = None):
    return _get_graph_impl(entity_id=entity_id)


def _serialize_task(t, render_markdown: bool = False, current_user=None, graph=None):
    return _serialize_task_fn(t, render_markdown=render_markdown, current_user=current_user, graph=graph)


def _serialize_priority(p):
    return _serialize_priority_fn(p)


def _get_active_rules(entity_id: str | None):
    """Get active rules for scoring (system + user rules)."""
    return list_rules(entity_id=entity_id, include_system=True, enabled_only=True)


def _task_detail_data(task_id: str, user, render_markdown: bool = True):
    """Build the template context dict for a single task detail view."""
    task = _get_task(task_id)
    if task is None:
        return None

    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    return {
        "task": _serialize_task(task, render_markdown=render_markdown, current_user=user, graph=graph),
        "priorities": [_serialize_priority(p) for p in priorities],
        "task_statuses": [s.value for s in TaskStatus],
    }


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
    user = _get_user(request)
    entity_id = user.entity_id if user else None

    task_status = None
    if status:
        try:
            task_status = TaskStatus(status)
        except ValueError:
            pass

    tag_names = None
    if tag:
        tag_names = [t.strip() for t in tag.split(",") if t.strip()]

    search_query = q.strip() if q else None

    graph = _get_graph(entity_id)

    tasks = _list_tasks(
        priority_id=priority,
        status=task_status,
        entity_id=entity_id,
        tag_names=tag_names,
        search_query=search_query,
    )
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    # Score and rank
    rules = _get_active_rules(entity_id)
    task_ids = [t.id for t in tasks]
    task_tags_map = get_tags_for_tasks(task_ids) if task_ids else {}
    scored_tasks = rank_tasks(tasks, graph, rules, task_tags_map)

    serialized = []
    for st in scored_tasks:
        task_data = _serialize_task(st.task, current_user=user, graph=graph)
        task_data["score"] = round(st.score, 2)
        task_data["importance"] = round(st.importance, 1)
        task_data["urgency"] = round(st.urgency, 1)
        task_data["aptness"] = round(st.aptness, 2)
        serialized.append(task_data)

    return _templates.TemplateResponse(
        request,
        "partials/task_rows.html",
        {
            "tasks": serialized,
            "priorities": [_serialize_priority(p) for p in priorities],
            "current_tag": tag,
            "current_status": status,
            "current_search": q,
        }
    )


@router.get("/tasks/new", response_class=HTMLResponse)
async def new_task_form(request: Request):
    """Show empty form for creating a new task."""
    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    return _templates.TemplateResponse(
        request,
        "partials/task_new_form.html",
        {
            "priorities": [_serialize_priority(p) for p in priorities],
            "task_statuses": [s.value for s in TaskStatus],
        }
    )


@router.post("/tasks/create", response_class=HTMLResponse)
async def create_task_submit(request: Request):
    """Create a new task and return the view mode (read-only display)."""
    user = _get_user(request)
    form_data = await request.form()

    name = (form_data.get("name") or "").strip()
    if not name:
        return HTMLResponse(
            content="<div class='error'>Name is required</div>",
            status_code=400,
        )

    creator_entity_id = user.entity_id if user else None
    created_by = user.id if user else None

    priority_id = (form_data.get("priority_id") or "").strip() or None
    due_date_str = form_data.get("due_date")
    notes = (form_data.get("notes") or "").strip() or None

    parsed_due_date = None
    if due_date_str:
        try:
            parsed_due_date = datetime.fromisoformat(due_date_str)
        except ValueError:
            pass

    # Resolve entity_id from priority owner if a priority is given
    task_entity_id = creator_entity_id
    graph = _get_graph(creator_entity_id)
    if priority_id:
        priority_node = graph.get(priority_id)
        if priority_node:
            task_entity_id = priority_node.entity_id

    task = _create_task(
        name=name,
        notes=notes,
        due_date=parsed_due_date,
        priority_id=priority_id,
        entity_id=task_entity_id,
        created_by=created_by,
    )

    # Fetch detail for view template
    detail_data = _task_detail_data(task.id, user)

    html_response = _templates.TemplateResponse(
        request,
        "partials/task_view.html",
        detail_data,
    )
    html_response.headers["HX-Trigger"] = "taskCreated"
    html_response.headers["HX-Push-Url"] = f"/tasks/{task.id}"
    html_response.headers["X-New-Item-Id"] = str(task.id)
    return html_response


@router.post("/tasks/quick-add", response_class=HTMLResponse)
async def quick_add_task(request: Request):
    """Create a task via quick-add modal and return the row HTML."""
    user = _get_user(request)
    form_data = await request.form()

    name = (form_data.get("name") or "").strip()
    if not name:
        return HTMLResponse(
            content="<div class='error'>Name is required</div>",
            status_code=400,
        )

    creator_entity_id = user.entity_id if user else None
    created_by = user.id if user else None

    priority_id = (form_data.get("priority_id") or "").strip() or None
    due_date_str = form_data.get("due_date")
    notes = (form_data.get("notes") or "").strip() or None

    parsed_due_date = None
    if due_date_str:
        try:
            parsed_due_date = datetime.fromisoformat(due_date_str)
        except ValueError:
            pass

    task_entity_id = creator_entity_id
    graph = _get_graph(creator_entity_id)
    if priority_id:
        priority_node = graph.get(priority_id)
        if priority_node:
            task_entity_id = priority_node.entity_id

    task = _create_task(
        name=name,
        notes=notes,
        due_date=parsed_due_date,
        priority_id=priority_id,
        entity_id=task_entity_id,
        created_by=created_by,
    )

    task_data = _serialize_task(task, current_user=user, graph=graph)
    html_response = _templates.TemplateResponse(
        request,
        "partials/task_row_single.html",
        {"task": task_data},
    )
    html_response.headers["HX-Trigger"] = "taskCreated"
    return html_response


@router.get("/tasks/quick-add/priorities", response_class=HTMLResponse)
async def quick_add_priorities(request: Request):
    """Return fresh priority options for the quick-add modal dropdown."""
    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    options = ['<option value="">Inbox (no priority)</option>']
    for p in priorities:
        sp = _serialize_priority(p)
        type_prefix = sp["priority_type"][:3].upper()
        options.append(f'<option value="{sp["id"]}">[{type_prefix}] {sp["name"]}</option>')

    return HTMLResponse(content="\n".join(options))


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: str):
    """Task detail - full page or HTMX partial."""
    user = _get_user(request)
    data = _task_detail_data(task_id, user)
    if data is None:
        return HTMLResponse(
            content="<div class='error'>Task not found</div>",
            status_code=404,
        )

    if _is_htmx_request(request):
        return _templates.TemplateResponse(
            request,
            "partials/task_view.html",
            data,
        )

    detail_html = _templates.get_template("partials/task_view.html").render(
        request=request, **data
    )
    return await _render_full_page(
        request,
        mode="tasks",
        initial_detail_html=detail_html,
    )


@router.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
async def task_edit(request: Request, task_id: str):
    """HTMX partial: edit mode for a single task."""
    user = _get_user(request)
    task = _get_task(task_id)
    if not task:
        return HTMLResponse(
            content="<div class='error'>Task not found</div>",
            status_code=404,
        )

    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    task_data = _serialize_task(task, render_markdown=False, current_user=user, graph=graph)
    task_data["notes_raw"] = task.description or ""

    return _templates.TemplateResponse(
        request,
        "partials/task_edit.html",
        {
            "task": task_data,
            "priorities": [_serialize_priority(p) for p in priorities],
            "task_statuses": [s.value for s in TaskStatus],
            "edit_mode": True,
        },
    )


@router.post("/tasks/{task_id}/properties", response_class=HTMLResponse)
async def task_save_properties(request: Request, task_id: str):
    """Save task properties and return view mode + OOB row update."""
    user = _get_user(request)
    task = _get_task(task_id)
    if not task:
        return HTMLResponse(
            content="<div class='error'>Task not found</div>",
            status_code=404,
        )

    # Permission check
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    permission = get_task_permission(task, user, graph)
    if not can_edit_task(permission):
        return HTMLResponse(
            content="<div class='error'>Permission denied</div>",
            status_code=403,
        )

    form_data = await request.form()
    name = (form_data.get("name") or "").strip()
    if not name:
        return HTMLResponse(
            content="<div class='error'>Name is required</div>",
            status_code=400,
        )

    priority_id = form_data.get("priority_id")
    due_date_str = form_data.get("due_date")
    notes = form_data.get("notes")

    parsed_due_date = None
    if due_date_str:
        try:
            parsed_due_date = datetime.fromisoformat(due_date_str)
        except ValueError:
            pass

    _update_task(
        task_id,
        name=name,
        status=task.status,
        priority_id=priority_id.strip() if priority_id else "",
        notes=notes.strip() if notes else "",
        due_date=parsed_due_date,
    )

    # Re-fetch for updated data
    task = _get_task(task_id)
    graph = _get_graph(entity_id)
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    task_data = _serialize_task(task, render_markdown=True, current_user=user, graph=graph)
    task_data["notes_raw"] = task.description or ""

    data = {
        "task": task_data,
        "priorities": [_serialize_priority(p) for p in priorities],
        "task_statuses": [s.value for s in TaskStatus],
    }

    view_html = _templates.TemplateResponse(
        request,
        "partials/task_view.html",
        data,
    ).body.decode()

    row_html = _templates.TemplateResponse(
        request,
        "partials/task_row_single.html",
        {"task": task_data, "oob": True},
    ).body.decode()

    return HTMLResponse(content=view_html + row_html)


@router.post("/tasks/{task_id}/notes", response_class=HTMLResponse)
async def task_save_notes(request: Request, task_id: str):
    """Save task notes and return updated notes section."""
    user = _get_user(request)
    task = _get_task(task_id)
    if not task:
        return HTMLResponse(
            content="<div class='error'>Task not found</div>",
            status_code=404,
        )

    # Permission check
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    permission = get_task_permission(task, user, graph)
    if not can_edit_task(permission):
        return HTMLResponse(
            content="<div class='error'>Permission denied</div>",
            status_code=403,
        )

    form_data = await request.form()
    notes = form_data.get("notes")

    _update_task(
        task_id,
        name=task.name,
        status=task.status,
        priority_id=task.priority_id or "",
        notes=notes.strip() if notes else "",
        due_date=task.due_date,
    )

    task = _get_task(task_id)
    task_data = _serialize_task(task, render_markdown=True, current_user=user, graph=graph)
    task_data["notes_raw"] = task.description or ""

    return _templates.TemplateResponse(
        request,
        "partials/item_notes.html",
        {
            "task": task_data,
            "item_type": "task",
            "item_id": task.id,
            "notes": task_data.get("notes", ""),
            "notes_raw": task.description or "",
        },
    )


@router.post("/tasks/{task_id}/quick-assign", response_class=HTMLResponse)
async def task_quick_assign(request: Request, task_id: str):
    """Quick-assign a task to a priority (inbox triage)."""
    user = _get_user(request)
    form = await request.form()
    priority_id = form.get("priority_id")
    if not priority_id:
        return HTMLResponse(content="", status_code=400)

    task = _get_task(task_id)
    if not task:
        return HTMLResponse(content="", status_code=404)

    # Permission check
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    permission = get_task_permission(task, user, graph)
    if not can_edit_task(permission):
        return HTMLResponse(content="", status_code=403)

    _update_task(task_id, priority_id=priority_id.strip())
    return HTMLResponse(content="", status_code=204)


@router.post("/tasks/{task_id}/toggle", response_class=HTMLResponse)
async def task_toggle_done(request: Request, task_id: str):
    """Toggle task between done and queued."""
    user = _get_user(request)
    task = _get_task(task_id)
    if not task:
        return HTMLResponse(content="", status_code=404)

    # Permission check
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    permission = get_task_permission(task, user, graph)
    if not can_toggle_task(permission):
        return HTMLResponse(content="", status_code=403)

    new_status = TaskStatus.QUEUED if task.status == TaskStatus.DONE else TaskStatus.DONE
    if new_status == TaskStatus.QUEUED and task.is_in_outbox:
        restore_from_outbox(task_id)
    else:
        _update_task_status(task_id, new_status)

    # Fire event triggers if task was marked done
    if new_status == TaskStatus.DONE and task.entity_id:
        task_data_for_trigger = {
            "id": task.id,
            "name": task.name,
            "priority_id": task.priority_id,
            "entity_id": task.entity_id,
            "tags": [],
        }
        on_task_completed(
            task_id=task.id,
            entity_id=task.entity_id,
            task_data=task_data_for_trigger,
            created_by=user.id if user else None,
        )

    task = _get_task(task_id)
    task_data = _serialize_task(task, current_user=user, graph=graph)

    # Include score data for the row display
    rules = _get_active_rules(entity_id)
    task_tags_map = get_tags_for_tasks([task_id])
    scored_tasks = rank_tasks([task], graph, rules, task_tags_map)
    if scored_tasks:
        st = scored_tasks[0]
        task_data["score"] = round(st.score, 2)
        task_data["importance"] = round(st.importance, 1)
        task_data["urgency"] = round(st.urgency, 1)
        task_data["aptness"] = round(st.aptness, 2)

    # Task moved to outbox — remove row from list immediately
    if task_data.get("is_in_outbox"):
        return HTMLResponse(content="")

    return _templates.TemplateResponse(
        request,
        "partials/task_row_single.html",
        {"task": task_data},
    )


@router.delete("/tasks/{task_id}", response_class=HTMLResponse)
async def delete_task_route(request: Request, task_id: str):
    """Delete a task and return empty content."""
    user = _get_user(request)
    task = _get_task(task_id)
    if not task:
        return HTMLResponse(content="", status_code=404)

    # Permission check
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    permission = get_task_permission(task, user, graph)
    if not can_delete_task(permission):
        return HTMLResponse(content="", status_code=403)

    _delete_task(task_id)
    return HTMLResponse(content="")


# -----------------------------------------------------------------------------
# Misplaced route: belongs with priority routes, extracted here for now
# -----------------------------------------------------------------------------

@router.delete("/priorities/{priority_id}", response_class=HTMLResponse)
async def delete_priority(request: Request, priority_id: str):
    """Delete a priority and all its edges."""
    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)

    if not graph.get(priority_id):
        return HTMLResponse(content="", status_code=404)

    unlink_tasks_from_priority(priority_id)
    graph.delete(priority_id)
    clear_graph_cache(entity_id)
    return HTMLResponse(content="")
