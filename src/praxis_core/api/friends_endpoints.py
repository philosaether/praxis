"""Friends API endpoints."""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from praxis_core.model import User
from praxis_core.persistence.user_persistence import (
    list_friends,
    remove_friend,
)
from praxis_core.api.auth import get_current_user


router = APIRouter()


# -----------------------------------------------------------------------------
# Response Models
# -----------------------------------------------------------------------------

class FriendResponse(BaseModel):
    id: int
    username: str
    email: str | None = None
    entity_id: str | None = None
    friends_since: str | None = None


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@router.get("", response_model=list[FriendResponse])
async def list_my_friends(user: User = Depends(get_current_user)):
    """
    List the current user's friends.
    Used for the share dropdown (only friends can be shared with).
    """
    friends = list_friends(user.id)
    return [
        FriendResponse(
            id=f["id"],
            username=f["username"],
            email=f.get("email"),
            entity_id=f.get("entity_id"),
            friends_since=f.get("friends_since"),
        )
        for f in friends
    ]


@router.delete("/{friend_user_id}")
async def remove_my_friend(
    friend_user_id: int,
    user: User = Depends(get_current_user),
):
    """Remove a friend (bidirectional)."""
    if friend_user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot unfriend yourself")

    success = remove_friend(user.id, friend_user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Friend not found")

    return {"success": True}
