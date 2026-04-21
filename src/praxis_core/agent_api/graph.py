"""Agent API — Priority graph queries and mutations."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from praxis_core.model import User
from praxis_core.web_api.auth import get_current_user


def _get_graph(entity_id):
    from praxis_core.serialization import get_graph
    return get_graph(entity_id)


def _clear_cache(entity_id):
    from praxis_core.serialization import clear_graph_cache
    clear_graph_cache(entity_id)


router = APIRouter()


class LinkRequest(BaseModel):
    child_id: str
    parent_id: str


class MoveRequest(BaseModel):
    child_id: str
    new_parent_id: str | None  # None = make root


@router.get("/roots")
async def get_roots(user: User = Depends(get_current_user)):
    """Get root priorities (no parents)."""
    graph = _get_graph(user.entity_id)
    roots = graph.roots()
    return [
        {"id": p.id, "name": p.name, "priority_type": p.priority_type.value}
        for p in sorted(roots, key=lambda p: p.rank or 999)
    ]


@router.get("/ancestors/{priority_id}")
async def get_ancestors(priority_id: str, user: User = Depends(get_current_user)):
    """Get ancestor chain for a priority (bottom-up path to root)."""
    graph = _get_graph(user.entity_id)
    if not graph.get(priority_id):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    ancestor_ids = graph.ancestors(priority_id)
    return [
        {"id": aid, "name": graph.get(aid).name, "priority_type": graph.get(aid).priority_type.value}
        for aid in ancestor_ids
        if graph.get(aid)
    ]


@router.get("/descendants/{priority_id}")
async def get_descendants(priority_id: str, user: User = Depends(get_current_user)):
    """Get all descendants of a priority."""
    graph = _get_graph(user.entity_id)
    if not graph.get(priority_id):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    descendant_ids = graph.descendants(priority_id)
    return [
        {"id": did, "name": graph.get(did).name, "priority_type": graph.get(did).priority_type.value}
        for did in descendant_ids
        if graph.get(did)
    ]


@router.get("/children/{priority_id}")
async def get_children(priority_id: str, user: User = Depends(get_current_user)):
    """Get direct children of a priority."""
    graph = _get_graph(user.entity_id)
    if not graph.get(priority_id):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    child_ids = graph.children.get(priority_id, set())
    return [
        {"id": cid, "name": graph.get(cid).name, "priority_type": graph.get(cid).priority_type.value}
        for cid in child_ids
        if graph.get(cid)
    ]


@router.post("/link")
async def link_priority(body: LinkRequest, user: User = Depends(get_current_user)):
    """Create a parent-child edge."""
    graph = _get_graph(user.entity_id)
    try:
        graph.link(body.child_id, body.parent_id)
    except ValueError as e:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": str(e)}, status_code=400)
    _clear_cache(user.entity_id)
    return {"linked": {"child": body.child_id, "parent": body.parent_id}}


@router.post("/unlink")
async def unlink_priority(body: LinkRequest, user: User = Depends(get_current_user)):
    """Remove a parent-child edge."""
    graph = _get_graph(user.entity_id)
    graph.unlink(body.child_id, body.parent_id)
    _clear_cache(user.entity_id)
    return {"unlinked": {"child": body.child_id, "parent": body.parent_id}}


@router.post("/move")
async def move_priority(body: MoveRequest, user: User = Depends(get_current_user)):
    """Move a priority: unlink from all current parents, link to new parent (or make root)."""
    graph = _get_graph(user.entity_id)
    if body.child_id not in graph.nodes:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Priority not found"}, status_code=404)

    # Unlink from all current parents
    for parent_id in list(graph.parents.get(body.child_id, set())):
        graph.unlink(body.child_id, parent_id)

    # Link to new parent if specified
    if body.new_parent_id:
        try:
            graph.link(body.child_id, body.new_parent_id)
        except ValueError as e:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": str(e)}, status_code=400)

    _clear_cache(user.entity_id)
    return {"moved": body.child_id, "new_parent": body.new_parent_id}


@router.get("/tree")
async def get_tree(user: User = Depends(get_current_user)):
    """Get the full priority tree as nested JSON."""
    graph = _get_graph(user.entity_id)

    def _build_node(p):
        child_ids = graph.children.get(p.id, set())
        children = [graph.get(cid) for cid in child_ids if graph.get(cid)]
        children.sort(key=lambda c: (c.rank or 999, c.name))
        return {
            "id": p.id,
            "name": p.name,
            "priority_type": p.priority_type.value,
            "status": p.status.value,
            "children": [_build_node(c) for c in children],
        }

    roots = sorted(graph.roots(), key=lambda p: (p.rank or 999, p.name))
    return [_build_node(r) for r in roots]
