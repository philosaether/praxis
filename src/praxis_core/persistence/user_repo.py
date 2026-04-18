"""User CRUD and password hashing."""

from datetime import datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from ulid import ULID

from praxis_core.model.users import User, UserRole
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
    tutorial_completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login TEXT
);

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

    from praxis_core.persistence.session_repo import SESSIONS_SCHEMA
    from praxis_core.persistence.invite_repo import INVITES_SCHEMA
    from praxis_core.persistence.friend_repo import FRIENDS_SCHEMA
    from praxis_core.persistence.friend_request_repo import FRIEND_REQUESTS_SCHEMA
    from praxis_core.persistence.priority_placement_repo import PRIORITY_PLACEMENTS_SCHEMA

    with get_connection() as conn:
        # Entities must be created before users (foreign key dependency)
        conn.executescript(ENTITIES_SCHEMA)
        conn.executescript(USERS_SCHEMA)
        conn.executescript(SESSIONS_SCHEMA)
        conn.executescript(INVITES_SCHEMA)
        conn.executescript(FRIENDS_SCHEMA)
        conn.executescript(FRIEND_REQUESTS_SCHEMA)
        conn.executescript(PRIORITY_PLACEMENTS_SCHEMA)
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


def search_users(query: str, current_user_id: int, limit: int = 20) -> list[dict]:
    """
    Search users by username prefix.
    Excludes: current user, existing friends, users with pending requests in either direction.
    """
    ensure_schema()
    search_pattern = query.strip() + "%"

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT u.id, u.username, u.created_at
            FROM users u
            WHERE u.username LIKE ? AND u.id != ? AND u.is_active = 1
            AND u.id NOT IN (
                SELECT friend_user_id FROM friends WHERE user_id = ?
            )
            AND u.id NOT IN (
                SELECT to_user_id FROM friend_requests
                WHERE from_user_id = ? AND status = 'pending'
            )
            AND u.id NOT IN (
                SELECT from_user_id FROM friend_requests
                WHERE to_user_id = ? AND status = 'pending'
            )
            ORDER BY u.username
            LIMIT ?
            """,
            (search_pattern, current_user_id, current_user_id, current_user_id, current_user_id, limit)
        ).fetchall()

    return [dict(row) for row in rows]


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


def mark_tutorial_completed(user_id: int) -> bool:
    """Mark the tutorial as completed for a user. Returns True if updated."""
    ensure_schema()
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE users SET tutorial_completed = 1 WHERE id = ?",
            (user_id,)
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
    tutorial_completed = bool(row["tutorial_completed"]) if "tutorial_completed" in row.keys() else False

    return User(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        password_hash=row["password_hash"],
        entity_id=entity_id,
        role=UserRole(row["role"]),
        is_active=bool(row["is_active"]),
        tutorial_completed=tutorial_completed,
        created_at=created_at,
        last_login=last_login,
    )
