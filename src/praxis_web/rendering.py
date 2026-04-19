"""
Shared rendering utilities for praxis_web route modules.

Provides the API client factory, template engine, HTMX detection,
and the full-page rendering helper that wraps partials in the app shell.
"""

import json
import os
import httpx
from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pathlib import Path


# Config
API_URL = os.getenv("PRAXIS_API_URL", "http://localhost:8000")
SESSION_COOKIE_NAME = "praxis_session"
PRAXIS_ENV = os.getenv("PRAXIS_ENV", "local")  # local, staging, production

# Templates
TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["praxis_env"] = PRAXIS_ENV
from markupsafe import Markup
templates.env.filters["tojson"] = lambda v: Markup(json.dumps(v))


def api_client(request: Request | None = None):
    """Create an API client, optionally with auth from session cookie."""
    headers = {}
    if request:
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        if session_token:
            headers["Authorization"] = f"Bearer {session_token}"
    return httpx.AsyncClient(base_url=API_URL, timeout=30.0, headers=headers)


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

    # Check if user is logged in
    if not request.cookies.get(SESSION_COOKIE_NAME):
        return RedirectResponse(url="/login", status_code=302)

    async with api_client(request) as client:
        # Fetch user info
        me_response = await client.get("/api/auth/me")
        if me_response.status_code != 200:
            response = RedirectResponse(url="/login", status_code=302)
            response.delete_cookie(key=SESSION_COOKIE_NAME)
            return response
        user = me_response.json()

        # Always fetch priorities for dropdowns
        priorities_response = await client.get("/api/priorities")
        priorities_data = priorities_response.json()

        # Fetch user's tags for filter dropdown
        tags_response = await client.get("/api/tags")
        tags_data = tags_response.json() if tags_response.status_code == 200 else {"tags": []}

        # Fetch tasks for task modes (needed for default list if no initial_list_html)
        tasks_data = {"tasks": []}
        if mode in ["tasks", "inbox", "outbox"] and not initial_list_html:
            if mode == "inbox":
                tasks_response = await client.get("/api/tasks/inbox")
            elif mode == "outbox":
                tasks_response = await client.get("/api/tasks", params={"outbox": "true"})
            else:
                tasks_response = await client.get("/api/tasks")
            tasks_data = tasks_response.json()

        # Fetch friend request notification counts for badge
        notif_response = await client.get("/api/friend-requests/notifications")
        notif_data = notif_response.json() if notif_response.status_code == 200 else {"total": 0}

    # New user detection: no priorities AND hasn't completed tutorial
    is_new_user = (
        len(priorities_data.get("priorities", [])) == 0
        and not user.get("tutorial_completed", False)
    )

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "user": user,
            "tasks": tasks_data.get("tasks", []),
            "priorities": priorities_data["priorities"],
            "priority_types": priorities_data["priority_types"],
            "user_tags": tags_data.get("tags", []),
            "default_mode": mode,
            "outbox_mode": mode == "outbox",
            "initial_list_html": initial_list_html,
            "initial_detail_html": initial_detail_html,
            "notification_count": notif_data.get("total", 0),
            "is_new_user": is_new_user,
        }
    )
