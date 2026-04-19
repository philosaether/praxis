"""Filter option routes — dynamic dropdown refresh for HTMX."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from praxis_web.rendering import templates, api_client

router = APIRouter()


@router.get("/filters/priorities", response_class=HTMLResponse)
async def filter_priority_options(request: Request, selected: str | None = None):
    """Return priority filter options for dropdown refresh."""
    async with api_client(request) as client:
        response = await client.get("/api/priorities")
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/components/filter_priority_options.html",
        {"priorities": data.get("priorities", []), "selected": selected}
    )


@router.get("/filters/tags", response_class=HTMLResponse)
async def filter_tag_options(request: Request, selected: str | None = None):
    """Return tag filter options for dropdown refresh."""
    async with api_client(request) as client:
        response = await client.get("/api/tags")
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/components/filter_tag_options.html",
        {"user_tags": data.get("tags", []), "selected": selected}
    )
