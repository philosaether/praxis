"""
Shared rendering utilities for praxis_web route modules.

Provides the template engine, HTMX detection, session validation,
and the full-page rendering helper that wraps partials in the app shell.
"""

import hashlib
import json
import os
from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pathlib import Path


# Config
SESSION_COOKIE_NAME = "praxis_session"
PRAXIS_ENV = os.getenv("PRAXIS_ENV", "local")  # local, staging, production

# Static asset cache-busting: hash key static files at import time
def _compute_asset_hash():
    """Short hash of compiled CSS/JS for cache-busting query params."""
    static_dir = Path(__file__).parent / "static"
    files = [
        static_dir / "css" / "main.css",
        static_dir / "js" / "dist" / "tutorial.js",
        static_dir / "js" / "dist" / "chips.js",
    ]
    h = hashlib.md5()
    for f in files:
        if f.exists():
            h.update(f.read_bytes())
    return h.hexdigest()[:8]

ASSET_HASH = _compute_asset_hash()

# Templates
TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["praxis_env"] = PRAXIS_ENV
templates.env.globals["asset_v"] = ASSET_HASH
templates.env.filters["tojson"] = lambda v: Markup(json.dumps(v))


def get_user(request: Request):
    """Get authenticated user from session cookie. Returns None if not authenticated."""
    from praxis_core.persistence import validate_session
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    result = validate_session(token)
    if result is None:
        return None
    _session, user = result
    return user


def is_htmx_request(request: Request) -> bool:
    """Check if this is an HTMX request (partial) vs full page load."""
    return request.headers.get("HX-Request") == "true"


def _prepare_rule_for_ui(rule: dict) -> dict:
    """Map API rule conditions to UI-friendly types (e.g., tag_match+missing → tag_missing)."""
    for c in rule.get("conditions", []):
        if c.get("type") == "tag_match" and c.get("params", {}).get("operator") == "missing":
            c["type"] = "tag_missing"
    return rule


async def render_full_page(
    request: Request,
    mode: str = "tasks",
    initial_list_html: str | None = None,
    initial_detail_html: str | None = None,
):
    """Render full home page with specific mode and optional pre-rendered content."""
    from fastapi.responses import RedirectResponse
    from praxis_core.serialization import get_graph, serialize_priority, serialize_task
    from praxis_core.persistence import list_tasks, validate_session
    from praxis_core.persistence.tag_persistence import get_tags_by_entity, get_tags_for_tasks
    from praxis_core.persistence.friend_request_repo import get_notification_counts
    from praxis_core.prioritization import rank_tasks
    from praxis_core.persistence.rule_persistence import list_rules
    from praxis_core.model import PriorityType

    # Check if user is logged in
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return RedirectResponse(url="/login", status_code=302)

    result = validate_session(token)
    if result is None:
        response = RedirectResponse(url="/login", status_code=302)
        response.delete_cookie(key=SESSION_COOKIE_NAME)
        return response
    _session, user = result

    # Load priority graph
    graph = get_graph(entity_id=user.entity_id)

    # Serialize priorities for dropdowns
    priorities = [
        serialize_priority(p, current_entity_id=user.entity_id)
        for p in graph.nodes.values()
    ]
    priority_types = [t.value for t in PriorityType]

    # Fetch user's tags for filter dropdown
    tags = get_tags_by_entity(user.entity_id)
    tags_data = [{"name": t} for t in sorted(tags)] if tags else []

    # Fetch tasks for task modes (needed for default list if no initial_list_html)
    tasks_serialized = []
    if mode in ["tasks", "inbox", "outbox"] and not initial_list_html:
        tasks = list_tasks(
            entity_id=user.entity_id,
            inbox_only=(mode == "inbox"),
            outbox_only=(mode == "outbox"),
        )
        rules = list_rules(entity_id=user.entity_id, enabled_only=True)
        task_ids = [t.id for t in tasks]
        tags_map = get_tags_for_tasks(task_ids) if task_ids else {}
        scored = rank_tasks(tasks, graph, rules, tags_map)
        tasks_serialized = [
            serialize_task(st.task, current_user=user, graph=graph)
            for st in scored
        ]

    # Fetch friend request notification counts for badge
    notif_data = get_notification_counts(user.id)

    # User dict for template (matches what templates expect)
    user_dict = {
        "id": user.id,
        "username": user.username,
        "entity_id": user.entity_id,
        "role": user.role.value if user.role else "user",
        "tutorial_completed": user.tutorial_completed,
    }

    # New user detection: no priorities AND hasn't completed tutorial
    is_new_user = (
        len(priorities) == 0
        and not user.tutorial_completed
    )

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "user": user_dict,
            "tasks": tasks_serialized,
            "priorities": priorities,
            "priority_types": priority_types,
            "user_tags": tags_data,
            "default_mode": mode,
            "outbox_mode": mode == "outbox",
            "initial_list_html": initial_list_html,
            "initial_detail_html": initial_detail_html,
            "notification_count": notif_data.get("total", 0),
            "is_new_user": is_new_user,
        }
    )
