"""API key persistence: create, validate, list, revoke."""

import secrets
import uuid
from datetime import datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from praxis_core.model.users import User
from praxis_core.persistence.database import get_connection


_ph = PasswordHasher()

API_KEYS_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    key_hash TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TEXT,
    expires_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(key_prefix);
"""


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns:
        (key_id, plaintext_key, key_prefix)
        The plaintext key is shown once at creation and never stored.
    """
    key_id = str(uuid.uuid4())
    random_part = secrets.token_hex(24)  # 48 hex chars
    plaintext_key = f"praxis_{random_part}"
    key_prefix = plaintext_key[:16]  # "praxis_" + first 9 hex chars
    return key_id, plaintext_key, key_prefix


def create_api_key(user_id: int, name: str) -> tuple[dict, str]:
    """Create a new API key for a user.

    Args:
        user_id: Owner user ID
        name: Human label for the key

    Returns:
        (key_metadata_dict, plaintext_key)
        The plaintext key is returned exactly once.
    """
    _ensure_schema()
    key_id, plaintext_key, key_prefix = generate_api_key()
    key_hash = _ph.hash(plaintext_key)
    now = datetime.now().isoformat()

    with get_connection() as conn:
        conn.execute(
            """INSERT INTO api_keys (id, key_hash, key_prefix, user_id, name, created_at, is_active)
               VALUES (?, ?, ?, ?, ?, ?, 1)""",
            (key_id, key_hash, key_prefix, user_id, name, now),
        )

    return {
        "id": key_id,
        "key_prefix": key_prefix,
        "name": name,
        "created_at": now,
        "last_used_at": None,
        "is_active": True,
    }, plaintext_key


def validate_api_key(plaintext_key: str) -> User | None:
    """Validate an API key and return the associated user.

    Also updates last_used_at on successful validation.
    Returns None if key is invalid, revoked, or expired.
    """
    _ensure_schema()

    if not plaintext_key.startswith("praxis_"):
        return None

    prefix = plaintext_key[:16]

    with get_connection() as conn:
        # Find candidate keys by prefix (narrows the search before hash check)
        rows = conn.execute(
            """SELECT id, key_hash, user_id, expires_at, is_active
               FROM api_keys WHERE key_prefix = ? AND is_active = 1""",
            (prefix,),
        ).fetchall()

        for row in rows:
            # Check expiry
            if row["expires_at"]:
                if datetime.fromisoformat(row["expires_at"]) < datetime.now():
                    continue

            # Verify hash
            try:
                _ph.verify(row["key_hash"], plaintext_key)
            except VerifyMismatchError:
                continue

            # Valid key — update last_used_at
            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
                (now, row["id"]),
            )

            # Load user
            from praxis_core.persistence.user_repo import get_user
            user = get_user(row["user_id"])
            if user and user.is_active:
                return user

    return None


def list_api_keys(user_id: int) -> list[dict]:
    """List all API keys for a user (metadata only, no hashes)."""
    _ensure_schema()
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT id, key_prefix, name, created_at, last_used_at, is_active
               FROM api_keys WHERE user_id = ? ORDER BY created_at DESC""",
            (user_id,),
        ).fetchall()

    return [
        {
            "id": row["id"],
            "key_prefix": row["key_prefix"],
            "name": row["name"],
            "created_at": row["created_at"],
            "last_used_at": row["last_used_at"],
            "is_active": bool(row["is_active"]),
        }
        for row in rows
    ]


def revoke_api_key(key_id: str, user_id: int) -> bool:
    """Revoke an API key. Returns True if revoked, False if not found or not owned."""
    _ensure_schema()
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE api_keys SET is_active = 0 WHERE id = ? AND user_id = ?",
            (key_id, user_id),
        )
        return cursor.rowcount > 0


# -----------------------------------------------------------------------------
# Schema
# -----------------------------------------------------------------------------

_schema_ensured = False


def _ensure_schema():
    global _schema_ensured
    if _schema_ensured:
        return
    with get_connection() as conn:
        conn.executescript(API_KEYS_SCHEMA)
    _schema_ensured = True
