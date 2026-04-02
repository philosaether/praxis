"""Rule persistence: CRUD operations for rules."""

import json
import sqlite3
from datetime import datetime

from ulid import ULID

from praxis_core.model.rules import Rule, RuleCondition, RuleEffect
from praxis_core.persistence.database import get_connection


# -----------------------------------------------------------------------------
# Schema
# -----------------------------------------------------------------------------

RULES_SCHEMA = """
CREATE TABLE IF NOT EXISTS rules (
    id TEXT PRIMARY KEY,
    entity_id TEXT,
    name TEXT NOT NULL,
    description TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 0,
    conditions TEXT NOT NULL,
    effects TEXT NOT NULL,
    is_system INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rules_entity ON rules(entity_id);
CREATE INDEX IF NOT EXISTS idx_rules_enabled ON rules(enabled);
CREATE INDEX IF NOT EXISTS idx_rules_system ON rules(is_system);
"""

_schema_ensured = False


def ensure_schema() -> None:
    """Ensure the rules schema exists."""
    global _schema_ensured
    if _schema_ensured:
        return
    with get_connection() as conn:
        conn.executescript(RULES_SCHEMA)
    _schema_ensured = True


# -----------------------------------------------------------------------------
# Row Conversion
# -----------------------------------------------------------------------------

def _row_to_rule(row: sqlite3.Row) -> Rule:
    """Convert a database row to a Rule."""
    conditions_data = json.loads(row["conditions"])
    effects_data = json.loads(row["effects"])

    return Rule(
        id=row["id"],
        entity_id=row["entity_id"],
        name=row["name"],
        description=row["description"],
        enabled=bool(row["enabled"]),
        priority=row["priority"],
        conditions=[RuleCondition.from_dict(c) for c in conditions_data],
        effects=[RuleEffect.from_dict(e) for e in effects_data],
        is_system=bool(row["is_system"]),
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
        updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
    )


# -----------------------------------------------------------------------------
# CRUD Operations
# -----------------------------------------------------------------------------

def create_rule(
    name: str,
    conditions: list[RuleCondition],
    effects: list[RuleEffect],
    entity_id: str | None = None,
    description: str | None = None,
    enabled: bool = True,
    priority: int = 0,
    is_system: bool = False,
) -> Rule:
    """Create a new rule."""
    ensure_schema()
    rule_id = str(ULID())
    now = datetime.now()

    conditions_json = json.dumps([c.to_dict() for c in conditions])
    effects_json = json.dumps([e.to_dict() for e in effects])

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO rules (id, entity_id, name, description, enabled, priority,
                             conditions, effects, is_system, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (rule_id, entity_id, name, description, int(enabled), priority,
             conditions_json, effects_json, int(is_system),
             now.isoformat(), now.isoformat()),
        )

    return Rule(
        id=rule_id,
        entity_id=entity_id,
        name=name,
        description=description,
        enabled=enabled,
        priority=priority,
        conditions=conditions,
        effects=effects,
        is_system=is_system,
        created_at=now,
        updated_at=now,
    )


def get_rule(rule_id: str) -> Rule | None:
    """Get a rule by ID."""
    ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM rules WHERE id = ?", (rule_id,)
        ).fetchone()
        if row:
            return _row_to_rule(row)
        return None


def list_rules(
    entity_id: str | None = None,
    include_system: bool = True,
    enabled_only: bool = False,
) -> list[Rule]:
    """
    List rules for an entity.

    Args:
        entity_id: Entity ID to filter by. If provided, returns rules owned by
                  this entity plus system rules (if include_system=True).
        include_system: Whether to include system rules (is_system=1).
        enabled_only: Whether to only return enabled rules.

    Returns:
        List of rules, sorted by priority (descending) then name.
    """
    ensure_schema()
    with get_connection() as conn:
        query = "SELECT * FROM rules WHERE 1=1"
        params = []

        if entity_id is not None:
            if include_system:
                query += " AND (entity_id = ? OR is_system = 1)"
                params.append(entity_id)
            else:
                query += " AND entity_id = ?"
                params.append(entity_id)
        elif not include_system:
            query += " AND is_system = 0"

        if enabled_only:
            query += " AND enabled = 1"

        query += " ORDER BY priority DESC, name ASC"

        rows = conn.execute(query, params).fetchall()
        return [_row_to_rule(row) for row in rows]


def update_rule(
    rule_id: str,
    name: str | None = None,
    description: str | None = None,
    conditions: list[RuleCondition] | None = None,
    effects: list[RuleEffect] | None = None,
    enabled: bool | None = None,
    priority: int | None = None,
) -> Rule | None:
    """
    Update a rule. Only provided fields are updated.

    System rules (is_system=1) cannot be modified.
    """
    ensure_schema()
    rule = get_rule(rule_id)
    if not rule:
        return None
    if rule.is_system:
        raise ValueError("Cannot modify system rules")

    updates = []
    params = []

    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if conditions is not None:
        updates.append("conditions = ?")
        params.append(json.dumps([c.to_dict() for c in conditions]))
    if effects is not None:
        updates.append("effects = ?")
        params.append(json.dumps([e.to_dict() for e in effects]))
    if enabled is not None:
        updates.append("enabled = ?")
        params.append(int(enabled))
    if priority is not None:
        updates.append("priority = ?")
        params.append(priority)

    if not updates:
        return rule

    updates.append("updated_at = ?")
    params.append(datetime.now().isoformat())
    params.append(rule_id)

    with get_connection() as conn:
        conn.execute(
            f"UPDATE rules SET {', '.join(updates)} WHERE id = ?",
            params,
        )

    return get_rule(rule_id)


def delete_rule(rule_id: str) -> bool:
    """
    Delete a rule.

    System rules (is_system=1) cannot be deleted.
    """
    ensure_schema()
    rule = get_rule(rule_id)
    if not rule:
        return False
    if rule.is_system:
        raise ValueError("Cannot delete system rules")

    with get_connection() as conn:
        conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    return True


def toggle_rule(rule_id: str) -> Rule | None:
    """Toggle a rule's enabled state."""
    rule = get_rule(rule_id)
    if not rule:
        return None

    return update_rule(rule_id, enabled=not rule.enabled)


# -----------------------------------------------------------------------------
# System Rules Management
# -----------------------------------------------------------------------------

def create_system_rule(
    rule_id: str,
    name: str,
    conditions: list[RuleCondition],
    effects: list[RuleEffect],
    description: str | None = None,
    priority: int = 0,
) -> Rule:
    """
    Create or update a system rule with a fixed ID.

    System rules are global (entity_id=None) and cannot be deleted by users.
    This is idempotent - if the rule exists, it will be updated.
    """
    ensure_schema()
    now = datetime.now()

    conditions_json = json.dumps([c.to_dict() for c in conditions])
    effects_json = json.dumps([e.to_dict() for e in effects])

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO rules (id, entity_id, name, description, enabled, priority,
                             conditions, effects, is_system, created_at, updated_at)
            VALUES (?, NULL, ?, ?, 1, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                priority = excluded.priority,
                conditions = excluded.conditions,
                effects = excluded.effects,
                updated_at = excluded.updated_at
            """,
            (rule_id, name, description, priority,
             conditions_json, effects_json,
             now.isoformat(), now.isoformat()),
        )

    return get_rule(rule_id)


def ensure_default_rules() -> None:
    """
    Ensure all default system rules exist.

    Called on app startup to seed the database with built-in rules.
    """
    from praxis_core.rules.defaults import get_default_rules

    for rule_def in get_default_rules():
        create_system_rule(
            rule_id=rule_def["id"],
            name=rule_def["name"],
            description=rule_def.get("description"),
            conditions=[RuleCondition.from_dict(c) for c in rule_def["conditions"]],
            effects=[RuleEffect.from_dict(e) for e in rule_def["effects"]],
            priority=rule_def.get("priority", 0),
        )
