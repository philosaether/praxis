"""Capacity condition evaluator."""

from praxis_core.dsl.conditions import EvaluationContext


def _evaluate_capacity(params: dict, ctx: EvaluationContext) -> bool:
    """Check capacity thresholds (post-beta)."""
    capacity_name = params.get("name") or params.get("id", "")
    capacity_value = ctx.capacities.get(capacity_name, 0.0)

    if "less_than" in params:
        if capacity_value >= params["less_than"]:
            return False
    if "at_most" in params:
        if capacity_value > params["at_most"]:
            return False
    if "at_least" in params:
        if capacity_value < params["at_least"]:
            return False
    if "greater_than" in params:
        if capacity_value <= params["greater_than"]:
            return False
    if "equals" in params:
        if capacity_value != params["equals"]:
            return False

    return True
