"""
Tests for DSL v2 execution engine.

Tests that parsed actions produce the correct outputs when executed.
"""

import pytest
from datetime import datetime
from pathlib import Path

from praxis_core.triggers.dsl_v2 import parse_practice
from praxis_core.triggers.engine_v2 import (
    ExecutionContext,
    execute_action,
    expand_template,
    parse_due_date,
    evaluate_condition,
    TaskSpec,
    PrioritySpec,
)
from praxis_core.triggers.models_v2 import Condition

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Load a YAML fixture file."""
    return (FIXTURES / name).read_text()


# -----------------------------------------------------------------------------
# Task creation
# -----------------------------------------------------------------------------

class TestTaskCreation:
    """Test that create actions produce correct task specs."""

    def test_practice_1_creates_task(self):
        """practice_1: Creates single task with correct properties."""
        yaml_content = load_fixture("practice_1.yml")
        practice = parse_practice(yaml_content)
        ctx = ExecutionContext(now=datetime(2026, 4, 3, 17, 0))
        result = execute_action(practice.actions[0], ctx)

        assert result.success
        assert len(result.tasks) == 1

        task = result.tasks[0]
        assert task.name == "Practice Leetcode"
        assert task.due_date == datetime(2026, 4, 3, 23, 59, 59)
        assert "code" in task.tags
        assert "deep_work" in task.tags

    def test_practice_2_creates_multiple_tasks(self):
        """practice_2: Creates two tasks from single action."""
        yaml_content = load_fixture("practice_2.yml")
        practice = parse_practice(yaml_content)
        ctx = ExecutionContext(now=datetime(2026, 4, 3, 17, 0))
        result = execute_action(practice.actions[0], ctx)

        assert result.success
        assert len(result.tasks) == 2
        assert all(t.name == "Practice Leetcode" for t in result.tasks)


# -----------------------------------------------------------------------------
# Template expansion
# -----------------------------------------------------------------------------

class TestTemplateExpansion:
    """Test that template variables expand correctly."""

    def test_date_variable(self):
        """{{date}} expands to ISO date."""
        ctx = ExecutionContext(now=datetime(2026, 4, 3, 14, 30))
        expanded = expand_template("Task for {{date}}", ctx)
        assert expanded == "Task for 2026-04-03"

    def test_event_variable(self):
        """{{event.name}} expands to triggering entity name."""
        ctx = ExecutionContext(
            now=datetime(2026, 4, 3),
            event_priority={"name": "Ship Project X", "priority_type": "goal"}
        )
        expanded = expand_template("Write case study: {{event.name}}", ctx)
        assert expanded == "Write case study: Ship Project X"


# -----------------------------------------------------------------------------
# Due date parsing
# -----------------------------------------------------------------------------

class TestDueDateParsing:
    """Test due date offset parsing."""

    def test_end_of_day(self):
        """end_of_day resolves to 23:59 today."""
        now = datetime(2026, 4, 3, 14, 30)
        due = parse_due_date("end_of_day", now)
        assert due == datetime(2026, 4, 3, 23, 59, 59)

    def test_plus_days(self):
        """+7d adds 7 days."""
        now = datetime(2026, 4, 3, 14, 30)
        due = parse_due_date("+7d", now)
        assert due.date() == datetime(2026, 4, 10).date()

    def test_structured_due(self):
        """Structured due with day and time."""
        now = datetime(2026, 4, 3, 14, 30)  # Friday
        due_spec = {"day": "monday", "time": "17:00"}
        due = parse_due_date(due_spec, now)
        # Monday after Friday April 3 is April 6
        assert due == datetime(2026, 4, 6, 17, 0)


# -----------------------------------------------------------------------------
# Condition evaluation
# -----------------------------------------------------------------------------

class TestConditionEvaluation:
    """Test condition evaluation."""

    def test_capacity_less_than(self):
        """capacity.less_than condition."""
        condition = Condition(type="capacity", params={"name": "Tech Interview", "less_than": 4.5})

        ctx = ExecutionContext(now=datetime(2026, 4, 3), capacities={"Tech Interview": 3.0})
        assert evaluate_condition(condition, ctx) == True

        ctx = ExecutionContext(now=datetime(2026, 4, 3), capacities={"Tech Interview": 5.0})
        assert evaluate_condition(condition, ctx) == False

    def test_event_type(self):
        """event.type condition."""
        condition = Condition(type="event", params={"type": "goal"})

        ctx = ExecutionContext(
            now=datetime(2026, 4, 3),
            event_priority={"priority_type": "goal"}
        )
        assert evaluate_condition(condition, ctx) == True

        ctx = ExecutionContext(
            now=datetime(2026, 4, 3),
            event_priority={"priority_type": "project"}
        )
        assert evaluate_condition(condition, ctx) == False

    def test_event_ancestor(self):
        """event.ancestor condition (name preserved for later resolution)."""
        # Ancestor resolution requires DB access, but we verify the condition
        # doesn't fail when ancestor is specified
        condition = Condition(type="event", params={"ancestor": "Career"})
        ctx = ExecutionContext(
            now=datetime(2026, 4, 3),
            event_priority={"priority_type": "goal", "name": "Ship MVP"}
        )
        # Should pass (ancestor check deferred to execution with DB)
        assert evaluate_condition(condition, ctx) == True


# -----------------------------------------------------------------------------
# Hierarchical create
# -----------------------------------------------------------------------------

class TestHierarchicalCreate:
    """Test priority + children creation."""

    def test_practice_5_creates_hierarchy(self):
        """practice_5: Creates priority with 4 child tasks."""
        yaml_content = load_fixture("practice_5.yml")
        practice = parse_practice(yaml_content)
        ctx = ExecutionContext(
            now=datetime(2026, 4, 3),
            event_priority={"name": "Ship MVP", "priority_type": "goal"}
        )
        result = execute_action(practice.actions[0], ctx)

        assert result.success
        assert len(result.priorities) == 1

        priority = result.priorities[0]
        assert priority.name == "Write a case study for Ship MVP"
        assert priority.type == "goal"
        assert len(priority.children) == 4

        # Verify children
        assert all(isinstance(c, TaskSpec) for c in priority.children)
        assert priority.children[0].name == "Gather resources"
        assert priority.children[3].name == "Publish & Post"


# -----------------------------------------------------------------------------
# Collation
# -----------------------------------------------------------------------------

class TestCollation:
    """Test task collation/batching."""

    def test_collate_children(self):
        """Collate target: children produces CollateSpec."""
        yaml_content = load_fixture("practice_6.yml")
        practice = parse_practice(yaml_content)
        ctx = ExecutionContext(now=datetime(2026, 4, 3, 8, 0))
        result = execute_action(practice.actions[0], ctx)

        assert result.success
        assert len(result.collations) == 1

        collation = result.collations[0]
        assert collation.target_shorthand == "children"
        assert "Shopping for" in collation.batch_name

    def test_collate_match_any(self):
        """Collate with match_any filter produces CollateSpec with filters."""
        yaml_content = load_fixture("practice_7.yml")
        practice = parse_practice(yaml_content)
        ctx = ExecutionContext(now=datetime(2026, 4, 3, 8, 0))
        result = execute_action(practice.actions[0], ctx)

        assert result.success
        assert len(result.collations) == 1

        collation = result.collations[0]
        assert collation.match_any is not None
        assert collation.exclude is not None
        assert "Shopping for" in collation.batch_name
