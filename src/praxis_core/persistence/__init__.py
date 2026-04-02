"""Praxis Core persistence layer."""

from praxis_core.persistence.database import (
    get_connection,
    DB_DIR,
    DB_PATH,
)
from praxis_core.persistence.priority_persistence import (
    PriorityGraph,
    priority_from_row,
    priority_to_row_values,
    PRIORITIES_SCHEMA,
)
from praxis_core.persistence.task_persistence import (
    create_task,
    get_task,
    list_tasks,
    update_task,
    update_task_status,
    delete_task,
    create_subtask,
    toggle_subtask,
    delete_subtask,
    reorder_subtasks,
    clear_tasks,
    seed_database,
    TASKS_SCHEMA,
)
from praxis_core.persistence.user_persistence import (
    # Schema
    USERS_SCHEMA,
    # Password utils
    hash_password,
    verify_password,
    # User CRUD
    create_user,
    get_user,
    get_user_by_username,
    get_user_by_email,
    authenticate_user,
    list_users,
    update_user_password,
    delete_user,
    # Session CRUD
    create_session,
    get_session,
    validate_session,
    delete_session,
    delete_user_sessions,
    cleanup_expired_sessions,
)
from praxis_core.persistence.rule_persistence import (
    RULES_SCHEMA,
    create_rule,
    get_rule,
    list_rules,
    update_rule,
    delete_rule,
    toggle_rule,
    create_system_rule,
    ensure_default_rules,
)
from praxis_core.persistence.tag_persistence import (
    get_tags_for_task,
    get_tags_for_tasks,
)

__all__ = [
    # Database
    "get_connection",
    "DB_DIR",
    "DB_PATH",
    # Priority persistence
    "PriorityGraph",
    "priority_from_row",
    "priority_to_row_values",
    "PRIORITIES_SCHEMA",
    # Task persistence
    "create_task",
    "get_task",
    "list_tasks",
    "update_task",
    "update_task_status",
    "delete_task",
    "create_subtask",
    "toggle_subtask",
    "delete_subtask",
    "reorder_subtasks",
    "clear_tasks",
    "seed_database",
    "TASKS_SCHEMA",
    # User persistence
    "USERS_SCHEMA",
    "hash_password",
    "verify_password",
    "create_user",
    "get_user",
    "get_user_by_username",
    "get_user_by_email",
    "authenticate_user",
    "list_users",
    "update_user_password",
    "delete_user",
    "create_session",
    "get_session",
    "validate_session",
    "delete_session",
    "delete_user_sessions",
    "cleanup_expired_sessions",
    # Rule persistence
    "RULES_SCHEMA",
    "create_rule",
    "get_rule",
    "list_rules",
    "update_rule",
    "delete_rule",
    "toggle_rule",
    "create_system_rule",
    "ensure_default_rules",
    # Tag persistence (subset)
    "get_tags_for_task",
    "get_tags_for_tasks",
]
