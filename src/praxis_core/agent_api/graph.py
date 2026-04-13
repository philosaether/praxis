"""Agent API — Priority graph queries (read-only)."""

from fastapi import APIRouter, Depends

from praxis_core.model import User
from praxis_core.api.auth import get_current_user


def _get_graph(entity_id):
    from praxis_core.api.app import get_graph
    return get_graph(entity_id)

router = APIRouter()


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
