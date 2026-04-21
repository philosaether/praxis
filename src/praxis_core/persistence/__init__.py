"""Praxis Core persistence layer."""

from praxis_core.persistence.database import (
    get_connection,
    DB_DIR,
    DB_PATH,
)
from praxis_core.persistence.priority_repo import (
    priority_from_row,
    priority_to_row_values,
    PRIORITIES_SCHEMA,
)
from praxis_core.persistence.priority_tree import PriorityTree
from praxis_core.persistence.priority_sharing import (
    ENTITY_SHARES_SCHEMA,
    share,
    unshare,
    get_shares,
    get_permission,
    share_with_user,
    unshare_user,
)

# Backward compatibility alias (PriorityGraph -> PriorityTree)
PriorityGraph = PriorityTree

from praxis_core.persistence.task_repo import (
    create_task,
    get_task,
    update_task,
    update_task_status,
    delete_task,
    restore_from_outbox,
    purge_old_outbox_tasks,
    unlink_tasks_from_priority,
    clear_tasks,
    seed_database,
    ensure_schema as ensure_task_schema,
    TASKS_SCHEMA,
)
from praxis_core.persistence.task_queries import (
    list_tasks,
)
from praxis_core.persistence.subtask_repo import (
    create_subtask,
    toggle_subtask,
    delete_subtask,
    reorder_subtasks,
)
from praxis_core.persistence.user_repo import (
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
    mark_tutorial_completed,
    create_group,
    list_user_groups,
    delete_user,
)
from praxis_core.persistence.session_repo import (
    create_session,
    get_session,
    validate_session,
    delete_session,
    delete_user_sessions,
    cleanup_expired_sessions,
)
from praxis_core.persistence.invite_repo import (
    create_invitation,
    list_invitations,
    get_invitation_by_token,
    validate_invitation,
    accept_invitation,
    revoke_invitation,
)
from praxis_core.persistence.friend_repo import (
    list_friends,
    add_friend,
    remove_friend,
    are_friends,
)
from praxis_core.persistence.rule_persistence import (
    RULES_SCHEMA,
    create_rule,
    get_rule,
    list_rules,
    update_rule,
    delete_rule,
    toggle_rule,
    seed_user_rules,
    restore_default_rules,
    ensure_default_rules,
)
from praxis_core.persistence.tag_persistence import (
    get_tags_for_task,
    get_tags_for_tasks,
)


def ensure_all_schemas() -> None:
    """Create all tables in dependency order. Safe to call on existing DBs."""
    from praxis_core.persistence.user_repo import ensure_schema as _ensure_user_schema
    from praxis_core.persistence.task_repo import ensure_schema as _ensure_task_schema
    from praxis_core.persistence.rule_persistence import ensure_schema as _ensure_rule_schema

    with get_connection() as conn:
        # 1. Priorities + edges (no ensure_schema exists — use raw DDL)
        conn.executescript(PRIORITIES_SCHEMA)
        conn.executescript(ENTITY_SHARES_SCHEMA)

    # 2. Users, entities, sessions, invites, friends, placements
    _ensure_user_schema()

    # 3. Tasks + outbox migration
    _ensure_task_schema()

    # 4. Rules
    _ensure_rule_schema()


__all__ = [
    # Database
    "get_connection",
    "DB_DIR",
    "DB_PATH",
    # Priority persistence
    "PriorityTree",
    "PriorityGraph",  # backward compatibility alias
    "priority_from_row",
    "priority_to_row_values",
    "PRIORITIES_SCHEMA",
    # Priority sharing
    "ENTITY_SHARES_SCHEMA",
    "share",
    "unshare",
    "get_shares",
    "get_permission",
    "share_with_user",
    "unshare_user",
    # Task persistence
    "create_task",
    "get_task",
    "list_tasks",
    "update_task",
    "update_task_status",
    "delete_task",
    "restore_from_outbox",
    "purge_old_outbox_tasks",
    "unlink_tasks_from_priority",
    "ensure_task_schema",
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
    "mark_tutorial_completed",
    "create_group",
    "list_user_groups",
    "delete_user",
    "create_session",
    "get_session",
    "validate_session",
    "delete_session",
    "delete_user_sessions",
    "cleanup_expired_sessions",
    # Invitation persistence
    "create_invitation",
    "list_invitations",
    "get_invitation_by_token",
    "validate_invitation",
    "accept_invitation",
    "revoke_invitation",
    # Friends persistence
    "list_friends",
    "add_friend",
    "remove_friend",
    "are_friends",
    # Rule persistence
    "RULES_SCHEMA",
    "create_rule",
    "get_rule",
    "list_rules",
    "update_rule",
    "delete_rule",
    "toggle_rule",
    "seed_user_rules",
    "restore_default_rules",
    "ensure_default_rules",
    # Schema management
    "ensure_all_schemas",
    # Tag persistence (subset)
    "get_tags_for_task",
    "get_tags_for_tasks",
]
