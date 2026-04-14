"""
Rules routes: list, create from template, edit, toggle, delete, import/export.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from praxis_web.rendering import (
    templates,
    api_client,
    is_htmx_request,
    render_full_page,
    _prepare_rule_for_ui,
)

router = APIRouter()


# -----------------------------------------------------------------------------
# Rule Templates
# -----------------------------------------------------------------------------

RULE_TEMPLATES = [
    {
        "id": "morning_boost",
        "name": "Morning Boost",
        "icon": "🌅",
        "description": "Increase aptness for tasks during morning hours when focus is high.",
        "conditions": [{"type": "time_window", "params": {"start": "06:00", "end": "12:00"}}],
        "effects": [{"target": "aptness", "operator": "multiply", "value": 1.5}],
    },
    {
        "id": "evening_wind_down",
        "name": "Evening Wind-down",
        "icon": "🌙",
        "description": "Reduce aptness in the evening to favor lighter tasks.",
        "conditions": [{"type": "time_window", "params": {"start": "20:00", "end": "23:59"}}],
        "effects": [{"target": "aptness", "operator": "multiply", "value": 0.5}],
    },
    {
        "id": "weekend_rest",
        "name": "Weekend Rest",
        "icon": "🛋️",
        "description": "Lower task urgency on weekends to encourage rest.",
        "conditions": [{"type": "day_of_week", "params": {"days": ["saturday", "sunday"]}}],
        "effects": [{"target": "aptness", "operator": "multiply", "value": 0.3}],
    },
    {
        "id": "deadline_crunch",
        "name": "Deadline Crunch",
        "icon": "⏰",
        "description": "Boost urgency when a task's due date is approaching.",
        "conditions": [{"type": "due_date_proximity", "params": {"due_type": "within_hours", "hours": 24}}],
        "effects": [{"target": "urgency", "operator": "add", "value": 5}],
    },
    {
        "id": "overdue_penalty",
        "name": "Overdue Penalty",
        "icon": "🚨",
        "description": "Significantly boost urgency for overdue tasks.",
        "conditions": [{"type": "due_date_proximity", "params": {"due_type": "overdue"}}],
        "effects": [{"target": "urgency", "operator": "set", "value": 10}],
    },
    {
        "id": "stale_nudge",
        "name": "Stale Task Nudge",
        "icon": "🧹",
        "description": "Increase urgency for tasks untouched for several days.",
        "conditions": [{"type": "staleness", "params": {"days": 7}}],
        "effects": [{"target": "urgency", "operator": "add", "value": 3}],
    },
    {
        "id": "deep_work",
        "name": "Deep Work Focus",
        "icon": "🎯",
        "description": "Boost aptness for tasks tagged with 'deep-work'.",
        "conditions": [{"type": "tag_match", "params": {"tag": "deep-work"}}],
        "effects": [{"target": "aptness", "operator": "multiply", "value": 2.0}],
    },
    {
        "id": "custom",
        "name": "Custom Rule",
        "icon": "✨",
        "description": "Start from scratch with a blank rule.",
        "conditions": [],
        "effects": [],
    },
]


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@router.get("/rules", response_class=HTMLResponse)
async def rules_page(request: Request):
    """Rules view - full page or HTMX partial."""
    if is_htmx_request(request):
        return await rules_list_partial(request)

    async with api_client(request) as client:
        response = await client.get("/api/rules")
        data = response.json() if response.status_code == 200 else {}
        rules = data.get("rules", [])

    list_html = templates.get_template("partials/rules_list.html").render(rules=rules)
    return await render_full_page(request, mode="rules", initial_list_html=list_html)


@router.get("/rules/list", response_class=HTMLResponse)
async def rules_list_partial(request: Request):
    """HTMX partial: list of rules."""
    async with api_client(request) as client:
        response = await client.get("/api/rules")
        data = response.json() if response.status_code == 200 else {}
        rules = data.get("rules", [])

    return templates.TemplateResponse(
        request,
        "partials/rules_list.html",
        {"rules": rules}
    )


# Specific routes MUST come before /{rule_id} catch-all
@router.get("/rules/new", response_class=HTMLResponse)
async def new_rule_wizard(request: Request):
    """Show rule template wizard."""
    return templates.TemplateResponse(
        request,
        "partials/rule_new_wizard.html",
        {"templates": RULE_TEMPLATES}
    )


@router.post("/rules/new/from-template", response_class=HTMLResponse)
async def new_rule_from_template(request: Request):
    """Create a new rule from a template and open the editor."""
    form_data = await request.form()
    template_id = form_data.get("template_id", "custom")

    # Find the template
    template = next((t for t in RULE_TEMPLATES if t["id"] == template_id), RULE_TEMPLATES[-1])

    # Create the rule via API
    async with api_client(request) as client:
        response = await client.post("/api/rules", json={
            "name": template["name"] if template_id != "custom" else "New Rule",
            "description": template["description"] if template_id != "custom" else "",
            "conditions": template["conditions"],
            "effects": template["effects"],
        })

        if response.status_code != 200:
            return HTMLResponse("<div class='error'>Failed to create rule</div>", status_code=400)

        data = response.json()
        rule = data.get("rule")

        # Get YAML representation for the editor
        yaml_response = await client.get(f"/api/rules/export/{rule['id']}")
        rule_yaml = yaml_response.text if yaml_response.status_code == 200 else ""

    # Return the edit form for the new rule
    html_response = templates.TemplateResponse(
        request,
        "partials/rule_edit.html",
        {"rule": rule, "rule_yaml": rule_yaml}
    )
    html_response.headers["HX-Trigger"] = "ruleCreated"
    return html_response


@router.get("/rules/export")
async def export_rules_web(request: Request):
    """Export all rules as YAML file."""
    async with api_client(request) as client:
        response = await client.get("/api/rules/export")
        if response.status_code != 200:
            return HTMLResponse("<div class='error'>Failed to export rules</div>")

        return Response(
            content=response.content,
            media_type="text/yaml",
            headers={"Content-Disposition": "attachment; filename=praxis-rules.yml"}
        )


@router.post("/rules/restore-defaults", response_class=HTMLResponse)
async def restore_defaults_web(request: Request):
    """Restore user's rules to defaults and return updated list."""
    async with api_client(request) as client:
        response = await client.post("/api/rules/restore-defaults")
        if response.status_code != 200:
            return HTMLResponse("<div class='error'>Failed to restore defaults</div>")
        data = response.json()
        rules = data.get("rules", [])

    return templates.TemplateResponse(
        request,
        "partials/rules_list.html",
        {"rules": rules}
    )


@router.post("/rules/import/preview")
async def import_preview_web(request: Request):
    """Preview rules from YAML content."""
    body = await request.body()
    async with api_client(request) as client:
        response = await client.post(
            "/api/rules/import/preview",
            content=body.decode('utf-8'),
            headers={"Content-Type": "text/plain"}
        )
        return Response(
            content=response.content,
            media_type="application/json",
            status_code=response.status_code
        )


@router.post("/rules/import")
async def import_rules_web(request: Request):
    """Import selected rules from YAML."""
    data = await request.json()
    async with api_client(request) as client:
        response = await client.post("/api/rules/import", json=data)
        return Response(
            content=response.content,
            media_type="application/json",
            status_code=response.status_code
        )


# Catch-all routes MUST come after specific routes
@router.get("/rules/{rule_id}", response_class=HTMLResponse)
async def rule_detail(request: Request, rule_id: str):
    """Rule detail - full page or HTMX partial."""
    async with api_client(request) as client:
        response = await client.get(f"/api/rules/{rule_id}")
        if response.status_code != 200:
            return HTMLResponse("<div class='error'>Rule not found</div>", status_code=404)
        data = response.json()
        rule = _prepare_rule_for_ui(data.get("rule"))

    # HTMX request - return partial
    if is_htmx_request(request):
        return templates.TemplateResponse(
            request,
            "partials/rule_view.html",
            {"rule": rule}
        )

    # Full page request - render with rule detail pre-loaded
    detail_html = templates.get_template("partials/rule_view.html").render(
        request=request, rule=rule
    )

    # Get rules list for left pane
    async with api_client(request) as client:
        list_response = await client.get("/api/rules")
        list_data = list_response.json() if list_response.status_code == 200 else {}
        rules = list_data.get("rules", [])

    list_html = templates.get_template("partials/rules_list.html").render(rules=rules)

    return await render_full_page(
        request,
        mode="rules",
        initial_list_html=list_html,
        initial_detail_html=detail_html
    )


@router.get("/rules/{rule_id}/edit", response_class=HTMLResponse)
async def rule_edit(request: Request, rule_id: str):
    """HTMX partial: rule edit mode with block editor."""
    async with api_client(request) as client:
        response = await client.get(f"/api/rules/{rule_id}")
        if response.status_code != 200:
            return HTMLResponse("<div class='error'>Rule not found</div>", status_code=404)
        data = response.json()
        rule = data.get("rule")

        # Get YAML representation for toggle view
        yaml_response = await client.get(f"/api/rules/export/{rule_id}")
        rule_yaml = yaml_response.text if yaml_response.status_code == 200 else ""

    _prepare_rule_for_ui(rule)

    return templates.TemplateResponse(
        request,
        "partials/rule_edit.html",
        {"rule": rule, "rule_yaml": rule_yaml}
    )


@router.post("/rules/{rule_id}", response_class=HTMLResponse)
async def rule_save(request: Request, rule_id: str):
    """Save rule edits and return view mode."""
    form_data = await request.form()

    # Check if we're in YAML mode
    yaml_content = form_data.get("yaml_content")

    if yaml_content:
        # YAML mode: parse and update via API
        async with api_client(request) as client:
            response = await client.put(
                f"/api/rules/{rule_id}/yaml",
                content=yaml_content,
                headers={"Content-Type": "text/plain"}
            )
            if response.status_code != 200:
                error = response.json().get("error", "Failed to save rule")
                return HTMLResponse(f"<div class='error'>{error}</div>", status_code=400)
            data = response.json()
            rule = data.get("rule")
    else:
        # Block mode: build rule data from form
        rule_data = {
            "name": form_data.get("name", ""),
            "description": form_data.get("description", ""),
            "priority": int(form_data.get("priority", 0)),
            "conditions": [],
            "effects": [],
        }

        # Parse conditions from form (conditions[0][type], conditions[0][start], etc.)
        condition_indices = set()
        for key in form_data.keys():
            if key.startswith("conditions["):
                idx = key.split("[")[1].split("]")[0]
                condition_indices.add(int(idx))

        for idx in sorted(condition_indices):
            cond_type = form_data.get(f"conditions[{idx}][type]")
            if not cond_type:
                continue

            condition = {"type": cond_type, "params": {}}

            if cond_type == "time_window":
                condition["params"]["start"] = form_data.get(f"conditions[{idx}][start]", "08:00")
                condition["params"]["end"] = form_data.get(f"conditions[{idx}][end]", "17:00")
            elif cond_type == "day_of_week":
                days = form_data.getlist(f"conditions[{idx}][days][]")
                condition["params"]["days"] = days
            elif cond_type in ("tag_match", "tag_missing"):
                condition["params"]["tag"] = form_data.get(f"conditions[{idx}][tag]", "")
                if cond_type == "tag_missing":
                    condition["type"] = "tag_match"
                    condition["params"]["operator"] = "missing"
                else:
                    condition["params"]["operator"] = "has"
            elif cond_type == "due_date_proximity":
                condition["params"]["due_type"] = form_data.get(f"conditions[{idx}][due_type]", "has_due_date")
                hours = form_data.get(f"conditions[{idx}][hours]")
                if hours:
                    condition["params"]["hours"] = int(hours)
            elif cond_type == "staleness":
                days = form_data.get(f"conditions[{idx}][days]")
                if days:
                    condition["params"]["days_untouched"] = int(days)
                condition["params"]["operator"] = "gte"
            elif cond_type == "engagement_recency":
                days = form_data.get(f"conditions[{idx}][days]")
                if days:
                    condition["params"]["days"] = int(days)
                condition["params"]["operator"] = "gte"

            rule_data["conditions"].append(condition)

        # Parse effects from form
        effect_indices = set()
        for key in form_data.keys():
            if key.startswith("effects["):
                idx = key.split("[")[1].split("]")[0]
                effect_indices.add(int(idx))

        for idx in sorted(effect_indices):
            target = form_data.get(f"effects[{idx}][target]")
            operator = form_data.get(f"effects[{idx}][operator]")
            value = form_data.get(f"effects[{idx}][value]", "")

            if target and operator:
                rule_data["effects"].append({
                    "target": target,
                    "operator": operator,
                    "value": value,
                })

        async with api_client(request) as client:
            response = await client.put(f"/api/rules/{rule_id}", json=rule_data)
            if response.status_code != 200:
                error = response.json().get("error", "Failed to save rule")
                return HTMLResponse(f"<div class='error'>{error}</div>", status_code=400)
            data = response.json()
            rule = _prepare_rule_for_ui(data.get("rule"))

    # Return view mode with trigger to refresh list
    html_response = templates.TemplateResponse(
        request,
        "partials/rule_view.html",
        {"rule": rule}
    )
    html_response.headers["HX-Trigger"] = "ruleUpdated"
    return html_response


@router.post("/rules/{rule_id}/toggle", response_class=HTMLResponse)
async def toggle_rule_web(request: Request, rule_id: str):
    """Toggle a rule's enabled state."""
    async with api_client(request) as client:
        response = await client.post(f"/api/rules/{rule_id}/toggle")
        if response.status_code != 200:
            return HTMLResponse("<div class='error'>Failed to toggle rule</div>")
    return HTMLResponse("")


@router.delete("/rules/{rule_id}", response_class=HTMLResponse)
async def delete_rule_web(request: Request, rule_id: str):
    """Delete a rule."""
    async with api_client(request) as client:
        response = await client.delete(f"/api/rules/{rule_id}")
        if response.status_code != 200:
            return HTMLResponse("<div class='error'>Failed to delete rule</div>")
    return HTMLResponse("")
