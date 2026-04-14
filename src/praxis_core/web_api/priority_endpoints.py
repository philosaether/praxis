"""Priority API endpoints."""

import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Form, Depends
from fastapi.responses import JSONResponse

from praxis_core.model import (
    PriorityType,
    PriorityStatus,
    Value,
    Goal,
    Practice,
    Initiative,
    User,
)
from praxis_core.web_api.auth import get_current_user_optional
from praxis_core.triggers import on_priority_status_changed, on_priority_created


router = APIRouter()


def _get_graph(entity_id: str | None = None):
    """Import here to avoid circular import."""
    from praxis_core.web_api.app import get_graph
    return get_graph(entity_id=entity_id)


def _serialize_priority(
    p,
    render_markdown: bool = False,
    current_entity_id: str | None = None,
    shares: list[dict] | None = None,
    include_action_cards: bool = False,
):
    """Import here to avoid circular import."""
    from praxis_core.web_api.app import serialize_priority
    return serialize_priority(
        p,
        render_markdown=render_markdown,
        current_entity_id=current_entity_id,
        shares=shares,
        include_action_cards=include_action_cards,
    )


def _serialize_task(t, render_markdown: bool = False, current_user=None, graph=None):
    """Import here to avoid circular import."""
    from praxis_core.web_api.app import serialize_task
    return serialize_task(t, render_markdown=render_markdown, current_user=current_user, graph=graph)


def _get_priority_tasks(priority_id: str):
    """Get all tasks associated with a priority (regardless of owner).

    When viewing a shared priority, users see all tasks linked to it.
    Access control is at the priority level, not the task level.
    """
    from praxis_core.persistence import list_tasks
    return list_tasks(priority_id=priority_id, include_done=True)


def _generate_priority_id(name: str, graph) -> str:
    """Generate a unique ULID for a priority."""
    from ulid import ULID
    return str(ULID())


def _create_priority_by_type(priority_type: str, id: str, name: str, entity_id: str | None = None):
    """Create a priority instance of the appropriate subclass."""
    now = datetime.now()
    if priority_type == "initiative":
        return Initiative(id=id, name=name, entity_id=entity_id, created_at=now, updated_at=now)
    elif priority_type == "value":
        return Value(id=id, name=name, entity_id=entity_id, created_at=now, updated_at=now)
    elif priority_type == "goal":
        return Goal(id=id, name=name, entity_id=entity_id, created_at=now, updated_at=now)
    elif priority_type == "practice":
        return Practice(id=id, name=name, entity_id=entity_id, created_at=now, updated_at=now)
    else:
        # Default to Initiative
        return Initiative(id=id, name=name, entity_id=entity_id, created_at=now, updated_at=now)


@router.post("")
async def create_priority_endpoint(
    new_priority_type: Annotated[str, Form(alias="new-priority-type")] = "initiative",
    user: User | None = Depends(get_current_user_optional),
):
    """Create a new priority with default values (legacy endpoint)."""
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)

    # Create name based on type
    type_label = new_priority_type.title()
    name = f"New {type_label}"

    # Generate unique ID
    priority_id = _generate_priority_id(name, graph)

    # Create the priority with entity_id
    priority = _create_priority_by_type(new_priority_type, priority_id, name, entity_id)

    # Add to graph
    graph.add(priority)

    return {"priority": _serialize_priority(priority)}


@router.post("/create")
async def create_priority_full(
    priority_type: Annotated[str, Form()] = "initiative",
    name: Annotated[str, Form()] = "",
    status: Annotated[str, Form()] = "active",
    parent_id: Annotated[str | None, Form()] = None,
    agent_context: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
    # Task assignment settings
    auto_assign_owner: Annotated[str | None, Form()] = "on",
    auto_assign_creator: Annotated[str | None, Form()] = None,
    # Goal fields
    complete_when: Annotated[str | None, Form()] = None,
    progress: Annotated[str | None, Form()] = None,
    due_date: Annotated[str | None, Form()] = None,
    user: User | None = Depends(get_current_user_optional),
):
    """Create a priority with all fields (form-first flow)."""
    if not name.strip():
        return JSONResponse({"error": "Name is required"}, status_code=400)

    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)

    priority_id = _generate_priority_id(name.strip(), graph)
    priority = _create_priority_by_type(priority_type, priority_id, name.strip(), entity_id)

    # Set common fields
    priority.status = PriorityStatus(status)
    priority.agent_context = agent_context.strip() if agent_context else None
    priority.description = notes.strip() if notes else None

    # Set task assignment settings (checkboxes: "on" if checked, None if not)
    priority.auto_assign_owner = auto_assign_owner == "on"
    priority.auto_assign_creator = auto_assign_creator == "on"

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

    # Return full detail data for rendering
    parent_ids = graph.parents.get(priority.id, set())
    child_ids = graph.children.get(priority.id, set())
    all_priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    return {
        "priority": _serialize_priority(priority, render_markdown=True, current_entity_id=entity_id),
        "parents": [_serialize_priority(graph.get(pid), current_entity_id=entity_id) for pid in sorted(parent_ids) if graph.get(pid)],
        "children": [_serialize_priority(graph.get(cid), current_entity_id=entity_id) for cid in sorted(child_ids) if graph.get(cid)],
        "all_priorities": [_serialize_priority(p, current_entity_id=entity_id) for p in all_priorities],
        "priority_statuses": [s.value for s in PriorityStatus],
    }


@router.get("")
async def list_priorities(
    type: str | None = None,
    active: bool = False,
    user: User | None = Depends(get_current_user_optional),
):
    """List priorities with optional filters."""
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)

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
        "priorities": [_serialize_priority(p, current_entity_id=entity_id) for p in priorities],
        "priority_types": [t.value for t in PriorityType],
        "priority_statuses": [s.value for s in PriorityStatus],
    }


def _sort_key(p):
    """Sort by rank (nulls last), then by name."""
    return (p.rank if p.rank is not None else 999, p.name)


@router.get("/tree")
async def priority_tree(
    user: User | None = Depends(get_current_user_optional),
):
    """Get tree structure for priorities."""
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    roots = sorted(graph.roots(), key=_sort_key)

    # Build children map for the entire tree
    children_map = {}
    for parent_id, child_ids in graph.children.items():
        children = [graph.get(cid) for cid in child_ids if graph.get(cid)]
        children_map[parent_id] = [
            _serialize_priority(c, current_entity_id=entity_id)
            for c in sorted(children, key=_sort_key)
        ]

    return {
        "roots": [_serialize_priority(r, current_entity_id=entity_id) for r in roots],
        "children_map": children_map,
    }


@router.get("/{priority_id}")
async def get_priority(
    priority_id: str,
    user: User | None = Depends(get_current_user_optional),
):
    """Get a single priority with its context."""
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    parent_ids = graph.parents.get(priority_id, set())
    child_ids = graph.children.get(priority_id, set())

    # Get shares for ownership display
    shares = graph.get_shares(priority_id) if priority.entity_id == entity_id else []

    # Get associated tasks (all users' tasks for shared priorities)
    tasks = _get_priority_tasks(priority_id)

    return {
        "priority": _serialize_priority(
            priority,
            render_markdown=True,
            current_entity_id=entity_id,
            shares=shares,
            include_action_cards=True,
        ),
        "parents": [_serialize_priority(graph.get(pid), current_entity_id=entity_id) for pid in sorted(parent_ids) if graph.get(pid)],
        "children": [_serialize_priority(graph.get(cid), current_entity_id=entity_id) for cid in sorted(child_ids) if graph.get(cid)],
        "tasks": [_serialize_task(t, current_user=user, graph=graph) for t in tasks],
    }


@router.get("/{priority_id}/edit")
async def get_priority_for_edit(
    priority_id: str,
    user: User | None = Depends(get_current_user_optional),
):
    """Get priority data for edit form."""
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    parent_ids = graph.parents.get(priority_id, set())
    all_priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

    # Get shares for ownership display
    shares = graph.get_shares(priority_id) if priority.entity_id == entity_id else []

    priority_data = _serialize_priority(priority, current_entity_id=entity_id, shares=shares)
    priority_data["notes_raw"] = priority.description or ""

    return {
        "priority": priority_data,
        "parents": [_serialize_priority(graph.get(pid), current_entity_id=entity_id) for pid in sorted(parent_ids) if graph.get(pid)],
        "all_priorities": [_serialize_priority(p, current_entity_id=entity_id) for p in all_priorities],
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
    complete_when: Annotated[str | None, Form()] = None,
    progress: Annotated[str | None, Form()] = None,
    due_date: Annotated[str | None, Form()] = None,
    # Parent link
    parent_id: Annotated[str | None, Form()] = None,
    user: User | None = Depends(get_current_user_optional),
):
    """Update a priority and return updated data."""
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    # Track old status for event trigger
    old_status = priority.status

    # Update fields
    priority.name = name.strip()
    priority.status = PriorityStatus(status)
    priority.agent_context = agent_context.strip() if agent_context else None
    priority.description = notes.strip() if notes else None
    priority.updated_at = datetime.now()

    if isinstance(priority, Goal):
        priority.complete_when = complete_when.strip() if complete_when else None
        priority.progress = progress.strip() if progress else None
        if due_date:
            try:
                priority.due_date = datetime.fromisoformat(due_date)
            except ValueError:
                priority.due_date = None
        else:
            priority.due_date = None

    graph.save_priority(priority)

    # Fire event trigger if status changed
    if priority.status != old_status and entity_id:
        priority_data = {
            "id": priority.id,
            "name": priority.name,
            "priority_type": priority.priority_type.value,
        }
        on_priority_status_changed(
            priority_id=priority.id,
            entity_id=entity_id,
            new_status=priority.status.value,
            priority_data=priority_data,
            created_by=user.id if user else None,
        )

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


@router.post("/{priority_id}/change-type")
async def change_priority_type(
    priority_id: str,
    new_priority_type: Annotated[str, Form()],
    user: User | None = Depends(get_current_user_optional),
):
    """Change a priority's type, preserving common fields."""
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    old_priority = graph.get(priority_id)

    if not old_priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    if old_priority.priority_type.value == new_priority_type:
        # No change, return current data
        return await get_priority_for_edit(priority_id, user)

    # Create new priority of new type, preserving common fields
    now = datetime.now()
    new_priority = _create_priority_by_type(new_priority_type, priority_id, old_priority.name, entity_id)

    # Copy common fields
    new_priority.status = old_priority.status
    new_priority.agent_context = old_priority.agent_context
    new_priority.description = old_priority.description
    new_priority.rank = old_priority.rank
    new_priority.created_at = old_priority.created_at
    new_priority.updated_at = now

    # Replace in graph
    graph.nodes[priority_id] = new_priority
    graph.save_priority(new_priority)

    # Return edit data for new type
    return await get_priority_for_edit(priority_id, user)


@router.post("/{priority_id}/properties")
async def update_priority_properties(
    priority_id: str,
    name: Annotated[str, Form()],
    status: Annotated[str, Form()],
    agent_context: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
    # Task assignment settings
    auto_assign_owner: Annotated[str | None, Form()] = None,
    auto_assign_creator: Annotated[str | None, Form()] = None,
    # Goal fields
    complete_when: Annotated[str | None, Form()] = None,
    progress: Annotated[str | None, Form()] = None,
    due_date: Annotated[str | None, Form()] = None,
    # Parent link
    parent_id: Annotated[str | None, Form()] = None,
    # Practice actions (chip editor serialized JSON)
    actions_config: Annotated[str | None, Form()] = None,
    user: User | None = Depends(get_current_user_optional),
):
    """Update priority properties including notes."""
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    # Validate name
    if not name.strip():
        return JSONResponse({"error": "Name is required"}, status_code=400)

    # Track old status for event trigger
    old_status = priority.status

    # Update common fields
    priority.name = name.strip()
    priority.status = PriorityStatus(status)
    priority.agent_context = agent_context.strip() if agent_context else None
    priority.description = notes.strip() if notes else None
    priority.updated_at = datetime.now()

    # Update task assignment settings (checkboxes: "on" if checked, None if not)
    priority.auto_assign_owner = auto_assign_owner == "on"
    priority.auto_assign_creator = auto_assign_creator == "on"

    # Update type-specific fields
    if isinstance(priority, Goal):
        priority.complete_when = complete_when.strip() if complete_when else None
        priority.progress = progress.strip() if progress else None
        if due_date:
            try:
                priority.due_date = datetime.fromisoformat(due_date)
            except ValueError:
                priority.due_date = None
        else:
            priority.due_date = None

    # For Practice priorities, update actions_config if provided.
    # The web layer assembles JSON from chip form fields server-side.
    if isinstance(priority, Practice):
        if actions_config is not None:
            stripped = actions_config.strip()
            # Check if config has no actions (clear case)
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
        priority_data = {
            "id": priority.id,
            "name": priority.name,
            "priority_type": priority.priority_type.value,
        }
        on_priority_status_changed(
            priority_id=priority.id,
            entity_id=entity_id,
            new_status=priority.status.value,
            priority_data=priority_data,
            created_by=user.id if user else None,
        )

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

    priority_data = _serialize_priority(priority, render_markdown=True, current_entity_id=entity_id, include_action_cards=True)
    priority_data["notes_raw"] = priority.description or ""

    return {
        "priority": priority_data,
        "parents": [_serialize_priority(graph.get(pid), current_entity_id=entity_id) for pid in sorted(parent_ids) if graph.get(pid)],
        "children": [_serialize_priority(graph.get(cid), current_entity_id=entity_id) for cid in sorted(child_ids) if graph.get(cid)],
        "all_priorities": [_serialize_priority(p, current_entity_id=entity_id) for p in all_priorities],
        "priority_statuses": [s.value for s in PriorityStatus],
        "priority_types": [t.value for t in PriorityType],
    }


@router.post("/{priority_id}/notes")
async def update_priority_notes(
    priority_id: str,
    notes: Annotated[str | None, Form()] = None,
    user: User | None = Depends(get_current_user_optional),
):
    """Update priority notes independently."""
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    priority.description = notes.strip() if notes else None
    priority.updated_at = datetime.now()
    graph.save_priority(priority)

    priority_data = _serialize_priority(priority, render_markdown=True)

    return {
        "priority": priority_data,
        "item_type": "priority",
        "item_id": priority.id,
        "notes": priority_data.get("notes", ""),
        "notes_raw": priority.description or "",
    }


from pydantic import BaseModel


class MoveRequest(BaseModel):
    new_parent_id: str | None = None
    sibling_ids: list[str] = []
    new_index: int = 0


@router.delete("/{priority_id}")
async def delete_priority(
    priority_id: str,
    user: User | None = Depends(get_current_user_optional),
):
    """Delete a priority and all its edges."""
    from praxis_core.web_api.app import clear_graph_cache
    from praxis_core.persistence.task_persistence import unlink_tasks_from_priority

    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)

    if not graph.get(priority_id):
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    unlink_tasks_from_priority(priority_id)
    graph.delete(priority_id)
    clear_graph_cache(entity_id)
    return {"success": True, "deleted_id": priority_id}


class DeleteRequest(BaseModel):
    delete_mode: str = "orphan"  # "orphan" or "cascade"


@router.post("/{priority_id}/delete")
async def delete_priority_with_options(
    priority_id: str,
    request_data: DeleteRequest,
    user: User | None = Depends(get_current_user_optional),
):
    """
    Delete a priority with options for handling children and linked tasks.

    delete_mode:
    - "orphan": Move children to this priority's parent (or make them roots)
    - "cascade": Delete all children recursively
    """
    from praxis_core.web_api.app import clear_graph_cache
    from praxis_core.persistence.task_persistence import unlink_tasks_from_priority

    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    delete_mode = request_data.delete_mode
    deleted_ids = [priority_id]

    # Get this priority's parent (if any)
    parent_ids = graph.parents.get(priority_id, set())
    new_parent_id = next(iter(parent_ids), None) if parent_ids else None

    # Get children
    child_ids = list(graph.children.get(priority_id, set()))

    if delete_mode == "cascade":
        # Recursively collect all descendant IDs
        def collect_descendants(pid):
            descendants = []
            for child_id in graph.children.get(pid, set()):
                descendants.append(child_id)
                descendants.extend(collect_descendants(child_id))
            return descendants

        all_descendants = collect_descendants(priority_id)

        # Unlink tasks from all priorities being deleted
        for pid in [priority_id] + all_descendants:
            unlink_tasks_from_priority(pid)

        # Delete descendants (deepest first to avoid issues)
        for desc_id in reversed(all_descendants):
            graph.delete(desc_id)
            deleted_ids.append(desc_id)

    else:  # orphan mode
        # Move children to the deleted priority's parent
        for child_id in child_ids:
            # Unlink from this priority
            graph.unlink(child_id, priority_id)
            # Link to new parent if one exists
            if new_parent_id:
                try:
                    graph.link(child_id, new_parent_id)
                except ValueError:
                    pass  # Ignore circular reference errors

        # Unlink tasks from this priority only
        unlink_tasks_from_priority(priority_id)

    # Delete the priority itself
    graph.delete(priority_id)
    clear_graph_cache(entity_id)

    return {
        "success": True,
        "deleted_ids": deleted_ids,
        "orphaned_children": child_ids if delete_mode == "orphan" else [],
    }


@router.post("/{priority_id}/move")
async def move_priority(
    priority_id: str,
    request_data: MoveRequest,
    user: User | None = Depends(get_current_user_optional),
):
    """
    Move a priority in the tree (reparent and/or reorder).

    Handles drag-and-drop operations from the tree view.
    """
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    new_parent_id = request_data.new_parent_id
    sibling_ids = request_data.sibling_ids
    new_index = request_data.new_index

    # Handle reparenting
    current_parents = graph.parents.get(priority_id, set())

    # Remove from old parent(s)
    for old_parent in list(current_parents):
        if old_parent != new_parent_id:
            graph.unlink(priority_id, old_parent)

    # Link to new parent (if not root)
    if new_parent_id and new_parent_id not in current_parents:
        try:
            graph.link(priority_id, new_parent_id)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    # Handle reordering - update rank based on position in siblings
    # For root priorities, rank determines importance
    # For children, we'll use rank for ordering within the parent
    if sibling_ids and priority_id in sibling_ids:
        new_rank = sibling_ids.index(priority_id) + 1
        priority.rank = new_rank
        graph.save_priority(priority)

        # Update ranks for all siblings to maintain order
        for i, sibling_id in enumerate(sibling_ids):
            if sibling_id != priority_id:
                sibling = graph.get(sibling_id)
                if sibling:
                    sibling.rank = i + 1
                    graph.save_priority(sibling)

    return {"success": True, "priority_id": priority_id}


# -----------------------------------------------------------------------------
# Sharing Endpoints
# -----------------------------------------------------------------------------

class ShareRequest(BaseModel):
    user_id: int
    permission: str = "contributor"  # viewer, contributor, editor


@router.post("/{priority_id}/share")
async def share_priority(
    priority_id: str,
    request_data: ShareRequest,
    user: User | None = Depends(get_current_user_optional),
):
    """
    Share a priority with another user.

    Only the owner can share a priority.
    permission: viewer (see only), contributor (add tasks), editor (full edit)
    """
    if not user:
        return JSONResponse({"error": "Authentication required"}, status_code=401)

    entity_id = user.entity_id
    graph = _get_graph(entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    # Check ownership (entity-based)
    permission = graph.get_permission(priority_id, entity_id)
    if permission != "owner":
        return JSONResponse({"error": "Only the owner can share this priority"}, status_code=403)

    # Validate permission level
    if request_data.permission not in ("viewer", "contributor", "editor"):
        return JSONResponse({"error": "Invalid permission level"}, status_code=400)

    # Can't share with yourself
    if request_data.user_id == user.id:
        return JSONResponse({"error": "Cannot share with yourself"}, status_code=400)

    # Share via user's personal entity
    graph.share_with_user(priority_id, request_data.user_id, request_data.permission)

    # Clear the target user's graph cache so they see the shared priority
    from praxis_core.web_api.app import clear_graph_cache
    from praxis_core.persistence import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT entity_id FROM users WHERE id = ?", (request_data.user_id,)
        ).fetchone()
        if row and row["entity_id"]:
            clear_graph_cache(row["entity_id"])

    return {
        "success": True,
        "priority_id": priority_id,
        "shared_with": request_data.user_id,
        "permission": request_data.permission,
    }


@router.delete("/{priority_id}/share/{target_user_id}")
async def unshare_priority(
    priority_id: str,
    target_user_id: int,
    user: User | None = Depends(get_current_user_optional),
):
    """Remove sharing for a priority with a user."""
    if not user:
        return JSONResponse({"error": "Authentication required"}, status_code=401)

    entity_id = user.entity_id
    graph = _get_graph(entity_id)

    # Check ownership (entity-based)
    permission = graph.get_permission(priority_id, entity_id)
    if permission != "owner":
        return JSONResponse({"error": "Only the owner can unshare this priority"}, status_code=403)

    # Unshare via user's personal entity
    removed = graph.unshare_user(priority_id, target_user_id)

    return {
        "success": removed,
        "priority_id": priority_id,
        "removed_user_id": target_user_id,
    }


@router.get("/{priority_id}/shares")
async def get_priority_shares(
    priority_id: str,
    user: User | None = Depends(get_current_user_optional),
):
    """Get list of users a priority is shared with."""
    if not user:
        return JSONResponse({"error": "Authentication required"}, status_code=401)

    entity_id = user.entity_id
    graph = _get_graph(entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    # Only owner can view shares (entity-based)
    permission = graph.get_permission(priority_id, entity_id)
    if permission != "owner":
        return JSONResponse({"error": "Only the owner can view shares"}, status_code=403)

    shares = graph.get_shares(priority_id)

    return {
        "priority_id": priority_id,
        "shares": shares,
    }
