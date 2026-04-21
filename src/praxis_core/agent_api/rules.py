"""Agent API — Rule operations."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from praxis_core.model import User
from praxis_core.model.rules import (
    Rule,
    RuleCondition,
    RuleEffect,
    ConditionType,
    EffectTarget,
    EffectOperator,
)
from praxis_core.persistence import (
    create_rule,
    get_rule,
    list_rules,
    update_rule,
    delete_rule,
    toggle_rule,
)
from praxis_core.web_api.auth import get_current_user

router = APIRouter()


# -- Request models -----------------------------------------------------------

class CreateRuleRequest(BaseModel):
    name: str
    description: str | None = None
    priority: int = 0
    conditions: list[dict]  # [{"type": "time_window", "params": {"start": "08:00", ...}}]
    effects: list[dict]     # [{"target": "aptness", "operator": "multiply", "value": 2.0}]


class UpdateRuleRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    priority: int | None = None
    conditions: list[dict] | None = None
    effects: list[dict] | None = None
    enabled: bool | None = None


# -- Serialization ------------------------------------------------------------

def _serialize(rule: Rule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "description": rule.description,
        "enabled": rule.enabled,
        "priority": rule.priority,
        "conditions": [c.to_dict() for c in rule.conditions],
        "effects": [e.to_dict() for e in rule.effects],
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


def _parse_conditions(raw: list[dict]) -> list[RuleCondition] | str:
    """Parse conditions, returning error string on failure."""
    conditions = []
    for c in raw:
        try:
            conditions.append(RuleCondition(type=ConditionType(c["type"]), params=c.get("params", {})))
        except (ValueError, KeyError) as e:
            return f"Invalid condition: {e}"
    return conditions


def _parse_effects(raw: list[dict]) -> list[RuleEffect] | str:
    """Parse effects, returning error string on failure."""
    effects = []
    for e in raw:
        try:
            target = EffectTarget(e["target"])
            operator = EffectOperator(e["operator"])
            if operator == EffectOperator.FORMULA:
                effects.append(RuleEffect(target=target, operator=operator, formula=e.get("formula", "")))
            else:
                value = e.get("value", 0)
                effects.append(RuleEffect(target=target, operator=operator, value=float(value)))
        except (ValueError, KeyError) as e:
            return f"Invalid effect: {e}"
    return effects


# -- Endpoints ----------------------------------------------------------------

@router.post("")
async def create_rule_endpoint(body: CreateRuleRequest, user: User = Depends(get_current_user)):
    """Create a rule."""
    from fastapi.responses import JSONResponse

    conditions = _parse_conditions(body.conditions)
    if isinstance(conditions, str):
        return JSONResponse({"error": conditions}, status_code=400)
    effects = _parse_effects(body.effects)
    if isinstance(effects, str):
        return JSONResponse({"error": effects}, status_code=400)

    rule = create_rule(
        name=body.name,
        description=body.description,
        conditions=conditions,
        effects=effects,
        entity_id=user.entity_id,
        priority=body.priority,
    )
    return _serialize(rule)


@router.get("")
async def list_rules_endpoint(
    enabled_only: bool = False,
    user: User = Depends(get_current_user),
):
    """List rules."""
    rules = list_rules(entity_id=user.entity_id, enabled_only=enabled_only)
    return [_serialize(r) for r in rules]


def _check_rule_access(rule: Rule, user: User):
    """Return 403 response if user doesn't own the rule, else None."""
    if rule.entity_id != user.entity_id:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Permission denied"}, status_code=403)
    return None


@router.get("/{rule_id}")
async def get_rule_endpoint(rule_id: str, user: User = Depends(get_current_user)):
    """Get a single rule."""
    rule = get_rule(rule_id)
    if not rule:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Rule not found"}, status_code=404)
    if err := _check_rule_access(rule, user):
        return err
    return _serialize(rule)


@router.put("/{rule_id}")
async def update_rule_endpoint(
    rule_id: str,
    body: UpdateRuleRequest,
    user: User = Depends(get_current_user),
):
    """Update a rule."""
    from fastapi.responses import JSONResponse

    rule = get_rule(rule_id)
    if not rule:
        return JSONResponse({"error": "Rule not found"}, status_code=404)
    if err := _check_rule_access(rule, user):
        return err

    kwargs = {}
    if body.name is not None:
        kwargs["name"] = body.name
    if body.description is not None:
        kwargs["description"] = body.description
    if body.priority is not None:
        kwargs["priority"] = body.priority
    if body.conditions is not None:
        conditions = _parse_conditions(body.conditions)
        if isinstance(conditions, str):
            return JSONResponse({"error": conditions}, status_code=400)
        kwargs["conditions"] = conditions
    if body.effects is not None:
        effects = _parse_effects(body.effects)
        if isinstance(effects, str):
            return JSONResponse({"error": effects}, status_code=400)
        kwargs["effects"] = effects
    if body.enabled is not None:
        kwargs["enabled"] = body.enabled

    updated = update_rule(rule_id, **kwargs)
    return _serialize(updated)


@router.post("/{rule_id}/toggle")
async def toggle_rule_endpoint(rule_id: str, user: User = Depends(get_current_user)):
    """Toggle a rule's enabled state."""
    rule = get_rule(rule_id)
    if not rule:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Rule not found"}, status_code=404)
    if err := _check_rule_access(rule, user):
        return err
    toggled = toggle_rule(rule_id)
    return _serialize(toggled)


@router.delete("/{rule_id}")
async def delete_rule_endpoint(rule_id: str, user: User = Depends(get_current_user)):
    """Delete a rule."""
    rule = get_rule(rule_id)
    if not rule:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Rule not found"}, status_code=404)
    if err := _check_rule_access(rule, user):
        return err
    delete_rule(rule_id)
    return {"deleted": rule_id}
