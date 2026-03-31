"""Invitation API endpoints for friend invites."""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from praxis_core.model import User
from praxis_core.persistence.user_persistence import (
    create_invitation,
    list_invitations,
    validate_invitation,
    revoke_invitation,
)
from praxis_core.api.auth import get_current_user


router = APIRouter()


# -----------------------------------------------------------------------------
# Request/Response Models
# -----------------------------------------------------------------------------

class CreateInviteRequest(BaseModel):
    email: str | None = None


class InviteResponse(BaseModel):
    id: str
    token: str
    email: str | None
    expires_at: str


class InviteListItem(BaseModel):
    id: str
    email: str | None
    status: str
    created_at: str
    expires_at: str


class ValidateInviteResponse(BaseModel):
    valid: bool
    inviter_username: str | None = None
    email: str | None = None


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@router.post("", response_model=InviteResponse)
async def create_invite(
    request: CreateInviteRequest,
    user: User = Depends(get_current_user),
):
    """
    Create an invitation to add a friend.
    Returns a token that can be shared with the invitee.
    """
    email = request.email.strip().lower() if request.email else None

    invitation = create_invitation(
        inviter_user_id=user.id,
        email=email,
    )

    return InviteResponse(
        id=invitation["id"],
        token=invitation["token"],
        email=invitation["email"],
        expires_at=invitation["expires_at"],
    )


@router.get("", response_model=list[InviteListItem])
async def list_my_invites(
    status: str | None = "pending",
    user: User = Depends(get_current_user),
):
    """List invitations created by the current user."""
    invitations = list_invitations(user.id, status=status)
    return [
        InviteListItem(
            id=inv["id"],
            email=inv["email"],
            status=inv["status"],
            created_at=inv["created_at"],
            expires_at=inv["expires_at"],
        )
        for inv in invitations
    ]


@router.delete("/{invite_id}")
async def revoke_invite(
    invite_id: str,
    user: User = Depends(get_current_user),
):
    """Revoke a pending invitation."""
    success = revoke_invitation(invite_id, user.id)
    if not success:
        raise HTTPException(
            status_code=404,
            detail="Invitation not found or already used",
        )
    return {"success": True}


@router.get("/validate/{token}", response_model=ValidateInviteResponse)
async def validate_invite(token: str):
    """
    Validate an invitation token (no auth required).
    Returns inviter info if valid.
    """
    invitation = validate_invitation(token)
    if invitation is None:
        return ValidateInviteResponse(valid=False)

    return ValidateInviteResponse(
        valid=True,
        inviter_username=invitation.get("inviter_username"),
        email=invitation.get("email"),
    )
