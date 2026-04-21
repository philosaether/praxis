"""
Rules routes: list, create from template, edit, toggle, delete, import/export.

Direct persistence calls — no httpx proxy.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from praxis_web.rendering import (
    templates,
    SESSION_COOKIE_NAME,
    is_htmx_request,
    render_full_page,
    _prepare_rule_for_ui,
)

from praxis_core.persistence import (
    validate_session,
    create_rule,
    get_rule,
    list_rules,
    update_rule,
    delete_rule,
    toggle_rule,
    restore_default_rules,
)
from praxis_core.model.rules import ConditionType, EffectTarget, EffectOperator, RuleCondition, RuleEffect
from praxis_core.rules import serialize_rules, serialize_rule, parse_rules, DSLParseError

router = APIRouter()


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _get_user(request: Request):
    """Get authenticated user from session cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    result = validate_session(token)
    if result is None:
        return None
    session, user = result
    return user


def _serialize_rule_json(rule) -> dict:
    """Convert a Rule to JSON-serializable dict."""
    return {
        "id": rule.id,
        "name": rule.name,
        "description": rule.description,
        "enabled": rule.enabled,
        "priority": rule.priority,
        "conditions": [
            {"type": c.type.value, "params": c.params}
            for c in rule.conditions
        ],
        "effects": [
            {
                "target": e.target.value,
                "operator": e.operator.value,
                "value": e.value,
                "formula": e.formula,
            }
            for e in rule.effects
        ],
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
    }


def _parse_conditions(conditions: list[dict]) -> list[RuleCondition] | str:
    """Parse condition dicts to RuleCondition objects. Returns error string on failure."""
    parsed = []
    for c in conditions:
        try:
            cond_type = ConditionType(c.get("type"))
            parsed.append(RuleCondition(type=cond_type, params=c.get("params", {})))
        except ValueError:
            return f"Invalid condition type: {c.get('type')}"
    return parsed


def _parse_effects(effects: list[dict]) -> list[RuleEffect] | str:
    """Parse effect dicts to RuleEffect objects. Returns error string on failure."""
    parsed = []
    for e in effects:
        try:
            target = EffectTarget(e.get("target"))
            operator = EffectOperator(e.get("operator"))
            value = e.get("value", "")

            if operator == EffectOperator.FORMULA:
                parsed.append(RuleEffect(target=target, operator=operator, formula=str(value)))
            else:
                try:
                    numeric_value = float(value) if value else 0.0
                except (ValueError, TypeError):
                    numeric_value = 0.0
                parsed.append(RuleEffect(target=target, operator=operator, value=numeric_value))
        except ValueError as exc:
            return f"Invalid effect: {str(exc)}"
    return parsed


# -----------------------------------------------------------------------------
# Rule Templates
# -----------------------------------------------------------------------------

RULE_TEMPLATES = [
    {
        "id": "morning_boost",
        "name": "Morning Boost",
        "icon": "light_mode",
        "description": "Increase aptness for tasks during morning hours when focus is high.",
        "conditions": [{"type": "time_window", "params": {"start": "06:00", "end": "12:00"}}],
        "effects": [{"target": "aptness", "operator": "multiply", "value": 1.5}],
    },
    {
        "id": "evening_wind_down",
        "name": "Evening Wind-down",
        "icon": "dark_mode",
        "description": "Reduce aptness in the evening to favor lighter tasks.",
        "conditions": [{"type": "time_window", "params": {"start": "20:00", "end": "23:59"}}],
        "effects": [{"target": "aptness", "operator": "multiply", "value": 0.5}],
    },
    {
        "id": "weekend_rest",
        "name": "Weekend Rest",
        "icon": "weekend",
        "description": "Lower task urgency on weekends to encourage rest.",
        "conditions": [{"type": "day_of_week", "params": {"days": ["saturday", "sunday"]}}],
        "effects": [{"target": "aptness", "operator": "multiply", "value": 0.3}],
    },
    {
        "id": "deadline_crunch",
        "name": "Deadline Crunch",
        "icon": "alarm",
        "description": "Boost urgency when a task's due date is approaching.",
        "conditions": [{"type": "due_date_proximity", "params": {"due_type": "within_hours", "hours": 24}}],
        "effects": [{"target": "urgency", "operator": "add", "value": 5}],
    },
    {
        "id": "overdue_penalty",
        "name": "Overdue Penalty",
        "icon": "warning",
        "description": "Significantly boost urgency for overdue tasks.",
        "conditions": [{"type": "due_date_proximity", "params": {"due_type": "overdue"}}],
        "effects": [{"target": "urgency", "operator": "set", "value": 10}],
    },
    {
        "id": "stale_nudge",
        "name": "Stale Task Nudge",
        "icon": "hourglass_bottom",
        "description": "Increase urgency for tasks untouched for several days.",
        "conditions": [{"type": "staleness", "params": {"days": 7}}],
        "effects": [{"target": "urgency", "operator": "add", "value": 3}],
    },
    {
        "id": "deep_work",
        "name": "Deep Work Focus",
        "icon": "center_focus_strong",
        "description": "Boost aptness for tasks tagged with 'deep-work'.",
        "conditions": [{"type": "tag_match", "params": {"tag": "deep-work"}}],
        "effects": [{"target": "aptness", "operator": "multiply", "value": 2.0}],
    },
    {
        "id": "custom",
        "name": "Custom Rule",
        "icon": "edit_note",
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

    user = _get_user(request)
    entity_id = user.entity_id if user else None
    rules = list_rules(entity_id=entity_id, include_system=False, enabled_only=False)
    rule_dicts = [_serialize_rule_json(r) for r in rules]

    list_html = templates.get_template("partials/rules_list.html").render(rules=rule_dicts)
    return await render_full_page(request, mode="rules", initial_list_html=list_html)


@router.get("/rules/list", response_class=HTMLResponse)
async def rules_list_partial(request: Request):
    """HTMX partial: list of rules."""
    user = _get_user(request)
    entity_id = user.entity_id if user else None
    rules = list_rules(entity_id=entity_id, include_system=False, enabled_only=False)
    rule_dicts = [_serialize_rule_json(r) for r in rules]

    return templates.TemplateResponse(
        request,
        "partials/rules_list.html",
        {"rules": rule_dicts}
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
    user = _get_user(request)
    if not user:
        return HTMLResponse("<div class='error'>Not authenticated</div>", status_code=401)

    form_data = await request.form()
    template_id = form_data.get("template_id", "custom")

    # Find the template
    template = next((t for t in RULE_TEMPLATES if t["id"] == template_id), RULE_TEMPLATES[-1])

    # Parse conditions and effects from the template
    parsed_conditions = _parse_conditions(template["conditions"])
    if isinstance(parsed_conditions, str):
        return HTMLResponse(f"<div class='error'>{parsed_conditions}</div>", status_code=400)

    parsed_effects = _parse_effects(template["effects"])
    if isinstance(parsed_effects, str):
        return HTMLResponse(f"<div class='error'>{parsed_effects}</div>", status_code=400)

    rule = create_rule(
        name=template["name"] if template_id != "custom" else "New Rule",
        description=template["description"] if template_id != "custom" else "",
        conditions=parsed_conditions,
        effects=parsed_effects,
        entity_id=user.entity_id,
    )

    rule_dict = _serialize_rule_json(rule)

    # Get YAML representation for the editor
    rule_yaml = serialize_rule(rule)

    # Return the edit form for the new rule
    html_response = templates.TemplateResponse(
        request,
        "partials/rule_edit.html",
        {"rule": rule_dict, "rule_yaml": rule_yaml}
    )
    html_response.headers["HX-Trigger"] = "ruleCreated"
    return html_response


@router.get("/rules/export")
async def export_rules_web(request: Request):
    """Export all rules as YAML file."""
    user = _get_user(request)
    if not user:
        return HTMLResponse("<div class='error'>Not authenticated</div>", status_code=401)

    rules = list_rules(entity_id=user.entity_id, include_system=False, enabled_only=False)
    yaml_content = serialize_rules(rules)

    return Response(
        content=yaml_content,
        media_type="text/yaml",
        headers={"Content-Disposition": "attachment; filename=praxis-rules.yml"}
    )


@router.post("/rules/restore-defaults", response_class=HTMLResponse)
async def restore_defaults_web(request: Request):
    """Restore user's rules to defaults and return updated list."""
    user = _get_user(request)
    if not user:
        return HTMLResponse("<div class='error'>Not authenticated</div>", status_code=401)

    rules = restore_default_rules(user.entity_id)
    rule_dicts = [_serialize_rule_json(r) for r in rules]

    return templates.TemplateResponse(
        request,
        "partials/rules_list.html",
        {"rules": rule_dicts}
    )


@router.post("/rules/import/preview")
async def import_preview_web(request: Request):
    """Preview rules from YAML content."""
    user = _get_user(request)
    if not user:
        return Response(
            content='{"error": "Not authenticated"}',
            media_type="application/json",
            status_code=401,
        )

    body = await request.body()
    yaml_content = body.decode("utf-8")

    try:
        rules = parse_rules(yaml_content)
    except DSLParseError as e:
        return Response(
            content=f'{{"error": "{str(e)}"}}',
            media_type="application/json",
            status_code=400,
        )

    preview = []
    for i, rule in enumerate(rules):
        preview.append({
            "temp_id": i,
            "name": rule.name,
            "description": rule.description,
            "priority": rule.priority,
            "conditions_count": len(rule.conditions),
            "effects_count": len(rule.effects),
        })

    import json
    return Response(
        content=json.dumps({"rules": preview, "yaml_content": yaml_content}),
        media_type="application/json",
    )


@router.post("/rules/import")
async def import_rules_web(request: Request):
    """Import selected rules from YAML."""
    user = _get_user(request)
    if not user:
        return Response(
            content='{"error": "Not authenticated"}',
            media_type="application/json",
            status_code=401,
        )

    data = await request.json()
    yaml_content = data.get("yaml_content", "")
    selected_indices = data.get("selected_indices", [])

    try:
        parsed_rules = parse_rules(yaml_content)
    except DSLParseError as e:
        return Response(
            content=f'{{"error": "{str(e)}"}}',
            media_type="application/json",
            status_code=400,
        )

    import json
    imported = []
    for i in selected_indices:
        if 0 <= i < len(parsed_rules):
            parsed_rule = parsed_rules[i]
            rule = create_rule(
                name=parsed_rule.name,
                description=parsed_rule.description,
                conditions=parsed_rule.conditions,
                effects=parsed_rule.effects,
                entity_id=user.entity_id,
                enabled=parsed_rule.enabled,
                priority=parsed_rule.priority,
            )
            imported.append(_serialize_rule_json(rule))

    return Response(
        content=json.dumps({"imported": imported, "count": len(imported)}),
        media_type="application/json",
    )


# Catch-all routes MUST come after specific routes
@router.get("/rules/{rule_id}", response_class=HTMLResponse)
async def rule_detail(request: Request, rule_id: str):
    """Rule detail - full page or HTMX partial."""
    rule = get_rule(rule_id)
    if not rule:
        return HTMLResponse("<div class='error'>Rule not found</div>", status_code=404)

    rule_dict = _prepare_rule_for_ui(_serialize_rule_json(rule))

    # HTMX request - return partial
    if is_htmx_request(request):
        return templates.TemplateResponse(
            request,
            "partials/rule_view.html",
            {"rule": rule_dict}
        )

    # Full page request - render with rule detail pre-loaded
    detail_html = templates.get_template("partials/rule_view.html").render(
        request=request, rule=rule_dict
    )

    # Get rules list for left pane
    user = _get_user(request)
    entity_id = user.entity_id if user else None
    rules = list_rules(entity_id=entity_id, include_system=False, enabled_only=False)
    rule_dicts = [_serialize_rule_json(r) for r in rules]

    list_html = templates.get_template("partials/rules_list.html").render(rules=rule_dicts)

    return await render_full_page(
        request,
        mode="rules",
        initial_list_html=list_html,
        initial_detail_html=detail_html
    )


@router.get("/rules/{rule_id}/edit", response_class=HTMLResponse)
async def rule_edit(request: Request, rule_id: str):
    """HTMX partial: rule edit mode with block editor."""
    rule = get_rule(rule_id)
    if not rule:
        return HTMLResponse("<div class='error'>Rule not found</div>", status_code=404)

    rule_dict = _serialize_rule_json(rule)
    _prepare_rule_for_ui(rule_dict)

    # Get YAML representation for toggle view
    rule_yaml = serialize_rule(rule)

    return templates.TemplateResponse(
        request,
        "partials/rule_edit.html",
        {"rule": rule_dict, "rule_yaml": rule_yaml}
    )


@router.post("/rules/{rule_id}", response_class=HTMLResponse)
async def rule_save(request: Request, rule_id: str):
    """Save rule edits and return view mode."""
    user = _get_user(request)
    if not user:
        return HTMLResponse("<div class='error'>Not authenticated</div>", status_code=401)

    form_data = await request.form()

    # Check if we're in YAML mode
    yaml_content = form_data.get("yaml_content")

    if yaml_content:
        # YAML mode: parse and update
        try:
            parsed_rules = parse_rules(yaml_content)
        except DSLParseError as e:
            return HTMLResponse(f"<div class='error'>{e}</div>", status_code=400)

        if not parsed_rules:
            return HTMLResponse("<div class='error'>No rule found in YAML</div>", status_code=400)
        if len(parsed_rules) > 1:
            return HTMLResponse("<div class='error'>Expected exactly one rule in YAML</div>", status_code=400)

        parsed = parsed_rules[0]
        updated = update_rule(
            rule_id=rule_id,
            name=parsed.name,
            description=parsed.description,
            conditions=parsed.conditions,
            effects=parsed.effects,
            priority=parsed.priority,
            enabled=parsed.enabled,
        )
        if not updated:
            return HTMLResponse("<div class='error'>Failed to save rule</div>", status_code=500)

        rule_dict = _prepare_rule_for_ui(_serialize_rule_json(updated))
    else:
        # Block mode: build rule data from form
        rule_data_name = form_data.get("name", "")
        rule_data_description = form_data.get("description", "")
        rule_data_priority = int(form_data.get("priority", 0))
        conditions = []
        effects = []

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

            conditions.append(condition)

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
                effects.append({
                    "target": target,
                    "operator": operator,
                    "value": value,
                })

        parsed_conditions = _parse_conditions(conditions)
        if isinstance(parsed_conditions, str):
            return HTMLResponse(f"<div class='error'>{parsed_conditions}</div>", status_code=400)

        parsed_effects = _parse_effects(effects)
        if isinstance(parsed_effects, str):
            return HTMLResponse(f"<div class='error'>{parsed_effects}</div>", status_code=400)

        updated = update_rule(
            rule_id=rule_id,
            name=rule_data_name,
            description=rule_data_description,
            conditions=parsed_conditions,
            effects=parsed_effects,
            priority=rule_data_priority,
        )
        if not updated:
            return HTMLResponse("<div class='error'>Failed to save rule</div>", status_code=500)

        rule_dict = _prepare_rule_for_ui(_serialize_rule_json(updated))

    # Return view mode with trigger to refresh list
    html_response = templates.TemplateResponse(
        request,
        "partials/rule_view.html",
        {"rule": rule_dict}
    )
    html_response.headers["HX-Trigger"] = "ruleUpdated"
    return html_response


@router.post("/rules/{rule_id}/toggle", response_class=HTMLResponse)
async def toggle_rule_web(request: Request, rule_id: str):
    """Toggle a rule's enabled state."""
    rule = get_rule(rule_id)
    if not rule:
        return HTMLResponse("<div class='error'>Rule not found</div>")

    toggle_rule(rule_id)
    return HTMLResponse("")


@router.delete("/rules/{rule_id}", response_class=HTMLResponse)
async def delete_rule_web(request: Request, rule_id: str):
    """Delete a rule."""
    rule = get_rule(rule_id)
    if not rule:
        return HTMLResponse("<div class='error'>Rule not found</div>")

    success = delete_rule(rule_id)
    if not success:
        return HTMLResponse("<div class='error'>Failed to delete rule</div>")
    return HTMLResponse("")
