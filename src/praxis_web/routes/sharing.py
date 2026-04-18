"""Sharing routes — friends, invites, friend requests, and priority sharing."""

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

    list_html = await _render_friends_list(request)
    return await render_full_page(request, mode="friends", initial_list_html=list_html)


@router.get("/friends/list", response_class=HTMLResponse)
async def friends_list_partial(request: Request):
    """HTMX partial: full friends list with requests, search, and notifications."""
    html = await _render_friends_list(request, as_template_response=True, http_request=request)
    return html


async def _render_friends_list(request: Request, as_template_response=False, http_request=None):
    """Fetch all friends data and render the list. Shared by full-page and partial routes."""
    async with api_client(request) as client:
        friends_resp = await client.get("/api/friends")
        friends = friends_resp.json() if friends_resp.status_code == 200 else []

        incoming_resp = await client.get("/api/friend-requests/incoming")
        incoming = incoming_resp.json() if incoming_resp.status_code == 200 else []

        outgoing_resp = await client.get("/api/friend-requests/outgoing")
        outgoing = outgoing_resp.json() if outgoing_resp.status_code == 200 else []

        accepted_resp = await client.get("/api/friend-requests/accepted")
        accepted = accepted_resp.json() if accepted_resp.status_code == 200 else []

        # Mark accepted notifications as seen now that we're rendering them
        if accepted:
            await client.post("/api/friend-requests/mark-seen")

    ctx = {
        "friends": friends,
        "incoming_requests": incoming,
        "outgoing_requests": outgoing,
        "accepted_notifications": accepted,
    }

    if as_template_response:
        return templates.TemplateResponse(http_request, "partials/friends_list.html", ctx)

    return templates.get_template("partials/friends_list.html").render(**ctx)


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
# Groups
# ---------------------------------------------------------------------------

@router.post("/groups", response_class=HTMLResponse)
async def create_group(request: Request):
    """Create a group entity."""
    form = await request.form()
    name = form.get("name", "").strip()
    member_ids = [int(uid) for uid in form.getlist("member_ids") if uid]

    async with api_client(request) as client:
        response = await client.post(
            "/api/auth/groups",
            json={"name": name, "member_ids": member_ids}
        )
        if response.status_code != 200:
            return HTMLResponse(content="<div class='error'>Failed to create group</div>")

    # Re-render friends list to show the new group
    return await _render_friends_list(request, as_template_response=True)


# ---------------------------------------------------------------------------
# Friend Requests
# ---------------------------------------------------------------------------

@router.post("/friends/request/{user_id}", response_class=HTMLResponse)
async def send_friend_request(request: Request, user_id: int):
    """Send a friend request and refresh the search results."""
    async with api_client(request) as client:
        response = await client.post(
            "/api/friend-requests",
            json={"to_user_id": user_id}
        )
        if response.status_code != 200:
            error = response.json().get("detail", "Failed to send request") if response.content else "Failed"
            return HTMLResponse(content=f"<div class='error'>{error}</div>", status_code=400)

    # Return a confirmation that replaces the search result row
    return HTMLResponse(content='<div class="friend-request-sent">Request sent</div>')


@router.post("/friends/request/{request_id}/accept", response_class=HTMLResponse)
async def accept_request(request: Request, request_id: str):
    """Accept a friend request and refresh the friends list."""
    async with api_client(request) as client:
        response = await client.post(f"/api/friend-requests/{request_id}/accept")
        if response.status_code != 200:
            return HTMLResponse(content="<div class='error'>Failed to accept</div>", status_code=400)

    # Refresh the full friends list to show the new friend
    return await friends_list_partial(request)


@router.post("/friends/request/{request_id}/decline", response_class=HTMLResponse)
async def decline_request(request: Request, request_id: str):
    """Decline a friend request and remove the row."""
    async with api_client(request) as client:
        response = await client.post(f"/api/friend-requests/{request_id}/decline")
        if response.status_code != 200:
            return HTMLResponse(content="<div class='error'>Failed to decline</div>", status_code=400)

    # Refresh the full friends list
    return await friends_list_partial(request)


@router.post("/friends/request/{request_id}/cancel", response_class=HTMLResponse)
async def cancel_request(request: Request, request_id: str):
    """Cancel an outgoing friend request."""
    async with api_client(request) as client:
        response = await client.post(f"/api/friend-requests/{request_id}/cancel")
        if response.status_code != 200:
            return HTMLResponse(content="<div class='error'>Failed to cancel</div>", status_code=400)

    # Refresh the full friends list
    return await friends_list_partial(request)


# ---------------------------------------------------------------------------
# User Search
# ---------------------------------------------------------------------------

@router.get("/friends/search", response_class=HTMLResponse)
async def search_users_partial(request: Request, q: str = ""):
    """HTMX partial: search results for adding friends."""
    if not q.strip():
        return HTMLResponse(content="")

    async with api_client(request) as client:
        response = await client.get("/api/auth/users/search", params={"q": q})
        results = response.json() if response.status_code == 200 else []

    return templates.TemplateResponse(
        request,
        "partials/friends_search_results.html",
        {"results": results, "query": q}
    )


# ---------------------------------------------------------------------------
# Priority Adoption
# ---------------------------------------------------------------------------

@router.post("/priorities/{priority_id}/adopt", response_class=HTMLResponse)
async def adopt_priority(request: Request, priority_id: str):
    """Adopt a shared priority into your own tree."""
    data = await request.json()
    parent_priority_id = data.get("parent_priority_id")

    async with api_client(request) as client:
        response = await client.post(
            f"/api/priorities/{priority_id}/adopt",
            json={"parent_priority_id": parent_priority_id}
        )

        if response.status_code != 200:
            try:
                error_data = response.json()
            except Exception:
                error_data = {"detail": response.text or "Failed to adopt"}
            return Response(
                content=json.dumps({"success": False, "error": error_data.get("detail", "Failed to adopt")}),
                media_type="application/json",
                status_code=response.status_code
            )

        return Response(
            content=json.dumps({"success": True}),
            media_type="application/json"
        )


@router.delete("/priorities/{priority_id}/adopt", response_class=HTMLResponse)
async def unadopt_priority(request: Request, priority_id: str):
    """Remove adoption, return to Shared with Me."""
    async with api_client(request) as client:
        response = await client.delete(f"/api/priorities/{priority_id}/adopt")

        if response.status_code != 200:
            error_data = response.json() if response.content else {}
            return Response(
                content=json.dumps({"success": False, "error": error_data.get("detail", "Failed")}),
                media_type="application/json",
                status_code=response.status_code
            )

        return Response(
            content=json.dumps({"success": True}),
            media_type="application/json"
        )


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
    allow_adoption = data.get("allow_adoption", False)

    if not user_id:
        return Response(
            content=json.dumps({"success": False, "error": "User ID required"}),
            media_type="application/json",
            status_code=400
        )

    async with api_client(request) as client:
        response = await client.post(
            f"/api/priorities/{priority_id}/share",
            json={"user_id": user_id, "permission": permission, "allow_adoption": allow_adoption}
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
