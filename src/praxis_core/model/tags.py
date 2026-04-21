"""Tag model for labeling tasks and priorities."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Tag:
    """A lightweight label for tasks and priorities.

    Tags are hooks for the aptness/Rules system - they allow Rules
    to identify and modify task aptness based on labels like "morning",
    "deep-work", "quick", etc.
    """
    id: str
    entity_id: str  # ULID of owning entity (tags are user-scoped)
    name: str
    color: str | None = None  # Optional hex color for UI chip styling
    created_at: datetime | None = None
