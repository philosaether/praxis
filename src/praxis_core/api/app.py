"""
FastAPI application for Praxis Core API.

Run with: uvicorn praxis_core.api.app:app --reload
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

from praxis_core.api.priority_endpoints import router as priority_router
from praxis_core.api.task_endpoints import router as task_router
from praxis_core.api.auth_endpoints import router as auth_router
from praxis_core.api.invite_endpoints import router as invite_router
from praxis_core.api.friends_endpoints import router as friends_router
from praxis_core.api.tag_endpoints import router as tag_router
from praxis_core.api.rule_endpoints import router as rule_router
from praxis_core.api.trigger_endpoints import router as trigger_router
from praxis_core.api.sse import get_sse_manager
from praxis_core.triggers import start_scheduler, stop_scheduler


# ---------------------------------------------------------------------
# App Lifespan
# ---------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle app startup and shutdown."""
    # Startup: seed default rules
    ensure_default_rules()

    # Wire up scheduler lifecycle to SSE connections
    # Scheduler starts when first client connects, stops when last disconnects
    sse_manager = get_sse_manager()
    sse_manager.set_lifecycle_callbacks(
        on_first_connect=start_scheduler,
        on_last_disconnect=stop_scheduler,
    )

    yield

    # Shutdown: ensure scheduler is stopped
    stop_scheduler()


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
app.include_router(tag_router, prefix="/api/tags", tags=["tags"])
app.include_router(rule_router, prefix="/api/rules", tags=["rules"])
app.include_router(trigger_router, prefix="/api/triggers", tags=["triggers"])


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
) -> dict:
    """Convert a Priority to JSON-serializable dict.

    Args:
        p: Priority object
        render_markdown: Whether to render notes as markdown
        current_entity_id: Current user's entity_id for ownership check
        shares: List of share dicts from graph.get_shares() for share indicators
    """
    notes = p.notes
    if render_markdown and notes:
        notes = render_md(notes)

    data = {
        "id": p.id,
        "name": p.name,
        "priority_type": p.priority_type.value,
        "status": p.status.value,
        "substatus": p.substatus,
        "entity_id": p.entity_id,
        "agent_context": p.agent_context,
        "notes": notes,
        "rank": p.rank,
        "auto_assign_owner": p.auto_assign_owner,
        "auto_assign_creator": p.auto_assign_creator,
        "created_at": fmt_datetime(p.created_at),
        "updated_at": fmt_datetime(p.updated_at),
    }

    # Add ownership/sharing info if entity context provided
    if current_entity_id:
        is_owner = p.entity_id == current_entity_id
        data["is_owner"] = is_owner
        data["is_shared_with_me"] = not is_owner

        if shares is not None:
            data["share_count"] = len(shares)
            data["shares"] = shares
        else:
            data["share_count"] = 0
            data["shares"] = []

    # Add type-specific fields
    if isinstance(p, Value):
        data["success_looks_like"] = p.success_looks_like
        data["obsolete_when"] = p.obsolete_when
    elif isinstance(p, Goal):
        data["complete_when"] = p.complete_when
        data["progress"] = p.progress
        data["due_date"] = fmt_date(p.due_date)
    elif isinstance(p, Practice):
        data["rhythm_frequency"] = p.rhythm_frequency
        data["rhythm_constraints"] = p.rhythm_constraints
        data["generation_prompt"] = p.generation_prompt

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
    notes = t.notes
    if render_markdown and notes:
        notes = render_md(notes)

    data = {
        "id": t.id,
        "name": t.name,
        "status": t.status.value,
        "notes": notes,
        "due_date": fmt_date(t.due_date),
        "created_at": fmt_datetime(t.created_at),
        "priority_id": t.priority_id,
        "priority_name": t.priority_name,
        "priority_type": t.priority_type,
        "entity_id": t.entity_id,
        "assigned_to": t.assigned_to,
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

    # Add permission flags if user context provided
    if current_user is not None:
        from praxis_core.api.task_endpoints import (
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
