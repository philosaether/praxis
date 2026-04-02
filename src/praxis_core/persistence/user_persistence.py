"""User and session persistence layer."""

import uuid
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from ulid import ULID

from praxis_core.model.users import User, Session, UserRole, SessionType
from praxis_core.persistence.database import get_connection


# -----------------------------------------------------------------------------
# Schema
# -----------------------------------------------------------------------------

USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT,
    password_hash TEXT NOT NULL,
    entity_id TEXT REFERENCES entities(id),
    role TEXT NOT NULL DEFAULT 'user',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login TEXT
);

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
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
"""

ENTITIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    parent_entity_id TEXT REFERENCES entities(id),
    config TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS entity_members (
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (entity_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_parent ON entities(parent_entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_members_user ON entity_members(user_id);
CREATE INDEX IF NOT EXISTS idx_entity_members_entity ON entity_members(entity_id);
"""

FRIENDS_SCHEMA = """
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
# Password Hashing
# -----------------------------------------------------------------------------

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password using Argon2id."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verify a password against its hash. Returns False if mismatch."""
    try:
        _hasher.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False


# -----------------------------------------------------------------------------
# Schema Management
# -----------------------------------------------------------------------------

_schema_ensured = False


def ensure_schema() -> None:
    """Ensure the entities, users, sessions, invitations, and friends tables exist."""
    global _schema_ensured
    if _schema_ensured:
        return
    with get_connection() as conn:
        # Entities must be created before users (foreign key dependency)
        conn.executescript(ENTITIES_SCHEMA)
        conn.executescript(USERS_SCHEMA)
        conn.executescript(FRIENDS_SCHEMA)
    _schema_ensured = True


# -----------------------------------------------------------------------------
# User CRUD
# -----------------------------------------------------------------------------

def create_user(
    username: str,
    password: str,
    email: str | None = None,
    role: UserRole = UserRole.USER,
) -> User:
    """Create a new user with hashed password and personal entity."""
    ensure_schema()
    now = datetime.now()
    now_str = now.isoformat()
    password_hash = hash_password(password)
    entity_id = str(ULID())

    with get_connection() as conn:
        # Create personal entity
        conn.execute(
            """
            INSERT INTO entities (id, type, name, config, created_at)
            VALUES (?, 'personal', ?, '{}', ?)
            """,
            (entity_id, username, now_str),
        )

        # Create user linked to entity
        cursor = conn.execute(
            """
            INSERT INTO users (username, email, password_hash, entity_id, role, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, email, password_hash, entity_id, role.value, now_str),
        )
        user_id = cursor.lastrowid

        # Add user as owner of their personal entity
        conn.execute(
            """
            INSERT INTO entity_members (entity_id, user_id, role, created_at)
            VALUES (?, ?, 'owner', ?)
            """,
            (entity_id, user_id, now_str),
        )

    # Seed default rules for the new user (outside transaction)
    from praxis_core.persistence.rule_persistence import seed_user_rules
    seed_user_rules(entity_id)

    return User(
        id=user_id,
        username=username,
        email=email,
        password_hash=password_hash,
        entity_id=entity_id,
        role=role,
        is_active=True,
        created_at=now,
    )


def get_user(user_id: int) -> User | None:
    """Get a user by ID."""
    ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        if row:
            return _row_to_user(row)
        return None


def get_user_by_username(username: str) -> User | None:
    """Get a user by username."""
    ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        if row:
            return _row_to_user(row)
        return None


def get_user_by_email(email: str) -> User | None:
    """Get a user by email."""
    ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()
        if row:
            return _row_to_user(row)
        return None


def authenticate_user(username_or_email: str, password: str) -> User | None:
    """
    Authenticate a user by username or email and password.
    Returns the user if credentials are valid, None otherwise.
    """
    # Try username first, then email
    user = get_user_by_username(username_or_email)
    if user is None and "@" in username_or_email:
        user = get_user_by_email(username_or_email)
    if user is None:
        return None
    if not user.is_active:
        return None
    if not verify_password(user.password_hash, password):
        return None

    # Update last_login
    with get_connection() as conn:
        now = datetime.now()
        conn.execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (now.isoformat(), user.id)
        )
        user.last_login = now

    return user


def list_users() -> list[User]:
    """List all users."""
    ensure_schema()
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY username").fetchall()
        return [_row_to_user(row) for row in rows]


def update_user_password(user_id: int, new_password: str) -> bool:
    """Update a user's password. Returns True if updated."""
    ensure_schema()
    password_hash = hash_password(new_password)
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id)
        )
        return cursor.rowcount > 0


def delete_user(user_id: int) -> bool:
    """Delete a user and all their sessions. Returns True if deleted."""
    ensure_schema()
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cursor.rowcount > 0


def _row_to_user(row) -> User:
    """Convert a database row to a User."""
    created_at = None
    if row["created_at"]:
        created_at = datetime.fromisoformat(row["created_at"])

    last_login = None
    if row["last_login"]:
        last_login = datetime.fromisoformat(row["last_login"])

    # Handle entity_id (may not exist in older schemas)
    entity_id = row["entity_id"] if "entity_id" in row.keys() else None

    return User(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        password_hash=row["password_hash"],
        entity_id=entity_id,
        role=UserRole(row["role"]),
        is_active=bool(row["is_active"]),
        created_at=created_at,
        last_login=last_login,
    )


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


def validate_session(session_id: str) -> tuple[Session, User] | None:
    """
    Validate a session and return the session and user if valid.
    Updates last_activity timestamp.
    Returns None if session is invalid, expired, or user is inactive.
    """
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
    ensure_schema()
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cursor.rowcount > 0


def delete_user_sessions(user_id: int) -> int:
    """Delete all sessions for a user. Returns count deleted."""
    ensure_schema()
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return cursor.rowcount


def cleanup_expired_sessions() -> int:
    """Delete all expired sessions. Returns count deleted."""
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


# -----------------------------------------------------------------------------
# Invitations
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


# -----------------------------------------------------------------------------
# Friends
# -----------------------------------------------------------------------------

def list_friends(user_id: int) -> list[dict]:
    """List all friends of a user with their user info."""
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
    ensure_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM friends WHERE user_id = ? AND friend_user_id = ?",
            (user_id, friend_user_id)
        ).fetchone()
        return row is not None
