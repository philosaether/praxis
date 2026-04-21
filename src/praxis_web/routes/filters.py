"""Filter option routes — dynamic dropdown refresh for HTMX."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from praxis_web.rendering import templates, SESSION_COOKIE_NAME
from praxis_core.persistence import validate_session
from praxis_core.persistence.tag_persistence import get_tags_by_entity
from praxis_core.serialization import get_graph, serialize_priority

router = APIRouter()


def _get_user(request):
    """Get authenticated user from session cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    result = validate_session(token)
    if result is None:
        return None
    session, user = result
    return user


def _serialize_tag(tag) -> dict:
    """Serialize a Tag for API response."""
    return {
        "id": tag.id,
        "name": tag.name,
        "color": tag.color,
        "created_at": tag.created_at.isoformat() if tag.created_at else None,
    }


@router.get("/filters/priorities", response_class=HTMLResponse)
async def filter_priority_options(request: Request, selected: str | None = None):
    """Return priority filter options for dropdown refresh."""
    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = get_graph(entity_id=entity_id)

    from praxis_core.model import PriorityStatus, PriorityType
    priorities = sorted(graph.nodes.values(), key=lambda p: (p.priority_type.value, p.name))
    serialized = [serialize_priority(p, current_entity_id=entity_id) for p in priorities]

    return templates.TemplateResponse(
        request,
        "partials/components/filter_priority_options.html",
        {"priorities": serialized, "selected": selected}
    )


@router.get("/filters/tags", response_class=HTMLResponse)
async def filter_tag_options(request: Request, selected: str | None = None):
    """Return tag filter options for dropdown refresh."""
    user = _get_user(request)
    entity_id = user.entity_id if user else None
    tags = get_tags_by_entity(entity_id) if entity_id else []

    return templates.TemplateResponse(
        request,
        "partials/components/filter_tag_options.html",
        {"user_tags": [_serialize_tag(t) for t in tags], "selected": selected}
    )
