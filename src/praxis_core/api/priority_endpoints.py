"""Priority API endpoints."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse

from praxis_core.model import (
    PriorityType,
    PriorityStatus,
    Goal,
    Obligation,
    Capacity,
    Accomplishment,
    Practice,
)


router = APIRouter()


def _get_graph():
    """Import here to avoid circular import."""
    from praxis_core.api.app import get_graph
    return get_graph()


def _serialize_priority(p, render_markdown: bool = False):
    """Import here to avoid circular import."""
    from praxis_core.api.app import serialize_priority
    return serialize_priority(p, render_markdown=render_markdown)


def _generate_priority_id(name: str, graph) -> str:
    """Generate a unique slug-style ID for a priority."""
    import re
    # Create base slug from name
    base_slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    if not base_slug:
        base_slug = "priority"

    # Ensure uniqueness
    slug = base_slug
    counter = 1
    while slug in graph.nodes:
        slug = f"{base_slug}-{counter}"
        counter += 1

    return slug


def _create_priority_by_type(priority_type: str, id: str, name: str):
    """Create a priority instance of the appropriate subclass."""
    now = datetime.now()
    if priority_type == "goal":
        return Goal(id=id, name=name, created_at=now, updated_at=now)
    elif priority_type == "obligation":
        return Obligation(id=id, name=name, created_at=now, updated_at=now)
    elif priority_type == "capacity":
        return Capacity(id=id, name=name, created_at=now, updated_at=now)
    elif priority_type == "accomplishment":
        return Accomplishment(id=id, name=name, created_at=now, updated_at=now)
    elif priority_type == "practice":
        return Practice(id=id, name=name, created_at=now, updated_at=now)
    else:
        # Default to Goal
        return Goal(id=id, name=name, created_at=now, updated_at=now)


@router.post("")
async def create_priority_endpoint(
    new_priority_type: Annotated[str, Form(alias="new-priority-type")] = "goal",
):
    """Create a new priority with default values."""
    graph = _get_graph()

    # Create name based on type
    type_label = new_priority_type.title()
    name = f"New {type_label}"

    # Generate unique ID
    priority_id = _generate_priority_id(name, graph)

    # Create the priority
    priority = _create_priority_by_type(new_priority_type, priority_id, name)

    # Add to graph
    graph.add(priority)

    return {"priority": _serialize_priority(priority)}


@router.get("")
async def list_priorities(
    type: str | None = None,
    active: bool = False,
):
    """List priorities with optional filters."""
    graph = _get_graph()

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
        "priorities": [_serialize_priority(p) for p in priorities],
        "priority_types": [t.value for t in PriorityType],
        "priority_statuses": [s.value for s in PriorityStatus],
    }


@router.get("/tree")
async def priority_tree():
    """Get tree structure for priorities."""
    graph = _get_graph()
    roots = sorted(graph.roots(), key=lambda p: (p.priority_type.value, p.name))

    # Build children map for the entire tree
    children_map = {}
    for parent_id, child_ids in graph.children.items():
        children_map[parent_id] = [
            _serialize_priority(graph.get(cid))
            for cid in sorted(child_ids)
            if graph.get(cid)
        ]

    return {
        "roots": [_serialize_priority(r) for r in roots],
        "children_map": children_map,
    }


@router.get("/{priority_id}")
async def get_priority(priority_id: str):
    """Get a single priority with its context."""
    graph = _get_graph()
    priority = graph.get(priority_id)

    if not priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    parent_ids = graph.parents.get(priority_id, set())
    child_ids = graph.children.get(priority_id, set())

    return {
        "priority": _serialize_priority(priority, render_markdown=True),
        "parents": [_serialize_priority(graph.get(pid)) for pid in sorted(parent_ids) if graph.get(pid)],
        "children": [_serialize_priority(graph.get(cid)) for cid in sorted(child_ids) if graph.get(cid)],
    }


@router.get("/{priority_id}/edit")
async def get_priority_for_edit(priority_id: str):
    """Get priority data for edit form."""
    graph = _get_graph()
    priority = graph.get(priority_id)

    if not priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    parent_ids = graph.parents.get(priority_id, set())
    all_priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    return {
        "priority": _serialize_priority(priority),
        "parents": [_serialize_priority(graph.get(pid)) for pid in sorted(parent_ids) if graph.get(pid)],
        "all_priorities": [_serialize_priority(p) for p in all_priorities],
        "priority_types": [t.value for t in PriorityType],
        "priority_statuses": [s.value for s in PriorityStatus],
        "edit_mode": True,
    }


@router.post("/{priority_id}")
async def update_priority(
    priority_id: str,
    name: Annotated[str, Form()],
    status: Annotated[str, Form()],
    agent_context: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
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
    graph = _get_graph()
    priority = graph.get(priority_id)

    if not priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    # Update fields
    priority.name = name.strip()
    priority.status = PriorityStatus(status)
    priority.agent_context = agent_context.strip() if agent_context else None
    priority.notes = notes.strip() if notes else None
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


@router.post("/{priority_id}/properties")
async def update_priority_properties(
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
    """Update priority properties (everything except notes)."""
    graph = _get_graph()
    priority = graph.get(priority_id)

    if not priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    # Validate name
    if not name.strip():
        return JSONResponse({"error": "Name is required"}, status_code=400)

    # Update common fields (preserve notes)
    priority.name = name.strip()
    priority.status = PriorityStatus(status)
    priority.agent_context = agent_context.strip() if agent_context else None
    # Note: priority.notes is NOT updated here
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

    # Return updated data with both raw and rendered notes
    parent_ids = graph.parents.get(priority_id, set())
    child_ids = graph.children.get(priority_id, set())
    all_priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    priority_data = _serialize_priority(priority, render_markdown=True)
    priority_data["notes_raw"] = priority.notes or ""

    return {
        "priority": priority_data,
        "parents": [_serialize_priority(graph.get(pid)) for pid in sorted(parent_ids) if graph.get(pid)],
        "children": [_serialize_priority(graph.get(cid)) for cid in sorted(child_ids) if graph.get(cid)],
        "all_priorities": [_serialize_priority(p) for p in all_priorities],
        "priority_statuses": [s.value for s in PriorityStatus],
    }


@router.post("/{priority_id}/notes")
async def update_priority_notes(
    priority_id: str,
    notes: Annotated[str | None, Form()] = None,
):
    """Update priority notes independently."""
    graph = _get_graph()
    priority = graph.get(priority_id)

    if not priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    priority.notes = notes.strip() if notes else None
    priority.updated_at = datetime.now()
    graph.save_priority(priority)

    priority_data = _serialize_priority(priority, render_markdown=True)

    return {
        "priority": priority_data,
        "item_type": "priority",
        "item_id": priority.id,
        "notes": priority_data.get("notes", ""),
        "notes_raw": priority.notes or "",
    }
