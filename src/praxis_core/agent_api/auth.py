"""Agent API — API key management endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from praxis_core.model import User
from praxis_core.web_api.auth import get_current_user
from praxis_core.persistence.api_key_repo import (
    create_api_key,
    list_api_keys,
    revoke_api_key,
)

router = APIRouter()


class CreateTokenRequest(BaseModel):
    name: str


@router.post("")
async def create_token(body: CreateTokenRequest, user: User = Depends(get_current_user)):
    """Create a new API key. Returns the plaintext key exactly once."""
    metadata, plaintext_key = create_api_key(user.id, body.name)
    return {
        **metadata,
        "key": plaintext_key,
    }


@router.get("")
async def list_tokens(user: User = Depends(get_current_user)):
    """List all API keys for the authenticated user."""
    keys = list_api_keys(user.id)
    return {"keys": keys}


@router.delete("/{key_id}")
async def revoke_token(key_id: str, user: User = Depends(get_current_user)):
    """Revoke an API key."""
    revoked = revoke_api_key(key_id, user.id)
    if not revoked:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Key not found or not owned by you"}, status_code=404)
    return {"revoked": key_id}
