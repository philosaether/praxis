"""
FastAPI application for Praxis web GUI.

Run with: uvicorn praxis.ui.api:app --reload

Requires: pip install -e ".[api]"
"""

from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse
from typing import Annotated
from datetime import datetime

from praxis_core import db
from praxis_core.models import TaskStatus
from praxis_core.priorities import (
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

app = FastAPI(title="Praxis Core API", description="Cue-based task management")


# ---------------------------------------------------------------------
# Graph Singleton
# ---------------------------------------------------------------------

_graph: PriorityGraph | None = None

def get_graph() -> PriorityGraph:
    global _graph
    if _graph is None:
        _graph = PriorityGraph(db.get_connection)
        _graph.load()
    return _graph


# -----------------------------------------------------------------------------
# Serialization Helpers
# -----------------------------------------------------------------------------

def fmt_datetime(dt: datetime | None) -> str | None:
    """Format datetime for display."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M")


def fmt_date(dt: datetime | None) -> str | None:
    """Format date (no time) for display."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d")


def serialize_priority(p) -> dict:
    """Convert a Priority to JSON-serializable dict."""
    data = {
        "id": p.id,
        "name": p.name,
        "priority_type": p.priority_type.value,
        "status": p.status.value,
        "agent_context": p.agent_context,
        "created_at": fmt_datetime(p.created_at),
        "updated_at": fmt_datetime(p.updated_at),
    }

    # Add type-specific fields
    if isinstance(p, Goal):
        data["success_looks_like"] = p.success_looks_like
        data["obsolete_when"] = p.obsolete_when
    elif isinstance(p, Obligation):
        data["consequence_of_neglect"] = p.consequence_of_neglect
    elif isinstance(p, Capacity):
        data["measurement_method"] = p.measurement_method
        data["measurement_rubric"] = p.measurement_rubric
        data["current_level"] = p.current_level
        data["target_level"] = p.target_level
        data["delta_description"] = p.delta_description
    elif isinstance(p, Accomplishment):
        data["success_criteria"] = p.success_criteria
        data["progress"] = p.progress
        data["due_date"] = fmt_date(p.due_date)
    elif isinstance(p, Practice):
        data["rhythm_frequency"] = p.rhythm_frequency
        data["rhythm_constraints"] = p.rhythm_constraints
        data["generation_prompt"] = p.generation_prompt

    return data


def serialize_task(t) -> dict:
    """Convert a Task to JSON-serializable dict."""
    return {
        "id": t.id,
        "title": t.title,
        "status": t.status.value,
        "notes": t.notes,
        "due_date": fmt_date(t.due_date),
        "created_at": fmt_datetime(t.created_at),
        "priority_id": t.priority_id,
        "priority_name": t.priority_name,
        "subtasks": [
            {
                "id": s.id,
                "title": s.title,
                "completed": s.completed,
                "sort_order": s.sort_order,
            }
            for s in t.subtasks
        ],
    }

# -----------------------------------------------------------------------------
# Routes: Priorities
# -----------------------------------------------------------------------------

@app.get("/api/priorities")
async def list_priorities(
    type: str | None = None,
    active: bool = False,
):
    """List priorities with optional filters."""
    graph = get_graph()

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

    return {
        "priorities": [serialize_priority(p) for p in priorities],
        "priority_types": [t.value for t in PriorityType],
        "priority_statuses": [s.value for s in PriorityStatus],
    }

@app.get("/api/priorities/tree")
async def priority_tree():
    """Get tree structure for priorities."""
    graph = get_graph()
    roots = sorted(graph.roots(), key=lambda p: (p.priority_type.value, p.name))

    # Build children map for the entire tree
    children_map = {}
    for parent_id, child_ids in graph.children.items():
        children_map[parent_id] = [
            serialize_priority(graph.get(cid))
            for cid in sorted(child_ids)
            if graph.get(cid)
        ]

    return {
        "roots": [serialize_priority(r) for r in roots],
        "children_map": children_map,
    }

@app.get("/api/priorities/{priority_id}")
async def get_priority(priority_id: str):
    """Get a single priority with its context."""
    graph = get_graph()
    priority = graph.get(priority_id)

    if not priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    parent_ids = graph.parents.get(priority_id, set())
    child_ids = graph.children.get(priority_id, set())

    return {
        "priority": serialize_priority(priority),
        "parents": [serialize_priority(graph.get(pid)) for pid in sorted(parent_ids) if graph.get(pid)],
        "children": [serialize_priority(graph.get(cid)) for cid in sorted(child_ids) if graph.get(cid)],
    }

@app.get("/api/priorities/{priority_id}/edit")
async def get_priority_for_edit(priority_id: str):
    """Get priority data for edit form."""
    graph = get_graph()
    priority = graph.get(priority_id)

    if not priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    parent_ids = graph.parents.get(priority_id, set())
    all_priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    return {
        "priority": serialize_priority(priority),
        "parents": [serialize_priority(graph.get(pid)) for pid in sorted(parent_ids) if graph.get(pid)],
        "all_priorities": [serialize_priority(p) for p in all_priorities],
        "priority_types": [t.value for t in PriorityType],
        "priority_statuses": [s.value for s in PriorityStatus],
        "edit_mode": True,
    }

@app.post("/api/priorities/{priority_id}")
async def update_priority(
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
    """Update a priority and return updated data."""
    graph = get_graph()
    priority = graph.get(priority_id)

    if not priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    # Update fields (same logic as before)
    priority.name = name.strip()
    priority.status = PriorityStatus(status)
    priority.agent_context = agent_context.strip() if agent_context else None
    priority.updated_at = datetime.now()

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

    graph.save_priority(priority)

    # Handle parent link changes
    current_parents = graph.parents.get(priority_id, set())
    new_parent = parent_id.strip() if parent_id else None

    for old_parent in list(current_parents):
        if old_parent != new_parent:
            graph.unlink(priority_id, old_parent)

    if new_parent and new_parent not in current_parents and new_parent != priority_id:
        try:
            graph.link(priority_id, new_parent)
        except ValueError:
            pass

    # Return updated data
    return await get_priority(priority_id)


# -----------------------------------------------------------------------------
# Routes: Tasks
# -----------------------------------------------------------------------------

@app.get("/api/tasks")
async def list_tasks(
    priority: str | None = None,
    status: str | None = None,
):
    """List tasks with optional filters."""
    task_status = None
    if status:
        try:
            task_status = TaskStatus(status)
        except ValueError:
            pass

    tasks = db.list_tasks(priority_id=priority, status=task_status)
    graph = get_graph()
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    return {
        "tasks": [serialize_task(t) for t in tasks],
        "priorities": [serialize_priority(p) for p in priorities],
    }

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: int):
    """Get a single task."""
    task = db.get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    graph = get_graph()
    priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    return {
        "task": serialize_task(task),
        "priorities": [serialize_priority(p) for p in priorities],
        "task_statuses": [s.value for s in TaskStatus],
    }

@app.post("/api/tasks/{task_id}/toggle")
async def toggle_task(task_id: int):
    """Toggle task between done and queued."""
    task = db.get_task(task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    new_status = TaskStatus.QUEUED if task.status == TaskStatus.DONE else TaskStatus.DONE
    db.update_task_status(task_id, new_status)

    task = db.get_task(task_id)
    return {"task": serialize_task(task)}