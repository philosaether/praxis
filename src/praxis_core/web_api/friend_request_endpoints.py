"""Friend request API endpoints."""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from praxis_core.model import User
from praxis_core.persistence.friend_request_repo import (
    send_request,
    list_incoming,
    list_outgoing,
    list_unseen_accepted,
    accept_request,
    decline_request,
    cancel_request,
    mark_accepted_seen,
    get_notification_counts,
)
from praxis_core.web_api.auth import get_current_user


router = APIRouter()


# -----------------------------------------------------------------------------
# Request/Response Models
# -----------------------------------------------------------------------------

class SendRequestBody(BaseModel):
    to_user_id: int


class FriendRequestResponse(BaseModel):
    id: str
    username: str
    created_at: str


class NotificationCountsResponse(BaseModel):
    pending_incoming: int
    unseen_accepted: int
    total: int


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@router.post("")
async def send_friend_request(
    body: SendRequestBody,
    user: User = Depends(get_current_user),
):
    """Send a friend request to another user."""
    try:
        result = send_request(user.id, body.to_user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.get("/incoming", response_model=list[FriendRequestResponse])
async def list_incoming_requests(user: User = Depends(get_current_user)):
    """List pending friend requests sent TO the current user."""
    rows = list_incoming(user.id)
    return [
        FriendRequestResponse(
            id=r["id"],
            username=r["username"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.get("/outgoing", response_model=list[FriendRequestResponse])
async def list_outgoing_requests(user: User = Depends(get_current_user)):
    """List pending friend requests sent BY the current user."""
    rows = list_outgoing(user.id)
    return [
        FriendRequestResponse(
            id=r["id"],
            username=r["username"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.get("/notifications", response_model=NotificationCountsResponse)
async def get_notifications(user: User = Depends(get_current_user)):
    """Get notification counts for the friends badge."""
    return get_notification_counts(user.id)


@router.get("/accepted")
async def list_accepted_notifications(user: User = Depends(get_current_user)):
    """List accepted requests the sender hasn't seen yet."""
    return list_unseen_accepted(user.id)


@router.post("/{request_id}/accept")
async def accept_friend_request(
    request_id: str,
    user: User = Depends(get_current_user),
):
    """Accept a pending friend request. Only the recipient can accept."""
    success = accept_request(request_id, user.id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot accept this request")
    return {"success": True}


@router.post("/{request_id}/decline")
async def decline_friend_request(
    request_id: str,
    user: User = Depends(get_current_user),
):
    """Decline a pending friend request. Only the recipient can decline."""
    success = decline_request(request_id, user.id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot decline this request")
    return {"success": True}


@router.post("/{request_id}/cancel")
async def cancel_friend_request(
    request_id: str,
    user: User = Depends(get_current_user),
):
    """Cancel a pending friend request. Only the sender can cancel."""
    success = cancel_request(request_id, user.id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot cancel this request")
    return {"success": True}


@router.post("/mark-seen")
async def mark_seen(user: User = Depends(get_current_user)):
    """Mark all accepted notifications as seen."""
    count = mark_accepted_seen(user.id)
    return {"marked": count}
