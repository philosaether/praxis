"""Praxis UI: CLI and web interfaces."""

from praxis.ui.cli import app as cli_app
from praxis.ui.api import app as api_app

__all__ = ["cli_app", "api_app"]
