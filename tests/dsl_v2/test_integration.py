"""
Integration tests for DSL v2.

End-to-end tests that verify the full flow:
YAML -> parse -> execute -> database
"""

import pytest
from datetime import datetime
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Load a YAML fixture file."""
    return (FIXTURES / name).read_text()


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Create a temporary test database."""
    import importlib

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("PRAXIS_DB_PATH", str(db_path))

    # Reload the database module to pick up new path
    import praxis_core.persistence.database as db_module
    importlib.reload(db_module)  # Force reload to pick up new env var

    # Ensure all required schemas exist
    import praxis_core.persistence.user_persistence as user_persistence
    import praxis_core.persistence.task_persistence as task_persistence
    import praxis_core.persistence.tag_persistence as tag_persistence
    importlib.reload(user_persistence)
    importlib.reload(task_persistence)
    importlib.reload(tag_persistence)

    user_persistence.ensure_schema()  # Creates users, entities, sessions tables
    task_persistence.ensure_schema()  # Creates tasks table
    tag_persistence.ensure_schema()   # Creates tags, task_tags tables

    # Priority schema is initialized via PriorityGraph
    import praxis_core.persistence.priority_persistence as priority_persistence
    importlib.reload(priority_persistence)
    graph = priority_persistence.PriorityGraph(db_module.get_connection, entity_id=None)
    graph.load()  # This initializes the priorities table

    # Create test entity for foreign key constraints
    with db_module.get_connection() as conn:
        conn.execute(
            "INSERT INTO entities (id, type, name) VALUES (?, ?, ?)",
            ("test-entity-123", "user", "Test Entity"),
        )

    yield db_path


# -----------------------------------------------------------------------------
# Full flow tests
# -----------------------------------------------------------------------------

class TestFullFlow:
    """End-to-end tests with actual database operations."""

    def test_practice_1_e2e(self, test_db):
        """practice_1: Full flow from YAML to task in database."""
        from praxis_core.triggers.dsl_v2 import parse_practice
        from praxis_core.triggers.engine_v2 import ExecutionContext
        from praxis_core.triggers.executor_v2 import execute_and_persist
        from praxis_core.persistence.task_persistence import list_tasks

        # 1. Parse YAML
        yaml_content = load_fixture("practice_1.yml")
        practice = parse_practice(yaml_content)

        # 2. Execute action
        ctx = ExecutionContext(
            now=datetime(2026, 4, 3, 17, 0),
            entity_id="test-entity-123",
        )
        action = practice.actions[0]
        counts = execute_and_persist(action, ctx, practice_id=None, created_by=None)

        # 3. Verify task created
        assert counts["tasks"] == 1
        assert counts.get("error") is None

        # 4. Verify in database
        tasks = list_tasks(entity_id="test-entity-123")
        assert len(tasks) == 1
        assert tasks[0].name == "Practice Leetcode"

    def test_practice_5_e2e(self, test_db):
        """practice_5: Priority + children created in single transaction."""
        from praxis_core.triggers.dsl_v2 import parse_practice
        from praxis_core.triggers.engine_v2 import ExecutionContext
        from praxis_core.triggers.executor_v2 import execute_and_persist
        from praxis_core.persistence.task_persistence import list_tasks
        from praxis_core.persistence.priority_persistence import PriorityGraph
        from praxis_core.persistence.database import get_connection

        # 1. Parse YAML
        yaml_content = load_fixture("practice_5.yml")
        practice = parse_practice(yaml_content)

        # 2. Execute with event context
        ctx = ExecutionContext(
            now=datetime(2026, 4, 3, 10, 0),
            entity_id="test-entity-123",
            event_priority={"name": "Ship MVP", "priority_type": "goal"},
        )
        action = practice.actions[0]
        counts = execute_and_persist(action, ctx)

        # 3. Verify counts
        assert counts.get("error") is None
        assert counts["priorities"] == 1
        assert counts["tasks"] == 4  # 4 child tasks

        # 4. Verify priority in database
        graph = PriorityGraph(get_connection, entity_id="test-entity-123")
        graph.load()
        priorities = list(graph.nodes.values())
        assert len(priorities) == 1
        assert "case study" in priorities[0].name.lower()

        # 5. Verify tasks under the priority
        tasks = list_tasks(priority_id=priorities[0].id)
        assert len(tasks) == 4
        task_names = [t.name for t in tasks]
        assert "Gather resources" in task_names
        assert "Publish & Post" in task_names


# -----------------------------------------------------------------------------
# Schedule matching tests
# -----------------------------------------------------------------------------

class TestScheduleMatching:
    """Test that schedules fire at correct times."""

    def test_weekday_schedule_fires_on_monday(self):
        """Weekday schedule should fire on Monday."""
        from praxis_core.triggers.models_v2 import Schedule
        from praxis_core.triggers.schedule_v2 import should_schedule_fire

        schedule = Schedule(interval="weekdays", at="09:00")
        # Monday April 6, 2026 at 10:00 (after scheduled time)
        now = datetime(2026, 4, 6, 10, 0)
        last_fired = None

        assert should_schedule_fire(schedule, now, last_fired) == True

    def test_weekday_schedule_skips_saturday(self):
        """Weekday schedule should not fire on Saturday."""
        from praxis_core.triggers.models_v2 import Schedule
        from praxis_core.triggers.schedule_v2 import should_schedule_fire

        schedule = Schedule(interval="weekdays", at="09:00")
        # Saturday April 4, 2026
        now = datetime(2026, 4, 4, 10, 0)
        last_fired = None

        assert should_schedule_fire(schedule, now, last_fired) == False

    def test_custom_cadence_respects_anchor(self):
        """14d cadence anchored to 2026-04-03 fires correctly."""
        from praxis_core.triggers.models_v2 import Schedule, Cadence
        from praxis_core.triggers.schedule_v2 import should_schedule_fire

        cadence = Cadence(frequency="14d", beginning="2026-04-03", at="08:00")
        schedule = Schedule(interval=cadence)

        # Should fire on April 3 (anchor date)
        now = datetime(2026, 4, 3, 9, 0)
        assert should_schedule_fire(schedule, now, None) == True

        # Should NOT fire on April 10 (7 days later, not 14)
        now = datetime(2026, 4, 10, 9, 0)
        assert should_schedule_fire(schedule, now, None) == False

        # Should fire on April 17 (14 days later)
        now = datetime(2026, 4, 17, 9, 0)
        assert should_schedule_fire(schedule, now, None) == True


# -----------------------------------------------------------------------------
# Event trigger tests
# -----------------------------------------------------------------------------

class TestEventTriggers:
    """Test event-based trigger firing."""

    def test_priority_completion_fires_trigger(self):
        """Completing a goal fires practice_4 style trigger."""
        from praxis_core.triggers.dsl_v2 import parse_practice
        from praxis_core.triggers.engine_v2 import ExecutionContext, execute_action

        yaml_content = load_fixture("practice_4.yml")
        practice = parse_practice(yaml_content)
        action = practice.actions[0]

        # Simulate completing a goal under Career
        ctx = ExecutionContext(
            now=datetime(2026, 4, 3, 10, 0),
            entity_id="test-entity",
            event_priority={"name": "Ship MVP", "priority_type": "goal"},
        )

        result = execute_action(action, ctx)
        assert result.success
        assert len(result.tasks) == 1
        assert "case study" in result.tasks[0].name.lower()

    def test_event_conditions_filter_correctly(self):
        """Trigger only fires when event conditions match."""
        from praxis_core.triggers.dsl_v2 import parse_practice
        from praxis_core.triggers.engine_v2 import ExecutionContext, execute_action

        yaml_content = load_fixture("practice_4.yml")
        practice = parse_practice(yaml_content)
        action = practice.actions[0]

        # Complete a "project" type - should NOT fire (condition is type: goal)
        ctx = ExecutionContext(
            now=datetime(2026, 4, 3, 10, 0),
            entity_id="test-entity",
            event_priority={"name": "Some Project", "priority_type": "project"},
        )

        result = execute_action(action, ctx)
        assert not result.success
        assert result.error_message == "Conditions not met"
