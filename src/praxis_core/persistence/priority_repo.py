"""Priority CRUD: schema, row conversion helpers."""

import sqlite3
from datetime import datetime

from praxis_core.model.priorities import (
    Priority,
    PriorityType,
    PriorityStatus,
    Value,
    Goal,
    Practice,
    Initiative,
    Org,
)


# ---------------------------------------------------------------------
# SQLite Schema
# ---------------------------------------------------------------------

PRIORITIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS priorities (
    id TEXT PRIMARY KEY,
    entity_id TEXT REFERENCES entities(id),
    priority_type TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',

    -- Common
    substatus TEXT,  -- Extension field (e.g., draft, backlog, abandoned)
    agent_context TEXT,  -- Scaffolding for AI integration
    description TEXT,
    rank INTEGER,

    -- Priority-level assignment
    assigned_to_entity_id TEXT REFERENCES entities(id),

    -- Goal (concrete outcome with end state)
    complete_when TEXT,
    due_date TEXT,
    progress TEXT,

    -- Practice fields
    actions_config TEXT,       -- JSON: v2 DSL actions array
    last_triggered_at TEXT,    -- datetime: managed by trigger system, not edit form

    -- Engagement tracking
    last_engaged_at TEXT,      -- datetime: updated when child tasks are completed

    -- Metadata
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS priority_edges (
    child_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (child_id, parent_id),
    FOREIGN KEY (child_id) REFERENCES priorities(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES priorities(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_priorities_type ON priorities(priority_type);
CREATE INDEX IF NOT EXISTS idx_priorities_status ON priorities(status);
CREATE INDEX IF NOT EXISTS idx_priorities_entity ON priorities(entity_id);
CREATE INDEX IF NOT EXISTS idx_priority_edges_child ON priority_edges(child_id);
CREATE INDEX IF NOT EXISTS idx_priority_edges_parent ON priority_edges(parent_id);
"""


# ---------------------------------------------------------------------
# Row Conversion
# ---------------------------------------------------------------------

def priority_from_row(row: sqlite3.Row) -> Priority:
    """Convert a database row to a Priority subclass."""
    priority_type = PriorityType(row["priority_type"])
    status = PriorityStatus(row["status"])
    created_at = _parse_datetime(row["created_at"])
    updated_at = _parse_datetime(row["updated_at"])

    # Handle fields that may not exist in older schemas
    keys = row.keys()
    entity_id = row["entity_id"] if "entity_id" in keys else None
    substatus = row["substatus"] if "substatus" in keys else None
    assigned_to_entity_id = row["assigned_to_entity_id"] if "assigned_to_entity_id" in keys else None

    # Handle description (was 'notes' in older schemas)
    description = row["description"] if "description" in keys else (row["notes"] if "notes" in keys else None)

    last_engaged_at = _parse_datetime(row["last_engaged_at"]) if "last_engaged_at" in keys else None

    common_kwargs = {
        "id": row["id"],
        "name": row["name"],
        "status": status,
        "substatus": substatus,
        "entity_id": entity_id,
        "agent_context": row["agent_context"],
        "description": description,
        "rank": row["rank"],
        "assigned_to_entity_id": assigned_to_entity_id,
        "last_engaged_at": last_engaged_at,
        "created_at": created_at,
        "updated_at": updated_at,
    }

    match priority_type:
        case PriorityType.VALUE:
            return Value(
                **common_kwargs,
                priority_type=priority_type,
            )

        case PriorityType.GOAL:
            return Goal(
                **common_kwargs,
                priority_type=priority_type,
                complete_when=row["complete_when"],
                due_date=_parse_datetime(row["due_date"]),
                progress=row["progress"],
            )

        case PriorityType.PRACTICE:
            # Handle practice fields (may not exist in older schemas)
            actions_config = row["actions_config"] if "actions_config" in keys else None
            last_triggered_at = _parse_datetime(row["last_triggered_at"]) if "last_triggered_at" in keys else None

            return Practice(
                **common_kwargs,
                priority_type=priority_type,
                actions_config=actions_config,
                last_triggered_at=last_triggered_at,
            )

        case PriorityType.INITIATIVE:
            return Initiative(
                **common_kwargs,
                priority_type=priority_type,
            )

        case PriorityType.ORG:
            return Org(
                **common_kwargs,
                priority_type=priority_type,
            )

    raise ValueError(f"Unknown priority type: {priority_type}")


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def priority_to_row_values(priority: Priority) -> tuple:
    """
    Convert a Priority (any subclass) to a tuple of values for SQL insert/update.
    Returns values in column order matching the INSERT statement.
    """
    # Type-specific fields default to None
    complete_when = None
    due_date = None
    progress = None
    actions_config = None

    # Extract type-specific fields based on actual type
    if isinstance(priority, Goal):
        complete_when = priority.complete_when
        due_date = priority.due_date.isoformat() if priority.due_date else None
        progress = priority.progress

    elif isinstance(priority, Practice):
        actions_config = priority.actions_config

    last_triggered_at = None
    if isinstance(priority, Practice) and priority.last_triggered_at:
        last_triggered_at = priority.last_triggered_at.isoformat()

    last_engaged_at = priority.last_engaged_at.isoformat() if priority.last_engaged_at else None

    now = datetime.now().isoformat()
    return (
        priority.id,
        priority.entity_id,
        priority.priority_type.value,
        priority.name,
        priority.status.value,
        priority.substatus,
        priority.agent_context,
        priority.description,
        priority.rank,
        priority.assigned_to_entity_id,
        complete_when,
        due_date,
        progress,
        actions_config,
        last_triggered_at,
        last_engaged_at,
        priority.created_at.isoformat() if priority.created_at else now,
        priority.updated_at.isoformat() if priority.updated_at else now,
    )
