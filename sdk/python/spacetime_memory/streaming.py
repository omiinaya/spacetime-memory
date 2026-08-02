"""
Streaming Events — event-driven architecture for memory mutations.

Emits typed events whenever memories are created, updated, deleted,
searched, or consolidated. Consumers subscribe via callbacks.

Usage:
    from spacetime_memory import Client
    from spacetime_memory.streaming import MemoryEvent, EventBus

    bus = EventBus()
    bus.subscribe("memory.created", lambda e: print(f"New memory: {e.data}"))
    client = Client(event_bus=bus)
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MemoryEvent:
    """A typed event in the memory lifecycle."""

    event_type: str  # e.g., "memory.created", "memory.updated", "search.performed"
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    workspace_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
            "workspace_id": self.workspace_id,
        }


# Pre-defined event type constants
EVENT_MEMORY_CREATED = "memory.created"
EVENT_MEMORY_UPDATED = "memory.updated"
EVENT_MEMORY_DELETED = "memory.deleted"
EVENT_MEMORY_READ = "memory.read"
EVENT_SEARCH_PERFORMED = "search.performed"
EVENT_CONSOLE_RAN = "consolidate.ran"
EVENT_ENTITY_EXTRACTED = "entity.extracted"


class EventBus:
    """Thread-safe publish/subscribe event bus for memory events.

    Usage:
        bus = EventBus()
        bus.subscribe("memory.created", my_handler)
        bus.emit(MemoryEvent("memory.created", data={"id": "..."}))
    """

    def __init__(self):
        self._subscribers: dict[str, list[Callable[[MemoryEvent], None]]] = defaultdict(list)
        self._lock = threading.Lock()
        self._event_log: list[dict[str, Any]] = []
        self._max_log_size = 1000

    def subscribe(
        self,
        event_type: str,
        callback: Callable[[MemoryEvent], None],
    ):
        """Subscribe to a specific event type. Use '*' for all events."""
        with self._lock:
            self._subscribers[event_type].append(callback)

    def unsubscribe(
        self,
        event_type: str,
        callback: Callable[[MemoryEvent], None],
    ):
        """Unsubscribe a callback from an event type."""
        with self._lock:
            if event_type in self._subscribers:
                self._subscribers[event_type] = [
                    cb for cb in self._subscribers[event_type] if cb is not callback
                ]

    def emit(self, event: MemoryEvent):
        """Emit an event to all matching subscribers.

        Subscribers to '*' receive ALL events.
        Subscriber exceptions are caught and logged — one failing handler
        won't break others.
        """
        with self._lock:
            # Log event
            self._event_log.append(event.to_dict())
            if len(self._event_log) > self._max_log_size:
                self._event_log = self._event_log[-self._max_log_size :]

            # Collect all callbacks (matching + wildcard)
            callbacks: list[Callable] = list(self._subscribers.get(event.event_type, []))
            callbacks.extend(self._subscribers.get("*", []))

        # Dispatch outside lock
        for cb in callbacks:
            try:
                cb(event)
            except Exception as e:
                logger.warning(
                    "Event handler for %s failed: %s",
                    event.event_type,
                    e,
                )

    def clear_log(self):
        """Clear the event log."""
        with self._lock:
            self._event_log.clear()

    def get_log(
        self,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get recent events from the log, optionally filtered by type.

        Args:
            event_type: Filter by event type, or None for all.
            limit: Max events to return.

        Returns:
            List of event dicts, most recent first.
        """
        with self._lock:
            log = self._event_log
            if event_type:
                log = [e for e in log if e["event_type"] == event_type]
            return list(reversed(log[-limit:]))

    @property
    def subscriber_count(self) -> int:
        """Total number of subscriber callbacks registered."""
        with self._lock:
            return sum(len(v) for v in self._subscribers.values())

    @property
    def event_count(self) -> int:
        """Total number of events in the log."""
        with self._lock:
            return len(self._event_log)
