"""
Schedule matching for DSL v2.

Determines when scheduled triggers should fire based on:
- Named intervals (daily, weekdays, weekly)
- Custom cadence (frequency + anchor date)
- Last fired time
"""

from datetime import datetime, timedelta
import re

from praxis_core.dsl.triggers import Schedule, Cadence


def should_schedule_fire(
    schedule: Schedule,
    now: datetime,
    last_fired: datetime | None,
) -> bool:
    """
    Determine if a schedule should fire.

    Uses "fire at first opportunity" pattern:
    - Fire once past the scheduled time
    - Don't fire again until next interval

    Args:
        schedule: The schedule configuration
        now: Current datetime
        last_fired: When this schedule last fired (None if never)

    Returns:
        True if the schedule should fire now
    """
    # Handle custom cadence
    if isinstance(schedule.interval, Cadence):
        return _should_cadence_fire(schedule.interval, now, last_fired)

    # Handle named intervals
    interval = schedule.interval.lower()

    # Parse scheduled time
    scheduled_time = schedule.at or "00:00"
    if isinstance(scheduled_time, list):
        # For 2x_daily, check if any time has passed
        return any(
            _check_named_interval(interval, now, last_fired, t)
            for t in scheduled_time
        )

    return _check_named_interval(interval, now, last_fired, scheduled_time)


def _check_named_interval(
    interval: str,
    now: datetime,
    last_fired: datetime | None,
    scheduled_time: str,
) -> bool:
    """Check if a named interval should fire."""
    # Parse time
    try:
        hour, minute = map(int, str(scheduled_time).split(":"))
    except (ValueError, AttributeError):
        hour, minute = 0, 0

    scheduled_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # Check day constraints
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

    if interval == "weekdays":
        if weekday >= 5:  # Saturday or Sunday
            return False
    elif interval == "weekly":
        # Would need schedule.day to know which day
        # For now, assume Monday if not specified
        if weekday != 0:
            return False
    elif interval in day_names:
        # Single day shorthand (e.g., "monday")
        if weekday != day_names.index(interval):
            return False
    # "daily" and "2x_daily" have no day constraints

    # Check if we're past the scheduled time
    if now < scheduled_today:
        return False

    # Check if already fired today (or this interval)
    if last_fired:
        if interval in ("daily", "weekdays") or interval in day_names:
            # Once per day
            if last_fired.date() >= now.date():
                return False
        elif interval == "weekly":
            # Once per week
            days_since = (now.date() - last_fired.date()).days
            if days_since < 7:
                return False
        elif interval == "2x_daily":
            # At least 6 hours since last fire
            hours_since = (now - last_fired).total_seconds() / 3600
            if hours_since < 6:
                return False

    return True


def _should_cadence_fire(
    cadence: Cadence,
    now: datetime,
    last_fired: datetime | None,
) -> bool:
    """
    Check if a custom cadence should fire.

    Cadence fires on anchor date and every N days/weeks after.
    """
    # Parse frequency
    freq_match = re.match(r"(\d+)([dw])", cadence.frequency.lower())
    if not freq_match:
        return False

    amount = int(freq_match.group(1))
    unit = freq_match.group(2)

    if unit == "w":
        interval_days = amount * 7
    else:
        interval_days = amount

    # Parse anchor date
    try:
        anchor = datetime.fromisoformat(cadence.beginning)
    except (ValueError, TypeError):
        return False

    # Parse scheduled time
    try:
        hour, minute = map(int, cadence.at.split(":"))
    except (ValueError, AttributeError):
        hour, minute = 0, 0

    # Calculate days since anchor
    days_since_anchor = (now.date() - anchor.date()).days

    # Check if today is on the cadence
    if days_since_anchor < 0:
        # Before anchor date
        return False

    if days_since_anchor % interval_days != 0:
        # Not on the cadence
        return False

    # Check if we're past the scheduled time today
    scheduled_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < scheduled_today:
        return False

    # Check if already fired today
    if last_fired and last_fired.date() >= now.date():
        return False

    return True


def next_fire_time(
    schedule: Schedule,
    now: datetime,
    last_fired: datetime | None = None,
) -> datetime | None:
    """
    Calculate the next time a schedule should fire.

    Useful for displaying "next run" in UI.
    """
    # Handle custom cadence
    if isinstance(schedule.interval, Cadence):
        return _next_cadence_fire(schedule.interval, now)

    # Handle named intervals
    interval = schedule.interval.lower()
    scheduled_time = schedule.at or "00:00"
    if isinstance(scheduled_time, list):
        scheduled_time = scheduled_time[0]

    try:
        hour, minute = map(int, str(scheduled_time).split(":"))
    except (ValueError, AttributeError):
        hour, minute = 0, 0

    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

    # Start from today's scheduled time
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # If already past today's time, start from tomorrow
    if now >= candidate:
        candidate += timedelta(days=1)

    # Find next valid day
    for _ in range(8):  # Max 7 days to find valid day
        weekday = candidate.weekday()

        if interval == "daily":
            return candidate
        elif interval == "weekdays":
            if weekday < 5:
                return candidate
        elif interval == "weekly":
            if weekday == 0:  # Monday
                return candidate
        elif interval in day_names:
            if weekday == day_names.index(interval):
                return candidate

        candidate += timedelta(days=1)

    return None


def _next_cadence_fire(cadence: Cadence, now: datetime) -> datetime | None:
    """Calculate next fire time for custom cadence."""
    freq_match = re.match(r"(\d+)([dw])", cadence.frequency.lower())
    if not freq_match:
        return None

    amount = int(freq_match.group(1))
    unit = freq_match.group(2)
    interval_days = amount * 7 if unit == "w" else amount

    try:
        anchor = datetime.fromisoformat(cadence.beginning)
        hour, minute = map(int, cadence.at.split(":"))
    except (ValueError, TypeError, AttributeError):
        return None

    # Find next occurrence on or after now
    days_since_anchor = (now.date() - anchor.date()).days

    if days_since_anchor < 0:
        # Anchor is in the future
        return anchor.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # Find next multiple of interval_days
    intervals_passed = days_since_anchor // interval_days
    next_interval_day = (intervals_passed + 1) * interval_days

    # Check if today is a fire day and we haven't passed the time
    if days_since_anchor % interval_days == 0:
        today_fire = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now < today_fire:
            return today_fire

    # Return next fire date
    next_date = anchor + timedelta(days=next_interval_day)
    return next_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
