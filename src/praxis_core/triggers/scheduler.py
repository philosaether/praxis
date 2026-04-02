"""
Trigger Scheduler - Background thread for automated task generation.

Handles:
- Checking scheduled triggers every minute
- Tracking time boundaries for Rules rescore
- Executing trigger actions when due
- Pushing SSE events for real-time updates
- Catch-up logic for missed scheduled triggers
"""

import asyncio
import threading
import time
import logging
from datetime import datetime, timedelta
from typing import Callable

from praxis_core.model.triggers import TriggerActionType
from praxis_core.triggers.engine import (
    TriggerContext,
    execute_trigger,
    should_trigger_fire,
)
from praxis_core.persistence import (
    list_triggers_by_event_type,
    record_trigger_fire,
    create_task,
)
from praxis_core.api.sse import (
    get_sse_manager,
    task_created_event,
    trigger_fired_event,
    rescore_event,
)


logger = logging.getLogger(__name__)


class TriggerScheduler:
    """
    Background scheduler for trigger execution.

    Runs in a daemon thread and checks for:
    - Scheduled triggers that are due to fire
    - Time boundaries that affect Rules scoring

    Usage:
        scheduler = TriggerScheduler()
        scheduler.start()
        # ... app runs ...
        scheduler.stop()
    """

    def __init__(self, check_interval_seconds: int = 60):
        """
        Initialize the scheduler.

        Args:
            check_interval_seconds: How often to check triggers (default: 60s)
        """
        self.check_interval = check_interval_seconds
        self.running = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event = threading.Event()

        # Track last known time boundaries for rescore detection
        self._last_check_time: datetime | None = None

        # Optional callback for task creation (allows testing without persistence)
        self._create_task_callback: Callable | None = None

    def start(self):
        """Start the scheduler background thread."""
        if self.running:
            logger.warning("Scheduler already running")
            return

        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Trigger scheduler started (on-demand mode)")

        # Do immediate catch-up check for any missed triggers
        self._do_catchup_check()

    def stop(self):
        """Stop the scheduler gracefully."""
        if not self.running:
            return

        logger.info("Stopping trigger scheduler...")
        self.running = False
        self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

        logger.info("Trigger scheduler stopped")

    def _do_catchup_check(self):
        """Check for any triggers that should have fired while offline."""
        try:
            now = datetime.now()
            triggers = list_triggers_by_event_type(
                event_type="schedule",
                enabled_only=True
            )

            for trigger in triggers:
                if should_trigger_fire(trigger, now):
                    logger.info(f"Catch-up: firing trigger {trigger.name}")
                    # Run in a separate thread to not block startup
                    threading.Thread(
                        target=self._execute_scheduled_trigger,
                        args=(trigger, now),
                        daemon=True
                    ).start()

        except Exception as e:
            logger.error(f"Error in catch-up check: {e}", exc_info=True)

    def _run_loop(self):
        """Main scheduler loop (runs in background thread)."""
        # Create a new event loop for this thread
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            while self.running:
                try:
                    now = datetime.now()

                    # Check scheduled triggers
                    self._check_scheduled_triggers(now)

                    # Check time boundaries for Rules rescore
                    self._check_time_boundaries(now)

                    self._last_check_time = now

                except Exception as e:
                    logger.error(f"Error in scheduler loop: {e}", exc_info=True)

                # Wait for next check (interruptible)
                self._stop_event.wait(timeout=self.check_interval)

        finally:
            self._loop.close()
            self._loop = None

    def _check_scheduled_triggers(self, now: datetime):
        """Check and execute any scheduled triggers that are due."""
        try:
            # Get all enabled scheduled triggers
            triggers = list_triggers_by_event_type(
                event_type="schedule",
                enabled_only=True
            )

            for trigger in triggers:
                if should_trigger_fire(trigger, now):
                    self._execute_scheduled_trigger(trigger, now)

        except Exception as e:
            logger.error(f"Error checking scheduled triggers: {e}", exc_info=True)

    def _execute_scheduled_trigger(self, trigger, now: datetime):
        """Execute a scheduled trigger and handle catch-up logic."""
        try:
            logger.info(f"Executing trigger: {trigger.name} ({trigger.id})")

            # Calculate missed fires for catch-up
            missed_count = self._calculate_missed_fires(trigger, now)

            # Create context
            ctx = TriggerContext(
                now=now,
                entity_id=trigger.entity_id,
            )

            # If trigger is attached to a practice, load practice data
            if trigger.practice_id:
                ctx.practice = self._get_practice_data(trigger.practice_id)

            # Execute the trigger
            result = execute_trigger(trigger, ctx)

            if result.success:
                # Process actions
                for action in result.actions_taken:
                    self._process_action(action, trigger, ctx, missed_count)

                # Record that trigger fired
                record_trigger_fire(trigger.id, now)

                # Send SSE notification
                self._send_trigger_fired_event(trigger, result.actions_taken)

            else:
                logger.debug(f"Trigger {trigger.name} conditions not met: {result.error_message}")

        except Exception as e:
            logger.error(f"Error executing trigger {trigger.id}: {e}", exc_info=True)

    def _calculate_missed_fires(self, trigger, now: datetime) -> int:
        """
        Calculate how many scheduled fires were missed.

        Returns the number of missed fires (0 if none).
        """
        if not trigger.last_fired_at:
            return 0

        params = trigger.event.params
        interval = params.get("interval", "daily")

        last_fired = trigger.last_fired_at
        days_since = (now.date() - last_fired.date()).days

        if interval == "daily" or interval == "weekdays":
            # One fire per day
            if interval == "weekdays":
                # Count only weekdays
                missed = 0
                check_date = last_fired.date() + timedelta(days=1)
                while check_date < now.date():
                    if check_date.weekday() < 5:  # Monday-Friday
                        missed += 1
                    check_date += timedelta(days=1)
                return missed
            else:
                return max(0, days_since - 1)

        elif interval == "weekly":
            weeks_since = days_since // 7
            return max(0, weeks_since - 1)

        elif interval == "2x_daily":
            hours_since = (now - last_fired).total_seconds() / 3600
            expected_fires = int(hours_since / 8)  # 8 hours between fires
            return max(0, expected_fires - 1)

        return 0

    def _process_action(
        self,
        action: dict,
        trigger,
        ctx: TriggerContext,
        missed_count: int
    ):
        """Process a trigger action (create task, collate, etc.)."""
        action_type = action["type"]
        params = action["params"]

        if action_type == "create_task":
            self._create_task(params, trigger, missed_count)

        elif action_type == "collate_tasks":
            self._collate_tasks(params, trigger)

    def _create_task(self, params: dict, trigger, missed_count: int):
        """Create a task from trigger action parameters."""
        try:
            name = params["name"]
            notes = params.get("notes") or ""

            # Add catch-up info to notes if missed fires
            if missed_count > 0:
                catch_up_note = f"\n\n---\nNote: {missed_count} scheduled occurrence(s) were missed while the system was offline."
                notes = (notes + catch_up_note).strip()

            # Use callback if set (for testing), otherwise use persistence
            if self._create_task_callback:
                task = self._create_task_callback(
                    name=name,
                    notes=notes,
                    due_date=params.get("due_date"),
                    priority_id=params.get("priority_id"),
                    entity_id=params.get("entity_id"),
                    tags=params.get("tags", []),
                )
            else:
                task = create_task(
                    name=name,
                    notes=notes,
                    due_date=params.get("due_date"),
                    priority_id=params.get("priority_id"),
                    entity_id=params.get("entity_id"),
                )

            logger.info(f"Created task: {name} (from trigger {trigger.name})")

            # Send SSE event
            self._send_task_created_event(task, trigger)

        except Exception as e:
            logger.error(f"Error creating task: {e}", exc_info=True)

    def _collate_tasks(self, params: dict, trigger):
        """
        Collate tasks into a batch task with subtasks.

        TODO: Implement collation logic when subtask system is ready.
        """
        logger.info(f"Collation action triggered: {params.get('batch_name')}")
        # Placeholder for collation implementation
        pass

    def _get_practice_data(self, practice_id: str) -> dict | None:
        """Load practice data for template expansion."""
        try:
            from praxis_core.persistence.priority_persistence import get_priority
            priority = get_priority(practice_id)
            if priority:
                return {
                    "id": priority.id,
                    "name": priority.name,
                    "priority_type": priority.priority_type,
                }
        except Exception as e:
            logger.error(f"Error loading practice data: {e}")
        return None

    def _send_task_created_event(self, task, trigger):
        """Send SSE event for task creation."""
        if not self._loop or not task:
            return

        try:
            sse_manager = get_sse_manager()
            event = task_created_event(
                task_id=task.id if hasattr(task, 'id') else str(task.get('id', '')),
                priority_id=task.priority_id if hasattr(task, 'priority_id') else task.get('priority_id')
            )

            # Run async broadcast in the thread's event loop
            entity_id = trigger.entity_id or ""
            future = asyncio.run_coroutine_threadsafe(
                sse_manager.broadcast(entity_id, event),
                self._loop
            )
            future.result(timeout=5.0)

        except Exception as e:
            logger.error(f"Error sending task_created event: {e}")

    def _send_trigger_fired_event(self, trigger, actions_taken: list):
        """Send SSE event for trigger execution."""
        if not self._loop:
            return

        try:
            sse_manager = get_sse_manager()
            action_type = actions_taken[0]["type"] if actions_taken else "unknown"
            result_id = actions_taken[0]["params"].get("task_id") if actions_taken else None

            event = trigger_fired_event(
                trigger_id=trigger.id,
                trigger_name=trigger.name,
                action_type=action_type,
                result_id=result_id
            )

            entity_id = trigger.entity_id or ""
            future = asyncio.run_coroutine_threadsafe(
                sse_manager.broadcast(entity_id, event),
                self._loop
            )
            future.result(timeout=5.0)

        except Exception as e:
            logger.error(f"Error sending trigger_fired event: {e}")

    def _check_time_boundaries(self, now: datetime):
        """
        Check if any time boundaries have been crossed for Rules rescore.

        Time boundaries are points where rule conditions change state:
        - Hour boundaries (for time-window rules)
        - Day boundaries (for day-of-week rules)
        """
        if not self._last_check_time:
            return

        last = self._last_check_time

        # Check if we crossed an hour boundary
        if now.hour != last.hour:
            self._send_rescore_event("time_boundary")

        # Check if we crossed a day boundary
        elif now.date() != last.date():
            self._send_rescore_event("day_boundary")

    def _send_rescore_event(self, reason: str):
        """Send SSE rescore event to all connected clients."""
        if not self._loop:
            return

        try:
            sse_manager = get_sse_manager()
            event = rescore_event(reason)

            # Broadcast to all users
            future = asyncio.run_coroutine_threadsafe(
                sse_manager.broadcast_to_all(event),
                self._loop
            )
            future.result(timeout=5.0)

            logger.debug(f"Sent rescore event: {reason}")

        except Exception as e:
            logger.error(f"Error sending rescore event: {e}")


# -----------------------------------------------------------------------------
# Global Scheduler Instance
# -----------------------------------------------------------------------------

_scheduler: TriggerScheduler | None = None


def get_scheduler() -> TriggerScheduler:
    """Get the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = TriggerScheduler()
    return _scheduler


def start_scheduler():
    """Start the global scheduler."""
    scheduler = get_scheduler()
    scheduler.start()


def stop_scheduler():
    """Stop the global scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.stop()
