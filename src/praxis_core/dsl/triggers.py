"""
Trigger models and matching logic for Rules and Practices.

Triggers define when an automation fires:
- Schedule: time-based (daily, weekdays, custom cadence)
- Event: entity-based (task completion, status change)

Rules without triggers are scoring rules (evaluated during ranking).
Rules with triggers are automation rules (evaluated when trigger fires).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
import re


class ScheduleInterval(StrEnum):
    """Named schedule intervals."""

    DAILY = "daily"
    WEEKDAYS = "weekdays"
    WEEKENDS = "weekends"
    WEEKLY = "weekly"
    TWICE_DAILY = "2x_daily"
    # Day names (monday, tuesday, etc.) are also valid but not in enum


class EventType(StrEnum):
    """Types of events that can trigger automation."""

    TASK_COMPLETION = "task_completion"
    TASK_STATUS_CHANGE = "task_status_change"
    PRIORITY_COMPLETION = "priority_completion"
    PRIORITY_STATUS_CHANGE = "priority_status_change"


DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


# -----------------------------------------------------------------------------
# Schedule Models
# -----------------------------------------------------------------------------


@dataclass
class Cadence:
    """
    Custom cadence for intervals like 'every 14 days'.

    Attributes:
        frequency: Interval string, e.g., "14d", "2w"
        beginning: Anchor date in ISO format, e.g., "2026-04-03"
        at: Time of day, e.g., "08:00"
    """

    frequency: str
    beginning: str
    at: str = "00:00"

    def to_dict(self) -> dict:
        return {
            "frequency": self.frequency,
            "beginning": self.beginning,
            "at": self.at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Cadence":
        beginning = data["beginning"]
        # YAML may parse date as datetime.date object
        if hasattr(beginning, "isoformat"):
            beginning = beginning.isoformat()
        return cls(
            frequency=data["frequency"],
            beginning=str(beginning),
            at=str(data.get("at", "00:00")),
        )


@dataclass
class Schedule:
    """
    Schedule configuration for time-based triggers.

    Attributes:
        interval: Named interval ("daily", "weekdays", "monday") or Cadence
        at: Time of day ("09:00") or list for 2x_daily (["08:00", "14:00"])
        day: For weekly interval, which day ("monday", etc.)
    """

    interval: str | Cadence
    at: str | list[str] | None = None
    day: str | None = None

    def to_dict(self) -> dict:
        result = {}
        if isinstance(self.interval, Cadence):
            result["interval"] = {"cadence": self.interval.to_dict()}
        else:
            result["interval"] = self.interval
        if self.at:
            result["at"] = self.at
        if self.day:
            result["day"] = self.day
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "Schedule":
        interval_data = data.get("interval", "daily")
        if isinstance(interval_data, dict) and "cadence" in interval_data:
            interval = Cadence.from_dict(interval_data["cadence"])
        else:
            interval = interval_data
        return cls(
            interval=interval,
            at=data.get("at"),
            day=data.get("day"),
        )


# -----------------------------------------------------------------------------
# Event Models
# -----------------------------------------------------------------------------


@dataclass
class Event:
    """
    Event configuration for entity-based triggers.

    Attributes:
        event_type: What kind of event triggers this
        to: For status_change events, the target status
        params: Additional filtering params
    """

    event_type: EventType
    to: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        result = {"event": self.event_type.value}
        if self.to:
            result["to"] = self.to
        if self.params:
            result.update(self.params)
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        # Handle shorthand: "task_completion" or full dict
        if isinstance(data, str):
            return cls(event_type=EventType(data))

        event_type_str = data.get("event") or data.get("type")
        return cls(
            event_type=EventType(event_type_str),
            to=data.get("to"),
            params={k: v for k, v in data.items() if k not in ("event", "type", "to")},
        )


# -----------------------------------------------------------------------------
# Unified Trigger
# -----------------------------------------------------------------------------


@dataclass
class Trigger:
    """
    A trigger that causes an automation to fire.

    Either schedule-based or event-based, not both.
    """

    schedule: Schedule | None = None
    event: Event | None = None

    def is_scheduled(self) -> bool:
        return self.schedule is not None

    def is_event_based(self) -> bool:
        return self.event is not None

    def to_dict(self) -> dict:
        if self.schedule:
            return {"schedule": self.schedule.to_dict()}
        if self.event:
            return self.event.to_dict()
        return {}

    @classmethod
    def from_dict(cls, data: dict) -> "Trigger":
        if "schedule" in data:
            return cls(schedule=Schedule.from_dict(data["schedule"]))
        if "event" in data:
            return cls(event=Event.from_dict(data["event"]))
        # Check if schedule data is at top level (without schedule: wrapper)
        if "interval" in data:
            return cls(schedule=Schedule.from_dict(data))
        return cls()


# -----------------------------------------------------------------------------
# Schedule Matching
# -----------------------------------------------------------------------------


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
            _check_named_interval(interval, now, last_fired, t) for t in scheduled_time
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

    if interval == "weekdays":
        if weekday >= 5:  # Saturday or Sunday
            return False
    elif interval == "weekends":
        if weekday < 5:  # Monday through Friday
            return False
    elif interval == "weekly":
        # Use schedule.day if specified, otherwise Monday
        # Note: schedule.day not accessible here, assume Monday
        if weekday != 0:
            return False
    elif interval in DAY_NAMES:
        # Single day shorthand (e.g., "monday")
        if weekday != DAY_NAMES.index(interval):
            return False
    # "daily" and "2x_daily" have no day constraints

    # Check if we're past the scheduled time
    if now < scheduled_today:
        return False

    # Check if already fired today (or this interval)
    if last_fired:
        if interval in ("daily", "weekdays", "weekends") or interval in DAY_NAMES:
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
        elif interval == "weekends":
            if weekday >= 5:
                return candidate
        elif interval == "weekly":
            if weekday == 0:  # Monday
                return candidate
        elif interval in DAY_NAMES:
            if weekday == DAY_NAMES.index(interval):
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


# -----------------------------------------------------------------------------
# Event Matching
# -----------------------------------------------------------------------------


def should_event_fire(
    event: Event,
    event_type: EventType,
    entity: dict,
) -> bool:
    """
    Determine if an event trigger matches an occurred event.

    Args:
        event: The event trigger configuration
        event_type: The type of event that occurred
        entity: The entity involved (task or priority as dict)

    Returns:
        True if the trigger should fire for this event
    """
    # Check event type matches
    if event.event_type != event_type:
        return False

    # For status_change events, check target status
    if event.to is not None:
        entity_status = entity.get("status")
        if entity_status != event.to:
            return False

    # Check any additional params
    for key, value in event.params.items():
        if entity.get(key) != value:
            return False

    return True
