"""Rule API endpoints."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from praxis_core.model import User
from praxis_core.persistence import list_rules, get_rule, toggle_rule
from praxis_core.api.auth import get_current_user_optional


router = APIRouter()


def _serialize_rule(rule) -> dict:
    """Convert a Rule to JSON-serializable dict."""
    return {
        "id": rule.id,
        "name": rule.name,
        "description": rule.description,
        "enabled": rule.enabled,
        "priority": rule.priority,
        "is_system": rule.is_system,
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
    """List all rules (system + user rules)."""
    entity_id = user.entity_id if user else None
    rules = list_rules(entity_id=entity_id, include_system=True, enabled_only=False)
    return {"rules": [_serialize_rule(r) for r in rules]}


@router.get("/{rule_id}")
async def get_rule_endpoint(
    rule_id: str,
    user: User | None = Depends(get_current_user_optional),
):
    """Get a single rule."""
    rule = get_rule(rule_id)
    if not rule:
        return JSONResponse({"error": "Rule not found"}, status_code=404)
    return {"rule": _serialize_rule(rule)}


@router.post("/{rule_id}/toggle")
async def toggle_rule_endpoint(
    rule_id: str,
    user: User | None = Depends(get_current_user_optional),
):
    """Toggle a rule's enabled state."""
    rule = get_rule(rule_id)
    if not rule:
        return JSONResponse({"error": "Rule not found"}, status_code=404)
    if rule.is_system:
        return JSONResponse({"error": "Cannot toggle system rules"}, status_code=403)

    updated = toggle_rule(rule_id)
    return {"rule": _serialize_rule(updated)}
