"""Time-related condition evaluators."""

from datetime import time

from praxis_core.dsl.conditions import EvaluationContext


def _evaluate_time_window(params: dict, ctx: EvaluationContext) -> bool:
    """Check if current time is within a time window."""
    # Handle both "08:00 to 12:00" string format and structured format
    if "value" in params:
        value = params["value"]
        if isinstance(value, str) and " to " in value:
            start_str, end_str = value.split(" to ", 1)
        else:
            return True  # No valid range specified
    else:
        start_str = params.get("start", "00:00")
        end_str = params.get("end", "23:59")

    try:
        start = time.fromisoformat(start_str.strip())
        end = time.fromisoformat(end_str.strip())
    except (ValueError, AttributeError):
        return True  # Invalid format, pass by default

    current = ctx.current_time()

    # Handle overnight windows (e.g., 22:00 to 06:00)
    if start <= end:
        return start <= current <= end
    else:
        return current >= start or current <= end


def _evaluate_day_of_week(params: dict, ctx: EvaluationContext) -> bool:
    """Check if current day matches specified days."""
    days_param = params.get("value") or params.get("days", [])

    if isinstance(days_param, str):
        # Handle "weekdays", "weekends", or comma-separated list
        days_param = days_param.lower()
        if days_param == "weekdays":
            allowed = {"monday", "tuesday", "wednesday", "thursday", "friday"}
        elif days_param == "weekends":
            allowed = {"saturday", "sunday"}
        else:
            allowed = {d.strip().lower() for d in days_param.split(",")}
    elif isinstance(days_param, list):
        allowed = {d.lower() for d in days_param}
    else:
        return True  # No days specified, pass by default

    return ctx.current_day() in allowed
