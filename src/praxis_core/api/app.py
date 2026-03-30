"""
FastAPI application for Praxis Core API.

Run with: uvicorn praxis_core.api.app:app --reload
"""

from datetime import datetime
from fastapi import FastAPI
import markdown

from praxis_core.model import (
    Value,
    Goal,
    Practice,
)
from praxis_core.persistence import get_connection, PriorityGraph

from praxis_core.api.priority_endpoints import router as priority_router
from praxis_core.api.task_endpoints import router as task_router
from praxis_core.api.auth_endpoints import router as auth_router


# ---------------------------------------------------------------------
# App Setup
# ---------------------------------------------------------------------

app = FastAPI(title="Praxis Core API", description="Cue-based task management")

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(priority_router, prefix="/api/priorities", tags=["priorities"])
app.include_router(task_router, prefix="/api/tasks", tags=["tasks"])


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
    """Render markdown text to HTML."""
    return markdown.markdown(text, extensions=["fenced_code", "tables", "nl2br"])


def serialize_priority(p, render_markdown: bool = False) -> dict:
    """Convert a Priority to JSON-serializable dict."""
    notes = p.notes
    if render_markdown and notes:
        notes = render_md(notes)

    data = {
        "id": p.id,
        "name": p.name,
        "priority_type": p.priority_type.value,
        "status": p.status.value,
        "agent_context": p.agent_context,
        "notes": notes,
        "rank": p.rank,
        "created_at": fmt_datetime(p.created_at),
        "updated_at": fmt_datetime(p.updated_at),
    }

    # Add type-specific fields
    if isinstance(p, Value):
        data["success_looks_like"] = p.success_looks_like
        data["obsolete_when"] = p.obsolete_when
    elif isinstance(p, Goal):
        data["success_criteria"] = p.success_criteria
        data["progress"] = p.progress
        data["due_date"] = fmt_date(p.due_date)
    elif isinstance(p, Practice):
        data["rhythm_frequency"] = p.rhythm_frequency
        data["rhythm_constraints"] = p.rhythm_constraints
        data["generation_prompt"] = p.generation_prompt

    return data


def serialize_task(t, render_markdown: bool = False) -> dict:
    """Convert a Task to JSON-serializable dict."""
    notes = t.notes
    if render_markdown and notes:
        notes = render_md(notes)

    return {
        "id": t.id,
        "name": t.name,
        "status": t.status.value,
        "notes": notes,
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
