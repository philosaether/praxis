"""Settings routes: account, API keys, outbox.

Direct persistence calls — no httpx proxy.
"""

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Annotated

from praxis_web.rendering import SESSION_COOKIE_NAME, templates, is_htmx_request
from praxis_core.persistence import validate_session


router = APIRouter()


def _get_user(request: Request):
    """Get authenticated user from session cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    result = validate_session(token)
    if result is None:
        return None
    _session, user = result
    return user


# -----------------------------------------------------------------------------
# Category list
# -----------------------------------------------------------------------------

@router.get("/settings/list", response_class=HTMLResponse)
async def settings_list(request: Request):
    """Settings category list for the left pane."""
    user = _get_user(request)
    if not user:
        return HTMLResponse("", status_code=401)

    from praxis_core.persistence.api_key_repo import list_api_keys
    keys = list_api_keys(user.id)

    return templates.TemplateResponse(
        request,
        "partials/settings_list.html",
        {"user": user, "key_count": len(keys)},
    )


# -----------------------------------------------------------------------------
# Account panel
# -----------------------------------------------------------------------------

@router.get("/settings/account", response_class=HTMLResponse)
async def account_panel(request: Request):
    """Account settings panel."""
    user = _get_user(request)
    if not user:
        return HTMLResponse("", status_code=401)

    return templates.TemplateResponse(
        request,
        "partials/settings/account.html",
        {"user": user},
    )


@router.post("/settings/account/password", response_class=HTMLResponse)
async def change_password(
    request: Request,
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
):
    """Change user password."""
    user = _get_user(request)
    if not user:
        return HTMLResponse("", status_code=401)

    # Validate
    if new_password != confirm_password:
        return templates.TemplateResponse(
            request,
            "partials/settings/account.html",
            {"user": user, "error": "New passwords do not match"},
        )

    if len(new_password) < 8:
        return templates.TemplateResponse(
            request,
            "partials/settings/account.html",
            {"user": user, "error": "Password must be at least 8 characters"},
        )

    # Verify current password
    from praxis_core.persistence import authenticate_user
    if authenticate_user(user.username, current_password) is None:
        return templates.TemplateResponse(
            request,
            "partials/settings/account.html",
            {"user": user, "error": "Current password is incorrect"},
        )

    # Update
    from praxis_core.persistence import update_user_password, hash_password
    update_user_password(user.id, hash_password(new_password))

    return templates.TemplateResponse(
        request,
        "partials/settings/account.html",
        {"user": user, "success": "Password changed successfully"},
    )


# -----------------------------------------------------------------------------
# API Keys panel
# -----------------------------------------------------------------------------

@router.get("/settings/api-keys", response_class=HTMLResponse)
async def api_keys_panel(request: Request):
    """API keys management panel."""
    user = _get_user(request)
    if not user:
        return HTMLResponse("", status_code=401)

    from praxis_core.persistence.api_key_repo import list_api_keys
    keys = list_api_keys(user.id)

    return templates.TemplateResponse(
        request,
        "partials/settings/api_keys.html",
        {"user": user, "keys": keys, "new_key": None},
    )


@router.post("/settings/api-keys/create", response_class=HTMLResponse)
async def create_api_key_route(
    request: Request,
    name: Annotated[str, Form()],
):
    """Create a new API key. Returns the panel with the plaintext key shown once."""
    user = _get_user(request)
    if not user:
        return HTMLResponse("", status_code=401)

    name = name.strip()
    if not name:
        name = "Unnamed key"

    from praxis_core.persistence.api_key_repo import create_api_key, list_api_keys
    metadata, plaintext_key = create_api_key(user.id, name)
    keys = list_api_keys(user.id)

    return templates.TemplateResponse(
        request,
        "partials/settings/api_keys.html",
        {"user": user, "keys": keys, "new_key": plaintext_key, "new_key_name": name},
    )


@router.delete("/settings/api-keys/{key_id}", response_class=HTMLResponse)
async def revoke_api_key_route(request: Request, key_id: str):
    """Revoke an API key. Returns updated key list."""
    user = _get_user(request)
    if not user:
        return HTMLResponse("", status_code=401)

    from praxis_core.persistence.api_key_repo import revoke_api_key, list_api_keys
    revoke_api_key(key_id, user.id)
    keys = list_api_keys(user.id)

    return templates.TemplateResponse(
        request,
        "partials/settings/api_keys.html",
        {"user": user, "keys": keys, "new_key": None},
    )


# -----------------------------------------------------------------------------
# Outbox panel
# -----------------------------------------------------------------------------

@router.get("/settings/outbox", response_class=HTMLResponse)
async def outbox_panel(request: Request):
    """Outbox panel — done tasks waiting for purge."""
    user = _get_user(request)
    if not user:
        return HTMLResponse("", status_code=401)

    from praxis_core.persistence import list_tasks
    from praxis_core.serialization import get_graph, serialize_task

    tasks = list_tasks(entity_id=user.entity_id, outbox_only=True)
    graph = get_graph(entity_id=user.entity_id)
    tasks_serialized = [serialize_task(t, current_user=user, graph=graph) for t in tasks]

    return templates.TemplateResponse(
        request,
        "partials/settings/outbox.html",
        {"user": user, "tasks": tasks_serialized},
    )


@router.post("/settings/outbox/{task_id}/restore", response_class=HTMLResponse)
async def restore_from_outbox_route(request: Request, task_id: str):
    """Restore a task from outbox back to queue, re-render outbox panel."""
    user = _get_user(request)
    if not user:
        return HTMLResponse("", status_code=401)

    from praxis_core.persistence import get_task
    from praxis_core.persistence.task_repo import restore_from_outbox

    task = get_task(task_id)
    if not task or task.entity_id != user.entity_id or not task.is_in_outbox:
        return HTMLResponse("", status_code=404)

    restore_from_outbox(task_id)

    # Re-render outbox inline (avoid double _get_user call)
    from praxis_core.persistence import list_tasks
    from praxis_core.serialization import get_graph, serialize_task

    tasks = list_tasks(entity_id=user.entity_id, outbox_only=True)
    graph = get_graph(entity_id=user.entity_id)
    tasks_serialized = [serialize_task(t, current_user=user, graph=graph) for t in tasks]

    return templates.TemplateResponse(
        request,
        "partials/settings/outbox.html",
        {"user": user, "tasks": tasks_serialized},
    )
