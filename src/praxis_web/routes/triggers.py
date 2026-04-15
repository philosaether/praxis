"""Trigger routes — proxy trigger checks to the API backend."""

from fastapi import APIRouter, Request
from fastapi.responses import Response

from praxis_web.rendering import api_client

router = APIRouter()


@router.post("/api/practices/check-triggers")
async def check_triggers_proxy(request: Request):
    """Proxy trigger check to API backend."""
    async with api_client(request) as client:
        response = await client.post("/api/practices/check-triggers")
        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type="application/json",
        )
