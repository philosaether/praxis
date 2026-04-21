"""Shared serialization helpers and graph cache.

Used by web routes, agent API, and any other interface that needs to
convert model objects to dicts or access the priority graph cache.

This module breaks the circular dependency that previously existed
between web_api/app.py and the endpoint modules.
"""

from datetime import datetime

import markdown

from praxis_core.model import Goal, Practice, User
from praxis_core.persistence import get_connection, PriorityGraph


# ---------------------------------------------------------------------
# Per-Entity Graph Cache
# ---------------------------------------------------------------------

_graphs: dict[str | None, PriorityGraph] = {}


def get_graph(entity_id: str | None = None) -> PriorityGraph:
    """Get a PriorityGraph instance for the given entity.

    Args:
        entity_id: Entity ID (ULID), or None for global graph (admin)

    Returns:
        PriorityGraph scoped to the entity (or global if entity_id is None)
    """
    if entity_id not in _graphs:
        _graphs[entity_id] = PriorityGraph(get_connection, entity_id=entity_id)
        _graphs[entity_id].load()
    return _graphs[entity_id]


def clear_graph_cache(entity_id: str | None = None) -> None:
    """Clear cached graph for an entity, or all if entity_id is None."""
    if entity_id is None:
        _graphs.clear()
    elif entity_id in _graphs:
        del _graphs[entity_id]


# ---------------------------------------------------------------------
# Formatting Helpers
# ---------------------------------------------------------------------

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


def render_md(text: str) -> str:
    """Render markdown text to HTML."""
    return markdown.markdown(text, extensions=["fenced_code", "tables"])


# ---------------------------------------------------------------------
# Entity Name Resolution
# ---------------------------------------------------------------------

def resolve_entity_name(entity_id: str, cache: dict | None = None) -> str | None:
    """Resolve an entity_id to a display name. Uses cache if provided."""
    if cache is not None and entity_id in cache:
        return cache[entity_id]

    with get_connection() as conn:
        ent_row = conn.execute(
            "SELECT name, type FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()
        if not ent_row:
            name = None
        elif ent_row["type"] == "personal":
            user_row = conn.execute(
                "SELECT username FROM users WHERE entity_id = ?", (entity_id,)
            ).fetchone()
            name = user_row["username"] if user_row else ent_row["name"]
        else:
            name = ent_row["name"]

    if cache is not None:
        cache[entity_id] = name
    return name


# ---------------------------------------------------------------------
# Task Permission Helpers
# ---------------------------------------------------------------------

def get_task_permission(task, user: User | None, graph=None) -> str | None:
    """
    Determine a user's permission level on a task.

    Returns one of:
      - 'owner': User's entity owns the task
      - 'creator': User created the task
      - 'contributor': User has contributor/editor permission on the priority
      - 'viewer': User has viewer permission on the priority
      - None: No access
    """
    if user is None:
        return None

    if task.entity_id == user.entity_id:
        return "owner"

    if task.created_by == user.id:
        return "creator"

    if task.priority_id and graph:
        priority_perm = graph.get_permission(task.priority_id, user.entity_id)
        if priority_perm in ("contributor", "editor"):
            return "contributor"
        if priority_perm == "viewer":
            return "viewer"
        if priority_perm == "owner":
            return "owner"

    return None


def can_view_task(permission: str | None) -> bool:
    return permission is not None


def can_edit_task(permission: str | None) -> bool:
    return permission in ("owner", "creator")


def can_toggle_task(permission: str | None) -> bool:
    return permission in ("owner", "creator")


def can_delete_task(permission: str | None) -> bool:
    return permission == "owner"


# ---------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------

def serialize_priority(
    p,
    render_markdown: bool = False,
    current_entity_id: str | None = None,
    shares: list[dict] | None = None,
    share_counts: dict[str, int] | None = None,
    include_action_cards: bool = False,
    entity_name_cache: dict | None = None,
) -> dict:
    """Convert a Priority to JSON-serializable dict."""
    description = p.description
    if render_markdown and description:
        description = render_md(description)

    data = {
        "id": p.id,
        "name": p.name,
        "priority_type": p.priority_type.value,
        "status": p.status.value,
        "substatus": p.substatus,
        "entity_id": p.entity_id,
        "agent_context": p.agent_context,
        "notes": description,  # Keep JSON key as 'notes' for frontend compatibility
        "rank": p.rank,
        "assigned_to_entity_id": p.assigned_to_entity_id,
        "created_at": fmt_datetime(p.created_at),
        "updated_at": fmt_datetime(p.updated_at),
    }

    # Resolve assignee name (cached across serialization calls)
    data["assigned_to_name"] = (
        resolve_entity_name(p.assigned_to_entity_id, entity_name_cache)
        if p.assigned_to_entity_id else None
    )

    # Add ownership/sharing info if entity context provided
    if current_entity_id:
        is_owner = p.entity_id == current_entity_id
        data["is_owner"] = is_owner
        data["is_shared_with_me"] = not is_owner

        if not is_owner:
            from praxis_core.persistence.priority_placement_repo import get_placement
            from praxis_core.persistence.priority_sharing import can_adopt
            placement = get_placement(p.id, current_entity_id)
            data["is_adopted"] = placement is not None
            data["can_adopt"] = can_adopt(get_connection, p.id, current_entity_id)
        else:
            data["is_adopted"] = False
            data["can_adopt"] = False

        if shares is not None:
            data["share_count"] = len(shares)
            data["shares"] = shares
        elif share_counts is not None:
            data["share_count"] = share_counts.get(p.id, 0)
            data["shares"] = []
        else:
            data["share_count"] = 0
            data["shares"] = []

    # Add type-specific fields
    if isinstance(p, Goal):
        data["complete_when"] = p.complete_when
        data["progress"] = p.progress
        data["due_date"] = fmt_date(p.due_date)
    elif isinstance(p, Practice):
        data["actions_config"] = p.actions_config
        data["last_triggered_at"] = fmt_date(p.last_triggered_at)
        if include_action_cards:
            if p.actions_config:
                from praxis_web.helpers.action_renderer import actions_to_card_data
                data["action_cards"] = actions_to_card_data(p.actions_config)
            else:
                data["action_cards"] = []

    return data


def serialize_task(
    t,
    render_markdown: bool = False,
    current_user=None,
    graph=None,
) -> dict:
    """Convert a Task to JSON-serializable dict."""
    description = t.description
    if render_markdown and description:
        description = render_md(description)

    data = {
        "id": t.id,
        "name": t.name,
        "status": t.status.value,
        "notes": description,  # Keep JSON key as 'notes' for frontend compatibility
        "due_date": fmt_date(t.due_date),
        "created_at": fmt_datetime(t.created_at),
        "priority_id": t.priority_id,
        "priority_name": t.priority_name,
        "priority_type": t.priority_type,
        "entity_id": t.entity_id,
        "created_by": t.created_by,
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

    # Resolve creator username
    if t.created_by:
        from praxis_core.persistence.user_repo import get_user as _get_user
        creator = _get_user(t.created_by)
        data["created_by_username"] = creator.username if creator else None

    # Outbox fields
    data["is_in_outbox"] = t.is_in_outbox
    if t.moved_to_outbox_at:
        data["moved_to_outbox_at"] = fmt_datetime(t.moved_to_outbox_at)

    # Add permission flags if user context provided
    if current_user is not None:
        permission = get_task_permission(t, current_user, graph)
        data["can_edit"] = can_edit_task(permission)
        data["can_toggle"] = can_toggle_task(permission)
        data["can_delete"] = can_delete_task(permission)
        data["permission"] = permission
    else:
        data["can_edit"] = True
        data["can_toggle"] = True
        data["can_delete"] = True
        data["permission"] = None

    return data
