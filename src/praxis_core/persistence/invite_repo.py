"""Invitation CRUD persistence."""

import uuid
from datetime import datetime, timedelta

from ulid import ULID

from praxis_core.persistence.database import get_connection


# -----------------------------------------------------------------------------
# Schema
# -----------------------------------------------------------------------------

INVITES_SCHEMA = """
CREATE TABLE IF NOT EXISTS invitations (
    id TEXT PRIMARY KEY,
    inviter_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email TEXT,  -- Optional, for future invite-by-email feature
    token TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL,
    accepted_by_user_id INTEGER REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_invitations_token ON invitations(token);
CREATE INDEX IF NOT EXISTS idx_invitations_inviter ON invitations(inviter_user_id);
CREATE INDEX IF NOT EXISTS idx_invitations_status ON invitations(status);
"""


# -----------------------------------------------------------------------------
# Invitation CRUD
# -----------------------------------------------------------------------------

def create_invitation(
    inviter_user_id: int,
    email: str | None = None,
    expires_in_days: int = 7,
) -> dict:
    """
    Create an invitation for a new user.
    Returns dict with id, token, email, expires_at.
    """
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    invitation_id = str(ULID())
    token = str(uuid.uuid4())
    now = datetime.now()
    expires_at = now + timedelta(days=expires_in_days)
    clean_email = email.lower().strip() if email else None

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO invitations (id, inviter_user_id, email, token, status, created_at, expires_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?)
            """,
            (invitation_id, inviter_user_id, clean_email, token, now.isoformat(), expires_at.isoformat())
        )

    return {
        "id": invitation_id,
        "token": token,
        "email": clean_email,
        "expires_at": expires_at.isoformat(),
    }


def list_invitations(user_id: int, status: str | None = "pending") -> list[dict]:
    """List invitations created by a user, optionally filtered by status."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        if status:
            rows = conn.execute(
                """
                SELECT id, email, token, status, created_at, expires_at, accepted_by_user_id
                FROM invitations WHERE inviter_user_id = ? AND status = ?
                ORDER BY created_at DESC
                """,
                (user_id, status)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, email, token, status, created_at, expires_at, accepted_by_user_id
                FROM invitations WHERE inviter_user_id = ?
                ORDER BY created_at DESC
                """,
                (user_id,)
            ).fetchall()

    return [dict(row) for row in rows]


def get_invitation_by_token(token: str) -> dict | None:
    """Get an invitation by its token. Returns None if not found."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT i.*, u.username as inviter_username
            FROM invitations i
            JOIN users u ON i.inviter_user_id = u.id
            WHERE i.token = ?
            """,
            (token,)
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def validate_invitation(token: str) -> dict | None:
    """
    Validate an invitation token.
    Returns invitation dict if valid (pending and not expired).
    Returns None if invalid, expired, or already used.
    """
    invitation = get_invitation_by_token(token)
    if invitation is None:
        return None

    if invitation["status"] != "pending":
        return None

    expires_at = datetime.fromisoformat(invitation["expires_at"])
    if expires_at < datetime.now():
        # Mark as expired
        with get_connection() as conn:
            conn.execute(
                "UPDATE invitations SET status = 'expired' WHERE id = ?",
                (invitation["id"],)
            )
        return None

    return invitation


def accept_invitation(token: str, accepting_user_id: int) -> bool:
    """
    Accept an invitation and create bidirectional friendship.
    Returns True if successful, False if invitation invalid.
    """
    invitation = validate_invitation(token)
    if invitation is None:
        return False

    inviter_user_id = invitation["inviter_user_id"]
    now = datetime.now().isoformat()

    with get_connection() as conn:
        # Update invitation status
        conn.execute(
            "UPDATE invitations SET status = 'accepted', accepted_by_user_id = ? WHERE id = ?",
            (accepting_user_id, invitation["id"])
        )

        # Create bidirectional friendship
        conn.execute(
            "INSERT OR IGNORE INTO friends (user_id, friend_user_id, created_at) VALUES (?, ?, ?)",
            (inviter_user_id, accepting_user_id, now)
        )
        conn.execute(
            "INSERT OR IGNORE INTO friends (user_id, friend_user_id, created_at) VALUES (?, ?, ?)",
            (accepting_user_id, inviter_user_id, now)
        )

    return True


def revoke_invitation(invitation_id: str, user_id: int) -> bool:
    """
    Revoke a pending invitation.
    Only the inviter can revoke. Returns True if revoked.
    """
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE invitations SET status = 'revoked'
            WHERE id = ? AND inviter_user_id = ? AND status = 'pending'
            """,
            (invitation_id, user_id)
        )
        return cursor.rowcount > 0
