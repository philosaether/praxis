"""Chip partial routes — HTMX endpoints for dynamic chip spawning.

Uses a factory pattern to register the many nearly-identical chip endpoints.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from praxis_web.rendering import templates, SESSION_COOKIE_NAME

router = APIRouter()


# ---------------------------------------------------------------------------
# Factory for simple chip partials
# ---------------------------------------------------------------------------

def _chip_route(router: APIRouter, path: str, template: str, defaults: dict | None = None):
    """Register a chip partial endpoint.

    Each chip route accepts query params that override *defaults*, then renders
    a Jinja template fragment.
    """
    _defaults = dict(defaults or {})

    @router.get(path, response_class=HTMLResponse)
    async def chip_partial(request: Request, **params):
        merged = {**_defaults, **params}
        return templates.TemplateResponse(request, template, merged)

    # Give each function a unique __name__ so FastAPI doesn't complain
    chip_partial.__name__ = f"chip_{path.rsplit('/', 1)[-1]}_partial"
    return chip_partial


# ---------------------------------------------------------------------------
# Simple chip registrations
# ---------------------------------------------------------------------------

_chip_route(router, "/partials/chips/day", "partials/chips/chip_day.html",
            {"name": "days", "value": "", "period": "weeks"})

_chip_route(router, "/partials/chips/number", "partials/chips/chip_number.html",
            {"name": "count", "value": "2"})

_chip_route(router, "/partials/chips/period", "partials/chips/chip_period.html",
            {"name": "period", "value": "weeks"})

_chip_route(router, "/partials/chips/month", "partials/chips/chip_month.html",
            {"name": "month", "value": "", "mode": "year"})

_chip_route(router, "/partials/chips/time", "partials/chips/chip_time.html",
            {"name": "time", "value": ""})

_chip_route(router, "/partials/chips/start", "partials/chips/chip_start.html",
            {"name": "start", "value": "immediately", "period": "weeks"})

_chip_route(router, "/partials/chips/event_subject", "partials/chips/chip_event_subject.html",
            {"name": "event_subject", "value": "goal"})

_chip_route(router, "/partials/chips/collate_target", "partials/chips/chip_collate_target.html",
            {"name": "collate_target", "value": "children"})

_chip_route(router, "/partials/chips/collate_name", "partials/chips/chip_collate_name.html",
            {"name": "collate_name", "value": "", "practice_name": ""})

_chip_route(router, "/partials/chips/priority_picker", "partials/chips/chip_priority_picker.html",
            {"name": "priority", "value": "", "value_path": "",
             "placeholder": "any priority", "variant": "priority"})

_chip_route(router, "/partials/chips/event_ancestor", "partials/chips/chip_event_ancestor.html",
            {"name": "event_ancestor", "value": "", "value_path": ""})

_chip_route(router, "/partials/chips/event_outcome", "partials/chips/chip_event_outcome.html",
            {"name": "event_outcome", "value": "completed"})

_chip_route(router, "/partials/chips/description", "partials/chips/chip_description.html",
            {"name": "description", "value": "", "practice_name": ""})

_chip_route(router, "/partials/chips/tags", "partials/chips/chip_tags.html",
            {"name": "tags", "value": ""})

_chip_route(router, "/partials/chips/due", "partials/chips/chip_due.html",
            {"name": "due", "value": "end_of_day"})

_chip_route(router, "/partials/chips/task_name", "partials/chips/chip_task_name.html",
            {"name": "task_name", "value": ""})


# ---------------------------------------------------------------------------
# Action card partial (more complex — needs DB access for priority tree)
# ---------------------------------------------------------------------------

@router.get("/partials/actions/card", response_class=HTMLResponse)
async def action_card_partial(
    request: Request,
    trigger_type: str = "schedule",
    action_type: str = "create",
    practice_name: str = "",
    editable: str = "true",
    mode: str = "edit",
    idx: int = 99,
):
    """Return a blank action card HTML fragment for client-side insertion."""
    from praxis_core.persistence import get_connection, PriorityGraph, validate_session
    from praxis_web.routes.priority_actions import _build_priority_tree

    action = {
        "trigger_type": trigger_type,
        "action_type": action_type,
    }

    priority_tree = None
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        result = validate_session(session_token)
        if result:
            _, user = result
            graph = PriorityGraph(get_connection, entity_id=user.entity_id)
            graph.load()
            priority_tree = _build_priority_tree(graph)

    return templates.TemplateResponse(
        request,
        "partials/actions/action_card.html",
        {
            "action": action,
            "idx": idx,
            "priority_id": "pending",
            "priority_name": practice_name,
            "editable": editable == "true",
            "mode": mode,
            "priority_tree": priority_tree,
        }
    )


# ---------------------------------------------------------------------------
# Chip demo page
# ---------------------------------------------------------------------------

@router.get("/demo/chips", response_class=HTMLResponse)
async def chip_demo(request: Request):
    """Demo page for chip components."""
    return templates.TemplateResponse(request, "chip_demo.html", {})
