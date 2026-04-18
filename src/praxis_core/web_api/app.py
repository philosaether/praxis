"""
FastAPI application for Praxis Core API.

Run with: uvicorn praxis_core.web_api.app:app --reload
"""

from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI
import markdown

from praxis_core.model import (
    Value,
    Goal,
    Practice,
)
from praxis_core.persistence import get_connection, PriorityGraph, ensure_default_rules

from praxis_core.web_api.priority_endpoints import router as priority_router
from praxis_core.web_api.task_endpoints import router as task_router
from praxis_core.web_api.auth_endpoints import router as auth_router
from praxis_core.web_api.invite_endpoints import router as invite_router
from praxis_core.web_api.friends_endpoints import router as friends_router
from praxis_core.web_api.friend_request_endpoints import router as friend_request_router
from praxis_core.web_api.tag_endpoints import router as tag_router
from praxis_core.web_api.rule_endpoints import router as rule_router
from praxis_core.web_api.trigger_endpoints import router as trigger_router

# Agent API (JSON-first, operation-focused)
from praxis_core.agent_api.priorities import router as agent_priority_router
from praxis_core.agent_api.tasks import router as agent_task_router
from praxis_core.agent_api.rules import router as agent_rule_router
from praxis_core.agent_api.graph import router as agent_graph_router


# ---------------------------------------------------------------------
# App Lifespan
# ---------------------------------------------------------------------

import logging
_log = logging.getLogger("praxis.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle app startup and shutdown."""
    # Startup: seed default rules
    ensure_default_rules()

    # Auto-migrate
    conn = get_connection()

    # tutorial_completed on users
    user_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "tutorial_completed" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN tutorial_completed INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE users SET tutorial_completed = 1")
        conn.commit()
        _log.warning("Auto-migrated: added tutorial_completed to users")

    # Priority-level assignment
    p_cols = {row[1] for row in conn.execute("PRAGMA table_info(priorities)").fetchall()}
    if "assigned_to_entity_id" not in p_cols:
        conn.execute("ALTER TABLE priorities ADD COLUMN assigned_to_entity_id TEXT REFERENCES entities(id)")
        conn.execute("UPDATE priorities SET assigned_to_entity_id = entity_id WHERE entity_id IS NOT NULL")
        conn.commit()
        _log.warning("Auto-migrated: added assigned_to_entity_id to priorities")
    # Drop legacy columns if present
    for col in ("auto_assign_owner", "auto_assign_creator"):
        if col in p_cols:
            try:
                conn.execute(f"ALTER TABLE priorities DROP COLUMN {col}")
                conn.commit()
                _log.warning("Auto-migrated: dropped %s from priorities", col)
            except Exception:
                pass  # SQLite < 3.35
    # Rename entity type
    conn.execute("UPDATE entities SET type = 'group' WHERE type = 'organization'")
    conn.commit()

    # Diagnostics
    cols = [row[1] for row in conn.execute("PRAGMA table_info(priorities)").fetchall()]
    missing = [c for c in ("description", "last_engaged_at", "agent_context", "assigned_to_entity_id") if c not in cols]
    if missing:
        _log.warning("DB schema missing columns on priorities: %s", missing)
    else:
        _log.warning("DB schema OK")

    all_routes = [r.path for r in app.routes if hasattr(r, 'path')]
    _log.warning("Core API: %d routes registered", len(all_routes))

    yield
    # Shutdown: nothing to clean up currently


# ---------------------------------------------------------------------
# App Setup
# ---------------------------------------------------------------------

app = FastAPI(
    title="Praxis Core API",
    description="Cue-based task management",
    lifespan=lifespan,
)

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(priority_router, prefix="/api/priorities", tags=["priorities"])
app.include_router(task_router, prefix="/api/tasks", tags=["tasks"])
app.include_router(invite_router, prefix="/api/invites", tags=["invites"])
app.include_router(friends_router, prefix="/api/friends", tags=["friends"])
app.include_router(friend_request_router, prefix="/api/friend-requests", tags=["friend-requests"])
app.include_router(tag_router, prefix="/api/tags", tags=["tags"])
app.include_router(rule_router, prefix="/api/rules", tags=["rules"])
app.include_router(trigger_router, prefix="/api", tags=["triggers"])

# Agent API
app.include_router(agent_priority_router, prefix="/agent/priorities", tags=["agent-priorities"])
app.include_router(agent_task_router, prefix="/agent/tasks", tags=["agent-tasks"])
app.include_router(agent_rule_router, prefix="/agent/rules", tags=["agent-rules"])
app.include_router(agent_graph_router, prefix="/agent/graph", tags=["agent-graph"])


@app.post("/api/cache/invalidate")
async def invalidate_cache(entity_id: str | None = None):
    """Invalidate cached graph for an entity (or all if entity_id is None)."""
    clear_graph_cache(entity_id)
    return {"success": True, "entity_id": entity_id}


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
# Serialization Helpers
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
    """Render markdown text to HTML.

    Uses standard CommonMark behavior - blank lines separate paragraphs,
    lists need blank line before them.
    """
    return markdown.markdown(text, extensions=["fenced_code", "tables"])


def serialize_priority(
    p,
    render_markdown: bool = False,
    current_entity_id: str | None = None,
    shares: list[dict] | None = None,
    include_action_cards: bool = False,
) -> dict:
    """Convert a Priority to JSON-serializable dict.

    Args:
        p: Priority object
        render_markdown: Whether to render description as markdown
        current_entity_id: Current user's entity_id for ownership check
        shares: List of share dicts from graph.get_shares() for share indicators
    """
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

    # Resolve assignee name
    if p.assigned_to_entity_id:
        from praxis_core.persistence.database import get_connection as _get_conn_ent
        with _get_conn_ent() as conn:
            ent_row = conn.execute(
                "SELECT name, type FROM entities WHERE id = ?", (p.assigned_to_entity_id,)
            ).fetchone()
            if ent_row:
                # For personal entities, show the username instead
                if ent_row["type"] == "personal":
                    user_row = conn.execute(
                        "SELECT username FROM users WHERE entity_id = ?", (p.assigned_to_entity_id,)
                    ).fetchone()
                    data["assigned_to_name"] = user_row["username"] if user_row else ent_row["name"]
                else:
                    data["assigned_to_name"] = ent_row["name"]
            else:
                data["assigned_to_name"] = None
    else:
        data["assigned_to_name"] = None

    # Add ownership/sharing info if entity context provided
    if current_entity_id:
        is_owner = p.entity_id == current_entity_id
        data["is_owner"] = is_owner
        data["is_shared_with_me"] = not is_owner

        # Check if adopted (placed in own tree) and if adoption is allowed
        if not is_owner:
            from praxis_core.persistence.priority_placement_repo import get_placement
            from praxis_core.persistence.priority_sharing import can_adopt
            from praxis_core.persistence.database import get_connection as _get_conn
            placement = get_placement(p.id, current_entity_id)
            data["is_adopted"] = placement is not None
            data["can_adopt"] = can_adopt(_get_conn, p.id, current_entity_id)
        else:
            data["is_adopted"] = False
            data["can_adopt"] = False

        if shares is not None:
            data["share_count"] = len(shares)
            data["shares"] = shares
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
    # Value and Initiative have no type-specific fields

    return data


def serialize_task(
    t,
    render_markdown: bool = False,
    current_user=None,
    graph=None,
) -> dict:
    """Convert a Task to JSON-serializable dict.

    If current_user and graph are provided, includes permission flags:
    - can_edit: User can edit task properties
    - can_toggle: User can toggle done/undone
    - can_delete: User can delete the task
    """
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
        from praxis_core.web_api.task_endpoints import (
            get_task_permission,
            can_edit_task,
            can_toggle_task,
            can_delete_task,
        )
        permission = get_task_permission(t, current_user, graph)
        data["can_edit"] = can_edit_task(permission)
        data["can_toggle"] = can_toggle_task(permission)
        data["can_delete"] = can_delete_task(permission)
        data["permission"] = permission
    else:
        # Default to full permissions for backwards compatibility
        data["can_edit"] = True
        data["can_toggle"] = True
        data["can_delete"] = True
        data["permission"] = None

    return data
