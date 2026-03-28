"""User and session persistence layer."""

import uuid
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

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
    """Ensure the users and sessions tables exist."""
    global _schema_ensured
    if _schema_ensured:
        return
    with get_connection() as conn:
        conn.executescript(USERS_SCHEMA)
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
    """Create a new user with hashed password."""
    ensure_schema()
    now = datetime.now()
    password_hash = hash_password(password)

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO users (username, email, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (username, email, password_hash, role.value, now.isoformat()),
        )
        return User(
            id=cursor.lastrowid,
            username=username,
            email=email,
            password_hash=password_hash,
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

    return User(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        password_hash=row["password_hash"],
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
