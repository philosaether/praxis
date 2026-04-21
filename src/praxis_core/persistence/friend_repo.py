"""Friendship CRUD persistence."""

from datetime import datetime

from praxis_core.persistence.database import get_connection


# -----------------------------------------------------------------------------
# Schema
# -----------------------------------------------------------------------------

FRIENDS_SCHEMA = """
CREATE TABLE IF NOT EXISTS friends (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    friend_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, friend_user_id)
);

CREATE INDEX IF NOT EXISTS idx_friends_user ON friends(user_id);
CREATE INDEX IF NOT EXISTS idx_friends_friend ON friends(friend_user_id);
"""


# -----------------------------------------------------------------------------
# Friends CRUD
# -----------------------------------------------------------------------------

def list_friends(user_id: int) -> list[dict]:
    """List all friends of a user with their user info."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT u.id, u.username, u.email, u.entity_id, f.created_at as friends_since
            FROM friends f
            JOIN users u ON f.friend_user_id = u.id
            WHERE f.user_id = ? AND u.is_active = 1
            ORDER BY u.username
            """,
            (user_id,)
        ).fetchall()

    return [dict(row) for row in rows]


def add_friend(user_id: int, friend_user_id: int) -> bool:
    """
    Add a bidirectional friendship.
    Returns True if created, False if already exists.
    """
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    if user_id == friend_user_id:
        return False

    now = datetime.now().isoformat()
    with get_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO friends (user_id, friend_user_id, created_at) VALUES (?, ?, ?)",
                (user_id, friend_user_id, now)
            )
            conn.execute(
                "INSERT INTO friends (user_id, friend_user_id, created_at) VALUES (?, ?, ?)",
                (friend_user_id, user_id, now)
            )
            return True
        except Exception:
            return False


def remove_friend(user_id: int, friend_user_id: int) -> bool:
    """
    Remove a bidirectional friendship.
    Returns True if removed, False if didn't exist.
    """
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM friends WHERE user_id = ? AND friend_user_id = ?",
            (user_id, friend_user_id)
        )
        conn.execute(
            "DELETE FROM friends WHERE user_id = ? AND friend_user_id = ?",
            (friend_user_id, user_id)
        )
        return cursor.rowcount > 0


def are_friends(user_id: int, friend_user_id: int) -> bool:
    """Check if two users are friends."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM friends WHERE user_id = ? AND friend_user_id = ?",
            (user_id, friend_user_id)
        ).fetchone()
        return row is not None
