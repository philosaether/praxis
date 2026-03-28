"""User and session models for authentication."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class UserRole(StrEnum):
    """User role for access control."""
    ADMIN = "admin"
    USER = "user"


class SessionType(StrEnum):
    """Type of session (determines auth mechanism)."""
    WEB = "web"  # Cookie-based
    API = "api"  # Token-based


@dataclass
class User:
    """A Praxis user account."""
    id: int
    username: str
    password_hash: str
    email: str | None = None
    role: UserRole = UserRole.USER
    is_active: bool = True
    created_at: datetime | None = None
    last_login: datetime | None = None


@dataclass
class Session:
    """An active user session (web or API)."""
    id: str  # UUID4 token
    user_id: int
    session_type: SessionType
    expires_at: datetime
    created_at: datetime | None = None
    last_activity: datetime | None = None
    user_agent: str | None = None
    ip_address: str | None = None
