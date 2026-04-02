"""Default system rules that ship with Praxis."""


def get_default_rules() -> list[dict]:
    """
    Return the default system rules.

    These rules implement the core prioritization behaviors:
    - Due date pressure (urgency increases as deadline approaches)
    - Overdue penalty (urgency continues climbing after deadline)
    - Staleness rise (untouched tasks gradually gain urgency)

    Rules are defined as dicts matching the Rule schema for easy
    modification and iteration during development.
    """
    return [
        # ---------------------------------------------------------------------
        # Due Date Rules
        # ---------------------------------------------------------------------
        {
            "id": "system-due-date-curve",
            "name": "Due Date Pressure",
            "description": "Urgency increases smoothly as due date approaches",
            "priority": 100,
            "conditions": [
                {
                    "type": "due_date_proximity",
                    "params": {"has_due_date": True, "overdue": False},
                },
            ],
            "effects": [
                {
                    "target": "urgency",
                    "operator": "formula",
                    # Smooth curve: urgency rises from 0 to 10 as deadline approaches
                    # At 7 days out: ~1.4, at 1 day out: 10, at 1 hour out: ~10
                    "formula": "min(10, 10 / max(1, days_until_due))",
                },
            ],
        },
        {
            "id": "system-overdue-penalty",
            "name": "Overdue Penalty",
            "description": "Overdue tasks have maximum urgency plus penalty",
            "priority": 110,  # Higher priority than due date curve
            "conditions": [
                {
                    "type": "due_date_proximity",
                    "params": {"overdue": True},
                },
            ],
            "effects": [
                {
                    "target": "urgency",
                    "operator": "formula",
                    # Base urgency of 10 plus 1 per day overdue, capped at 15
                    "formula": "min(15, 10 + days_overdue)",
                },
            ],
        },
        # ---------------------------------------------------------------------
        # Staleness Rules
        # ---------------------------------------------------------------------
        {
            "id": "system-staleness-rise",
            "name": "Staleness Rise",
            "description": "Tasks untouched for days gradually gain urgency",
            "priority": 50,
            "conditions": [
                {
                    "type": "staleness",
                    "params": {"days_untouched": 3, "operator": "gte"},
                },
            ],
            "effects": [
                {
                    "target": "urgency",
                    "operator": "formula",
                    # +1 urgency per 3 days untouched, capped at +5
                    "formula": "min(5, (days_since_touched - 3) / 3 + 1)",
                },
            ],
        },
        # ---------------------------------------------------------------------
        # Time-Based Rules (examples for users to customize)
        # ---------------------------------------------------------------------
        # These are disabled by default but serve as templates
        # {
        #     "id": "system-morning-focus",
        #     "name": "Morning Focus",
        #     "description": "Boost deep-work tasks during morning hours",
        #     "priority": 30,
        #     "conditions": [
        #         {"type": "time_window", "params": {"start": "08:00", "end": "12:00"}},
        #         {"type": "tag_match", "params": {"tag": "deep-work", "operator": "has"}},
        #     ],
        #     "effects": [
        #         {"target": "aptness", "operator": "multiply", "value": 1.5},
        #     ],
        # },
        # {
        #     "id": "system-evening-wind-down",
        #     "name": "Evening Wind Down",
        #     "description": "Suppress deep-work tasks in the evening",
        #     "priority": 30,
        #     "conditions": [
        #         {"type": "time_window", "params": {"start": "18:00", "end": "23:59"}},
        #         {"type": "tag_match", "params": {"tag": "deep-work", "operator": "has"}},
        #     ],
        #     "effects": [
        #         {"target": "aptness", "operator": "multiply", "value": 0.3},
        #     ],
        # },
    ]


# Rule templates for the wizard (future feature)
RULE_TEMPLATES = [
    {
        "id": "template-morning-focus",
        "name": "Morning Focus",
        "description": "Boost deep-work tasks during morning hours (8am-12pm)",
        "conditions": [
            {"type": "time_window", "params": {"start": "08:00", "end": "12:00"}},
            {"type": "tag_match", "params": {"tag": "deep-work", "operator": "has"}},
        ],
        "effects": [
            {"target": "aptness", "operator": "multiply", "value": 1.5},
        ],
    },
    {
        "id": "template-evening-wind-down",
        "name": "Evening Wind Down",
        "description": "Suppress deep-work tasks in the evening",
        "conditions": [
            {"type": "time_window", "params": {"start": "18:00", "end": "23:59"}},
            {"type": "tag_match", "params": {"tag": "deep-work", "operator": "has"}},
        ],
        "effects": [
            {"target": "aptness", "operator": "multiply", "value": 0.3},
        ],
    },
    {
        "id": "template-weekend-mode",
        "name": "Weekend Mode",
        "description": "Suppress work tasks on weekends",
        "conditions": [
            {"type": "day_of_week", "params": {"days": ["saturday", "sunday"]}},
            {"type": "tag_match", "params": {"tag": "work", "operator": "has"}},
        ],
        "effects": [
            {"target": "aptness", "operator": "multiply", "value": 0.2},
        ],
    },
    {
        "id": "template-exercise-streak",
        "name": "Exercise Streak",
        "description": "Urgency increases the longer since last exercise",
        "conditions": [
            {"type": "tag_match", "params": {"tag": "exercise", "operator": "has"}},
            {"type": "recency", "params": {"tag": "exercise", "days_since": 1, "operator": "gte"}},
        ],
        "effects": [
            {
                "target": "urgency",
                "operator": "formula",
                "formula": "min(10, days_since_tag_completion * 2)",
            },
        ],
    },
    {
        "id": "template-quick-wins",
        "name": "Quick Wins",
        "description": "Boost quick tasks tagged for short time windows",
        "conditions": [
            {"type": "tag_match", "params": {"tag": "quick", "operator": "has"}},
        ],
        "effects": [
            {"target": "aptness", "operator": "multiply", "value": 1.3},
        ],
    },
    {
        "id": "template-low-energy",
        "name": "Low Energy Evening",
        "description": "Boost low-energy tasks after 6pm",
        "conditions": [
            {"type": "time_window", "params": {"start": "18:00", "end": "23:59"}},
            {"type": "tag_match", "params": {"tag": "low-energy", "operator": "has"}},
        ],
        "effects": [
            {"target": "aptness", "operator": "multiply", "value": 1.4},
        ],
    },
]
