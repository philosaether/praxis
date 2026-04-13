"""
Verify rules-based task scoring across a day.

Simulates Phil's workflow rules against a set of tagged tasks,
walking through a day in hourly increments to show how the queue
reorders based on time-of-day, tags, due dates, and engagement recency.

Run:  python -m tests.test_rules_scoring
"""

from datetime import datetime, timedelta
from dataclasses import dataclass

from praxis_core.model import Task
from praxis_core.model.tasks import TaskStatus
from praxis_core.model.rules import (
    Rule, RuleCondition, RuleEffect,
    ConditionType, EffectTarget, EffectOperator,
)
from praxis_core.rules.engine import evaluate_rules


# -- Mock tasks ---------------------------------------------------------------

def make_task(name: str, priority_id: str = "p1", due_date: datetime | None = None) -> Task:
    return Task(
        id=name.lower().replace(" ", "_"),
        name=name,
        entity_id="test",
        status=TaskStatus.QUEUED,
        priority_id=priority_id,
        due_date=due_date,
        created_at=datetime(2026, 4, 10),
    )


# Tasks with different tags and priorities
MONDAY = datetime(2026, 4, 13)

TASKS = {
    "Leetcode": {
        "task": make_task("Do a Leetcode", priority_id="practice_leet"),
        "tags": {"deep_work"},
        "last_engaged_at": MONDAY - timedelta(days=1),  # yesterday
    },
    "Refactor engine": {
        "task": make_task("Refactor scoring engine", priority_id="praxis"),
        "tags": {"deep_work"},
        "last_engaged_at": MONDAY - timedelta(hours=12),
    },
    "Call Akanksha": {
        "task": make_task("Call Akanksha", priority_id="networking"),
        "tags": {"networking"},
        "last_engaged_at": MONDAY - timedelta(days=10),  # 10 days ago
    },
    "File taxes": {
        "task": make_task("File taxes", priority_id="admin",
                          due_date=MONDAY + timedelta(days=2)),
        "tags": {"admin"},
        "last_engaged_at": MONDAY - timedelta(days=5),
    },
    "Read Dune": {
        "task": make_task("Read Dune", priority_id="reading"),
        "tags": {"relaxation"},
        "last_engaged_at": MONDAY - timedelta(days=2),
    },
}


# -- Phil's rules ------------------------------------------------------------

def make_rule(name: str, priority: int, conditions: list, effects: list) -> Rule:
    return Rule(
        id=name.lower().replace(" ", "_"),
        name=name,
        entity_id="test",
        priority=priority,
        conditions=[RuleCondition(type=c[0], params=c[1]) for c in conditions],
        effects=[RuleEffect(target=e[0], operator=e[1], value=e[2], formula=e[3] if len(e) > 3 else None) for e in effects],
    )


RULES = [
    # System defaults
    make_rule("Due Date Pressure", 100,
        [(ConditionType.DUE_DATE_PROXIMITY, {"has_due_date": True, "overdue": False})],
        [(EffectTarget.URGENCY, EffectOperator.FORMULA, None, "min(10, 10 / max(1, days_until_due))")],
    ),
    make_rule("Overdue Penalty", 110,
        [(ConditionType.DUE_DATE_PROXIMITY, {"overdue": True})],
        [(EffectTarget.URGENCY, EffectOperator.FORMULA, None, "min(15, 10 + days_overdue)")],
    ),
    make_rule("Staleness Rise", 50,
        [(ConditionType.STALENESS, {"days_untouched": 3, "operator": "gte"})],
        [(EffectTarget.URGENCY, EffectOperator.FORMULA, None, "min(5, (days_since_touched - 3) / 3 + 1)")],
    ),

    # Morning: boost deep work
    make_rule("Morning Deep Work", 80,
        [
            (ConditionType.TIME_WINDOW, {"start": "06:00", "end": "12:00"}),
            (ConditionType.TAG_MATCH, {"tag": "deep_work", "operator": "has"}),
        ],
        [(EffectTarget.APTNESS, EffectOperator.MULTIPLY, 2.0)],
    ),

    # Afternoon: boost non-deep-work tasks
    make_rule("Afternoon Non-Deep", 80,
        [
            (ConditionType.TIME_WINDOW, {"start": "12:00", "end": "17:00"}),
            (ConditionType.TAG_MATCH, {"tag": "deep_work", "operator": "missing"}),
        ],
        [(EffectTarget.APTNESS, EffectOperator.MULTIPLY, 1.5)],
    ),

    # Afternoon: networking urgency from recency
    make_rule("Networking Recency", 70,
        [
            (ConditionType.TAG_MATCH, {"tag": "networking", "operator": "has"}),
        ],
        [(EffectTarget.URGENCY, EffectOperator.FORMULA, None,
          "min(8, days_since_last_engaged / 2)")],
    ),

    # Evening: boost relaxation
    make_rule("Evening Relaxation", 80,
        [
            (ConditionType.TIME_WINDOW, {"start": "17:00", "end": "23:00"}),
            (ConditionType.TAG_MATCH, {"tag": "relaxation", "operator": "has"}),
        ],
        [(EffectTarget.APTNESS, EffectOperator.MULTIPLY, 2.0)],
    ),
]

# Sort by priority (highest first) as the engine expects
RULES.sort(key=lambda r: r.priority, reverse=True)


# -- Simulation ---------------------------------------------------------------

BASE_IMPORTANCE = 5.0  # default for all tasks in this test


def score_at(task_name: str, hour: int) -> tuple[float, float, float, float, list[str]]:
    """Score a task at a given hour on MONDAY. Returns (score, importance, urgency, aptness, rules)."""
    entry = TASKS[task_name]
    task = entry["task"]
    tags = entry["tags"]
    last_engaged = entry["last_engaged_at"]
    now = MONDAY.replace(hour=hour)

    result = evaluate_rules(
        rules=RULES,
        task=task,
        task_tags=tags,
        base_importance=BASE_IMPORTANCE,
        base_urgency=0.0,
        last_engaged_at=last_engaged,
        now=now,
    )

    importance = BASE_IMPORTANCE + result.importance_modifier
    urgency = result.urgency_modifier
    aptness = result.aptness
    score = (importance + urgency) * aptness

    return score, importance, urgency, aptness, result.matched_rules


def main():
    hours_to_check = [7, 10, 13, 15, 18, 21]
    task_names = list(TASKS.keys())

    print("=" * 90)
    print("RULES SCORING VERIFICATION — Monday 2026-04-13")
    print("=" * 90)

    for hour in hours_to_check:
        time_label = f"{hour:02d}:00"
        print(f"\n--- {time_label} ---")

        scored = []
        for name in task_names:
            score, imp, urg, apt, rules = score_at(name, hour)
            scored.append((score, name, imp, urg, apt, rules))

        scored.sort(reverse=True)

        for rank, (score, name, imp, urg, apt, rules) in enumerate(scored, 1):
            rule_names = ", ".join(r.replace("_", " ") for r in rules) if rules else "none"
            print(f"  {rank}. {name:<20s}  score={score:6.1f}  "
                  f"(I={imp:.0f} U={urg:.1f} A={apt:.1f})  "
                  f"rules: {rule_names}")


if __name__ == "__main__":
    main()
