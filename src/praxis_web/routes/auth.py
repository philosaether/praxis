"""
Authentication routes: login, logout, signup, invite acceptance.

Direct persistence calls — no httpx proxy.
"""

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Annotated

from praxis_core.persistence import (
    create_user,
    authenticate_user,
    create_session,
    validate_session,
    delete_session,
    delete_user_sessions,
    get_user_by_username,
    mark_tutorial_completed,
)
from praxis_core.persistence.invite_repo import (
    get_invitation_by_token,
    validate_invitation,
    accept_invitation,
)
from praxis_core.model.users import SessionType
from praxis_web.rendering import SESSION_COOKIE_NAME, templates

router = APIRouter()


def _session_cookie(redirect: RedirectResponse, session_id: str) -> RedirectResponse:
    """Set the standard session cookie on a redirect response."""
    redirect.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        samesite="lax",
        # secure=True,  # Enable in production with HTTPS
        max_age=7 * 24 * 60 * 60,  # 7 days
    )
    return redirect


def _extract_request_meta(request: Request) -> tuple[str | None, str | None]:
    """Extract user_agent and ip_address from a request."""
    user_agent = request.headers.get("User-Agent")
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip_address = forwarded.split(",")[0].strip()
    else:
        ip_address = request.client.host if request.client else None
    return user_agent, ip_address


# -----------------------------------------------------------------------------
# Login
# -----------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    """Display login page."""
    # If already logged in, redirect to home
    if request.cookies.get(SESSION_COOKIE_NAME):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": error}
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    """Handle login form submission."""
    user = authenticate_user(username, password)
    if user is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid username or password"},
            status_code=401
        )

    user_agent, ip_address = _extract_request_meta(request)
    session = create_session(
        user_id=user.id,
        session_type=SessionType.WEB,
        user_agent=user_agent,
        ip_address=ip_address,
    )

    redirect = RedirectResponse(url="/", status_code=302)
    return _session_cookie(redirect, session.id)


# -----------------------------------------------------------------------------
# Logout
# -----------------------------------------------------------------------------

@router.get("/logout")
@router.post("/logout")
async def logout(request: Request):
    """Log out and clear session."""
    session_token = request.cookies.get(SESSION_COOKIE_NAME)

    if session_token:
        result = validate_session(session_token)
        if result:
            _, user = result
            delete_user_sessions(user.id)

    # Clear cookie and redirect to login
    redirect = RedirectResponse(url="/login", status_code=302)
    redirect.delete_cookie(key=SESSION_COOKIE_NAME)
    return redirect


# -----------------------------------------------------------------------------
# Tutorial
# -----------------------------------------------------------------------------

@router.post("/tutorial-completed")
async def tutorial_completed(request: Request):
    """Mark the onboarding tutorial as completed."""
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        result = validate_session(session_token)
        if result:
            _, user = result
            mark_tutorial_completed(user.id)
    return {"message": "Tutorial marked as completed"}


# -----------------------------------------------------------------------------
# Signup
# -----------------------------------------------------------------------------

@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request, error: str | None = None, invite_token: str | None = None):
    """Display signup page. Requires a valid invite token."""
    # If already logged in, redirect to home
    if request.cookies.get(SESSION_COOKIE_NAME):
        return RedirectResponse(url="/", status_code=302)
    # No invite token — redirect to login
    if not invite_token:
        return RedirectResponse(url="/login", status_code=302)
    # Invalid/expired token — redirect to login
    if validate_invitation(invite_token) is None:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        request,
        "signup.html",
        {"error": error, "invite_token": invite_token}
    )


@router.post("/signup")
async def signup_submit(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()],
    invite_token: Annotated[str | None, Form()] = None,
):
    """Handle signup form submission. Requires a valid invite token."""
    # Reject signup without invite token
    if not invite_token:
        return templates.TemplateResponse(
            request,
            "signup.html",
            {"error": "An invitation is required to create an account."},
            status_code=403
        )

    # Validate passwords match
    if password != password_confirm:
        return templates.TemplateResponse(
            request,
            "signup.html",
            {"error": "Passwords do not match", "invite_token": invite_token},
            status_code=400
        )

    # Validate username format
    clean_username = username.strip()
    if len(clean_username) < 3:
        return templates.TemplateResponse(
            request,
            "signup.html",
            {"error": "Username must be at least 3 characters", "invite_token": invite_token},
            status_code=400
        )
    if len(clean_username) > 50:
        return templates.TemplateResponse(
            request,
            "signup.html",
            {"error": "Username must be 50 characters or less", "invite_token": invite_token},
            status_code=400
        )
    if not clean_username.replace("_", "").replace("-", "").isalnum():
        return templates.TemplateResponse(
            request,
            "signup.html",
            {"error": "Username can only contain letters, numbers, underscores, and hyphens", "invite_token": invite_token},
            status_code=400
        )

    # Validate password length
    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "signup.html",
            {"error": "Password must be at least 8 characters", "invite_token": invite_token},
            status_code=400
        )

    # Check if username already exists
    if get_user_by_username(clean_username) is not None:
        return templates.TemplateResponse(
            request,
            "signup.html",
            {"error": "Username already taken", "invite_token": invite_token},
            status_code=400
        )

    # Validate invite token if provided
    invitation = None
    if invite_token:
        invitation = validate_invitation(invite_token)
        if invitation is None:
            return templates.TemplateResponse(
                request,
                "signup.html",
                {"error": "Invalid or expired invitation", "invite_token": invite_token},
                status_code=400
            )

    # Create the user
    user = create_user(username=clean_username, password=password)

    # Accept invitation and create friendship
    if invitation:
        accept_invitation(invite_token, user.id)

    # Create session and log in automatically
    user_agent, ip_address = _extract_request_meta(request)
    session = create_session(
        user_id=user.id,
        session_type=SessionType.WEB,
        user_agent=user_agent,
        ip_address=ip_address,
    )

    redirect = RedirectResponse(url="/", status_code=302)
    return _session_cookie(redirect, session.id)


# -----------------------------------------------------------------------------
# Invite Acceptance
# -----------------------------------------------------------------------------

@router.get("/invite/{token}", response_class=HTMLResponse)
async def invite_page(request: Request, token: str):
    """Display invite acceptance page."""
    invitation = get_invitation_by_token(token)

    if invitation is None or invitation["status"] != "pending":
        return templates.TemplateResponse(
            request,
            "invite.html",
            {"valid": False, "error": "This invitation is invalid or has expired."}
        )

    # Check expiry
    from datetime import datetime
    expires_at = datetime.fromisoformat(invitation["expires_at"])
    if expires_at < datetime.now():
        return templates.TemplateResponse(
            request,
            "invite.html",
            {"valid": False, "error": "This invitation is invalid or has expired."}
        )

    # If logged in, accept the invite directly (creates friendship)
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        result = validate_session(session_token)
        if result:
            _, user = result
            accept_invitation(token, user.id)
            return RedirectResponse(url="/", status_code=302)

    # Show signup form with invite context
    return templates.TemplateResponse(
        request,
        "invite.html",
        {
            "valid": True,
            "inviter_username": invitation.get("inviter_username"),
            "email": invitation.get("email"),
            "token": token,
        }
    )
