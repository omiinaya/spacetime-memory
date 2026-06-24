"""
Unit tests for spacetime_memory.streaming — EventBus and MemoryEvent.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from spacetime_memory.streaming import (
    MemoryEvent,
    EventBus,
    EVENT_MEMORY_CREATED,
    EVENT_MEMORY_UPDATED,
    EVENT_MEMORY_DELETED,
    EVENT_MEMORY_READ,
    EVENT_SEARCH_PERFORMED,
    EVENT_CONSOLE_RAN,
    EVENT_ENTITY_EXTRACTED,
)


class TestMemoryEvent:
    """Tests for the MemoryEvent dataclass."""

    def test_defaults(self):
        e = MemoryEvent("memory.created")
        assert e.event_type == "memory.created"
        assert e.data == {}
        assert isinstance(e.timestamp, float)
        assert e.workspace_id == ""
        assert len(e.event_id) == 12

    def test_full_fields(self):
        e = MemoryEvent(
            "memory.updated",
            data={"id": "abc"},
            timestamp=1234567890.0,
            event_id="deadbeefcafe",
            workspace_id="ws-1",
        )
        assert e.event_type == "memory.updated"
        assert e.data == {"id": "abc"}
        assert e.timestamp == 1234567890.0
        assert e.event_id == "deadbeefcafe"
        assert e.workspace_id == "ws-1"

    def test_to_dict(self):
        e = MemoryEvent(
            "memory.deleted",
            data={"id": "x"},
            timestamp=100.0,
            event_id="abc123def456",
            workspace_id="ws-2",
        )
        d = e.to_dict()
        assert d == {
            "event_type": "memory.deleted",
            "data": {"id": "x"},
            "timestamp": 100.0,
            "event_id": "abc123def456",
            "workspace_id": "ws-2",
        }

    def test_event_id_auto_generated(self):
        e1 = MemoryEvent("memory.read")
        e2 = MemoryEvent("memory.read")
        # Should be unique
        assert e1.event_id != e2.event_id
        assert len(e1.event_id) == 12
        assert len(e2.event_id) == 12

    def test_event_constants(self):
        """Verify all pre-defined constants are as expected."""
        assert EVENT_MEMORY_CREATED == "memory.created"
        assert EVENT_MEMORY_UPDATED == "memory.updated"
        assert EVENT_MEMORY_DELETED == "memory.deleted"
        assert EVENT_MEMORY_READ == "memory.read"
        assert EVENT_SEARCH_PERFORMED == "search.performed"
        assert EVENT_CONSOLE_RAN == "consolidate.ran"
        assert EVENT_ENTITY_EXTRACTED == "entity.extracted"


class TestEventBusInit:
    """Tests for EventBus initialization and properties."""

    def test_initial_state(self):
        bus = EventBus()
        assert bus.subscriber_count == 0
        assert bus.event_count == 0

    def test_custom_max_log_size(self):
        bus = EventBus()
        assert bus._max_log_size == 1000


class TestEventBusSubscribeUnsubscribe:
    """Tests for subscribe/unsubscribe."""

    def test_subscribe(self):
        bus = EventBus()
        cb = lambda e: None
        bus.subscribe("memory.created", cb)
        assert bus.subscriber_count == 1

    def test_subscribe_multiple(self):
        bus = EventBus()
        cb1 = lambda e: None
        cb2 = lambda e: None
        bus.subscribe("memory.created", cb1)
        bus.subscribe("memory.updated", cb2)
        assert bus.subscriber_count == 2

    def test_subscribe_wildcard(self):
        bus = EventBus()
        cb = lambda e: None
        bus.subscribe("*", cb)
        assert bus.subscriber_count == 1

    def test_unsubscribe(self):
        bus = EventBus()
        cb = lambda e: None
        bus.subscribe("memory.created", cb)
        assert bus.subscriber_count == 1
        bus.unsubscribe("memory.created", cb)
        assert bus.subscriber_count == 0

    def test_unsubscribe_not_present(self):
        """Unsubscribing a callback not registered should not error."""
        bus = EventBus()
        cb = lambda e: None
        bus.unsubscribe("memory.created", cb)  # no error
        assert bus.subscriber_count == 0

    def test_unsubscribe_wrong_event_type(self):
        bus = EventBus()
        cb = lambda e: None
        bus.subscribe("memory.created", cb)
        bus.unsubscribe("memory.updated", cb)  # wrong type
        assert bus.subscriber_count == 1  # still there

    def test_subscribe_same_event_multiple_callbacks(self):
        bus = EventBus()
        cb1 = lambda e: None
        cb2 = lambda e: None
        bus.subscribe("memory.created", cb1)
        bus.subscribe("memory.created", cb2)
        assert bus.subscriber_count == 2


class TestEventBusEmit:
    """Tests for emit behavior."""

    def test_emit_to_matching_subscriber(self):
        bus = EventBus()
        received = []
        bus.subscribe("memory.created", lambda e: received.append(e.event_type))
        bus.emit(MemoryEvent("memory.created"))
        assert received == ["memory.created"]

    def test_emit_to_non_matching(self):
        bus = EventBus()
        received = []
        bus.subscribe("memory.updated", lambda e: received.append(e.event_type))
        bus.emit(MemoryEvent("memory.created"))
        assert received == []  # no match

    def test_emit_to_wildcard(self):
        bus = EventBus()
        received = []
        bus.subscribe("*", lambda e: received.append(e.event_type))
        bus.emit(MemoryEvent("memory.created"))
        bus.emit(MemoryEvent("memory.updated"))
        assert received == ["memory.created", "memory.updated"]

    def test_emit_both_matching_and_wildcard(self):
        bus = EventBus()
        types = []
        bus.subscribe("memory.created", lambda e: types.append(("exact", e.event_type)))
        bus.subscribe("*", lambda e: types.append(("wild", e.event_type)))
        bus.emit(MemoryEvent("memory.created"))
        assert len(types) == 2
        assert ("exact", "memory.created") in types
        assert ("wild", "memory.created") in types

    def test_emit_increments_event_count(self):
        bus = EventBus()
        assert bus.event_count == 0
        bus.emit(MemoryEvent("memory.created"))
        assert bus.event_count == 1
        bus.emit(MemoryEvent("memory.updated"))
        assert bus.event_count == 2

    def test_emit_logs_event(self):
        bus = EventBus()
        bus.emit(MemoryEvent("memory.created", data={"id": "1"}))
        log = bus.get_log()
        assert len(log) == 1
        assert log[0]["event_type"] == "memory.created"
        assert log[0]["data"] == {"id": "1"}

    def test_emit_log_trims_at_max(self):
        bus = EventBus()
        bus._max_log_size = 5
        for i in range(10):
            bus.emit(MemoryEvent("memory.created", data={"i": i}))
        log = bus.get_log()
        assert len(log) == 5
        # Should have the last 5
        values = [e["data"]["i"] for e in log]
        assert values == [9, 8, 7, 6, 5]  # reversed order

    def test_emit_handler_exception_does_not_break_others(self):
        bus = EventBus()

        def crashing(e):
            raise RuntimeError("boom")

        ok_received = []
        bus.subscribe("memory.created", crashing)
        bus.subscribe("memory.created", lambda e: ok_received.append("ok"))
        bus.emit(MemoryEvent("memory.created"))
        assert ok_received == ["ok"]

    def test_emit_handler_exception_logged(self, caplog):
        bus = EventBus()

        def crashing(e):
            raise ValueError("test error")

        bus.subscribe("memory.created", crashing)
        with caplog.at_level("WARNING"):
            bus.emit(MemoryEvent("memory.created"))
        assert "Event handler for memory.created failed" in caplog.text


class TestEventBusLog:
    """Tests for event log management."""

    def test_clear_log(self):
        bus = EventBus()
        bus.emit(MemoryEvent("memory.created"))
        assert bus.event_count == 1
        bus.clear_log()
        assert bus.event_count == 0

    def test_get_log_without_filter(self):
        bus = EventBus()
        bus.emit(MemoryEvent("memory.created", data={"id": "a"}))
        bus.emit(MemoryEvent("memory.updated", data={"id": "b"}))
        log = bus.get_log()
        assert len(log) == 2
        # most recent first
        assert log[0]["event_type"] == "memory.updated"
        assert log[1]["event_type"] == "memory.created"

    def test_get_log_with_filter(self):
        bus = EventBus()
        bus.emit(MemoryEvent("memory.created"))
        bus.emit(MemoryEvent("memory.created"))
        bus.emit(MemoryEvent("memory.updated"))
        log = bus.get_log(event_type="memory.created")
        assert len(log) == 2
        assert all(e["event_type"] == "memory.created" for e in log)

    def test_get_log_with_limit(self):
        bus = EventBus()
        for i in range(10):
            bus.emit(MemoryEvent("memory.created", data={"i": i}))
        log = bus.get_log(limit=3)
        assert len(log) == 3

    def test_get_log_empty(self):
        bus = EventBus()
        log = bus.get_log()
        assert log == []


class TestEventBusProperties:
    """Tests for subscriber_count and event_count properties."""

    def test_subscriber_count(self):
        bus = EventBus()
        assert bus.subscriber_count == 0
        bus.subscribe("memory.created", lambda e: None)
        assert bus.subscriber_count == 1
        bus.subscribe("*", lambda e: None)
        assert bus.subscriber_count == 2

    def test_event_count(self):
        bus = EventBus()
        assert bus.event_count == 0
        bus.emit(MemoryEvent("memory.created"))
        assert bus.event_count == 1
        bus.clear_log()
        assert bus.event_count == 0


class TestThreadSafety:
    """Tests for thread-safe operations."""

    def test_emit_thread_safety(self):
        """Verify emit and subscribe work across threads."""
        import threading

        bus = EventBus()
        received = []
        bus.subscribe("*", lambda e: received.append(e.event_type))

        def emit_n(n):
            for _ in range(n):
                bus.emit(MemoryEvent("memory.created"))

        t1 = threading.Thread(target=emit_n, args=(50,))
        t2 = threading.Thread(target=emit_n, args=(50,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(received) == 100  # both threads emitted × wildcard
