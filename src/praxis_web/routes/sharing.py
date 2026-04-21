"""Sharing routes — friends, invites, friend requests, and priority sharing.

Direct persistence calls — no httpx proxy.
"""

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from praxis_web.rendering import templates, SESSION_COOKIE_NAME, is_htmx_request, render_full_page

from praxis_core.persistence import validate_session
from praxis_core.persistence.friend_repo import list_friends, remove_friend
from praxis_core.persistence.friend_request_repo import (
    send_request,
    accept_request as do_accept_request,
    decline_request as do_decline_request,
    cancel_request as do_cancel_request,
    list_incoming,
    list_outgoing,
    list_unseen_accepted,
    mark_accepted_seen,
    get_notification_counts,
)
from praxis_core.persistence.invite_repo import create_invitation
from praxis_core.persistence.user_repo import search_users, create_group, list_user_groups, get_user
from praxis_core.persistence.database import get_connection
from praxis_core.persistence.priority_sharing import can_adopt as check_adopt
from praxis_core.persistence.priority_placement_repo import (
    adopt_priority as do_adopt,
    unadopt_priority as do_unadopt,
)
from praxis_core.serialization import get_graph, clear_graph_cache

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user(request: Request):
    """Get authenticated user from session cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    result = validate_session(token)
    if result is None:
        return None
    session, user = result
    return user


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
    user = _get_user(request)
    if not user:
        ctx = {
            "friends": [],
            "incoming_requests": [],
            "outgoing_requests": [],
            "accepted_notifications": [],
            "groups": [],
        }
        if as_template_response:
            return templates.TemplateResponse(http_request, "partials/friends_list.html", ctx)
        return templates.get_template("partials/friends_list.html").render(**ctx)

    friends = list_friends(user.id)
    incoming = list_incoming(user.id)
    outgoing = list_outgoing(user.id)
    accepted = list_unseen_accepted(user.id)

    # Mark accepted notifications as seen now that we're rendering them
    if accepted:
        mark_accepted_seen(user.id)

    groups = list_user_groups(user.id)

    ctx = {
        "friends": friends,
        "incoming_requests": incoming,
        "outgoing_requests": outgoing,
        "accepted_notifications": accepted,
        "groups": groups,
    }

    if as_template_response:
        return templates.TemplateResponse(http_request, "partials/friends_list.html", ctx)

    return templates.get_template("partials/friends_list.html").render(**ctx)


@router.delete("/friends/{friend_id}", response_class=HTMLResponse)
async def remove_friend_route(request: Request, friend_id: int):
    """Remove a friend."""
    user = _get_user(request)
    if not user:
        return HTMLResponse(content="<div class='error'>Not authenticated</div>", status_code=401)

    if friend_id == user.id:
        return HTMLResponse(content="<div class='error'>Cannot unfriend yourself</div>", status_code=400)

    success = remove_friend(user.id, friend_id)
    if not success:
        return HTMLResponse(content="<div class='error'>Failed to remove friend</div>")

    # Return empty content to remove the row
    return HTMLResponse(content="")


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

@router.post("/groups")
async def create_group_route(request: Request):
    """Create a group entity."""
    user = _get_user(request)
    if not user:
        return Response(content='{"error": "Not authenticated"}', status_code=401,
                        media_type="application/json")

    body = await request.json()
    name = body.get("name", "").strip()
    member_ids = body.get("member_ids", [])

    if not name:
        return Response(content='{"error": "Group name is required"}', status_code=400,
                        media_type="application/json")

    entity_id = create_group(name, user.id, member_ids)
    return Response(
        content=json.dumps({"ok": True, "entity_id": entity_id}),
        media_type="application/json",
    )


@router.get("/groups/{entity_id}", response_class=HTMLResponse)
async def group_detail(request: Request, entity_id: str):
    """Show group detail with members."""
    user = _get_user(request)
    if not user:
        return HTMLResponse(content="<div class='error'>Not authenticated</div>", status_code=401)

    with get_connection() as conn:
        entity = conn.execute("SELECT * FROM entities WHERE id = ? AND type = 'group'", (entity_id,)).fetchone()
        if not entity:
            return HTMLResponse(content="<div class='error'>Group not found</div>")

        # Check user is a member
        membership = conn.execute(
            "SELECT role FROM entity_members WHERE entity_id = ? AND user_id = ?",
            (entity_id, user.id)
        ).fetchone()
        if not membership:
            return HTMLResponse(content="<div class='error'>Not a member of this group</div>")

        members = conn.execute(
            """SELECT u.id, u.username, u.entity_id, em.role
               FROM entity_members em
               JOIN users u ON em.user_id = u.id
               WHERE em.entity_id = ?
               ORDER BY em.role, u.username""",
            (entity_id,)
        ).fetchall()

    group = {
        "entity_id": entity_id,
        "name": entity["name"],
        "members": [dict(m) for m in members],
        "user_role": membership["role"],
    }

    # Filter friends to only those not already in the group
    friends = list_friends(user.id)
    member_ids = {m["id"] for m in group.get("members", [])}
    non_members = [f for f in friends if f["id"] not in member_ids]

    return templates.TemplateResponse(
        request,
        "partials/group_detail.html",
        {
            "group": group,
            "non_members": non_members,
            "is_owner": group.get("user_role") == "owner",
            "current_user_id": user.id,
        }
    )


@router.post("/groups/{entity_id}/members/{user_id}", response_class=HTMLResponse)
async def add_group_member(request: Request, entity_id: str, user_id: int):
    """Add a member and refresh the group detail."""
    user = _get_user(request)
    if not user:
        return HTMLResponse(content="<div class='error'>Not authenticated</div>", status_code=401)

    with get_connection() as conn:
        membership = conn.execute(
            "SELECT role FROM entity_members WHERE entity_id = ? AND user_id = ?",
            (entity_id, user.id)
        ).fetchone()
        if not membership or membership["role"] != "owner":
            return HTMLResponse(content="<div class='error'>Only owners can add members</div>", status_code=403)

        conn.execute(
            "INSERT OR IGNORE INTO entity_members (entity_id, user_id, role, created_at) VALUES (?, ?, 'member', datetime('now'))",
            (entity_id, user_id),
        )

    return await group_detail(request, entity_id)


@router.delete("/groups/{entity_id}/members/{user_id}", response_class=HTMLResponse)
async def remove_group_member(request: Request, entity_id: str, user_id: int):
    """Remove a member and refresh the group detail."""
    user = _get_user(request)
    if not user:
        return HTMLResponse(content="<div class='error'>Not authenticated</div>", status_code=401)

    with get_connection() as conn:
        membership = conn.execute(
            "SELECT role FROM entity_members WHERE entity_id = ? AND user_id = ?",
            (entity_id, user.id)
        ).fetchone()
        if not membership or membership["role"] != "owner":
            return HTMLResponse(content="<div class='error'>Only owners can remove members</div>", status_code=403)

        if user_id == user.id:
            return HTMLResponse(content="<div class='error'>Cannot remove yourself</div>", status_code=400)

        conn.execute(
            "DELETE FROM entity_members WHERE entity_id = ? AND user_id = ?",
            (entity_id, user_id),
        )

    return await group_detail(request, entity_id)


# ---------------------------------------------------------------------------
# Friend Requests
# ---------------------------------------------------------------------------

@router.post("/friends/request/{user_id}", response_class=HTMLResponse)
async def send_friend_request(request: Request, user_id: int):
    """Send a friend request and refresh the search results."""
    user = _get_user(request)
    if not user:
        return HTMLResponse(content="<div class='error'>Not authenticated</div>", status_code=401)

    try:
        send_request(user.id, user_id)
    except ValueError as e:
        return HTMLResponse(content=f"<div class='error'>{e}</div>", status_code=400)

    # Return a confirmation that replaces the search result row
    return HTMLResponse(content='<div class="friend-request-sent">Request sent</div>')


@router.post("/friends/request/{request_id}/accept", response_class=HTMLResponse)
async def accept_request_route(request: Request, request_id: str):
    """Accept a friend request and refresh the friends list."""
    user = _get_user(request)
    if not user:
        return HTMLResponse(content="<div class='error'>Not authenticated</div>", status_code=401)

    success = do_accept_request(request_id, user.id)
    if not success:
        return HTMLResponse(content="<div class='error'>Failed to accept</div>", status_code=400)

    # Refresh the full friends list to show the new friend
    return await friends_list_partial(request)


@router.post("/friends/request/{request_id}/decline", response_class=HTMLResponse)
async def decline_request_route(request: Request, request_id: str):
    """Decline a friend request and remove the row."""
    user = _get_user(request)
    if not user:
        return HTMLResponse(content="<div class='error'>Not authenticated</div>", status_code=401)

    success = do_decline_request(request_id, user.id)
    if not success:
        return HTMLResponse(content="<div class='error'>Failed to decline</div>", status_code=400)

    # Refresh the full friends list
    return await friends_list_partial(request)


@router.post("/friends/request/{request_id}/cancel", response_class=HTMLResponse)
async def cancel_request_route(request: Request, request_id: str):
    """Cancel an outgoing friend request."""
    user = _get_user(request)
    if not user:
        return HTMLResponse(content="<div class='error'>Not authenticated</div>", status_code=401)

    success = do_cancel_request(request_id, user.id)
    if not success:
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

    user = _get_user(request)
    if not user:
        return HTMLResponse(content="")

    results = search_users(q.strip(), user.id)

    return templates.TemplateResponse(
        request,
        "partials/friends_search_results.html",
        {"results": results, "query": q}
    )


# ---------------------------------------------------------------------------
# Priority Adoption
# ---------------------------------------------------------------------------

@router.post("/priorities/{priority_id}/adopt", response_class=HTMLResponse)
async def adopt_priority_route(request: Request, priority_id: str):
    """Adopt a shared priority into your own tree."""
    user = _get_user(request)
    if not user:
        return Response(
            content=json.dumps({"success": False, "error": "Not authenticated"}),
            media_type="application/json",
            status_code=401,
        )

    data = await request.json()
    parent_priority_id = data.get("parent_priority_id")

    entity_id = user.entity_id
    graph = get_graph(entity_id=entity_id)

    # Must be a shared priority (not owned)
    permission = graph.get_permission(priority_id, entity_id)
    if permission == "owner":
        return Response(
            content=json.dumps({"success": False, "error": "Cannot adopt your own priority"}),
            media_type="application/json",
            status_code=400,
        )
    if permission is None:
        return Response(
            content=json.dumps({"success": False, "error": "Priority not found or not shared with you"}),
            media_type="application/json",
            status_code=404,
        )

    # Check if adoption is allowed
    if not check_adopt(get_connection, priority_id, entity_id):
        return Response(
            content=json.dumps({"success": False, "error": "Adoption not allowed for this share"}),
            media_type="application/json",
            status_code=403,
        )

    # Validate parent if provided — must be owned by the adopter
    if parent_priority_id:
        parent = graph.get(parent_priority_id)
        if not parent or parent.entity_id != entity_id:
            return Response(
                content=json.dumps({"success": False, "error": "Parent priority must be one of your own"}),
                media_type="application/json",
                status_code=400,
            )

    result = do_adopt(
        priority_id=priority_id,
        entity_id=entity_id,
        parent_priority_id=parent_priority_id,
        rank=data.get("rank"),
    )

    clear_graph_cache(entity_id)

    return Response(
        content=json.dumps({"success": True, **result}),
        media_type="application/json",
    )


@router.delete("/priorities/{priority_id}/adopt", response_class=HTMLResponse)
async def unadopt_priority_route(request: Request, priority_id: str):
    """Remove adoption, return to Shared with Me."""
    user = _get_user(request)
    if not user:
        return Response(
            content=json.dumps({"success": False, "error": "Not authenticated"}),
            media_type="application/json",
            status_code=401,
        )

    removed = do_unadopt(priority_id, user.entity_id)
    if not removed:
        return Response(
            content=json.dumps({"success": False, "error": "No adoption found"}),
            media_type="application/json",
            status_code=404,
        )

    clear_graph_cache(user.entity_id)

    return Response(
        content=json.dumps({"success": True}),
        media_type="application/json",
    )


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------

@router.post("/invites")
async def create_invite(request: Request):
    """Create an invite and return the token."""
    user = _get_user(request)
    if not user:
        return Response(
            content=json.dumps({"error": "Not authenticated"}),
            media_type="application/json",
            status_code=401,
        )

    invitation = create_invitation(inviter_user_id=user.id, email=None)

    return Response(
        content=json.dumps({
            "id": invitation["id"],
            "token": invitation["token"],
            "email": invitation["email"],
            "expires_at": invitation["expires_at"],
        }),
        media_type="application/json",
    )


# ---------------------------------------------------------------------------
# User lookup (for share dropdown)
# ---------------------------------------------------------------------------

@router.get("/users", response_class=HTMLResponse)
async def get_users_for_share(request: Request):
    """Get list of friends for share dropdown (only friends can be shared with)."""
    user = _get_user(request)
    if not user:
        return Response(content="[]", media_type="application/json")

    friends = list_friends(user.id)
    return Response(content=json.dumps(friends), media_type="application/json")


# ---------------------------------------------------------------------------
# Priority sharing
# ---------------------------------------------------------------------------

@router.post("/priorities/{priority_id}/share")
async def share_priority(request: Request, priority_id: str):
    """Share a priority with another user."""
    user = _get_user(request)
    if not user:
        return Response(
            content=json.dumps({"success": False, "error": "Not authenticated"}),
            media_type="application/json",
            status_code=401,
        )

    data = await request.json()
    target_user_id = data.get("user_id")
    permission = data.get("permission", "contributor")
    allow_adoption = data.get("allow_adoption", False)

    if not target_user_id:
        return Response(
            content=json.dumps({"success": False, "error": "User ID required"}),
            media_type="application/json",
            status_code=400,
        )

    entity_id = user.entity_id
    graph = get_graph(entity_id=entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return Response(
            content=json.dumps({"success": False, "error": "Priority not found"}),
            media_type="application/json",
            status_code=404,
        )

    # Check ownership (entity-based)
    perm = graph.get_permission(priority_id, entity_id)
    if perm != "owner":
        return Response(
            content=json.dumps({"success": False, "error": "Only the owner can share this priority"}),
            media_type="application/json",
            status_code=403,
        )

    # Validate permission level
    if permission not in ("viewer", "contributor", "editor"):
        return Response(
            content=json.dumps({"success": False, "error": "Invalid permission level"}),
            media_type="application/json",
            status_code=400,
        )

    # Can't share with yourself
    if target_user_id == user.id:
        return Response(
            content=json.dumps({"success": False, "error": "Cannot share with yourself"}),
            media_type="application/json",
            status_code=400,
        )

    graph.share_with_user(priority_id, target_user_id, permission, allow_adoption)

    # Clear the target user's graph cache so they see the shared priority
    with get_connection() as conn:
        row = conn.execute(
            "SELECT entity_id FROM users WHERE id = ?", (target_user_id,)
        ).fetchone()
        if row and row["entity_id"]:
            clear_graph_cache(row["entity_id"])

    # Also clear owner's cache so share count updates
    clear_graph_cache(entity_id)

    return Response(
        content=json.dumps({"success": True}),
        media_type="application/json",
    )
