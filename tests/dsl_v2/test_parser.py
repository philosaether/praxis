"""
Tests for DSL v2 parser.

Each test parses a fixture file and verifies the resulting model structure.
Fixtures are Phil's practice_*.yml examples from the design phase.
"""

import pytest
from pathlib import Path

from praxis_core.triggers.dsl_v2 import parse_practice
from praxis_core.triggers.models_v2 import TaskTemplate, PriorityTemplate

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Load a YAML fixture file."""
    return (FIXTURES / name).read_text()


# -----------------------------------------------------------------------------
# Phase 1: Multi-action foundation
# -----------------------------------------------------------------------------

class TestPhase1MultiAction:
    """Test parsing of multi-action practices."""

    def test_practice_1_single_action(self):
        """practice_1: Single action with weekday schedule."""
        yaml_content = load_fixture("practice_1.yml")
        practice = parse_practice(yaml_content)

        assert practice.name == "Technical Interview Prep"
        assert len(practice.actions) == 1

        action = practice.actions[0]
        assert action.trigger.schedule is not None
        assert action.trigger.schedule.interval == "weekdays"

        assert action.create is not None
        assert len(action.create.items) == 1
        assert isinstance(action.create.items[0], TaskTemplate)
        assert action.create.items[0].name == "Practice Leetcode"

    def test_practice_2_multiple_tasks(self):
        """practice_2: Single action creating multiple tasks."""
        yaml_content = load_fixture("practice_2.yml")
        practice = parse_practice(yaml_content)

        assert practice.name == "Technical Interview Prep"
        assert len(practice.actions) == 1

        action = practice.actions[0]
        assert action.create is not None
        assert len(action.create.items) == 2
        assert all(isinstance(t, TaskTemplate) for t in action.create.items)
        assert all(t.name == "Practice Leetcode" for t in action.create.items)


# -----------------------------------------------------------------------------
# Phase 2: Custom cadence
# -----------------------------------------------------------------------------

class TestPhase2Cadence:
    """Test parsing of custom cadence intervals."""

    def test_practice_6_custom_cadence(self):
        """practice_6: 14-day cadence with anchor date."""
        from praxis_core.triggers.models_v2 import Cadence

        yaml_content = load_fixture("practice_6.yml")
        practice = parse_practice(yaml_content)

        assert practice.name == "Biweekly shopping"
        assert len(practice.actions) == 1

        action = practice.actions[0]
        assert action.trigger.schedule is not None

        interval = action.trigger.schedule.interval
        assert isinstance(interval, Cadence)
        assert interval.frequency == "14d"
        assert interval.beginning == "2026-04-03"
        assert interval.at == "08:00"


# -----------------------------------------------------------------------------
# Phase 3: Hierarchical create
# -----------------------------------------------------------------------------

class TestPhase3Hierarchy:
    """Test parsing of hierarchical create (priorities with children)."""

    def test_practice_5_priority_with_children(self):
        """practice_5: Create priority with child tasks."""
        yaml_content = load_fixture("practice_5.yml")
        practice = parse_practice(yaml_content)

        assert practice.name == "Show Your Work"
        assert len(practice.actions) == 1

        action = practice.actions[0]

        # Check event trigger
        assert action.trigger.event is not None
        assert action.trigger.event.type.value == "priority_completion"

        # Check create action
        assert action.create is not None
        assert len(action.create.items) == 1

        priority = action.create.items[0]
        assert isinstance(priority, PriorityTemplate)
        assert priority.name == "Write a case study for {{priority.name}}"
        assert priority.type == "goal"
        assert priority.due == "+30d"
        assert "writing" in priority.tags

        # Check children
        assert len(priority.children) == 4
        assert all(isinstance(c, TaskTemplate) for c in priority.children)
        assert priority.children[0].name == "Gather resources"
        assert priority.children[3].name == "Publish & Post"
        assert "publish" in priority.children[3].tags


# -----------------------------------------------------------------------------
# Phase 4: Enhanced collation
# -----------------------------------------------------------------------------

class TestPhase4Collation:
    """Test parsing of collation with match_any/match_all/exclude."""

    def test_practice_6_simple_collate(self):
        """practice_6: Simple collate with target: children."""
        yaml_content = load_fixture("practice_6.yml")
        practice = parse_practice(yaml_content)

        assert len(practice.actions) == 1
        action = practice.actions[0]

        assert action.collate is not None
        assert action.collate.target.shorthand == "children"
        assert action.collate.as_template.name == "Shopping for {{today}}"

    def test_practice_7_filtered_collate(self):
        """practice_7: Collate with match_any and exclude."""
        yaml_content = load_fixture("practice_7.yml")
        practice = parse_practice(yaml_content)

        assert len(practice.actions) == 1
        action = practice.actions[0]

        assert action.collate is not None
        target = action.collate.target

        # Should have match_any with ancestor and tag
        assert target.match_any is not None
        assert len(target.match_any) == 2
        # Check that ancestor and tag are in match_any
        match_any_keys = [list(d.keys())[0] for d in target.match_any]
        assert "ancestor" in match_any_keys
        assert "tag" in match_any_keys

        # Should have exclude with status: done
        assert target.exclude is not None
        assert len(target.exclude) == 1
        assert target.exclude[0] == {"status": "done"}


# -----------------------------------------------------------------------------
# Phase 5: Name resolution
# -----------------------------------------------------------------------------

class TestPhase5NameResolution:
    """Test name-to-ID resolution."""

    def test_practice_4_ancestor_reference(self):
        """practice_4: Reference 'Career' by name is preserved for later resolution."""
        yaml_content = load_fixture("practice_4.yml")
        practice = parse_practice(yaml_content)

        # At parse time, names are preserved as-is
        # Resolution to IDs happens at execution time
        action = practice.actions[0]

        # Find the event condition with ancestor
        event_condition = None
        for c in action.conditions:
            if c.type == "event":
                event_condition = c
                break

        assert event_condition is not None
        assert event_condition.params.get("ancestor") == "Career"


# -----------------------------------------------------------------------------
# Phase 6: Explicit condition subjects
# -----------------------------------------------------------------------------

class TestPhase6Conditions:
    """Test parsing of explicit condition subjects."""

    def test_practice_3_capacity_condition(self):
        """practice_3: Capacity threshold conditions."""
        yaml_content = load_fixture("practice_3.yml")
        practice = parse_practice(yaml_content)

        # Should have 2 actions (building vs maintenance)
        assert len(practice.actions) == 2

        # First action: capacity less_than 4.5
        action0 = practice.actions[0]
        cap_condition0 = None
        for c in action0.conditions:
            if c.type == "capacity":
                cap_condition0 = c
                break
        assert cap_condition0 is not None
        assert cap_condition0.params.get("less_than") == 4.5

        # Second action: capacity at_least 4.5
        action1 = practice.actions[1]
        cap_condition1 = None
        for c in action1.conditions:
            if c.type == "capacity":
                cap_condition1 = c
                break
        assert cap_condition1 is not None
        assert cap_condition1.params.get("at_least") == 4.5

    def test_practice_4_event_conditions(self):
        """practice_4: Event type and ancestor conditions."""
        yaml_content = load_fixture("practice_4.yml")
        practice = parse_practice(yaml_content)

        action = practice.actions[0]

        # Find event condition
        event_condition = None
        for c in action.conditions:
            if c.type == "event":
                event_condition = c
                break

        assert event_condition is not None
        assert event_condition.params.get("type") == "goal"
        assert event_condition.params.get("ancestor") == "Career"


# -----------------------------------------------------------------------------
# Smoke test helper
# -----------------------------------------------------------------------------

def test_all_fixtures_load():
    """Verify all fixture files are readable YAML."""
    import yaml

    for fixture_path in FIXTURES.glob("*.yml"):
        content = fixture_path.read_text()
        try:
            data = yaml.safe_load(content)
            assert "practice" in data, f"{fixture_path.name}: missing 'practice' key"
        except yaml.YAMLError as e:
            pytest.fail(f"{fixture_path.name}: invalid YAML - {e}")
