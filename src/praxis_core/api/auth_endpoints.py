"""Authentication API endpoints."""

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from praxis_core.model import User, Session, SessionType
from praxis_core.persistence import (
    authenticate_user,
    create_session,
    delete_session,
    delete_user_sessions,
)
from praxis_core.api.auth import get_current_user


router = APIRouter()


# -----------------------------------------------------------------------------
# Request/Response Models
# -----------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    session_id: str
    user_id: int
    username: str
    role: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str | None
    role: str
    is_active: bool


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@router.post("/login", response_model=LoginResponse)
async def login(request: Request, credentials: LoginRequest):
    """
    Authenticate with username and password.

    Returns a session token for subsequent API calls.
    Use the session_id as a Bearer token in the Authorization header.
    """
    user = authenticate_user(credentials.username, credentials.password)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password",
        )

    # Extract request metadata for session
    user_agent = request.headers.get("User-Agent")
    # Get client IP (handle proxies)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip_address = forwarded.split(",")[0].strip()
    else:
        ip_address = request.client.host if request.client else None

    # Create session
    session = create_session(
        user_id=user.id,
        session_type=SessionType.API,
        user_agent=user_agent,
        ip_address=ip_address,
    )

    return LoginResponse(
        session_id=session.id,
        user_id=user.id,
        username=user.username,
        role=user.role.value,
    )


@router.post("/logout")
async def logout(user: User = Depends(get_current_user)):
    """
    Logout the current user.

    Invalidates all sessions for this user.
    """
    count = delete_user_sessions(user.id)
    return {"message": "Logged out", "sessions_invalidated": count}


@router.post("/logout/session/{session_id}")
async def logout_session(
    session_id: str,
    user: User = Depends(get_current_user),
):
    """
    Logout a specific session.

    Only the session owner can logout their own sessions.
    """
    # Verify the session belongs to this user
    from praxis_core.persistence import get_session
    session = get_session(session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    delete_session(session_id)
    return {"message": "Session invalidated"}


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    """Get the current authenticated user's information."""
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role.value,
        is_active=user.is_active,
    )
