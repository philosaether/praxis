import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from enum import StrEnum

from praxis_core.models import Task

CONFIG_DIR = Path.home() / ".praxis"
FILTERS_PATH = CONFIG_DIR / "filters.json"


# ---------------------------------------------------------------------
# Filter Type Registry
# ---------------------------------------------------------------------

class MatchType(StrEnum):
    WORKSTREAM = "workstream"  # Match tasks in a specific workstream
    USER = "user"              # Match tasks assigned to a user (future)
    TAG = "tag"                # Match tasks with a specific tag (future)
    ALL = "all"                # Match all tasks


class ConstraintType(StrEnum):
    HOURS = "hours"            # Time of day: {"after": 9, "before": 17}
    DAYS = "days"              # Day of week: {"only": [...]} or {"exclude": [...]}
    DUE_WITHIN = "due_within"  # Due date proximity: {"days": 3} (future)
    PRIORITY = "priority"      # Task priority level (future)

FILTER_TYPES = {
    "match": list(MatchType),
    "constraint": list(ConstraintType),
}


@dataclass
class ScoredTask:
    task: Task
    weight: float = 0.0

def load_filters() -> list[dict]:
    if not FILTERS_PATH.exists():
        return []
    
    with open(FILTERS_PATH) as filters:
        data = json.load(filters)
    
    if isinstance(data, dict):
        return data.get("filters", [])
    return data

def _matches_task(filter_definition: dict, task: Task, user: str | None = None) -> bool:
    match = filter_definition.get("match", {})

    if match.get(MatchType.ALL):
        return True

    if MatchType.WORKSTREAM in match:
        if task.workstream_name != match[MatchType.WORKSTREAM]:
            return False

    if MatchType.USER in match:
        if user is None or user != match[MatchType.USER]:
            return False

    if MatchType.TAG in match:
        # TODO: implement when tasks have tags
        pass
    
    return True

def _check_hours_constraint(constraint: dict, now: datetime) -> bool:
    hour = now.hour

    if "after" in constraint and hour < constraint["after"]:
        return False
    if "before" in constraint and hour >= constraint["before"]:
        return False
    
    return True

def _check_days_constraint(constraint: dict, now: datetime) -> bool:
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    today = day_names[now.weekday()]

    if "only" in constraint:
        return today in constraint["only"]
    if "exclude" in constraint:
        return today not in constraint["exclude"]

    return True

def _evaluate_constraint(constraint_type: str, constraint_value: dict, now: datetime) -> bool:
    if constraint_type == ConstraintType.HOURS:
        return _check_hours_constraint(constraint_value, now)
    elif constraint_type == ConstraintType.DAYS:
        return _check_days_constraint(constraint_value, now)
    else:
        return True   

def _evaluate_hard_filter(filter_definition: dict, now: datetime) -> bool:
    constraint = filter_definition.get("constraint", {})

    for constraint_type, constraint_value in constraint.items():
        if not _evaluate_constraint(constraint_type, constraint_value, now):
            return False

    return True

def _evaluate_soft_filter(filter_definition: dict, now: datetime) -> float:
    weight_definition = filter_definition.get("weight", {})
    boost = weight_definition.get("boost", 0)
    when = weight_definition.get("when", {})

    if not when:
        return boost

    for constraint_type, constraint_value in when.items():
        if not _evaluate_constraint(constraint_type, constraint_value, now):
            return 0

    return boost

def apply_filters(
    tasks: list[Task],
    user: str | None = None,
    now: datetime | None = None,
) -> list[ScoredTask]:
    
    results = []
    
    if now is None:
        now = datetime.now()

    filters = load_filters()
    hard_filters = [filter for filter in filters if filter.get("type") == "hard"]
    soft_filters = [filter for filter in filters if filter.get("type") == "soft"]

    for task in tasks:
        excluded = False
        for filter_definition in hard_filters:
            if _matches_task(filter_definition, task, user):
                if not _evaluate_hard_filter(filter_definition, now):
                    excluded = True
                    break

        if excluded:
            continue

        weight = 0.0
        for filter_definition in soft_filters:
            if _matches_task(filter_definition, task, user):
                weight += _evaluate_soft_filter(filter_definition, now)

        results.append(ScoredTask(task=task, weight=weight))

    results.sort(key=lambda scored_task: scored_task.weight, reverse=True)

    return results