"""Friend request CRUD persistence."""

from datetime import datetime

from ulid import ULID

from praxis_core.persistence.database import get_connection
from praxis_core.persistence.friend_repo import add_friend, are_friends


# -----------------------------------------------------------------------------
# Schema
# -----------------------------------------------------------------------------

FRIEND_REQUESTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS friend_requests (
    id TEXT PRIMARY KEY,
    from_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    seen_at TEXT,
    UNIQUE(from_user_id, to_user_id)
);

CREATE INDEX IF NOT EXISTS idx_friend_requests_to ON friend_requests(to_user_id);
CREATE INDEX IF NOT EXISTS idx_friend_requests_from ON friend_requests(from_user_id);
CREATE INDEX IF NOT EXISTS idx_friend_requests_status ON friend_requests(status);
"""


# -----------------------------------------------------------------------------
# Friend Request CRUD
# -----------------------------------------------------------------------------

def send_request(from_user_id: int, to_user_id: int) -> dict:
    """
    Send a friend request.
    Raises ValueError if self-request, already friends, or pending request exists.
    Returns the created request dict.
    """
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    if from_user_id == to_user_id:
        raise ValueError("Cannot send a friend request to yourself")

    if are_friends(from_user_id, to_user_id):
        raise ValueError("Already friends")

    with get_connection() as conn:
        # Check for existing pending request in either direction
        existing = conn.execute(
            """
            SELECT id, from_user_id, to_user_id FROM friend_requests
            WHERE status = 'pending'
            AND ((from_user_id = ? AND to_user_id = ?) OR (from_user_id = ? AND to_user_id = ?))
            """,
            (from_user_id, to_user_id, to_user_id, from_user_id)
        ).fetchone()

        if existing:
            if existing["from_user_id"] == to_user_id:
                raise ValueError("This user has already sent you a request")
            raise ValueError("Friend request already pending")

        request_id = str(ULID())
        now = datetime.now().isoformat()

        conn.execute(
            """
            INSERT INTO friend_requests (id, from_user_id, to_user_id, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (request_id, from_user_id, to_user_id, now)
        )

    return {
        "id": request_id,
        "from_user_id": from_user_id,
        "to_user_id": to_user_id,
        "status": "pending",
        "created_at": now,
    }


def list_incoming(user_id: int) -> list[dict]:
    """List pending friend requests TO this user."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT fr.id, fr.from_user_id, fr.created_at, u.username
            FROM friend_requests fr
            JOIN users u ON fr.from_user_id = u.id
            WHERE fr.to_user_id = ? AND fr.status = 'pending'
            ORDER BY fr.created_at DESC
            """,
            (user_id,)
        ).fetchall()

    return [dict(row) for row in rows]


def list_outgoing(user_id: int) -> list[dict]:
    """List pending friend requests FROM this user."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT fr.id, fr.to_user_id, fr.created_at, u.username
            FROM friend_requests fr
            JOIN users u ON fr.to_user_id = u.id
            WHERE fr.from_user_id = ? AND fr.status = 'pending'
            ORDER BY fr.created_at DESC
            """,
            (user_id,)
        ).fetchall()

    return [dict(row) for row in rows]


def list_unseen_accepted(user_id: int) -> list[dict]:
    """List accepted requests FROM this user where the sender hasn't seen the acceptance."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT fr.id, fr.to_user_id, fr.resolved_at, u.username
            FROM friend_requests fr
            JOIN users u ON fr.to_user_id = u.id
            WHERE fr.from_user_id = ? AND fr.status = 'accepted' AND fr.seen_at IS NULL
            ORDER BY fr.resolved_at DESC
            """,
            (user_id,)
        ).fetchall()

    return [dict(row) for row in rows]


def accept_request(request_id: str, user_id: int) -> bool:
    """
    Accept a friend request. Only the recipient can accept.
    Creates bidirectional friendship. Returns True if accepted.
    """
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    now = datetime.now().isoformat()

    with get_connection() as conn:
        # Use UPDATE with WHERE status='pending' to atomically claim the request
        cursor = conn.execute(
            """UPDATE friend_requests SET status = 'accepted', resolved_at = ?
               WHERE id = ? AND to_user_id = ? AND status = 'pending'""",
            (now, request_id, user_id)
        )
        if cursor.rowcount == 0:
            return False

        row = conn.execute(
            "SELECT from_user_id, to_user_id FROM friend_requests WHERE id = ?",
            (request_id,)
        ).fetchone()

        # Create friendship inside the same connection context
        conn.execute(
            "INSERT OR IGNORE INTO friends (user_id, friend_user_id, created_at) VALUES (?, ?, ?)",
            (row["from_user_id"], row["to_user_id"], now)
        )
        conn.execute(
            "INSERT OR IGNORE INTO friends (user_id, friend_user_id, created_at) VALUES (?, ?, ?)",
            (row["to_user_id"], row["from_user_id"], now)
        )

    return True


def decline_request(request_id: str, user_id: int) -> bool:
    """Decline a friend request. Only the recipient can decline."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    now = datetime.now().isoformat()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE friend_requests SET status = 'declined', resolved_at = ?
            WHERE id = ? AND to_user_id = ? AND status = 'pending'
            """,
            (now, request_id, user_id)
        )
        return cursor.rowcount > 0


def cancel_request(request_id: str, user_id: int) -> bool:
    """Cancel a friend request. Only the sender can cancel."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    now = datetime.now().isoformat()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE friend_requests SET status = 'cancelled', resolved_at = ?
            WHERE id = ? AND from_user_id = ? AND status = 'pending'
            """,
            (now, request_id, user_id)
        )
        return cursor.rowcount > 0


def mark_accepted_seen(user_id: int) -> int:
    """Mark all unseen accepted requests from this user as seen. Returns count marked."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    now = datetime.now().isoformat()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE friend_requests SET seen_at = ?
            WHERE from_user_id = ? AND status = 'accepted' AND seen_at IS NULL
            """,
            (now, user_id)
        )
        return cursor.rowcount


def get_notification_counts(user_id: int) -> dict:
    """Get notification counts for the friends badge."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        pending = conn.execute(
            "SELECT COUNT(*) as n FROM friend_requests WHERE to_user_id = ? AND status = 'pending'",
            (user_id,)
        ).fetchone()["n"]

        unseen_accepted = conn.execute(
            "SELECT COUNT(*) as n FROM friend_requests WHERE from_user_id = ? AND status = 'accepted' AND seen_at IS NULL",
            (user_id,)
        ).fetchone()["n"]

    return {
        "pending_incoming": pending,
        "unseen_accepted": unseen_accepted,
        "total": pending + unseen_accepted,
    }
