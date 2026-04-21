"""
Priority tree routes: hierarchy tree view, drag-and-drop, and deletion.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from praxis_web.rendering import templates, api_client

router = APIRouter()


# -----------------------------------------------------------------------------
# Tree Views
# -----------------------------------------------------------------------------

@router.get("/priorities/tree", response_class=HTMLResponse)
async def priority_tree(request: Request):
    """HTMX partial: tree view of priority hierarchy."""
    async with api_client(request) as client:
        response = await client.get("/api/priorities/tree")
        data = response.json()

    return templates.TemplateResponse(
        request,
        "partials/priority_tree.html",
        {
            "roots": data["roots"],
            "shared_roots": data.get("shared_roots", []),
            "children_map": data["children_map"],
        }
    )


@router.get("/priorities/tree-pane", response_class=HTMLResponse)
async def priority_tree_pane(request: Request):
    """HTMX partial: full tree view for right pane."""
    async with api_client(request) as client:
        response = await client.get("/api/priorities/tree")
        data = response.json()

    # Build nested tree structure for recursive rendering
    children_map = data["children_map"]

    def nest_children(node):
        """Recursively attach children to nodes."""
        node_id = node["id"]
        node["children"] = children_map.get(node_id, [])
        for child in node["children"]:
            nest_children(child)
        return node

    roots = [nest_children(root) for root in data["roots"]]
    shared_roots = [nest_children(root) for root in data.get("shared_roots", [])]

    return templates.TemplateResponse(
        request,
        "partials/priority_tree_pane.html",
        {"roots": roots, "shared_roots": shared_roots}
    )


# -----------------------------------------------------------------------------
# Tree Node
# -----------------------------------------------------------------------------

@router.get("/priorities/{priority_id}/tree-node", response_class=HTMLResponse)
async def priority_tree_node(request: Request, priority_id: str):
    """Return a single tree node HTML for inserting into the tree."""
    async with api_client(request) as client:
        response = await client.get(f"/api/priorities/{priority_id}")
        if response.status_code == 404:
            return HTMLResponse(content="", status_code=404)
        data = response.json()

    priority = data["priority"]
    # New priorities have no children yet
    priority["children"] = []

    return templates.TemplateResponse(
        request,
        "partials/priority_tree_node.html",
        {"node": priority, "depth": 0}
    )


# -----------------------------------------------------------------------------
# Move / Delete
# -----------------------------------------------------------------------------

@router.post("/priorities/{priority_id}/move", response_class=HTMLResponse)
async def priority_move(request: Request, priority_id: str):
    """Handle drag-and-drop move of a priority in the tree."""
    data = await request.json()
    new_parent_id = data.get("new_parent_id")
    sibling_ids = data.get("sibling_ids", [])
    new_index = data.get("new_index", 0)

    async with api_client(request) as client:
        # Update parent relationship
        response = await client.post(
            f"/api/priorities/{priority_id}/move",
            json={
                "new_parent_id": new_parent_id,
                "sibling_ids": sibling_ids,
                "new_index": new_index
            }
        )

        if response.status_code != 200:
            return HTMLResponse(
                content="Failed to move priority",
                status_code=response.status_code
            )

    return HTMLResponse(content="OK", status_code=200)


@router.post("/priorities/{priority_id}/delete", response_class=HTMLResponse)
async def priority_delete(request: Request, priority_id: str):
    """Delete a priority, handling children and linked tasks."""
    data = await request.json()
    delete_mode = data.get("delete_mode", "orphan")

    async with api_client(request) as client:
        response = await client.post(
            f"/api/priorities/{priority_id}/delete",
            json={"delete_mode": delete_mode}
        )

        if response.status_code != 200:
            return HTMLResponse(
                content="Failed to delete priority",
                status_code=response.status_code
            )

    return HTMLResponse(content="OK", status_code=200)
