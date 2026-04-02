"""Trigger persistence: CRUD operations for triggers."""

import json
import sqlite3
from datetime import datetime

from ulid import ULID

from praxis_core.model.rules import RuleCondition
from praxis_core.model.triggers import (
    Trigger,
    TriggerEvent,
    TriggerAction,
)
from praxis_core.persistence.database import get_connection


# -----------------------------------------------------------------------------
# Schema
# -----------------------------------------------------------------------------

TRIGGERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS triggers (
    id TEXT PRIMARY KEY,
    entity_id TEXT,
    practice_id TEXT REFERENCES priorities(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 0,
    event TEXT NOT NULL,
    conditions TEXT NOT NULL,
    actions TEXT NOT NULL,
    last_fired_at TEXT,
    fire_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_triggers_entity ON triggers(entity_id);
CREATE INDEX IF NOT EXISTS idx_triggers_practice ON triggers(practice_id);
CREATE INDEX IF NOT EXISTS idx_triggers_enabled ON triggers(enabled);
"""

_schema_ensured = False


def ensure_schema() -> None:
    """Ensure the triggers schema exists."""
    global _schema_ensured
    if _schema_ensured:
        return
    with get_connection() as conn:
        conn.executescript(TRIGGERS_SCHEMA)
    _schema_ensured = True


# -----------------------------------------------------------------------------
# Row Conversion
# -----------------------------------------------------------------------------

def _row_to_trigger(row: sqlite3.Row) -> Trigger:
    """Convert a database row to a Trigger."""
    event_data = json.loads(row["event"])
    conditions_data = json.loads(row["conditions"])
    actions_data = json.loads(row["actions"])

    return Trigger(
        id=row["id"],
        entity_id=row["entity_id"],
        practice_id=row["practice_id"],
        name=row["name"],
        description=row["description"],
        enabled=bool(row["enabled"]),
        priority=row["priority"],
        event=TriggerEvent.from_dict(event_data),
        conditions=[RuleCondition.from_dict(c) for c in conditions_data],
        actions=[TriggerAction.from_dict(a) for a in actions_data],
        last_fired_at=datetime.fromisoformat(row["last_fired_at"]) if row["last_fired_at"] else None,
        fire_count=row["fire_count"],
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
    )


# -----------------------------------------------------------------------------
# CRUD Operations
# -----------------------------------------------------------------------------

def create_trigger(
    name: str,
    event: TriggerEvent,
    actions: list[TriggerAction],
    entity_id: str | None = None,
    practice_id: str | None = None,
    conditions: list[RuleCondition] | None = None,
    description: str | None = None,
    enabled: bool = True,
    priority: int = 0,
) -> Trigger:
    """Create a new trigger."""
    ensure_schema()
    trigger_id = str(ULID())
    now = datetime.now()

    conditions = conditions or []
    event_json = json.dumps(event.to_dict())
    conditions_json = json.dumps([c.to_dict() for c in conditions])
    actions_json = json.dumps([a.to_dict() for a in actions])

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO triggers (id, entity_id, practice_id, name, description,
                                enabled, priority, event, conditions, actions,
                                fire_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (trigger_id, entity_id, practice_id, name, description,
             int(enabled), priority, event_json, conditions_json, actions_json,
             0, now.isoformat(), now.isoformat()),
        )

    return Trigger(
        id=trigger_id,
        entity_id=entity_id,
        practice_id=practice_id,
        name=name,
        description=description,
        enabled=enabled,
        priority=priority,
        event=event,
        conditions=conditions,
        actions=actions,
        last_fired_at=None,
        fire_count=0,
        created_at=now,
        updated_at=now,
    )


def get_trigger(trigger_id: str) -> Trigger | None:
    """Get a trigger by ID."""
    ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM triggers WHERE id = ?", (trigger_id,)
        ).fetchone()
        if row:
            return _row_to_trigger(row)
        return None


def list_triggers(
    entity_id: str | None = None,
    practice_id: str | None = None,
    enabled_only: bool = False,
) -> list[Trigger]:
    """
    List triggers with optional filters.

    Args:
        entity_id: Filter by owner entity.
        practice_id: Filter by associated practice.
        enabled_only: Only return enabled triggers.

    Returns:
        List of triggers, sorted by priority (descending) then name.
    """
    ensure_schema()
    with get_connection() as conn:
        query = "SELECT * FROM triggers WHERE 1=1"
        params = []

        if entity_id is not None:
            query += " AND entity_id = ?"
            params.append(entity_id)

        if practice_id is not None:
            query += " AND practice_id = ?"
            params.append(practice_id)

        if enabled_only:
            query += " AND enabled = 1"

        query += " ORDER BY priority DESC, name ASC"

        rows = conn.execute(query, params).fetchall()
        return [_row_to_trigger(row) for row in rows]


def list_triggers_by_event_type(
    event_type: str,
    entity_id: str | None = None,
    enabled_only: bool = True,
) -> list[Trigger]:
    """
    List triggers that listen for a specific event type.

    Used by the event dispatcher to find triggers to evaluate.
    """
    ensure_schema()
    with get_connection() as conn:
        query = "SELECT * FROM triggers WHERE json_extract(event, '$.type') = ?"
        params = [event_type]

        if entity_id is not None:
            query += " AND entity_id = ?"
            params.append(entity_id)

        if enabled_only:
            query += " AND enabled = 1"

        query += " ORDER BY priority DESC, name ASC"

        rows = conn.execute(query, params).fetchall()
        return [_row_to_trigger(row) for row in rows]


def update_trigger(
    trigger_id: str,
    name: str | None = None,
    description: str | None = None,
    event: TriggerEvent | None = None,
    conditions: list[RuleCondition] | None = None,
    actions: list[TriggerAction] | None = None,
    enabled: bool | None = None,
    priority: int | None = None,
    practice_id: str | None = None,
) -> Trigger | None:
    """
    Update a trigger. Only provided fields are updated.
    """
    ensure_schema()
    trigger = get_trigger(trigger_id)
    if not trigger:
        return None

    updates = []
    params = []

    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if event is not None:
        updates.append("event = ?")
        params.append(json.dumps(event.to_dict()))
    if conditions is not None:
        updates.append("conditions = ?")
        params.append(json.dumps([c.to_dict() for c in conditions]))
    if actions is not None:
        updates.append("actions = ?")
        params.append(json.dumps([a.to_dict() for a in actions]))
    if enabled is not None:
        updates.append("enabled = ?")
        params.append(int(enabled))
    if priority is not None:
        updates.append("priority = ?")
        params.append(priority)
    if practice_id is not None:
        updates.append("practice_id = ?")
        params.append(practice_id)

    if not updates:
        return trigger

    updates.append("updated_at = ?")
    params.append(datetime.now().isoformat())
    params.append(trigger_id)

    with get_connection() as conn:
        conn.execute(
            f"UPDATE triggers SET {', '.join(updates)} WHERE id = ?",
            params,
        )

    return get_trigger(trigger_id)


def delete_trigger(trigger_id: str) -> bool:
    """Delete a trigger."""
    ensure_schema()
    with get_connection() as conn:
        result = conn.execute("DELETE FROM triggers WHERE id = ?", (trigger_id,))
        return result.rowcount > 0


def toggle_trigger(trigger_id: str) -> Trigger | None:
    """Toggle a trigger's enabled state."""
    trigger = get_trigger(trigger_id)
    if not trigger:
        return None

    return update_trigger(trigger_id, enabled=not trigger.enabled)


def record_trigger_fire(trigger_id: str, fired_at: datetime | None = None) -> Trigger | None:
    """
    Record that a trigger fired.

    Updates last_fired_at and increments fire_count.
    """
    ensure_schema()
    fired_at = fired_at or datetime.now()

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE triggers
            SET last_fired_at = ?, fire_count = fire_count + 1, updated_at = ?
            WHERE id = ?
            """,
            (fired_at.isoformat(), datetime.now().isoformat(), trigger_id),
        )

    return get_trigger(trigger_id)


def delete_triggers_for_practice(practice_id: str) -> int:
    """
    Delete all triggers associated with a practice.

    Called when a practice is deleted (cascade).
    Returns the number of triggers deleted.
    """
    ensure_schema()
    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM triggers WHERE practice_id = ?", (practice_id,)
        )
        return result.rowcount
