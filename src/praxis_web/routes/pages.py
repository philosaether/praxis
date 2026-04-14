"""Page routes — full-page renders that wrap partials in the app shell."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from praxis_web.rendering import templates, api_client, is_htmx_request, render_full_page

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    """Full page: two-pane layout with tasks as default view."""
    return await render_full_page(request, mode="tasks")


@router.get("/tasks", response_class=HTMLResponse)
async def tasks_page(
    request: Request,
    priority: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    q: str | None = None,
):
    """Tasks queue view - full page or HTMX partial."""
    if is_htmx_request(request):
        # Import here to avoid circular — tasks_list_partial lives in app.py still
        from praxis_web.app import tasks_list_partial
        return await tasks_list_partial(request, priority=priority, status=status, tag=tag, q=q)
    return await render_full_page(request, mode="tasks")


@router.get("/tasks/inbox", response_class=HTMLResponse)
async def tasks_inbox_page(request: Request):
    """Inbox view - full page or HTMX partial."""
    if is_htmx_request(request):
        async with api_client(request) as client:
            response = await client.get("/api/tasks", params={"inbox": "true"})
            data = response.json()
        return templates.TemplateResponse(
            request,
            "partials/task_rows.html",
            {"tasks": data["tasks"], "priorities": data.get("priorities", [])}
        )
    return await render_full_page(request, mode="inbox")


@router.get("/tasks/outbox", response_class=HTMLResponse)
async def tasks_outbox_page(request: Request):
    """Outbox view - completed tasks awaiting deletion."""
    if is_htmx_request(request):
        async with api_client(request) as client:
            response = await client.get("/api/tasks", params={"outbox": "true"})
            data = response.json()
        return templates.TemplateResponse(
            request,
            "partials/task_rows.html",
            {"tasks": data["tasks"], "priorities": data.get("priorities", []), "outbox_mode": True}
        )
    return await render_full_page(request, mode="outbox")


@router.get("/priorities", response_class=HTMLResponse)
async def priorities_page(request: Request):
    """Priorities view - full page or HTMX partial."""
    if is_htmx_request(request):
        # Import here to avoid circular — priorities_list_partial lives in app.py still
        from praxis_web.app import priorities_list_partial
        return await priorities_list_partial(request)

    # For full page, render the priority list and tree pane
    async with api_client(request) as client:
        response = await client.get("/api/priorities")
        data = response.json()

        # Also get tree data for detail pane
        tree_response = await client.get("/api/priorities/tree")
        tree_data = tree_response.json()

    list_html = templates.get_template("partials/priority_rows.html").render(
        priorities=data["priorities"]
    )

    # Build nested tree structure for recursive rendering
    children_map = tree_data["children_map"]

    def nest_children(node):
        node_id = node["id"]
        node["children"] = children_map.get(node_id, [])
        for child in node["children"]:
            nest_children(child)
        return node

    roots = [nest_children(root) for root in tree_data["roots"]]

    detail_html = templates.get_template("partials/priority_tree_pane.html").render(
        roots=roots
    )

    return await render_full_page(request, mode="priorities", initial_list_html=list_html, initial_detail_html=detail_html)
