"""Authentication dependencies for FastAPI endpoints."""

from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from praxis_core.model import User
from praxis_core.persistence import validate_session


# Optional bearer token security (doesn't require auth, just extracts if present)
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> User:
    """
    Dependency that extracts and validates the authenticated user.

    Checks for auth in this order:
    1. Authorization: Bearer <token> header
    2. request.state.user (set by middleware)

    Raises 401 if not authenticated.
    """
    # First, check if middleware already set the user
    user = getattr(request.state, "user", None)
    if user is not None:
        return user

    # Try bearer token from Authorization header
    if credentials is not None:
        token = credentials.credentials

        # 1. Try session token
        result = validate_session(token)
        if result is not None:
            session, user = result
            request.state.user = user
            request.state.session = session
            return user

        # 2. Try API key (praxis_... format)
        from praxis_core.persistence.api_key_repo import validate_api_key
        user = validate_api_key(token)
        if user is not None:
            request.state.user = user
            return user

    raise HTTPException(
        status_code=401,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> User | None:
    """
    Dependency that returns the authenticated user or None.

    Use this for endpoints that work with or without auth.
    """
    # Check middleware-set user
    user = getattr(request.state, "user", None)
    if user is not None:
        return user

    # Try bearer token
    if credentials is not None:
        token = credentials.credentials

        result = validate_session(token)
        if result is not None:
            session, user = result
            request.state.user = user
            request.state.session = session
            return user

        from praxis_core.persistence.api_key_repo import validate_api_key
        user = validate_api_key(token)
        if user is not None:
            request.state.user = user
            return user

    return None


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Dependency that requires the user to be an admin."""
    from praxis_core.model import UserRole
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Admin access required",
        )
    return user


async def get_current_user_from_request(request: Request) -> User | None:
    """
    Get the current user from request state (set by middleware).

    Use this for non-FastAPI-dependency contexts where you have
    direct access to the request object.
    """
    return getattr(request.state, "user", None)
