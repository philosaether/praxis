"""Session lifecycle persistence."""

import uuid
from datetime import datetime, timedelta

from praxis_core.model.users import Session, SessionType
from praxis_core.persistence.database import get_connection


# -----------------------------------------------------------------------------
# Schema
# -----------------------------------------------------------------------------

SESSIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL,
    last_activity TEXT,
    user_agent TEXT,
    ip_address TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
"""


# -----------------------------------------------------------------------------
# Session CRUD
# -----------------------------------------------------------------------------

def create_session(
    user_id: int,
    session_type: SessionType,
    expires_in_hours: int = 168,  # 7 days default
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> Session:
    """Create a new session for a user."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    session_id = str(uuid.uuid4())
    now = datetime.now()
    expires_at = now + timedelta(hours=expires_in_hours)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO sessions (id, user_id, session_type, created_at, expires_at, user_agent, ip_address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, user_id, session_type.value, now.isoformat(),
             expires_at.isoformat(), user_agent, ip_address),
        )
        return Session(
            id=session_id,
            user_id=user_id,
            session_type=session_type,
            expires_at=expires_at,
            created_at=now,
            user_agent=user_agent,
            ip_address=ip_address,
        )


def get_session(session_id: str) -> Session | None:
    """Get a session by ID. Returns None if not found or expired."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,)
        ).fetchone()
        if row is None:
            return None

        session = _row_to_session(row)

        # Check expiration
        if session.expires_at < datetime.now():
            # Clean up expired session
            delete_session(session_id)
            return None

        return session


def validate_session(session_id: str) -> tuple[Session, "User"] | None:
    """
    Validate a session and return the session and user if valid.
    Updates last_activity timestamp.
    Returns None if session is invalid, expired, or user is inactive.
    """
    from praxis_core.persistence.user_repo import get_user

    session = get_session(session_id)
    if session is None:
        return None

    user = get_user(session.user_id)
    if user is None or not user.is_active:
        delete_session(session_id)
        return None

    # Update last activity
    with get_connection() as conn:
        now = datetime.now()
        conn.execute(
            "UPDATE sessions SET last_activity = ? WHERE id = ?",
            (now.isoformat(), session_id)
        )
        session.last_activity = now

    return session, user


def delete_session(session_id: str) -> bool:
    """Delete a session (logout). Returns True if deleted."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cursor.rowcount > 0


def delete_user_sessions(user_id: int) -> int:
    """Delete all sessions for a user. Returns count deleted."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return cursor.rowcount


def cleanup_expired_sessions() -> int:
    """Delete all expired sessions. Returns count deleted."""
    from praxis_core.persistence.user_repo import ensure_schema
    ensure_schema()

    with get_connection() as conn:
        now = datetime.now().isoformat()
        cursor = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        return cursor.rowcount


def _row_to_session(row) -> Session:
    """Convert a database row to a Session."""
    created_at = None
    if row["created_at"]:
        created_at = datetime.fromisoformat(row["created_at"])

    expires_at = datetime.fromisoformat(row["expires_at"])

    last_activity = None
    if row["last_activity"]:
        last_activity = datetime.fromisoformat(row["last_activity"])

    return Session(
        id=row["id"],
        user_id=row["user_id"],
        session_type=SessionType(row["session_type"]),
        expires_at=expires_at,
        created_at=created_at,
        last_activity=last_activity,
        user_agent=row["user_agent"],
        ip_address=row["ip_address"],
    )
