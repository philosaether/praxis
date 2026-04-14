"""
Due date parsing for action templates.

Handles multiple formats: shorthand strings, structured dicts, relative time expressions.
"""

from datetime import datetime, timedelta
import re


def parse_due_date(due: str | dict | None, now: datetime) -> datetime | None:
    """
    Parse a due date specification.

    Shorthand formats:
        end_of_day      → today 23:59
        end_of_week     → Friday 17:00
        tomorrow        → tomorrow 23:59
        +1d, +7d        → N days from now
        +2h, +30m       → N hours/minutes from now
        next_monday     → next Monday 09:00

    Structured format:
        {day: "today", time: "17:00"}
        {day: "friday", time: "17:00"}
        {day: "+4", time: "12:00"}
    """
    if due is None:
        return None

    # Structured format
    if isinstance(due, dict):
        day_spec = due.get("day", "today")
        time_spec = due.get("time", "23:59")

        try:
            hour, minute = map(int, str(time_spec).split(":"))
        except (ValueError, AttributeError):
            hour, minute = 23, 59

        if day_spec == "today":
            result = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        elif day_spec == "tomorrow":
            result = (now + timedelta(days=1)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
        elif str(day_spec).startswith("+"):
            try:
                days = int(day_spec[1:])
                result = (now + timedelta(days=days)).replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
            except ValueError:
                return None
        else:
            # Day name: friday, monday, etc.
            result = _next_weekday(day_spec, now)
            if result:
                result = result.replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )

        return result

    # Shorthand format
    due = str(due).strip().lower()

    # Relative offsets: +1d, +8h, +30m
    match = re.match(r"\+(\d+)([dhm])", due)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if unit == "d":
            return now + timedelta(days=amount)
        elif unit == "h":
            return now + timedelta(hours=amount)
        elif unit == "m":
            return now + timedelta(minutes=amount)

    # Keywords
    if due == "end_of_day":
        return now.replace(hour=23, minute=59, second=59, microsecond=0)

    if due == "end_of_week":
        days_until_friday = (4 - now.weekday()) % 7
        if days_until_friday == 0 and now.hour >= 17:
            days_until_friday = 7
        friday = now + timedelta(days=days_until_friday)
        return friday.replace(hour=17, minute=0, second=0, microsecond=0)

    if due == "tomorrow":
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=23, minute=59, second=59, microsecond=0)

    # next_monday, next_tuesday, etc.
    match = re.match(r"next_(\w+)", due)
    if match:
        day_name = match.group(1)
        result = _next_weekday(day_name, now)
        if result:
            return result.replace(hour=9, minute=0, second=0, microsecond=0)

    return None


def _next_weekday(day_name: str, now: datetime) -> datetime | None:
    """Get the next occurrence of a weekday."""
    day_map = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    target = day_map.get(day_name.lower())
    if target is None:
        return None

    days_ahead = (target - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7  # Next week
    return now + timedelta(days=days_ahead)
