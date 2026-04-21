"""Praxis Core API."""

from praxis_core.web_api.app import app

# Re-export from canonical location for backwards compatibility
from praxis_core.serialization import (
    get_graph,
    serialize_priority,
    serialize_task,
    fmt_datetime,
    fmt_date,
)

__all__ = [
    "app",
    "get_graph",
    "serialize_priority",
    "serialize_task",
    "fmt_datetime",
    "fmt_date",
]
