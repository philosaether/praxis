"""Configuration for Praxis Home (open source home server)."""

from dataclasses import dataclass, field


@dataclass
class PraxisHomeConfig:
    """Configuration for Praxis Home server.

    This config is designed for personal/home use:
    - Single user or small family
    - Password auth only (no OAuth)
    - Runs on local network
    """

    # Server settings
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    web_host: str = "0.0.0.0"
    web_port: int = 8080

    # Auth settings
    allow_registration: bool = False  # Create users via CLI only
    session_expiry_hours: int = 168  # 7 days
    require_https: bool = False  # Local network is OK

    # Database
    db_path: str = "~/.praxis/praxis.db"

    def __post_init__(self):
        """Expand paths."""
        import os
        self.db_path = os.path.expanduser(self.db_path)
