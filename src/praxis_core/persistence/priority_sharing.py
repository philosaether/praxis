"""Priority sharing: entity-based share/unshare operations."""


# ---------------------------------------------------------------------
# Entity Shares Schema
# ---------------------------------------------------------------------

ENTITY_SHARES_SCHEMA = """
-- Entity-based sharing (replaces priority_shares)
CREATE TABLE IF NOT EXISTS entity_shares (
    priority_id TEXT NOT NULL REFERENCES priorities(id) ON DELETE CASCADE,
    shared_with_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    permission TEXT NOT NULL DEFAULT 'contributor',
    allow_adoption INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (priority_id, shared_with_entity_id)
);

CREATE INDEX IF NOT EXISTS idx_entity_shares_entity ON entity_shares(shared_with_entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_shares_priority ON entity_shares(priority_id);

-- Legacy table (deprecated, kept for migration)
CREATE TABLE IF NOT EXISTS priority_shares (
    priority_id TEXT NOT NULL REFERENCES priorities(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission TEXT NOT NULL DEFAULT 'contributor',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (priority_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_priority_shares_user ON priority_shares(user_id);
CREATE INDEX IF NOT EXISTS idx_priority_shares_priority ON priority_shares(priority_id);
"""


# ---------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------

_migrated = False

def _migrate_allow_adoption(conn) -> None:
    """Add allow_adoption column if missing (for existing DBs)."""
    global _migrated
    if _migrated:
        return
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(entity_shares)").fetchall()}
    if "allow_adoption" not in cols:
        conn.execute("ALTER TABLE entity_shares ADD COLUMN allow_adoption INTEGER NOT NULL DEFAULT 0")
    _migrated = True


# ---------------------------------------------------------------------
# Sharing Operations
# ---------------------------------------------------------------------

def share(connection_factory, priority_id: str, target_entity_id: str, permission: str = "contributor", allow_adoption: bool = False) -> None:
    """
    Share a priority with another entity.

    Args:
        connection_factory: Callable returning a DB connection context manager
        priority_id: The priority to share
        target_entity_id: The entity to share with (personal or organization)
        permission: One of 'viewer', 'contributor', 'editor'
        allow_adoption: Whether the recipient can adopt this priority into their own tree
    """
    if permission not in ("viewer", "contributor", "editor"):
        raise ValueError(f"Invalid permission: {permission}")

    with connection_factory() as conn:
        _migrate_allow_adoption(conn)
        conn.execute("""
            INSERT INTO entity_shares (priority_id, shared_with_entity_id, permission, allow_adoption)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(priority_id, shared_with_entity_id) DO UPDATE SET
                permission = excluded.permission,
                allow_adoption = excluded.allow_adoption
        """, (priority_id, target_entity_id, permission, int(allow_adoption)))


def share_with_user(connection_factory, priority_id: str, user_id: int, permission: str = "contributor", allow_adoption: bool = False) -> None:
    """
    Share a priority with a user (via their personal entity).

    Args:
        connection_factory: Callable returning a DB connection context manager
        priority_id: The priority to share
        user_id: The user to share with
        permission: One of 'viewer', 'contributor', 'editor'
        allow_adoption: Whether the recipient can adopt this priority into their own tree
    """
    # Look up user's personal entity
    with connection_factory() as conn:
        row = conn.execute(
            "SELECT entity_id FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not row or not row["entity_id"]:
            raise ValueError(f"User {user_id} has no personal entity")
        target_entity_id = row["entity_id"]

    share(connection_factory, priority_id, target_entity_id, permission, allow_adoption)


def unshare(connection_factory, priority_id: str, target_entity_id: str) -> bool:
    """
    Remove sharing for a priority with an entity.
    Returns True if a share was removed.
    """
    with connection_factory() as conn:
        cursor = conn.execute("""
            DELETE FROM entity_shares
            WHERE priority_id = ? AND shared_with_entity_id = ?
        """, (priority_id, target_entity_id))
        return cursor.rowcount > 0


def unshare_user(connection_factory, priority_id: str, user_id: int) -> bool:
    """
    Remove sharing for a priority with a user (via their personal entity).
    Returns True if a share was removed.
    """
    with connection_factory() as conn:
        row = conn.execute(
            "SELECT entity_id FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not row or not row["entity_id"]:
            return False
        target_entity_id = row["entity_id"]

    return unshare(connection_factory, priority_id, target_entity_id)


def get_shares(connection_factory, priority_id: str) -> list[dict]:
    """
    Get all entities a priority is shared with.
    Returns list of {entity_id, entity_name, permission, created_at, user_id, username}.
    For personal entities, includes the user info.
    """
    with connection_factory() as conn:
        _migrate_allow_adoption(conn)
        rows = conn.execute("""
            SELECT es.shared_with_entity_id, es.permission, es.allow_adoption, es.created_at,
                   e.name as entity_name, e.type as entity_type,
                   u.id as user_id, u.username
            FROM entity_shares es
            JOIN entities e ON es.shared_with_entity_id = e.id
            LEFT JOIN users u ON e.id = u.entity_id
            WHERE es.priority_id = ?
        """, (priority_id,)).fetchall()
        return [
            {
                "entity_id": row["shared_with_entity_id"],
                "entity_name": row["entity_name"],
                "entity_type": row["entity_type"],
                "user_id": row["user_id"],
                "username": row["username"],
                "permission": row["permission"],
                "allow_adoption": bool(row["allow_adoption"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]


def get_permission(connection_factory, priority_id: str, entity_id: str, priority=None) -> str | None:
    """
    Get an entity's permission level for a priority.
    Returns 'owner', 'viewer', 'contributor', 'editor', or None.

    Args:
        connection_factory: Callable returning a DB connection context manager
        priority_id: The priority to check
        entity_id: The entity to check permissions for
        priority: Optional pre-loaded Priority object (avoids extra DB lookup)
    """
    # Check if owner (entity owns the priority)
    if priority is not None and priority.entity_id == entity_id:
        return "owner"

    # If no priority passed, check ownership via DB
    if priority is None:
        with connection_factory() as conn:
            row = conn.execute(
                "SELECT entity_id FROM priorities WHERE id = ?", (priority_id,)
            ).fetchone()
            if row and row["entity_id"] == entity_id:
                return "owner"

    # Check entity_shares
    with connection_factory() as conn:
        share_row = conn.execute("""
            SELECT permission FROM entity_shares
            WHERE priority_id = ? AND shared_with_entity_id = ?
        """, (priority_id, entity_id)).fetchone()
        if share_row:
            return share_row["permission"]

    return None


def can_adopt(connection_factory, priority_id: str, entity_id: str) -> bool:
    """Check if an entity has adoption permission for a shared priority."""
    with connection_factory() as conn:
        _migrate_allow_adoption(conn)
        row = conn.execute("""
            SELECT allow_adoption FROM entity_shares
            WHERE priority_id = ? AND shared_with_entity_id = ?
        """, (priority_id, entity_id)).fetchone()
        return bool(row and row["allow_adoption"])
