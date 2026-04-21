"""
Practice action editor routes: wizard, create, delete, YAML import/export.
"""

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from praxis_web.rendering import (
    templates,
    api_client,
    SESSION_COOKIE_NAME,
)

router = APIRouter()


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _build_priority_tree(graph) -> list[dict]:
    """Build a nested priority tree for the priority picker chip."""
    roots = graph.roots()

    def build_node(priority):
        child_ids = graph.children.get(priority.id, set())
        children = []
        for cid in sorted(child_ids):
            child = graph.nodes.get(cid)
            if child:
                children.append(build_node(child))
        return {"name": priority.name, "id": priority.id, "children": children}

    return [build_node(r) for r in sorted(roots, key=lambda p: p.name)]


def _build_action_preview(wizard_data: dict) -> str:
    """Build human-readable preview sentence for action."""
    parts = []

    # Trigger part
    if wizard_data["trigger_type"] == "schedule":
        sched = wizard_data.get("schedule", {})
        interval = sched.get("interval", "weekdays")

        if interval == "daily":
            parts.append("Every day")
        elif interval == "weekdays":
            parts.append("On weekdays")
        elif interval in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
            days = sched.get("days", [])
            if days and len(days) > 1:
                day_names = [d.capitalize() for d in days]
                parts.append(f"Every {', '.join(day_names[:-1])} and {day_names[-1]}")
            else:
                parts.append(f"Every {interval.capitalize()}")
        elif interval in ["custom_days", "custom_weeks"]:
            val = sched.get("cadence_value", 2)
            unit = sched.get("cadence_unit", "w")
            unit_word = "days" if unit == "d" else "weeks"
            parts.append(f"Every {val} {unit_word}")

        if sched.get("at"):
            parts[-1] += f" at {sched['at']}"
    else:
        # Event trigger
        event = wizard_data.get("event", {})
        entity = event.get("entity", "task")
        lifecycle = event.get("lifecycle", "completed")
        filter_info = event.get("filter", {})
        filter_type = filter_info.get("type", "any")

        parts.append(f"When a {entity} is {lifecycle}")
        if filter_type == "under_practice":
            parts[-1] += " under this Practice"
        elif filter_type == "tagged" and filter_info.get("tag"):
            parts[-1] += f" tagged [{filter_info['tag']}]"

    # Action part
    action_type = wizard_data.get("action_type", "create")
    task_name = wizard_data.get("task_name", "Untitled task")

    if action_type == "collate":
        parts.append(f"batch tasks into '{task_name}'")
    else:
        parts.append(f"create a task called '{task_name}'")

    # Due part
    due = wizard_data.get("task_due")
    if due:
        due_text = {
            "end_of_day": "due at end of day",
            "+1d": "due tomorrow",
            "+2d": "due in 2 days",
            "+3d": "due in 3 days",
            "+7d": "due in 1 week",
            "end_of_week": "due at end of week",
        }.get(due, "")
        if due_text:
            parts[-1] += f", {due_text}"

    return ", ".join(parts) + "."


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@router.get("/priorities/{priority_id}/actions", response_class=HTMLResponse)
async def priority_actions_editor(request: Request, priority_id: str):
    """HTMX partial: Actions editor for a Practice."""
    from praxis_core.persistence import get_connection, PriorityGraph, validate_session
    from praxis_web.helpers.action_renderer import actions_to_card_data, actions_to_yaml

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return HTMLResponse(content="<div class='error'>Authentication required</div>", status_code=401)

    result = validate_session(session_token)
    if not result:
        return HTMLResponse(content="<div class='error'>Invalid session</div>", status_code=401)

    _, user = result

    graph = PriorityGraph(get_connection, entity_id=user.entity_id)
    graph.load()

    priority = graph.get(priority_id)
    if not priority:
        return HTMLResponse(content="<div class='error'>Priority not found</div>", status_code=404)

    action_cards = actions_to_card_data(priority.actions_config)
    actions_yaml = actions_to_yaml(priority.actions_config)
    editable = priority.entity_id == user.entity_id
    priority_tree = _build_priority_tree(graph)

    return templates.TemplateResponse(
        request,
        "partials/actions/actions_editor.html",
        {
            "priority": {"id": priority_id, "name": priority.name, "actions_config": priority.actions_config},
            "action_cards": action_cards,
            "actions_yaml": actions_yaml,
            "editable": editable,
            "priority_name": priority.name,
            "priority_tree": priority_tree,
        }
    )


@router.get("/priorities/{priority_id}/actions/wizard", response_class=HTMLResponse)
async def priority_actions_wizard(
    request: Request,
    priority_id: str,
    replace: str = "",
):
    """HTMX partial: Single-step action creation wizard."""
    from praxis_core.persistence import get_connection, PriorityGraph, validate_session

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return HTMLResponse(content="<div class='error'>Authentication required</div>", status_code=401)

    result = validate_session(session_token)
    if not result:
        return HTMLResponse(content="<div class='error'>Invalid session</div>", status_code=401)

    _, user = result

    graph = PriorityGraph(get_connection, entity_id=user.entity_id)
    graph.load()

    priority = graph.get(priority_id)
    if not priority:
        return HTMLResponse(content="<div class='error'>Priority not found</div>", status_code=404)

    return templates.TemplateResponse(
        request,
        "partials/actions/action_wizard.html",
        {
            "priority_id": priority_id,
            "practice_name": priority.name,
            "replace": replace,
        }
    )


@router.post("/priorities/{priority_id}/actions", response_class=HTMLResponse)
async def priority_actions_create(request: Request, priority_id: str):
    """Create a new action from wizard data."""
    from praxis_core.persistence import get_connection, PriorityGraph, validate_session
    from praxis_core.dsl import PracticeConfig
    from praxis_web.wizards.action_wizard import parse_wizard_form
    from datetime import datetime

    # Authenticate via session cookie
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return HTMLResponse(content="<div class='error'>Authentication required</div>", status_code=401)

    result = validate_session(session_token)
    if not result:
        return HTMLResponse(content="<div class='error'>Invalid session</div>", status_code=401)

    _, user = result

    form = await request.form()
    form_data = dict(form)

    graph = PriorityGraph(get_connection, entity_id=user.entity_id)
    graph.load()

    priority = graph.get(priority_id)
    if not priority:
        return HTMLResponse(content="<div class='error'>Priority not found</div>", status_code=404)

    if priority.entity_id != user.entity_id:
        return HTMLResponse(content="<div class='error'>Permission denied</div>", status_code=403)

    # Parse existing config or create new
    if priority.actions_config:
        try:
            config = PracticeConfig.from_json(priority.actions_config)
        except:
            config = PracticeConfig(name=priority.name)
    else:
        config = PracticeConfig(name=priority.name)

    # Build action from form data and add to config
    action = parse_wizard_form(form_data, existing_config=priority.actions_config)
    config.actions.append(action)
    priority.actions_config = config.to_json()
    priority.updated_at = datetime.now()

    graph.save_priority(priority)

    # Clear the API's graph cache so it reloads from DB
    # Must call the API endpoint since API runs in a separate process
    async with api_client(request) as client:
        await client.post("/api/cache/invalidate", params={"entity_id": user.entity_id})

    # Return updated editor with card data
    from praxis_web.helpers.action_renderer import actions_to_card_data, actions_to_yaml
    action_cards = actions_to_card_data(priority.actions_config)
    actions_yaml = actions_to_yaml(priority.actions_config)

    return templates.TemplateResponse(
        request,
        "partials/actions/actions_editor.html",
        {
            "priority": {"id": priority_id, "name": priority.name, "actions_config": priority.actions_config},
            "action_cards": action_cards,
            "actions_yaml": actions_yaml,
            "editable": True,
            "priority_name": priority.name,
        }
    )


@router.post("/priorities/{priority_id}/actions/create", response_class=HTMLResponse)
async def priority_actions_create_from_wizard(
    request: Request,
    priority_id: str,
    trigger_type: str = "schedule",
    action_type: str = "create",
    replace: str = "",
):
    """Create a new action from the single-step wizard. Adds a blank action
    with the chosen trigger/action type and returns the updated editor."""
    from praxis_core.persistence import get_connection, PriorityGraph, validate_session
    from praxis_core.dsl import PracticeConfig
    from praxis_web.wizards.action_wizard import build_blank_action
    from datetime import datetime

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return HTMLResponse(content="<div class='error'>Authentication required</div>", status_code=401)
    result = validate_session(session_token)
    if not result:
        return HTMLResponse(content="<div class='error'>Invalid session</div>", status_code=401)
    _, user = result

    graph = PriorityGraph(get_connection, entity_id=user.entity_id)
    graph.load()

    priority = graph.get(priority_id)
    if not priority:
        return HTMLResponse(content="<div class='error'>Priority not found</div>", status_code=404)
    if priority.entity_id != user.entity_id:
        return HTMLResponse(content="<div class='error'>Permission denied</div>", status_code=403)

    # Parse existing config or create new
    if priority.actions_config:
        try:
            config = PracticeConfig.from_json(priority.actions_config)
        except Exception:
            config = PracticeConfig(name=priority.name)
    else:
        config = PracticeConfig(name=priority.name)

    action = build_blank_action(trigger_type=trigger_type, action_type=action_type)

    # Replace or append
    if replace and replace.isdigit():
        idx = int(replace)
        if 0 <= idx < len(config.actions):
            config.actions[idx] = action
    else:
        config.actions.append(action)

    priority.actions_config = config.to_json()
    priority.updated_at = datetime.now()
    graph.save_priority(priority)

    async with api_client(request) as client:
        await client.post("/api/cache/invalidate", params={"entity_id": user.entity_id})

    # Return updated editor with card data
    from praxis_web.helpers.action_renderer import actions_to_card_data, actions_to_yaml
    action_cards = actions_to_card_data(priority.actions_config)
    actions_yaml = actions_to_yaml(priority.actions_config)

    return templates.TemplateResponse(
        request,
        "partials/actions/actions_editor.html",
        {
            "priority": {"id": priority_id, "name": priority.name, "actions_config": priority.actions_config},
            "action_cards": action_cards,
            "actions_yaml": actions_yaml,
            "editable": True,
            "priority_name": priority.name,
        }
    )


@router.delete("/priorities/{priority_id}/actions/{action_idx}")
async def priority_actions_delete(request: Request, priority_id: str, action_idx: int):
    """Delete an action by index."""
    from praxis_core.persistence import get_connection, PriorityGraph, validate_session
    from praxis_core.dsl import PracticeConfig
    from datetime import datetime

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return {"success": False, "error": "Authentication required"}
    result = validate_session(session_token)
    if not result:
        return {"success": False, "error": "Invalid session"}
    _, user = result

    graph = PriorityGraph(get_connection, entity_id=user.entity_id)
    graph.load()

    priority = graph.get(priority_id)
    if not priority:
        return {"success": False, "error": "Priority not found"}

    if priority.entity_id != user.entity_id:
        return {"success": False, "error": "Permission denied"}

    if not priority.actions_config:
        return {"success": False, "error": "No actions to delete"}

    try:
        config = PracticeConfig.from_json(priority.actions_config)
        if 0 <= action_idx < len(config.actions):
            config.actions.pop(action_idx)
            priority.actions_config = config.to_json() if config.actions else None
            priority.updated_at = datetime.now()
            graph.save_priority(priority)

            # Clear the API's graph cache so it reloads from DB
            async with api_client(request) as client:
                await client.post("/api/cache/invalidate", params={"entity_id": user.entity_id})

            return {"success": True}
        else:
            return {"success": False, "error": "Invalid action index"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/priorities/{priority_id}/actions/yaml", response_class=HTMLResponse)
async def priority_actions_yaml_get(request: Request, priority_id: str):
    """Get actions as YAML editor HTML."""
    from praxis_core.persistence import get_connection, PriorityGraph, validate_session
    from praxis_web.helpers.action_renderer import actions_to_yaml

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return HTMLResponse("<p class='error'>Authentication required</p>")
    result = validate_session(session_token)
    if not result:
        return HTMLResponse("<p class='error'>Invalid session</p>")
    _, user = result

    graph = PriorityGraph(get_connection, entity_id=user.entity_id)
    graph.load()

    priority = graph.get(priority_id)
    if not priority:
        return HTMLResponse("<p class='error'>Priority not found</p>")
    if priority.entity_id != user.entity_id:
        return HTMLResponse("<p class='error'>Permission denied</p>")

    yaml_content = actions_to_yaml(priority.actions_config)

    # Return HTML with textarea that auto-saves on blur
    html = f'''
    <div class="actions-editor-yaml" id="actions-editor-{priority_id}">
        <textarea name="yaml" rows="12" class="property-input yaml-input"
                  hx-post="/priorities/{priority_id}/actions/yaml"
                  hx-trigger="blur changed"
                  hx-target="#yaml-status-{priority_id}"
                  hx-swap="innerHTML">{yaml_content}</textarea>
        <span id="yaml-status-{priority_id}" class="yaml-status"></span>
    </div>
    '''
    return HTMLResponse(html)


@router.post("/priorities/{priority_id}/actions/to-yaml", response_class=HTMLResponse)
async def priority_actions_to_yaml(request: Request, priority_id: str):
    """Convert current chip form values to YAML editor HTML (no DB save)."""
    from praxis_core.persistence import validate_session
    from praxis_web.helpers.action_renderer import assemble_actions_config, actions_to_yaml

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return HTMLResponse("<p class='error'>Authentication required</p>")
    result = validate_session(session_token)
    if not result:
        return HTMLResponse("<p class='error'>Invalid session</p>")

    form_data = dict(await request.form())
    actions_config = assemble_actions_config(form_data, form_data.get("name", ""))
    yaml_content = actions_to_yaml(actions_config)

    html = f'''
    <div class="actions-editor-yaml" id="actions-editor-{priority_id}">
        <textarea name="yaml" rows="12" class="property-input yaml-input"
                  hx-post="/priorities/{priority_id}/actions/yaml"
                  hx-trigger="blur changed"
                  hx-target="#yaml-status-{priority_id}"
                  hx-swap="innerHTML">{yaml_content}</textarea>
        <span id="yaml-status-{priority_id}" class="yaml-status"></span>
    </div>
    '''
    return HTMLResponse(html)


@router.post("/priorities/{priority_id}/actions/to-chips", response_class=HTMLResponse)
async def priority_actions_to_chips(request: Request, priority_id: str):
    """Convert YAML text to chip editor HTML (no DB save)."""
    from praxis_core.persistence import get_connection, PriorityGraph, validate_session
    from praxis_web.helpers.action_renderer import (
        yaml_to_actions_config, actions_to_card_data, actions_to_yaml,
    )

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return HTMLResponse("<p class='error'>Authentication required</p>")
    result = validate_session(session_token)
    if not result:
        return HTMLResponse("<p class='error'>Invalid session</p>")
    _, user = result

    form_data = dict(await request.form())
    yaml_content = form_data.get("yaml", "")

    try:
        actions_config = yaml_to_actions_config(yaml_content)
    except ValueError:
        # Invalid YAML — fall back to DB state
        graph = PriorityGraph(get_connection, entity_id=user.entity_id)
        graph.load()
        priority = graph.get(priority_id)
        actions_config = priority.actions_config if priority else None

    action_cards = actions_to_card_data(actions_config)
    actions_yaml = actions_to_yaml(actions_config)

    graph = PriorityGraph(get_connection, entity_id=user.entity_id)
    graph.load()
    priority = graph.get(priority_id)
    editable = priority.entity_id == user.entity_id if priority else False

    priority_tree = _build_priority_tree(graph)

    return templates.TemplateResponse(
        request,
        "partials/actions/actions_editor.html",
        {
            "priority": {"id": priority_id, "name": priority.name if priority else "", "actions_config": actions_config},
            "action_cards": action_cards,
            "actions_yaml": actions_yaml,
            "editable": editable,
            "priority_name": priority.name if priority else "",
            "priority_tree": priority_tree,
        }
    )


@router.post("/priorities/{priority_id}/actions/yaml", response_class=HTMLResponse)
async def priority_actions_yaml_save(
    request: Request,
    priority_id: str,
    yaml_content: str = Form(..., alias="yaml"),
):
    """Save actions from YAML text."""
    from praxis_core.persistence import get_connection, PriorityGraph, validate_session
    from praxis_web.helpers.action_renderer import yaml_to_actions_config, actions_to_yaml
    from datetime import datetime

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return HTMLResponse("<p class='error'>Authentication required</p>")
    result = validate_session(session_token)
    if not result:
        return HTMLResponse("<p class='error'>Invalid session</p>")
    _, user = result

    graph = PriorityGraph(get_connection, entity_id=user.entity_id)
    graph.load()

    priority = graph.get(priority_id)
    if not priority:
        return HTMLResponse("<p class='error'>Priority not found</p>")

    if priority.entity_id != user.entity_id:
        return HTMLResponse("<p class='error'>Permission denied</p>")

    try:
        actions_config = yaml_to_actions_config(yaml_content, priority.name)
        priority.actions_config = actions_config
        priority.updated_at = datetime.now()
        graph.save_priority(priority)

        # Clear graph cache so it reloads from DB
        from praxis_core.serialization import clear_graph_cache
        clear_graph_cache(user.entity_id)

        return HTMLResponse('<span class="yaml-status--saved">saved</span>')
    except ValueError as e:
        from html import escape
        return HTMLResponse(f'<span class="yaml-status--error">{escape(str(e))}</span>')


@router.post("/priorities/{priority_id}/actions/validate")
async def priority_actions_yaml_validate(
    request: Request,
    priority_id: str,
    yaml: str = Form(...),
):
    """Validate YAML without saving."""
    from praxis_web.helpers.action_renderer import yaml_to_actions_config
    from praxis_core.dsl import PracticeConfig

    try:
        actions_config = yaml_to_actions_config(yaml, "test")
        config = PracticeConfig.from_json(actions_config)
        return {"valid": True, "action_count": len(config.actions)}
    except ValueError as e:
        return {"valid": False, "error": str(e)}
