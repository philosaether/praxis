"""
DSL v2 executor: wires engine specs to persistence.

Takes TaskSpec/PrioritySpec/CollateSpec from the engine and creates
actual entities in the database.
"""

from datetime import datetime
from ulid import ULID

from praxis_core.model.tasks import Task
from praxis_core.model.priorities import Priority, Goal, Practice, PriorityType, PriorityStatus
from praxis_core.persistence.task_persistence import create_task, list_tasks
from praxis_core.persistence.priority_persistence import PriorityGraph
from praxis_core.persistence.database import get_connection

from .engine_v2 import (
    TaskSpec,
    PrioritySpec,
    CollateSpec,
    ExecutionResult,
    ExecutionContext,
    execute_action,
)
from praxis_core.dsl import PracticeAction


# -----------------------------------------------------------------------------
# Task Creation
# -----------------------------------------------------------------------------

def create_task_from_spec(
    spec: TaskSpec,
    parent_priority_id: str | None = None,
    created_by: int | None = None,
) -> Task:
    """
    Create a Task from a TaskSpec.

    Args:
        spec: The task specification from engine execution
        parent_priority_id: Override for priority_id (used for hierarchy)
        created_by: User ID who created this task (for assignment)

    Returns:
        The created Task entity
    """
    priority_id = parent_priority_id or spec.priority_id

    task = create_task(
        name=spec.name,
        description=spec.notes,
        due_date=spec.due_date,
        priority_id=priority_id,
        entity_id=spec.entity_id,
        created_by=created_by,
    )

    # Handle tags if present
    if spec.tags:
        _assign_tags_to_task(task.id, spec.tags, spec.entity_id)

    return task


def _assign_tags_to_task(task_id: str, tag_names: list[str], entity_id: str | None) -> None:
    """Assign tags to a task, creating tags if they don't exist."""
    if not entity_id or not tag_names:
        return

    with get_connection() as conn:
        for tag_name in tag_names:
            # Get or create tag
            tag_row = conn.execute(
                "SELECT id FROM tags WHERE entity_id = ? AND name = ?",
                (entity_id, tag_name)
            ).fetchone()

            if tag_row:
                tag_id = tag_row["id"]
            else:
                tag_id = str(ULID())
                conn.execute(
                    "INSERT INTO tags (id, entity_id, name) VALUES (?, ?, ?)",
                    (tag_id, entity_id, tag_name)
                )

            # Link task to tag (ignore if already linked)
            conn.execute(
                "INSERT OR IGNORE INTO task_tags (task_id, tag_id) VALUES (?, ?)",
                (task_id, tag_id)
            )


# -----------------------------------------------------------------------------
# Priority Creation
# -----------------------------------------------------------------------------

def create_priority_from_spec(
    spec: PrioritySpec,
    parent_id: str | None = None,
    graph: PriorityGraph | None = None,
) -> Priority:
    """
    Create a Priority from a PrioritySpec, including children.

    Args:
        spec: The priority specification from engine execution
        parent_id: Parent priority ID for hierarchy
        graph: Optional PriorityGraph instance (creates one if not provided)

    Returns:
        The created Priority entity
    """
    if graph is None:
        graph = PriorityGraph(get_connection, entity_id=spec.entity_id)
        graph.load()

    # Map type string to PriorityType
    priority_type = PriorityType(spec.type) if spec.type else PriorityType.GOAL

    # Create the appropriate priority subclass
    priority_id = str(ULID())
    now = datetime.now()

    if priority_type == PriorityType.GOAL:
        priority = Goal(
            id=priority_id,
            name=spec.name,
            entity_id=spec.entity_id,
            description=spec.notes,
            due_date=spec.due_date,
            status=PriorityStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
    elif priority_type == PriorityType.PRACTICE:
        priority = Practice(
            id=priority_id,
            name=spec.name,
            entity_id=spec.entity_id,
            description=spec.notes,
            status=PriorityStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
    else:
        priority = Priority(
            id=priority_id,
            name=spec.name,
            priority_type=priority_type,
            entity_id=spec.entity_id,
            description=spec.notes,
            status=PriorityStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )

    # Save the priority
    graph.save_priority(priority)

    # Link to parent if provided (save_edge takes child_id, parent_id)
    if parent_id:
        graph.save_edge(priority_id, parent_id)

    # Handle tags
    if spec.tags:
        _assign_tags_to_priority(priority_id, spec.tags, spec.entity_id)

    # Create children recursively
    for child_spec in spec.children:
        if isinstance(child_spec, TaskSpec):
            create_task_from_spec(child_spec, parent_priority_id=priority_id)
        elif isinstance(child_spec, PrioritySpec):
            create_priority_from_spec(child_spec, parent_id=priority_id, graph=graph)

    return priority


def _assign_tags_to_priority(priority_id: str, tag_names: list[str], entity_id: str | None) -> None:
    """Assign tags to a priority, creating tags if they don't exist."""
    if not entity_id or not tag_names:
        return

    with get_connection() as conn:
        for tag_name in tag_names:
            # Get or create tag
            tag_row = conn.execute(
                "SELECT id FROM tags WHERE entity_id = ? AND name = ?",
                (entity_id, tag_name)
            ).fetchone()

            if tag_row:
                tag_id = tag_row["id"]
            else:
                tag_id = str(ULID())
                conn.execute(
                    "INSERT INTO tags (id, entity_id, name) VALUES (?, ?, ?)",
                    (tag_id, entity_id, tag_name)
                )

            # Link priority to tag
            conn.execute(
                "INSERT OR IGNORE INTO priority_tags (priority_id, tag_id) VALUES (?, ?)",
                (priority_id, tag_id)
            )


# -----------------------------------------------------------------------------
# Collation Execution
# -----------------------------------------------------------------------------

def execute_collation(
    spec: CollateSpec,
    practice_id: str | None = None,
    created_by: int | None = None,
) -> Task | None:
    """
    Execute a collation: gather matching tasks and create a batch task.

    Args:
        spec: The collation specification
        practice_id: ID of the practice for "children" shorthand
        created_by: User ID for task creation

    Returns:
        The created batch task, or None if no tasks matched
    """
    # Gather tasks based on target
    matching_tasks = _gather_collation_targets(spec, practice_id)

    if not matching_tasks:
        return None

    # Create the batch task
    batch_task = create_task(
        name=spec.batch_name,
        due_date=spec.batch_due,
        priority_id=practice_id,
        entity_id=spec.entity_id,
        created_by=created_by,
    )

    # Assign tags
    if spec.batch_tags:
        _assign_tags_to_task(batch_task.id, spec.batch_tags, spec.entity_id)

    # Link matched tasks as subtasks or children
    # For now, we'll add a note listing them
    task_names = [t.name for t in matching_tasks]
    if task_names:
        notes = "Batched tasks:\n" + "\n".join(f"- {name}" for name in task_names)
        from praxis_core.persistence.task_persistence import update_task
        update_task(batch_task.id, notes=notes)

    return batch_task


def _gather_collation_targets(spec: CollateSpec, practice_id: str | None) -> list[Task]:
    """Gather tasks matching the collation target specification."""
    entity_id = spec.entity_id

    # Handle shorthand targets
    if spec.target_shorthand:
        shorthand = spec.target_shorthand.lower()

        if shorthand == "children" and practice_id:
            return list_tasks(
                priority_id=practice_id,
                include_done=False,
                entity_id=entity_id,
            )

        if shorthand == "descendants" and practice_id:
            return _gather_descendant_tasks(practice_id, entity_id)

        if shorthand.startswith("tagged:"):
            tag_name = shorthand.split(":", 1)[1].strip()
            return list_tasks(
                include_done=False,
                entity_id=entity_id,
                tag_names=[tag_name],
            )

    # Handle complex filtering (match_any, match_all, exclude)
    task_sets = []

    if spec.match_any:
        any_tasks = _gather_match_any(spec.match_any, entity_id, practice_id)
        task_sets.append(any_tasks)

    if spec.match_all:
        all_tasks = _gather_match_all(spec.match_all, entity_id, practice_id)
        task_sets.append(all_tasks)

    # Combine: if both match_any and match_all, intersect them
    if not task_sets:
        return []
    if len(task_sets) == 1:
        result = task_sets[0]
    else:
        # Intersect by task ID
        id_sets = [set(t.id for t in ts) for ts in task_sets]
        common_ids = id_sets[0].intersection(*id_sets[1:])
        by_id = {t.id: t for ts in task_sets for t in ts}
        result = [by_id[tid] for tid in common_ids]

    # Apply exclude filters
    if spec.exclude:
        result = _apply_excludes(result, spec.exclude)

    return result


def _get_collation_graph(entity_id: str | None) -> PriorityGraph:
    """Load graph once for collation operations."""
    graph = PriorityGraph(get_connection, entity_id=entity_id)
    graph.load()
    return graph


def _gather_descendant_tasks(priority_id: str, entity_id: str | None, graph: PriorityGraph | None = None) -> list[Task]:
    """Gather tasks from a priority and all its descendants."""
    if not graph:
        graph = _get_collation_graph(entity_id)

    descendant_ids = graph.descendants(priority_id)
    all_priority_ids = {priority_id} | descendant_ids

    all_tasks = []
    for pid in all_priority_ids:
        tasks = list_tasks(priority_id=pid, include_done=False, entity_id=entity_id)
        all_tasks.extend(tasks)
    return all_tasks


def _resolve_ancestor_name(name: str, entity_id: str | None, graph: PriorityGraph | None = None) -> str | None:
    """Resolve a priority name to its ID."""
    if not graph:
        graph = _get_collation_graph(entity_id)
    for p in graph.nodes.values():
        if p.name.lower() == name.lower():
            return p.id
    return None


def _execute_filter(f: dict, entity_id: str | None, graph: PriorityGraph) -> list[Task]:
    """Execute a single collation filter and return matching tasks."""
    if "tag" in f:
        return list_tasks(include_done=False, entity_id=entity_id, tag_names=[f["tag"]])
    if "ancestor" in f:
        ancestor_id = _resolve_ancestor_name(f["ancestor"], entity_id, graph)
        if ancestor_id:
            return _gather_descendant_tasks(ancestor_id, entity_id, graph)
    if "priority_id" in f:
        return list_tasks(priority_id=f["priority_id"], include_done=False, entity_id=entity_id)
    return []


def _gather_match_any(filters: list[dict], entity_id: str | None, practice_id: str | None) -> list[Task]:
    """OR logic: gather tasks matching any of the filters."""
    graph = _get_collation_graph(entity_id)
    all_tasks = []
    for f in filters:
        all_tasks.extend(_execute_filter(f, entity_id, graph))

    # Deduplicate
    seen = set()
    unique = []
    for t in all_tasks:
        if t.id not in seen:
            seen.add(t.id)
            unique.append(t)
    return unique


def _gather_match_all(filters: list[dict], entity_id: str | None, practice_id: str | None) -> list[Task]:
    """AND logic: gather tasks matching all filters (intersection)."""
    graph = _get_collation_graph(entity_id)
    sets = []
    all_by_id: dict[str, Task] = {}
    for f in filters:
        tasks = _execute_filter(f, entity_id, graph)
        for t in tasks:
            all_by_id[t.id] = t
        sets.append({t.id for t in tasks})

    if not sets:
        return []

    # Intersect all ID sets
    common_ids = sets[0]
    for s in sets[1:]:
        common_ids &= s

    return [all_by_id[tid] for tid in common_ids]


def _apply_excludes(tasks: list[Task], excludes: list[dict]) -> list[Task]:
    """Filter out tasks matching any exclude criterion."""
    result = tasks
    for ex in excludes:
        if "status" in ex:
            result = [t for t in result if t.status.value != ex["status"]]
        if "tag" in ex:
            # Would need tag lookup per task — for now, skip
            pass
        if "priority_id" in ex:
            result = [t for t in result if t.priority_id != ex["priority_id"]]
    return result


# -----------------------------------------------------------------------------
# Full Action Execution
# -----------------------------------------------------------------------------

def execute_and_persist(
    action: PracticeAction,
    ctx: ExecutionContext,
    practice_id: str | None = None,
    created_by: int | None = None,
) -> dict:
    """
    Execute an action and persist the results.

    Args:
        action: The practice action to execute
        ctx: Execution context
        practice_id: ID of the parent practice
        created_by: User ID for created entities

    Returns:
        Dict with counts: {tasks: N, priorities: N, collations: N}
    """
    # Execute the action to get specs.
    # NOTE: entities created here must NOT fire event triggers (on_task_created,
    # on_priority_created) or infinite loops are possible. The persistence
    # functions (create_task, create_priority_from_spec) don't fire events —
    # events are only fired from API endpoints. Keep it that way.
    result = execute_action(action, ctx)

    if not result.success:
        return {"error": result.error_message, "tasks": 0, "priorities": 0, "collations": 0}

    counts = {"tasks": 0, "priorities": 0, "collations": 0}

    # Create tasks
    for task_spec in result.tasks:
        create_task_from_spec(
            task_spec,
            parent_priority_id=practice_id,
            created_by=created_by,
        )
        counts["tasks"] += 1

    # Create priorities (with children)
    for priority_spec in result.priorities:
        priority = create_priority_from_spec(
            priority_spec,
            parent_id=practice_id,
        )
        counts["priorities"] += 1
        # Count children
        counts["tasks"] += _count_task_children(priority_spec)

    # Execute collations
    for collate_spec in result.collations:
        batch_task = execute_collation(
            collate_spec,
            practice_id=practice_id,
            created_by=created_by,
        )
        if batch_task:
            counts["collations"] += 1

    return counts


def _count_task_children(spec: PrioritySpec) -> int:
    """Count total task children in a priority spec (recursive)."""
    count = 0
    for child in spec.children:
        if isinstance(child, TaskSpec):
            count += 1
        elif isinstance(child, PrioritySpec):
            count += _count_task_children(child)
    return count
