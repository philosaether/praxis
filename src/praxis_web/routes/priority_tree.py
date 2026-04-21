"""
Priority tree routes: hierarchy tree view, drag-and-drop, and deletion.

Direct persistence — no httpx proxy.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from praxis_core.model import PriorityStatus
from praxis_core.serialization import get_graph, clear_graph_cache, serialize_priority
from praxis_core.persistence import validate_session
from praxis_web.rendering import SESSION_COOKIE_NAME, templates

router = APIRouter()

# Shared cache for entity name resolution within a request
_entity_name_cache: dict = {}


def _get_user(request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    result = validate_session(token)
    if result is None:
        return None
    session, user = result
    return user


def _ser(p, current_entity_id=None, share_counts=None):
    return serialize_priority(
        p,
        current_entity_id=current_entity_id,
        share_counts=share_counts,
        entity_name_cache=_entity_name_cache,
    )


def _sort_key(p):
    """Sort by rank (nulls last), then by name."""
    return (p.rank if p.rank is not None else 999, p.name)


# -----------------------------------------------------------------------------
# Tree Views
# -----------------------------------------------------------------------------

@router.get("/priorities/tree", response_class=HTMLResponse)
async def priority_tree(request: Request):
    """HTMX partial: tree view of priority hierarchy."""
    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = get_graph(entity_id=entity_id)
    roots = sorted(graph.roots(), key=_sort_key)

    # Batch-load share counts
    sc = None
    if entity_id:
        from praxis_core.persistence.priority_sharing import get_share_counts_for_entity
        from praxis_core.persistence.database import get_connection as _get_conn
        sc = get_share_counts_for_entity(_get_conn, entity_id)

    # Build children map for the entire tree
    children_map = {}
    for parent_id, child_ids in graph.children.items():
        children = [graph.get(cid) for cid in child_ids if graph.get(cid)]
        children_map[parent_id] = [
            _ser(c, current_entity_id=entity_id, share_counts=sc)
            for c in sorted(children, key=_sort_key)
        ]

    serialized_roots = [_ser(r, current_entity_id=entity_id, share_counts=sc) for r in roots]
    owned_roots = [r for r in serialized_roots if r.get("is_owner", True)]
    shared_roots = [r for r in serialized_roots if r.get("is_shared_with_me")]

    # Apply placements: move adopted priorities from shared_roots into the owned tree
    if entity_id:
        from praxis_core.persistence.priority_placement_repo import list_placements
        placements = {p["priority_id"]: p for p in list_placements(entity_id)}

        if placements:
            adopted_ids = set(placements.keys())
            still_shared = [r for r in shared_roots if r["id"] not in adopted_ids]

            for root in shared_roots:
                if root["id"] in adopted_ids:
                    p = placements[root["id"]]
                    root["is_adopted"] = True
                    root["adopted_rank"] = p["rank"]
                    if p["parent_priority_id"]:
                        if p["parent_priority_id"] not in children_map:
                            children_map[p["parent_priority_id"]] = []
                        children_map[p["parent_priority_id"]].append(root)
                    else:
                        owned_roots.append(root)

            shared_roots = still_shared

    return templates.TemplateResponse(
        request,
        "partials/priority_tree.html",
        {
            "roots": owned_roots,
            "shared_roots": shared_roots,
            "children_map": children_map,
        }
    )


@router.get("/priorities/tree-pane", response_class=HTMLResponse)
async def priority_tree_pane(request: Request):
    """HTMX partial: full tree view for right pane."""
    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = get_graph(entity_id=entity_id)
    roots = sorted(graph.roots(), key=_sort_key)

    # Batch-load share counts
    sc = None
    if entity_id:
        from praxis_core.persistence.priority_sharing import get_share_counts_for_entity
        from praxis_core.persistence.database import get_connection as _get_conn
        sc = get_share_counts_for_entity(_get_conn, entity_id)

    # Build children map for the entire tree
    children_map = {}
    for parent_id, child_ids in graph.children.items():
        children = [graph.get(cid) for cid in child_ids if graph.get(cid)]
        children_map[parent_id] = [
            _ser(c, current_entity_id=entity_id, share_counts=sc)
            for c in sorted(children, key=_sort_key)
        ]

    serialized_roots = [_ser(r, current_entity_id=entity_id, share_counts=sc) for r in roots]
    owned_roots = [r for r in serialized_roots if r.get("is_owner", True)]
    shared_roots = [r for r in serialized_roots if r.get("is_shared_with_me")]

    # Apply placements
    if entity_id:
        from praxis_core.persistence.priority_placement_repo import list_placements
        placements = {p["priority_id"]: p for p in list_placements(entity_id)}

        if placements:
            adopted_ids = set(placements.keys())
            still_shared = [r for r in shared_roots if r["id"] not in adopted_ids]

            for root in shared_roots:
                if root["id"] in adopted_ids:
                    p = placements[root["id"]]
                    root["is_adopted"] = True
                    root["adopted_rank"] = p["rank"]
                    if p["parent_priority_id"]:
                        if p["parent_priority_id"] not in children_map:
                            children_map[p["parent_priority_id"]] = []
                        children_map[p["parent_priority_id"]].append(root)
                    else:
                        owned_roots.append(root)

            shared_roots = still_shared

    # Build nested tree structure for recursive rendering
    def nest_children(node):
        """Recursively attach children to nodes."""
        node_id = node["id"]
        node["children"] = children_map.get(node_id, [])
        for child in node["children"]:
            nest_children(child)
        return node

    nested_roots = [nest_children(root) for root in owned_roots]
    nested_shared = [nest_children(root) for root in shared_roots]

    return templates.TemplateResponse(
        request,
        "partials/priority_tree_pane.html",
        {"roots": nested_roots, "shared_roots": nested_shared}
    )


# -----------------------------------------------------------------------------
# Tree Node
# -----------------------------------------------------------------------------

@router.get("/priorities/{priority_id}/tree-node", response_class=HTMLResponse)
async def priority_tree_node(request: Request, priority_id: str):
    """Return a single tree node HTML for inserting into the tree."""
    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = get_graph(entity_id=entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return HTMLResponse(content="", status_code=404)

    priority_dict = _ser(priority, current_entity_id=entity_id)
    # New priorities have no children yet
    priority_dict["children"] = []

    return templates.TemplateResponse(
        request,
        "partials/priority_tree_node.html",
        {"node": priority_dict, "depth": 0}
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

    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = get_graph(entity_id=entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return HTMLResponse(content="Priority not found", status_code=404)

    # Handle reparenting
    current_parents = graph.parents.get(priority_id, set())

    # Remove from old parent(s)
    for old_parent in list(current_parents):
        if old_parent != new_parent_id:
            graph.unlink(priority_id, old_parent)

    # Link to new parent (if not root)
    if new_parent_id and new_parent_id not in current_parents:
        try:
            graph.link(priority_id, new_parent_id)
        except ValueError:
            return HTMLResponse(content="Cannot create circular reference", status_code=400)

    # Handle reordering
    if sibling_ids and priority_id in sibling_ids:
        new_rank = sibling_ids.index(priority_id) + 1
        priority.rank = new_rank
        graph.save_priority(priority)

        for i, sibling_id in enumerate(sibling_ids):
            if sibling_id != priority_id:
                sibling = graph.get(sibling_id)
                if sibling:
                    sibling.rank = i + 1
                    graph.save_priority(sibling)

    return HTMLResponse(content="OK", status_code=200)


@router.post("/priorities/{priority_id}/delete", response_class=HTMLResponse)
async def priority_delete(request: Request, priority_id: str):
    """Delete a priority, handling children and linked tasks."""
    data = await request.json()
    delete_mode = data.get("delete_mode", "orphan")

    from praxis_core.persistence.task_repo import unlink_tasks_from_priority

    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = get_graph(entity_id=entity_id)
    priority = graph.get(priority_id)

    if not priority:
        return HTMLResponse(content="Priority not found", status_code=404)

    # Get this priority's parent (if any)
    parent_ids = graph.parents.get(priority_id, set())
    new_parent_id = next(iter(parent_ids), None) if parent_ids else None

    # Get children
    child_ids = list(graph.children.get(priority_id, set()))

    if delete_mode == "cascade":
        def collect_descendants(pid):
            descendants = []
            for child_id in graph.children.get(pid, set()):
                descendants.append(child_id)
                descendants.extend(collect_descendants(child_id))
            return descendants

        all_descendants = collect_descendants(priority_id)

        for pid in [priority_id] + all_descendants:
            unlink_tasks_from_priority(pid)

        for desc_id in reversed(all_descendants):
            graph.delete(desc_id)

    else:  # orphan mode
        for child_id in child_ids:
            graph.unlink(child_id, priority_id)
            if new_parent_id:
                try:
                    graph.link(child_id, new_parent_id)
                except ValueError:
                    pass

        unlink_tasks_from_priority(priority_id)

    graph.delete(priority_id)
    clear_graph_cache(entity_id)

    return HTMLResponse(content="OK", status_code=200)
