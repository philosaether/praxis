"""
Prioritization engine for ranking tasks.

Three-dimensional scoring:
- Importance: inherited from priority hierarchy (static, based on root rank)
- Urgency: calculated by rules (due date pressure, staleness, etc.)
- Aptness: contextual relevance multiplier (time-of-day, tags, etc.)

Final score formula: (importance + urgency) × aptness
"""

from dataclasses import dataclass

from praxis_core.model import Task
from praxis_core.model.rules import Rule
from praxis_core.persistence import PriorityGraph
from praxis_core.rules.engine import evaluate_rules


@dataclass
class ScoredTask:
    """A task with its computed priority score."""
    task: Task
    score: float
    importance: float
    urgency: float
    aptness: float = 1.0
    matched_rules: list[str] | None = None


# Default importance for tasks with no ranked ancestor
DEFAULT_IMPORTANCE = 5.0


def get_importance(task: Task, graph: PriorityGraph) -> float:
    """
    Calculate importance score for a task based on its priority hierarchy.

    Walks up the DAG to find a root priority with a rank.
    Returns 10 - rank, or DEFAULT_IMPORTANCE if no rank found.
    """
    if not task.priority_id:
        return DEFAULT_IMPORTANCE

    path = graph.path_to_root(task.priority_id)
    if not path:
        return DEFAULT_IMPORTANCE

    root_id = path[-1]
    root = graph.get(root_id)
    if root is None:
        return DEFAULT_IMPORTANCE

    rank = getattr(root, 'rank', None)
    if rank is None:
        return DEFAULT_IMPORTANCE

    return max(10.0 - rank, 1.0)


def score_task(
    task: Task,
    graph: PriorityGraph,
    rules: list[Rule],
    task_tags: set[str] | None = None,
) -> ScoredTask:
    """
    Score a task using the rules engine.

    Formula: (importance + urgency) × aptness

    Args:
        task: The task to score
        graph: Priority graph for importance calculation
        rules: List of enabled rules to evaluate
        task_tags: Set of tag names on the task

    Returns:
        ScoredTask with final score, components, and matched rules
    """
    base_importance = get_importance(task, graph)

    # Get priority depth for rule context
    depth = 0
    if task.priority_id:
        path = graph.path_to_root(task.priority_id)
        depth = len(path) if path else 0

    # Evaluate rules (urgency comes entirely from rules)
    result = evaluate_rules(
        rules=rules,
        task=task,
        task_tags=task_tags,
        base_importance=base_importance,
        base_urgency=0.0,
        priority_depth=depth,
    )

    # Final scores
    importance = base_importance + result.importance_modifier
    urgency = result.urgency_modifier
    aptness = result.aptness
    score = (importance + urgency) * aptness

    return ScoredTask(
        task=task,
        score=score,
        importance=importance,
        urgency=urgency,
        aptness=aptness,
        matched_rules=result.matched_rules,
    )


def rank_tasks(
    tasks: list[Task],
    graph: PriorityGraph,
    rules: list[Rule],
    task_tags_map: dict[str, set[str]] | None = None,
) -> list[ScoredTask]:
    """
    Score and rank tasks by priority.

    Args:
        tasks: Tasks to rank
        graph: Priority graph for importance calculation
        rules: List of enabled rules to evaluate
        task_tags_map: Optional mapping of task_id -> set of tag names

    Returns:
        Tasks sorted by score (highest first).
    """
    scored = [
        score_task(
            task=task,
            graph=graph,
            rules=rules,
            task_tags=task_tags_map.get(task.id, set()) if task_tags_map else None,
        )
        for task in tasks
    ]
    scored.sort(key=lambda st: st.score, reverse=True)
    return scored
