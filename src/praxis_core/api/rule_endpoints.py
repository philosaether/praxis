"""Rule API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Body
from fastapi.responses import JSONResponse, Response

from praxis_core.model import User
from praxis_core.persistence import list_rules, get_rule, toggle_rule, restore_default_rules, create_rule
from praxis_core.api.auth import get_current_user, get_current_user_optional
from praxis_core.rules import serialize_rules, serialize_rule, parse_rules, DSLParseError


router = APIRouter()


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


@router.get("")
async def list_rules_endpoint(
    user: User | None = Depends(get_current_user_optional),
):
    """List user's rules."""
    entity_id = user.entity_id if user else None
    rules = list_rules(entity_id=entity_id, include_system=False, enabled_only=False)
    return {"rules": [_serialize_rule_json(r) for r in rules]}


# -----------------------------------------------------------------------------
# Export Endpoints (must be before /{rule_id} to avoid route conflicts)
# -----------------------------------------------------------------------------

@router.get("/export")
async def export_rules(
    user: User = Depends(get_current_user),
):
    """Export all user's rules as YAML."""
    rules = list_rules(entity_id=user.entity_id, include_system=False, enabled_only=False)
    yaml_content = serialize_rules(rules)

    return Response(
        content=yaml_content,
        media_type="text/yaml",
        headers={"Content-Disposition": "attachment; filename=praxis-rules.yml"}
    )


@router.get("/export/{rule_id}")
async def export_single_rule(
    rule_id: str,
    user: User = Depends(get_current_user),
):
    """Export a single rule as YAML."""
    rule = get_rule(rule_id)
    if not rule:
        return JSONResponse({"error": "Rule not found"}, status_code=404)

    yaml_content = serialize_rule(rule)
    filename = f"praxis-rule-{rule.name.lower().replace(' ', '-')}.yml"

    return Response(
        content=yaml_content,
        media_type="text/yaml",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# -----------------------------------------------------------------------------
# Import Endpoints
# -----------------------------------------------------------------------------

@router.post("/import/preview")
async def import_preview(
    yaml_content: Annotated[str, Body(media_type="text/plain")],
    user: User = Depends(get_current_user),
):
    """
    Parse YAML and return rules for selection.

    Returns a preview of rules that would be imported, allowing the user
    to select which ones to actually import.
    """
    try:
        rules = parse_rules(yaml_content)
    except DSLParseError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    # Return parsed rules with temporary IDs for selection
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

    return {"rules": preview, "yaml_content": yaml_content}


@router.post("/import")
async def import_rules(
    yaml_content: Annotated[str, Body()],
    selected_indices: Annotated[list[int], Body()],
    user: User = Depends(get_current_user),
):
    """
    Import selected rules from YAML.

    Args:
        yaml_content: The YAML content to parse
        selected_indices: List of rule indices to import (from preview)
    """
    try:
        parsed_rules = parse_rules(yaml_content)
    except DSLParseError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    imported = []
    for i in selected_indices:
        if 0 <= i < len(parsed_rules):
            parsed_rule = parsed_rules[i]
            # Create the rule in the database
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

    return {"imported": imported, "count": len(imported)}


# -----------------------------------------------------------------------------
# Restore Defaults
# -----------------------------------------------------------------------------

@router.post("/restore-defaults")
async def restore_defaults_endpoint(
    user: User = Depends(get_current_user),
):
    """Restore user's rules to defaults."""
    rules = restore_default_rules(user.entity_id)
    return {"rules": [_serialize_rule_json(r) for r in rules]}


# -----------------------------------------------------------------------------
# Single Rule Endpoints
# -----------------------------------------------------------------------------

@router.get("/{rule_id}")
async def get_rule_endpoint(
    rule_id: str,
    user: User | None = Depends(get_current_user_optional),
):
    """Get a single rule."""
    rule = get_rule(rule_id)
    if not rule:
        return JSONResponse({"error": "Rule not found"}, status_code=404)
    return {"rule": _serialize_rule_json(rule)}


@router.post("/{rule_id}/toggle")
async def toggle_rule_endpoint(
    rule_id: str,
    user: User | None = Depends(get_current_user_optional),
):
    """Toggle a rule's enabled state."""
    rule = get_rule(rule_id)
    if not rule:
        return JSONResponse({"error": "Rule not found"}, status_code=404)

    updated = toggle_rule(rule_id)
    return {"rule": _serialize_rule_json(updated)}
