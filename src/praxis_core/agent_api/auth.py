"""Authentication dependencies for agent API endpoints."""

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
    1. Authorization: Bearer <token> header (session token or API key)

    Raises 401 if not authenticated.
    """
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
