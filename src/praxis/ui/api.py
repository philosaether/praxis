"""
FastAPI application for Praxis web GUI.

Run with: uvicorn praxis.ui.api:app --reload

Requires: pip install -e ".[api]"
"""

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Annotated
from datetime import datetime

from praxis.core import db
from praxis.core.models import TaskStatus
from praxis.core.priorities import (
    PriorityGraph,
    PriorityType,
    PriorityStatus,
    Goal,
    Obligation,
    Capacity,
    Accomplishment,
    Practice,
)

# ---------------------------------------------------------------------
# App Setup
# ---------------------------------------------------------------------

app = FastAPI(title="Praxis", description="Cue-based task management")

# Static files and templates
STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ---------------------------------------------------------------------
# Graph Singleton
# ---------------------------------------------------------------------

_graph: PriorityGraph | None = None

def get_graph() -> PriorityGraph:
    """Get or create the priority graph singleton."""
    global _graph
    if _graph is None:
        _graph = PriorityGraph(db.get_connection)
        _graph.load()
    return _graph


# ---------------------------------------------------------------------
# Helper: Build context for detail/edit templates
# ---------------------------------------------------------------------

def _priority_context(priority_id: str, edit_mode: bool = False):
    """Build template context for priority detail or edit view."""
    graph = get_graph()
    priority = graph.get(priority_id)

    if not priority:
        return None

    parent_ids = graph.parents.get(priority_id, set())
    child_ids = graph.children.get(priority_id, set())
    parents = [graph.get(pid) for pid in sorted(parent_ids) if graph.get(pid)]
    children = [graph.get(cid) for cid in sorted(child_ids) if graph.get(cid)]

    # All priorities for parent selection dropdown
    all_priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    return {
        "priority": priority,
        "parents": parents,
        "children": children,
        "all_priorities": all_priorities,
        "priority_types": list(PriorityType),
        "priority_statuses": list(PriorityStatus),
        "edit_mode": edit_mode,
    }


# ---------------------------------------------------------------------
# Routes: Pages
# ---------------------------------------------------------------------

@app.get("/", response_class=RedirectResponse)
async def root():
    """Redirect to main page."""
    return RedirectResponse(url="/priorities", status_code=302)


@app.get("/priorities", response_class=HTMLResponse)
async def priorities_page(request: Request):
    """Full page: two-pane layout with list on left."""
    graph = get_graph()
    priorities = sorted(
        graph.nodes.values(),
        key=lambda p: (p.priority_type.value, p.name)
    )

    return templates.TemplateResponse(
        request,
        "priority_list.html",
        {
            "priorities": priorities,
            "priority_types": list(PriorityType),
            "selected_type": None,
            "active_only": False,
        }
    )


# ---------------------------------------------------------------------
# Routes: HTMX Partials - Priority List & Tree
# ---------------------------------------------------------------------

@app.get("/priorities/list", response_class=HTMLResponse)
async def priorities_list_partial(
    request: Request,
    type: str | None = None,
    active: bool = False,
):
    """HTMX partial: filtered list of priorities."""
    graph = get_graph()

    # Filter by type if specified
    if type:
        try:
            priority_type = PriorityType(type)
            priorities = graph.by_type(priority_type)
        except ValueError:
            priorities = list(graph.nodes.values())
    else:
        priorities = list(graph.nodes.values())

    # Filter by active status
    if active:
        priorities = [p for p in priorities if p.status == PriorityStatus.ACTIVE]

    # Sort by type, then name
    priorities = sorted(priorities, key=lambda p: (p.priority_type.value, p.name))

    return templates.TemplateResponse(
        request,
        "partials/priority_rows.html",
        {"priorities": priorities}
    )


@app.get("/priorities/tree", response_class=HTMLResponse)
async def priority_tree(request: Request):
    """HTMX partial: tree view of priority hierarchy."""
    graph = get_graph()
    roots = sorted(graph.roots(), key=lambda p: (p.priority_type.value, p.name))

    return templates.TemplateResponse(
        request,
        "partials/priority_tree.html",
        {"roots": roots, "graph": graph}
    )


@app.get("/priorities/tree/{priority_id}/children", response_class=HTMLResponse)
async def priority_tree_children(request: Request, priority_id: str):
    """HTMX partial: children of a tree node (for lazy loading)."""
    graph = get_graph()
    child_ids = graph.children.get(priority_id, set())
    children = [graph.get(cid) for cid in sorted(child_ids) if graph.get(cid)]

    return templates.TemplateResponse(
        request,
        "partials/tree_children.html",
        {"children": children, "graph": graph}
    )


# ---------------------------------------------------------------------
# Routes: HTMX Partials - Priority Detail & Edit
# ---------------------------------------------------------------------

@app.get("/priorities/{priority_id}", response_class=HTMLResponse)
async def priority_detail(request: Request, priority_id: str):
    """HTMX partial: detail view for a single priority."""
    ctx = _priority_context(priority_id, edit_mode=False)
    if not ctx:
        return HTMLResponse(
            content="<div class='error'>Priority not found</div>",
            status_code=404
        )

    return templates.TemplateResponse(request, "partials/priority_detail.html", ctx)


@app.get("/priorities/{priority_id}/edit", response_class=HTMLResponse)
async def priority_edit_form(request: Request, priority_id: str):
    """HTMX partial: edit form for a priority."""
    ctx = _priority_context(priority_id, edit_mode=True)
    if not ctx:
        return HTMLResponse(
            content="<div class='error'>Priority not found</div>",
            status_code=404
        )

    return templates.TemplateResponse(request, "partials/priority_edit.html", ctx)


@app.post("/priorities/{priority_id}", response_class=HTMLResponse)
async def priority_save(
    request: Request,
    priority_id: str,
    name: Annotated[str, Form()],
    status: Annotated[str, Form()],
    agent_context: Annotated[str | None, Form()] = None,
    # Goal fields
    success_looks_like: Annotated[str | None, Form()] = None,
    obsolete_when: Annotated[str | None, Form()] = None,
    # Obligation fields
    consequence_of_neglect: Annotated[str | None, Form()] = None,
    # Capacity fields
    measurement_method: Annotated[str | None, Form()] = None,
    measurement_rubric: Annotated[str | None, Form()] = None,
    current_level: Annotated[str | None, Form()] = None,
    target_level: Annotated[str | None, Form()] = None,
    # Accomplishment fields
    success_criteria: Annotated[str | None, Form()] = None,
    progress: Annotated[str | None, Form()] = None,
    due_date: Annotated[str | None, Form()] = None,
    # Practice fields
    rhythm_frequency: Annotated[str | None, Form()] = None,
    rhythm_constraints: Annotated[str | None, Form()] = None,
    generation_prompt: Annotated[str | None, Form()] = None,
    # Parent link
    parent_id: Annotated[str | None, Form()] = None,
):
    """Save edits to a priority and return updated detail view."""
    graph = get_graph()
    priority = graph.get(priority_id)

    if not priority:
        return HTMLResponse(
            content="<div class='error'>Priority not found</div>",
            status_code=404
        )

    # Update common fields
    priority.name = name.strip()
    priority.status = PriorityStatus(status)
    priority.agent_context = agent_context.strip() if agent_context else None
    priority.updated_at = datetime.now()

    # Update type-specific fields
    if isinstance(priority, Goal):
        priority.success_looks_like = success_looks_like.strip() if success_looks_like else None
        priority.obsolete_when = obsolete_when.strip() if obsolete_when else None

    elif isinstance(priority, Obligation):
        priority.consequence_of_neglect = consequence_of_neglect.strip() if consequence_of_neglect else None

    elif isinstance(priority, Capacity):
        priority.measurement_method = measurement_method.strip() if measurement_method else None
        priority.measurement_rubric = measurement_rubric.strip() if measurement_rubric else None
        priority.current_level = current_level.strip() if current_level else None
        priority.target_level = target_level.strip() if target_level else None

    elif isinstance(priority, Accomplishment):
        priority.success_criteria = success_criteria.strip() if success_criteria else None
        priority.progress = progress.strip() if progress else None
        if due_date:
            try:
                priority.due_date = datetime.fromisoformat(due_date)
            except ValueError:
                priority.due_date = None
        else:
            priority.due_date = None

    elif isinstance(priority, Practice):
        priority.rhythm_frequency = rhythm_frequency.strip() if rhythm_frequency else None
        priority.rhythm_constraints = rhythm_constraints.strip() if rhythm_constraints else None
        priority.generation_prompt = generation_prompt.strip() if generation_prompt else None

    # Persist to database
    graph.save_priority(priority)

    # Handle parent link changes
    current_parents = graph.parents.get(priority_id, set())
    new_parent = parent_id.strip() if parent_id else None

    # For simplicity: single parent model (unlink all, then link new)
    for old_parent in list(current_parents):
        if old_parent != new_parent:
            graph.unlink(priority_id, old_parent)

    if new_parent and new_parent not in current_parents and new_parent != priority_id:
        try:
            graph.link(priority_id, new_parent)
        except ValueError:
            pass  # Ignore cycle errors for now

    # Return updated detail view
    ctx = _priority_context(priority_id, edit_mode=False)
    return templates.TemplateResponse(request, "partials/priority_detail.html", ctx)


# ---------------------------------------------------------------------
# Routes: Tasks
# ---------------------------------------------------------------------

@app.get("/tasks/list", response_class=HTMLResponse)
async def tasks_list_partial(
    request: Request,
    priority: str | None = None,
    status: str | None = None,
):
    """HTMX partial: filtered list of tasks."""
    # Parse status filter
    task_status = None
    if status:
        try:
            task_status = TaskStatus(status)
        except ValueError:
            pass

    tasks = db.list_tasks(priority_id=priority, status=task_status)

    # Get all priorities for filter dropdown
    graph = get_graph()
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    return templates.TemplateResponse(
        request,
        "partials/task_rows.html",
        {"tasks": tasks, "priorities": priorities}
    )


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: int):
    """HTMX partial: detail view for a single task."""
    task = db.get_task(task_id)
    if not task:
        return HTMLResponse(
            content="<div class='error'>Task not found</div>",
            status_code=404
        )

    graph = get_graph()
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    return templates.TemplateResponse(
        request,
        "partials/task_detail.html",
        {
            "task": task,
            "priorities": priorities,
            "task_statuses": list(TaskStatus),
        }
    )


@app.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
async def task_edit_form(request: Request, task_id: int):
    """HTMX partial: edit form for a task."""
    task = db.get_task(task_id)
    if not task:
        return HTMLResponse(
            content="<div class='error'>Task not found</div>",
            status_code=404
        )

    graph = get_graph()
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    return templates.TemplateResponse(
        request,
        "partials/task_edit.html",
        {
            "task": task,
            "priorities": priorities,
            "task_statuses": list(TaskStatus),
        }
    )


@app.post("/tasks/{task_id}", response_class=HTMLResponse)
async def task_save(
    request: Request,
    task_id: int,
    title: Annotated[str, Form()],
    status: Annotated[str, Form()],
    priority_id: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
    due_date: Annotated[str | None, Form()] = None,
):
    """Save edits to a task and return updated detail view."""
    # Parse due date
    parsed_due_date = None
    if due_date:
        try:
            parsed_due_date = datetime.fromisoformat(due_date)
        except ValueError:
            pass

    task = db.update_task(
        task_id=task_id,
        title=title.strip(),
        status=TaskStatus(status),
        priority_id=priority_id.strip() if priority_id else "",
        notes=notes.strip() if notes else None,
        due_date=parsed_due_date,
    )

    if not task:
        return HTMLResponse(
            content="<div class='error'>Task not found</div>",
            status_code=404
        )

    graph = get_graph()
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    return templates.TemplateResponse(
        request,
        "partials/task_detail.html",
        {
            "task": task,
            "priorities": priorities,
            "task_statuses": list(TaskStatus),
        }
    )


@app.post("/tasks/{task_id}/toggle", response_class=HTMLResponse)
async def task_toggle_done(request: Request, task_id: int):
    """Toggle task between done and queued."""
    task = db.get_task(task_id)
    if not task:
        return HTMLResponse(content="", status_code=404)

    # Toggle status
    new_status = TaskStatus.QUEUED if task.status == TaskStatus.DONE else TaskStatus.DONE
    db.update_task_status(task_id, new_status)

    # Return updated row
    task = db.get_task(task_id)
    return templates.TemplateResponse(
        request,
        "partials/task_row_single.html",
        {"task": task}
    )
