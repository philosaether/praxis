"""Page routes — full-page renders that wrap partials in the app shell.

Direct persistence calls — no httpx proxy.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from praxis_web.rendering import templates, SESSION_COOKIE_NAME, is_htmx_request, render_full_page

from praxis_core.model import TaskStatus, PriorityType, PriorityStatus
from praxis_core.persistence import (
    validate_session,
    list_tasks as _list_tasks,
    list_rules,
    get_tags_for_tasks,
)
from praxis_core.persistence.user_repo import list_user_groups
from praxis_core.persistence.priority_sharing import get_share_counts_for_entity
from praxis_core.persistence.priority_placement_repo import list_placements
from praxis_core.persistence.database import get_connection
from praxis_core.prioritization import rank_tasks
from praxis_core.serialization import (
    get_graph as _get_graph_impl,
    serialize_task as _serialize_task_fn,
    serialize_priority as _serialize_priority_fn,
)

router = APIRouter()


# -- helpers ------------------------------------------------------------------

def _get_user(request: Request):
    """Resolve the current user from session cookie, or None."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    result = validate_session(token)
    if result is None:
        return None
    _session, user = result
    return user


def _get_graph(entity_id: str | None = None):
    return _get_graph_impl(entity_id=entity_id)


def _serialize_task(t, current_user=None, graph=None):
    return _serialize_task_fn(t, current_user=current_user, graph=graph)


def _serialize_priority(p, current_entity_id=None, share_counts=None):
    return _serialize_priority_fn(p, current_entity_id=current_entity_id, share_counts=share_counts)


def _get_active_rules(entity_id: str | None):
    """Get active rules for scoring (system + user rules)."""
    return list_rules(entity_id=entity_id, include_system=True, enabled_only=True)


def _sort_key(p):
    """Sort by rank (nulls last), then by name."""
    return (p.rank if p.rank is not None else 999, p.name)


# -- routes -------------------------------------------------------------------

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
        from praxis_web.routes.tasks import tasks_list_partial
        return await tasks_list_partial(request, priority=priority, status=status, tag=tag, q=q)
    return await render_full_page(request, mode="tasks")


@router.get("/tasks/inbox", response_class=HTMLResponse)
async def tasks_inbox_page(request: Request):
    """Inbox view - full page or HTMX partial."""
    if is_htmx_request(request):
        user = _get_user(request)
        entity_id = user.entity_id if user else None
        graph = _get_graph(entity_id)

        # For inbox: find Org-type priorities assigned to groups the user belongs to
        org_priority_ids = None
        if user:
            user_groups = list_user_groups(user.id)
            group_entity_ids = {g["entity_id"] for g in user_groups}
            if group_entity_ids:
                org_priority_ids = [
                    p.id for p in graph.nodes.values()
                    if p.priority_type.value == "org"
                    and p.assigned_to_entity_id in group_entity_ids
                ]

        tasks = _list_tasks(
            entity_id=entity_id,
            inbox_only=True,
            org_priority_ids=org_priority_ids,
        )
        priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

        # Score and rank
        rules = _get_active_rules(entity_id)
        task_ids = [t.id for t in tasks]
        task_tags_map = get_tags_for_tasks(task_ids) if task_ids else {}
        scored_tasks = rank_tasks(tasks, graph, rules, task_tags_map)

        serialized = []
        for st in scored_tasks:
            task_data = _serialize_task(st.task, current_user=user, graph=graph)
            task_data["score"] = round(st.score, 2)
            task_data["importance"] = round(st.importance, 1)
            task_data["urgency"] = round(st.urgency, 1)
            task_data["aptness"] = round(st.aptness, 2)
            serialized.append(task_data)

        # Fetch priority tree for inline triage picker
        priority_tree = _build_picker_tree(graph)

        return templates.TemplateResponse(
            request,
            "partials/task_rows.html",
            {
                "tasks": serialized,
                "priorities": [_serialize_priority(p) for p in priorities],
                "inbox_mode": True,
                "priority_tree": priority_tree,
            }
        )
    return await render_full_page(request, mode="inbox")


def _build_picker_tree(graph) -> list[dict]:
    """Build priority picker tree directly from graph.

    Picker needs: [{name, id, children: [{name, id, children: [...]}]}]
    """
    roots = sorted(graph.roots(), key=_sort_key)

    def build_node(priority) -> dict:
        child_ids = graph.children.get(priority.id, set())
        children = []
        for cid in sorted(child_ids):
            child = graph.nodes.get(cid)
            if child:
                children.append(build_node(child))
        return {
            "name": priority.name,
            "id": priority.id,
            "children": children,
        }

    return [build_node(r) for r in roots]


@router.get("/tasks/outbox", response_class=HTMLResponse)
async def tasks_outbox_page(request: Request):
    """Outbox view - completed tasks awaiting deletion."""
    if is_htmx_request(request):
        user = _get_user(request)
        entity_id = user.entity_id if user else None
        graph = _get_graph(entity_id)

        tasks = _list_tasks(entity_id=entity_id, outbox_only=True)
        priorities = sorted(graph.nodes.values(), key=lambda p: p.name)

        # Score and rank
        rules = _get_active_rules(entity_id)
        task_ids = [t.id for t in tasks]
        task_tags_map = get_tags_for_tasks(task_ids) if task_ids else {}
        scored_tasks = rank_tasks(tasks, graph, rules, task_tags_map)

        serialized = []
        for st in scored_tasks:
            task_data = _serialize_task(st.task, current_user=user, graph=graph)
            task_data["score"] = round(st.score, 2)
            task_data["importance"] = round(st.importance, 1)
            task_data["urgency"] = round(st.urgency, 1)
            task_data["aptness"] = round(st.aptness, 2)
            serialized.append(task_data)

        return templates.TemplateResponse(
            request,
            "partials/task_rows.html",
            {"tasks": serialized, "priorities": [_serialize_priority(p) for p in priorities], "outbox_mode": True}
        )
    return await render_full_page(request, mode="outbox")


@router.get("/priorities", response_class=HTMLResponse)
async def priorities_page(request: Request):
    """Priorities view - full page or HTMX partial."""
    if is_htmx_request(request):
        from praxis_web.routes.priorities import priorities_list_partial
        return await priorities_list_partial(request)

    user = _get_user(request)
    entity_id = user.entity_id if user else None
    graph = _get_graph(entity_id)

    # List all priorities for left pane
    priorities = sorted(graph.nodes.values(), key=lambda p: (p.priority_type.value, p.name))

    list_html = templates.get_template("partials/priority_rows.html").render(
        priorities=[_serialize_priority(p, current_entity_id=entity_id) for p in priorities]
    )

    # Build tree for detail pane
    roots = sorted(graph.roots(), key=_sort_key)

    # Batch-load share counts
    sc = None
    if entity_id:
        sc = get_share_counts_for_entity(get_connection, entity_id)

    children_map = {}
    for parent_id, child_ids in graph.children.items():
        children = [graph.get(cid) for cid in child_ids if graph.get(cid)]
        children_map[parent_id] = [
            _serialize_priority(c, current_entity_id=entity_id, share_counts=sc)
            for c in sorted(children, key=_sort_key)
        ]

    serialized_roots = [_serialize_priority(r, current_entity_id=entity_id, share_counts=sc) for r in roots]
    owned_roots = [r for r in serialized_roots if r.get("is_owner", True)]
    shared_roots = [r for r in serialized_roots if r.get("is_shared_with_me")]

    # Apply placements: move adopted priorities from shared_roots into the owned tree
    if entity_id:
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

    # Build nested tree for recursive template rendering
    def nest_children(node):
        node_id = node["id"]
        node["children"] = children_map.get(node_id, [])
        for child in node["children"]:
            nest_children(child)
        return node

    nested_roots = [nest_children(root) for root in owned_roots]
    nested_shared = [nest_children(root) for root in shared_roots]

    detail_html = templates.get_template("partials/priority_tree_pane.html").render(
        roots=nested_roots, shared_roots=nested_shared
    )

    return await render_full_page(request, mode="priorities", initial_list_html=list_html, initial_detail_html=detail_html)
