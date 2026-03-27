"""
Prioritization engine for ranking tasks.

Two-dimensional scoring:
- Importance: inherited from priority hierarchy (static, based on root rank)
- Urgency: calculated based on due dates, capacity deltas, etc. (dynamic)

Combined score determines task queue ordering.
"""

from dataclasses import dataclass
from datetime import datetime

from praxis_core.model import Task
from praxis_core.model.priorities import Capacity
from praxis_core.persistence import PriorityGraph


@dataclass
class ScoredTask:
    """A task with its computed priority score."""
    task: Task
    score: float
    importance: float
    urgency: float


# Default importance for tasks with no ranked ancestor
DEFAULT_IMPORTANCE = 5.0

# Weights for combining importance and urgency
IMPORTANCE_WEIGHT = 0.5
URGENCY_WEIGHT = 0.5


# ---------------------------------------------------------------------------
# Importance (static, inherited from hierarchy)
# ---------------------------------------------------------------------------

def get_importance(task: Task, graph: PriorityGraph) -> float:
    """
    Calculate importance score for a task based on its priority hierarchy.

    Walks up the DAG to find a root priority with a rank.
    Returns 10 - rank, or DEFAULT_IMPORTANCE if no rank found.
    """
    if not task.priority_id:
        return DEFAULT_IMPORTANCE

    # Walk up to root
    path = graph.path_to_root(task.priority_id)

    if not path:
        return DEFAULT_IMPORTANCE

    # The last item in path is the root
    root_id = path[-1]
    root = graph.get(root_id)

    if root is None:
        return DEFAULT_IMPORTANCE

    # Get rank from root (field to be added to Priority model)
    rank = getattr(root, 'rank', None)

    if rank is None:
        return DEFAULT_IMPORTANCE

    # importance = 10 - rank, with floor of 1
    return max(10.0 - rank, 1.0)


# ---------------------------------------------------------------------------
# Urgency (dynamic, calculated on refresh)
# ---------------------------------------------------------------------------

def get_urgency(task: Task, graph: PriorityGraph) -> float:
    """
    Calculate urgency score for a task.

    Factors:
    - Due date proximity (0-10 scale)
    - Capacity delta (0-5 scale, additive)

    Returns combined urgency, capped at 10.
    """
    urgency = 0.0

    # Due date urgency
    urgency += _due_date_urgency(task.due_date)

    # Capacity delta urgency (if task is under a Capacity)
    if task.priority_id:
        urgency += _capacity_delta_urgency(task.priority_id, graph)

    return min(urgency, 10.0)


def _due_date_urgency(due_date: datetime | None) -> float:
    """
    Calculate urgency based on due date proximity.

    Scale (0-10):
    - No due date: 0
    - > 30 days away: 1
    - 7-30 days: 2-5 (gradual increase)
    - 1-7 days: 5-8 (faster increase)
    - Due today: 9
    - Overdue: 10
    """
    if due_date is None:
        return 0.0

    now = datetime.now()

    # Handle date-only comparison (strip time if due_date has no time component)
    if due_date.hour == 0 and due_date.minute == 0 and due_date.second == 0:
        now = now.replace(hour=0, minute=0, second=0, microsecond=0)

    days_until = (due_date - now).days

    if days_until < 0:
        return 10.0  # Overdue
    elif days_until == 0:
        return 9.0   # Due today
    elif days_until <= 7:
        # 1-7 days: linear from 8 down to 5
        return 8.0 - (days_until - 1) * 0.5
    elif days_until <= 30:
        # 7-30 days: linear from 5 down to 2
        return 5.0 - (days_until - 7) * (3.0 / 23.0)
    else:
        return 1.0   # > 30 days


def _capacity_delta_urgency(priority_id: str, graph: PriorityGraph) -> float:
    """
    Calculate urgency based on capacity delta in the priority chain.

    Walks up the DAG to find a Capacity. If found, calculates urgency
    based on the gap between current and target level.

    Returns 0-5 (additive to due date urgency).
    """
    path = graph.path_to_root(priority_id)

    for pid in path:
        priority = graph.get(pid)
        if isinstance(priority, Capacity):
            return _parse_capacity_delta(priority)

    return 0.0


def _parse_capacity_delta(capacity: Capacity) -> float:
    """
    Parse current/target levels and return urgency based on delta.

    Handles various formats: "3", "3/10", "70%", etc.
    Returns 0-5 urgency score.
    """
    current = _parse_level(capacity.current_level)
    target = _parse_level(capacity.target_level)

    if current is None or target is None:
        return 0.0

    if target <= current:
        return 0.0  # At or above target

    # Delta as percentage of target
    delta_pct = (target - current) / target

    # Map to 0-5 scale
    return delta_pct * 5.0


def _parse_level(level_str: str | None) -> float | None:
    """
    Parse a level string into a numeric value.

    Handles:
    - "7" -> 7.0
    - "3/10" -> 3.0 (uses numerator for current, denominator for target)
    - "70%" -> 70.0 (percentage as number, not decimal)
    """
    if not level_str:
        return None

    level_str = level_str.strip()

    # Percentage: "70%" -> 70.0
    if level_str.endswith('%'):
        try:
            return float(level_str[:-1])
        except ValueError:
            pass

    # Fraction: "3/10" -> 3.0 (numerator only)
    if '/' in level_str:
        try:
            num, _ = level_str.split('/', 1)
            return float(num.strip())
        except ValueError:
            pass

    # Plain number
    try:
        return float(level_str)
    except ValueError:
        pass

    return None


# ---------------------------------------------------------------------------
# Combined Scoring
# ---------------------------------------------------------------------------

def score_task(task: Task, graph: PriorityGraph) -> ScoredTask:
    """
    Calculate the combined priority score for a task.

    Score = (importance * weight) + (urgency * weight)
    """
    importance = get_importance(task, graph)
    urgency = get_urgency(task, graph)

    score = (importance * IMPORTANCE_WEIGHT) + (urgency * URGENCY_WEIGHT)

    return ScoredTask(
        task=task,
        score=score,
        importance=importance,
        urgency=urgency,
    )


def rank_tasks(tasks: list[Task], graph: PriorityGraph) -> list[ScoredTask]:
    """
    Score and rank tasks by priority.

    Returns tasks sorted by score (highest first).
    """
    scored = [score_task(task, graph) for task in tasks]
    scored.sort(key=lambda st: st.score, reverse=True)
    return scored
