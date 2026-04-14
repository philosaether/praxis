"""User and session persistence layer.

Backward-compatibility shim -- re-exports everything from the split modules:
  user_repo, session_repo, invite_repo, friend_repo
"""

# User CRUD and password hashing
from praxis_core.persistence.user_repo import (  # noqa: F401
    USERS_SCHEMA,
    ENTITIES_SCHEMA,
    hash_password,
    verify_password,
    ensure_schema,
    create_user,
    get_user,
    get_user_by_username,
    get_user_by_email,
    authenticate_user,
    list_users,
    update_user_password,
    delete_user,
)

# Session lifecycle
from praxis_core.persistence.session_repo import (  # noqa: F401
    create_session,
    get_session,
    validate_session,
    delete_session,
    delete_user_sessions,
    cleanup_expired_sessions,
)

# Invitations
from praxis_core.persistence.invite_repo import (  # noqa: F401
    create_invitation,
    list_invitations,
    get_invitation_by_token,
    validate_invitation,
    accept_invitation,
    revoke_invitation,
)

# Friends
from praxis_core.persistence.friend_repo import (  # noqa: F401
    FRIENDS_SCHEMA,
    list_friends,
    add_friend,
    remove_friend,
    are_friends,
)
