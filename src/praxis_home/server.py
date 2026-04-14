"""Praxis Home server entry point.

Usage:
    praxis-home serve     # Start both API and web servers
    praxis-home setup     # Create admin user (first-time setup)
    praxis-home migrate   # Migrate existing data to admin user
"""

import os
import sys
import getpass
import asyncio
import uvicorn
from multiprocessing import Process

from praxis_home.config import PraxisHomeConfig


def setup(config: PraxisHomeConfig | None = None):
    """Create the initial admin user for first-time setup."""
    if config is None:
        config = PraxisHomeConfig()

    # Ensure database directory exists
    db_dir = os.path.dirname(config.db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    # Set database path for praxis_core
    os.environ["PRAXIS_DB_PATH"] = config.db_path

    # Import after setting env var
    from praxis_core.persistence import get_user_by_username, create_user
    from praxis_core.model import UserRole

    print("Praxis Home Setup")
    print("=" * 40)
    print()

    # Get admin credentials
    print("Create admin account:")

    # Get username
    while True:
        username = input("  Username: ").strip()
        if not username:
            print("  Username is required.")
            continue
        if len(username) < 3:
            print("  Username must be at least 3 characters.")
            continue
        # Check if user already exists
        existing = get_user_by_username(username)
        if existing:
            print(f"  User '{username}' already exists.")
            continue
        break

    while True:
        password = getpass.getpass("  Password: ")
        if len(password) < 8:
            print("  Password must be at least 8 characters.")
            continue
        confirm = getpass.getpass("  Confirm password: ")
        if password != confirm:
            print("  Passwords do not match.")
            continue
        break

    email = input("  Email (optional): ").strip() or None

    # Create admin user
    user = create_user(
        username=username,
        password=password,
        email=email,
        role=UserRole.ADMIN,
    )

    print()
    print(f"Admin user '{username}' created (ID: {user.id})")
    print()
    print("Start the server with: praxis-home serve")


def run_api_server(config: PraxisHomeConfig):
    """Run the API server."""
    os.environ["PRAXIS_DB_PATH"] = config.db_path
    uvicorn.run(
        "praxis_core.web_api.app:app",
        host=config.api_host,
        port=config.api_port,
        log_level="info",
    )


def run_web_server(config: PraxisHomeConfig):
    """Run the web server."""
    os.environ["PRAXIS_API_URL"] = f"http://localhost:{config.api_port}"
    uvicorn.run(
        "praxis_web.app:app",
        host=config.web_host,
        port=config.web_port,
        log_level="info",
    )


def serve(config: PraxisHomeConfig | None = None):
    """Start both API and web servers."""
    if config is None:
        config = PraxisHomeConfig()

    # Ensure database directory exists
    db_dir = os.path.dirname(config.db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    print("Starting Praxis Home...")
    print(f"  API:  http://{config.api_host}:{config.api_port}")
    print(f"  Web:  http://{config.web_host}:{config.web_port}")
    print()

    # Start API server in background process
    api_process = Process(target=run_api_server, args=(config,))
    api_process.start()

    # Give API a moment to start
    import time
    time.sleep(1)

    # Run web server in main process
    try:
        run_web_server(config)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        api_process.terminate()
        api_process.join()


def migrate(config: PraxisHomeConfig | None = None):
    """Migrate existing tasks and priorities to admin user.

    This command:
    1. Runs setup if admin doesn't exist
    2. Assigns all unowned tasks to admin
    3. Assigns all unowned priorities to admin
    """
    if config is None:
        config = PraxisHomeConfig()

    # Ensure database directory exists
    db_dir = os.path.dirname(config.db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    # Set database path for praxis_core
    os.environ["PRAXIS_DB_PATH"] = config.db_path

    # Import after setting env var
    from praxis_core.persistence import get_user_by_username, get_connection
    from praxis_core.persistence.task_persistence import ensure_schema as ensure_task_schema
    from praxis_core.persistence.priority_persistence import PriorityGraph

    print("Praxis Home Migration")
    print("=" * 40)
    print()

    # Ensure schemas are up to date (this adds user_id columns if missing)
    print("Updating database schema...")
    ensure_task_schema()
    # Loading the graph triggers schema migration for priorities
    graph = PriorityGraph(get_connection)
    graph.load()
    print()

    # Check if admin exists, create if not
    admin = get_user_by_username("admin")
    if not admin:
        print("No admin user found. Running setup first...")
        print()
        setup(config)
        admin = get_user_by_username("admin")
        if not admin:
            print("Failed to create admin user.")
            sys.exit(1)

    admin_id = admin.id
    print(f"Migrating data to admin user (ID: {admin_id})...")
    print()

    # Migrate tasks
    with get_connection() as conn:
        result = conn.execute(
            "UPDATE tasks SET user_id = ? WHERE user_id IS NULL",
            (admin_id,)
        )
        task_count = result.rowcount
        print(f"  Tasks migrated: {task_count}")

    # Migrate priorities
    with get_connection() as conn:
        result = conn.execute(
            "UPDATE priorities SET user_id = ? WHERE user_id IS NULL",
            (admin_id,)
        )
        priority_count = result.rowcount
        print(f"  Priorities migrated: {priority_count}")

    print()
    print("Migration complete!")
    print()
    print("Start the server with: praxis-home serve")


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    config = PraxisHomeConfig()

    if command == "serve":
        serve(config)
    elif command == "setup":
        setup(config)
    elif command == "migrate":
        migrate(config)
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
