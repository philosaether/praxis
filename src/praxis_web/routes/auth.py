"""
Authentication routes: login, logout, signup, invite acceptance.
"""

import httpx
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Annotated

from praxis_web.rendering import (
    templates,
    api_client,
    API_URL,
    SESSION_COOKIE_NAME,
)

router = APIRouter()


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
    async with httpx.AsyncClient(base_url=API_URL, timeout=30.0) as client:
        response = await client.post(
            "/api/auth/login",
            json={"username": username, "password": password}
        )

        if response.status_code != 200:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Invalid username or password"},
                status_code=401
            )

        data = response.json()
        session_id = data["session_id"]

        # Set session cookie and redirect to home
        redirect = RedirectResponse(url="/", status_code=302)
        redirect.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            samesite="lax",
            # secure=True,  # Enable in production with HTTPS
            max_age=7 * 24 * 60 * 60,  # 7 days
        )
        return redirect


# -----------------------------------------------------------------------------
# Logout
# -----------------------------------------------------------------------------

@router.get("/logout")
@router.post("/logout")
async def logout(request: Request):
    """Log out and clear session."""
    session_token = request.cookies.get(SESSION_COOKIE_NAME)

    # Call API to invalidate session
    if session_token:
        async with api_client(request) as client:
            await client.post("/api/auth/logout")

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
    async with api_client(request) as client:
        await client.post("/api/auth/tutorial-completed")
    return {"message": "Tutorial marked as completed"}


# -----------------------------------------------------------------------------
# Signup
# -----------------------------------------------------------------------------

@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request, error: str | None = None, invite_token: str | None = None):
    """Display signup page."""
    # If already logged in, redirect to home
    if request.cookies.get(SESSION_COOKIE_NAME):
        return RedirectResponse(url="/", status_code=302)
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
    """Handle signup form submission."""
    # Validate passwords match
    if password != password_confirm:
        return templates.TemplateResponse(
            request,
            "signup.html",
            {"error": "Passwords do not match", "invite_token": invite_token},
            status_code=400
        )

    async with httpx.AsyncClient(base_url=API_URL, timeout=30.0) as client:
        register_data = {"username": username, "password": password}
        if invite_token:
            register_data["invite_token"] = invite_token
        response = await client.post(
            "/api/auth/register",
            json=register_data
        )

        if response.status_code != 200:
            error_data = response.json()
            error_msg = error_data.get("detail", "Registration failed")
            return templates.TemplateResponse(
                request,
                "signup.html",
                {"error": error_msg, "invite_token": invite_token},
                status_code=400
            )

        # Registration successful - log them in automatically
        login_response = await client.post(
            "/api/auth/login",
            json={"username": username, "password": password}
        )

        if login_response.status_code == 200:
            data = login_response.json()
            session_id = data["session_id"]

            redirect = RedirectResponse(url="/", status_code=302)
            redirect.set_cookie(
                key=SESSION_COOKIE_NAME,
                value=session_id,
                httponly=True,
                samesite="lax",
                max_age=7 * 24 * 60 * 60,
            )
            return redirect

        # Fallback: redirect to login page
        return RedirectResponse(url="/login", status_code=302)


# -----------------------------------------------------------------------------
# Invite Acceptance
# -----------------------------------------------------------------------------

@router.get("/invite/{token}", response_class=HTMLResponse)
async def invite_page(request: Request, token: str):
    """Display invite acceptance page."""
    # Validate the token
    async with httpx.AsyncClient(base_url=API_URL, timeout=30.0) as client:
        response = await client.get(f"/api/invites/validate/{token}")
        data = response.json()

    if not data.get("valid"):
        return templates.TemplateResponse(
            request,
            "invite.html",
            {"valid": False, "error": "This invitation is invalid or has expired."}
        )

    # Check if user is already logged in
    if request.cookies.get(SESSION_COOKIE_NAME):
        # Could add "accept while logged in" flow here
        # For now, redirect to home with a message
        return templates.TemplateResponse(
            request,
            "invite.html",
            {
                "valid": True,
                "logged_in": True,
                "inviter_username": data.get("inviter_username"),
                "token": token,
            }
        )

    # Show signup form with invite context
    return templates.TemplateResponse(
        request,
        "invite.html",
        {
            "valid": True,
            "logged_in": False,
            "inviter_username": data.get("inviter_username"),
            "email": data.get("email"),
            "token": token,
        }
    )
