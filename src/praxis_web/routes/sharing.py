"""Sharing routes — friends, invites, and priority sharing."""

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from praxis_web.rendering import templates, api_client, is_htmx_request, render_full_page

router = APIRouter()


# ---------------------------------------------------------------------------
# Friends
# ---------------------------------------------------------------------------

@router.get("/friends", response_class=HTMLResponse)
async def friends_page(request: Request):
    """Friends view - full page or HTMX partial."""
    if is_htmx_request(request):
        return await friends_list_partial(request)

    # For full page, render the friends list
    async with api_client(request) as client:
        response = await client.get("/api/friends")
        friends = response.json() if response.status_code == 200 else []

    list_html = templates.get_template("partials/friends_list.html").render(
        friends=friends
    )

    return await render_full_page(request, mode="friends", initial_list_html=list_html)


@router.get("/friends/list", response_class=HTMLResponse)
async def friends_list_partial(request: Request):
    """HTMX partial: list of friends."""
    async with api_client(request) as client:
        response = await client.get("/api/friends")
        friends = response.json() if response.status_code == 200 else []

    return templates.TemplateResponse(
        request,
        "partials/friends_list.html",
        {"friends": friends}
    )


@router.delete("/friends/{friend_id}", response_class=HTMLResponse)
async def remove_friend(request: Request, friend_id: int):
    """Remove a friend."""
    async with api_client(request) as client:
        response = await client.delete(f"/api/friends/{friend_id}")
        if response.status_code != 200:
            return HTMLResponse(content="<div class='error'>Failed to remove friend</div>")

    # Return empty content to remove the row
    return HTMLResponse(content="")


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------

@router.post("/invites")
async def create_invite(request: Request):
    """Create an invite and return the token."""
    async with api_client(request) as client:
        response = await client.post("/api/invites", json={})

        if response.status_code != 200:
            error_data = response.json() if response.content else {}
            return Response(
                content=json.dumps({"error": error_data.get("detail", "Failed to create invite")}),
                media_type="application/json",
                status_code=response.status_code
            )

        return Response(
            content=response.content,
            media_type="application/json"
        )


# ---------------------------------------------------------------------------
# User lookup (for share dropdown)
# ---------------------------------------------------------------------------

@router.get("/users", response_class=HTMLResponse)
async def get_users_for_share(request: Request):
    """Get list of friends for share dropdown (only friends can be shared with)."""
    async with api_client(request) as client:
        response = await client.get("/api/friends")
        if response.status_code != 200:
            return HTMLResponse(content="[]")
        friends = response.json()
    return Response(content=json.dumps(friends), media_type="application/json")


# ---------------------------------------------------------------------------
# Priority sharing
# ---------------------------------------------------------------------------

@router.post("/priorities/{priority_id}/share")
async def share_priority(request: Request, priority_id: str):
    """Share a priority with another user."""
    data = await request.json()
    user_id = data.get("user_id")
    permission = data.get("permission", "contributor")

    if not user_id:
        return Response(
            content=json.dumps({"success": False, "error": "User ID required"}),
            media_type="application/json",
            status_code=400
        )

    async with api_client(request) as client:
        response = await client.post(
            f"/api/priorities/{priority_id}/share",
            json={"user_id": user_id, "permission": permission}
        )

        if response.status_code != 200:
            error_data = response.json() if response.content else {}
            return Response(
                content=json.dumps({
                    "success": False,
                    "error": error_data.get("detail", "Failed to share")
                }),
                media_type="application/json",
                status_code=response.status_code
            )

        return Response(
            content=json.dumps({"success": True}),
            media_type="application/json"
        )
