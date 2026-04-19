"""Entity models for ownership and organization."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class EntityType(StrEnum):
    """Type of entity."""
    PERSONAL = "personal"
    GROUP = "group"


class EntityRole(StrEnum):
    """Role within an entity."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


@dataclass
class Entity:
    """
    An ownership unit in Praxis.

    Entities own priorities and tasks. Users are members of entities.
    Every user has a personal entity (1:1). Users can also be members
    of organization entities (many-to-many).
    """
    id: str  # ULID
    type: EntityType
    name: str
    parent_entity_id: str | None = None
    config: dict = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass
class EntityMember:
    """Membership linking a user to an entity."""
    entity_id: str
    user_id: int
    role: EntityRole = EntityRole.MEMBER
    created_at: datetime | None = None
