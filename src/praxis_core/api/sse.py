"""
Server-Sent Events (SSE) manager for real-time updates.

Handles:
- Client subscriptions per user/session
- Event broadcasting (task_created, task_updated, rescore, trigger_fired)
- Connection lifecycle management
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any
from collections import defaultdict


@dataclass
class SSEEvent:
    """An event to be sent to clients."""
    type: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def format(self) -> str:
        """Format as SSE message."""
        payload = {**self.data, "timestamp": self.timestamp}
        return f"event: {self.type}\ndata: {json.dumps(payload)}\n\n"


class SSEManager:
    """
    Manages SSE connections and broadcasts events to subscribers.

    Thread-safe for use with background scheduler thread and web request handlers.

    Also manages the trigger scheduler lifecycle - starts when first client connects,
    stops when last client disconnects.
    """

    def __init__(self):
        # Map of entity_id -> set of asyncio.Queue
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        # Map of queue -> entity_id (for cleanup)
        self._queue_to_entity: dict[asyncio.Queue, str] = {}
        # Lock for thread-safe access
        self._lock = asyncio.Lock()
        # Callback for scheduler lifecycle (set by app startup)
        self._on_first_connect: callable = None
        self._on_last_disconnect: callable = None

    async def subscribe(self, entity_id: str) -> asyncio.Queue:
        """
        Subscribe to events for an entity.

        Returns a queue that will receive SSEEvent objects.
        Starts the scheduler when first client connects.
        """
        queue: asyncio.Queue = asyncio.Queue()
        was_empty = False
        async with self._lock:
            was_empty = self.get_subscriber_count() == 0
            self._subscribers[entity_id].add(queue)
            self._queue_to_entity[queue] = entity_id

        # Start scheduler on first connection
        if was_empty and self._on_first_connect:
            self._on_first_connect()

        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Unsubscribe a queue from events. Stops scheduler when last client disconnects."""
        is_now_empty = False
        async with self._lock:
            entity_id = self._queue_to_entity.pop(queue, None)
            if entity_id and queue in self._subscribers[entity_id]:
                self._subscribers[entity_id].discard(queue)
                # Clean up empty sets
                if not self._subscribers[entity_id]:
                    del self._subscribers[entity_id]
            is_now_empty = self.get_subscriber_count() == 0

        # Stop scheduler when last client disconnects
        if is_now_empty and self._on_last_disconnect:
            self._on_last_disconnect()

    async def broadcast(self, entity_id: str, event: SSEEvent) -> int:
        """
        Broadcast an event to all subscribers for an entity.

        Returns the number of subscribers that received the event.
        """
        count = 0
        async with self._lock:
            subscribers = list(self._subscribers.get(entity_id, []))

        for queue in subscribers:
            try:
                queue.put_nowait(event)
                count += 1
            except asyncio.QueueFull:
                # Skip if queue is full (client not consuming fast enough)
                pass

        return count

    async def broadcast_to_all(self, event: SSEEvent) -> int:
        """Broadcast an event to all subscribers (all entities)."""
        count = 0
        async with self._lock:
            all_queues = [q for queues in self._subscribers.values() for q in queues]

        for queue in all_queues:
            try:
                queue.put_nowait(event)
                count += 1
            except asyncio.QueueFull:
                pass

        return count

    def get_subscriber_count(self, entity_id: str | None = None) -> int:
        """Get the number of active subscribers."""
        if entity_id:
            return len(self._subscribers.get(entity_id, []))
        return sum(len(queues) for queues in self._subscribers.values())

    def set_lifecycle_callbacks(
        self,
        on_first_connect: callable = None,
        on_last_disconnect: callable = None
    ) -> None:
        """Set callbacks for scheduler lifecycle management."""
        self._on_first_connect = on_first_connect
        self._on_last_disconnect = on_last_disconnect


# -----------------------------------------------------------------------------
# Event Factory Functions
# -----------------------------------------------------------------------------

def task_created_event(task_id: str, priority_id: str | None = None) -> SSEEvent:
    """Create a task_created event."""
    return SSEEvent(
        type="task_created",
        data={"task_id": task_id, "priority_id": priority_id}
    )


def task_updated_event(task_id: str) -> SSEEvent:
    """Create a task_updated event."""
    return SSEEvent(
        type="task_updated",
        data={"task_id": task_id}
    )


def task_deleted_event(task_id: str) -> SSEEvent:
    """Create a task_deleted event."""
    return SSEEvent(
        type="task_deleted",
        data={"task_id": task_id}
    )


def rescore_event(reason: str) -> SSEEvent:
    """Create a rescore event (triggers full task list refresh)."""
    return SSEEvent(
        type="rescore",
        data={"reason": reason}
    )


def trigger_fired_event(
    trigger_id: str,
    trigger_name: str,
    action_type: str,
    result_id: str | None = None
) -> SSEEvent:
    """Create a trigger_fired event."""
    return SSEEvent(
        type="trigger_fired",
        data={
            "trigger_id": trigger_id,
            "trigger_name": trigger_name,
            "action_type": action_type,
            "result_id": result_id,
        }
    )


def priority_updated_event(priority_id: str) -> SSEEvent:
    """Create a priority_updated event."""
    return SSEEvent(
        type="priority_updated",
        data={"priority_id": priority_id}
    )


# -----------------------------------------------------------------------------
# Global Instance
# -----------------------------------------------------------------------------

# Singleton instance for the application
_sse_manager: SSEManager | None = None


def get_sse_manager() -> SSEManager:
    """Get the global SSE manager instance."""
    global _sse_manager
    if _sse_manager is None:
        _sse_manager = SSEManager()
    return _sse_manager
