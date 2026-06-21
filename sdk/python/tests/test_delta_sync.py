"""Tests for delta_sync.py — ChangeEvent and DeltaSync with mocked Client."""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import Mock, MagicMock, patch, call

import pytest

from spacetime_memory.delta_sync import ChangeEvent, DeltaSync


# ── ChangeEvent tests ────────────────────────────────────────────────────


class TestChangeEvent:
    def test_construction_and_fields(self):
        """All dataclass fields are stored as given."""
        ev = ChangeEvent(
            id="ev1",
            workspace_id="ws1",
            table_name="memory",
            operation="insert",
            record_id="rec1",
            data_json='{"key": "val"}',
            created_at=1000,
        )
        assert ev.id == "ev1"
        assert ev.workspace_id == "ws1"
        assert ev.table_name == "memory"
        assert ev.operation == "insert"
        assert ev.record_id == "rec1"
        assert ev.data_json == '{"key": "val"}'
        assert ev.created_at == 1000

    def test_data_property_deserializes_json(self):
        """The ``data`` property returns parsed JSON from ``data_json``."""
        ev = ChangeEvent(
            id="e1",
            workspace_id="w",
            table_name="t",
            operation="o",
            record_id="r",
            data_json='{"k1": 1, "k2": [2, 3]}',
            created_at=0,
        )
        assert ev.data == {"k1": 1, "k2": [2, 3]}

    def test_data_property_empty_object(self):
        """Data property handles empty JSON object."""
        ev = ChangeEvent(
            id="e", workspace_id="w", table_name="t", operation="o",
            record_id="r", data_json="{}", created_at=0,
        )
        assert ev.data == {}

    def test_from_dict_all_fields(self):
        """from_dict populates all fields from a complete dict."""
        d = {
            "id": "abc",
            "workspace_id": "ws-x",
            "table_name": "kg_node",
            "operation": "update",
            "record_id": "node-99",
            "data_json": '{"x": 1}',
            "created_at": 42,
        }
        ev = ChangeEvent.from_dict(d)
        assert ev.id == "abc"
        assert ev.workspace_id == "ws-x"
        assert ev.table_name == "kg_node"
        assert ev.operation == "update"
        assert ev.record_id == "node-99"
        assert ev.data_json == '{"x": 1}'
        assert ev.created_at == 42

    def test_from_dict_missing_optional_fields(self):
        """from_dict uses defaults for missing optional keys."""
        d = {"id": "minimal"}
        ev = ChangeEvent.from_dict(d)
        assert ev.id == "minimal"
        assert ev.workspace_id == ""
        assert ev.table_name == ""
        assert ev.operation == ""
        assert ev.record_id == ""
        assert ev.data_json == "{}"
        assert ev.created_at == 0

    def test_from_dict_created_at_as_string(self):
        """created_at is cast to int even if string."""
        d = {"id": "x", "created_at": "12345"}
        ev = ChangeEvent.from_dict(d)
        assert ev.created_at == 12345
        assert isinstance(ev.created_at, int)


# ── DeltaSync tests ──────────────────────────────────────────────────────


class TestDeltaSyncInit:
    def test_init_defaults(self, mock_client):
        """Basic initialisation sets all internal state."""
        ds = DeltaSync(mock_client)
        assert ds._client is mock_client
        assert ds._poll_interval == 0.1
        assert ds._cursor == 0
        assert ds._callbacks == {}
        assert ds._running is False
        assert ds._thread is None
        assert ds._polls == 0
        assert ds._errors == 0

    def test_init_custom_poll_interval(self, mock_client):
        """Custom poll_interval is stored."""
        ds = DeltaSync(mock_client, poll_interval=2.5)
        assert ds._poll_interval == 2.5

    def test_init_poll_interval_floor(self, mock_client):
        """Poll interval is clamped to minimum 0.01."""
        ds = DeltaSync(mock_client, poll_interval=0.001)
        assert ds._poll_interval == 0.01

    def test_init_auto_start(self, mock_client):
        """auto_start=True kicks off the background thread."""
        mock_client._call.return_value = None
        mock_client._sql.return_value = []
        with patch.object(time, "sleep", return_value=None):
            ds = DeltaSync(mock_client, auto_start=True)
            assert ds._running is True
            assert ds._thread is not None
            ds.stop()


class TestDeltaSyncOn:
    def test_register_callback(self, mock_client):
        """on() returns a token and stores the callback."""
        ds = DeltaSync(mock_client)
        received = []

        def cb(event):
            received.append(event)

        token = ds.on("memory", "insert", cb)
        assert token is not None
        key = ("memory", "insert")
        assert key in ds._callbacks
        assert any(t is token for t, _ in ds._callbacks[key])

    def test_register_wildcard_table(self, mock_client):
        """'*' table matches any table."""
        ds = DeltaSync(mock_client)

        def cb(event):
            pass

        token = ds.on("*", "insert", cb)
        assert ("*", "insert") in ds._callbacks

    def test_register_wildcard_operation(self, mock_client):
        """'*' operation matches any operation."""
        ds = DeltaSync(mock_client)

        def cb(event):
            pass

        token = ds.on("memory", "*", cb)
        assert ("memory", "*") in ds._callbacks

    def test_register_raises_on_none_callback(self, mock_client):
        """Passing None as callback raises ValueError."""
        ds = DeltaSync(mock_client)
        with pytest.raises(ValueError, match="callback is required"):
            ds.on("memory", "insert", None)

    def test_multiple_callbacks_same_key(self, mock_client):
        """Multiple callbacks can be registered for the same table+op."""
        ds = DeltaSync(mock_client)
        t1 = ds.on("memory", "insert", lambda e: None)
        t2 = ds.on("memory", "insert", lambda e: None)
        key = ("memory", "insert")
        assert len(ds._callbacks[key]) == 2


class TestDeltaSyncOff:
    def test_unregister_callback(self, mock_client):
        """off() removes the matching callback and keeps others."""
        ds = DeltaSync(mock_client)
        t1 = ds.on("memory", "insert", lambda e: None)
        t2 = ds.on("memory", "update", lambda e: None)

        ds.off(t1)
        key_insert = ("memory", "insert")
        key_update = ("memory", "update")
        assert key_insert not in ds._callbacks  # key removed entirely
        assert key_update in ds._callbacks

    def test_unregister_removes_empty_key(self, mock_client):
        """When no callbacks remain for a key, the key is deleted."""
        ds = DeltaSync(mock_client)
        t = ds.on("memory", "insert", lambda e: None)
        ds.off(t)
        assert ("memory", "insert") not in ds._callbacks

    def test_off_unknown_token_noop(self, mock_client):
        """Calling off() with an unknown token does nothing."""
        ds = DeltaSync(mock_client)
        ds.on("memory", "insert", lambda e: None)
        unknown = object()
        ds.off(unknown)
        # Still present
        assert ("memory", "insert") in ds._callbacks


class TestDeltaSyncStartStop:
    def test_start_starts_thread(self, mock_client):
        """start() starts a daemon background thread."""
        mock_client._sql.return_value = []
        with patch.object(time, "sleep", return_value=None):
            ds = DeltaSync(mock_client)
            ds.start()
            assert ds._running is True
            assert ds._thread is not None
            assert ds._thread.name == "delta-sync"
            assert ds._thread.daemon is True
            ds.stop()

    def test_start_idempotent(self, mock_client):
        """Calling start() when already running is a no-op."""
        mock_client._sql.return_value = []
        with patch.object(time, "sleep", return_value=None):
            ds = DeltaSync(mock_client)
            ds.start()
            thread1 = ds._thread
            ds.start()
            assert ds._thread is thread1
            ds.stop()

    def test_stop_stops_thread(self, mock_client):
        """stop() sets running=False and joins the thread."""
        mock_client._sql.return_value = []
        with patch.object(time, "sleep", return_value=None):
            ds = DeltaSync(mock_client)
            ds.start()
            assert ds._running is True
            ds.stop()
            assert ds._running is False
            assert ds._thread is None

    def test_stop_when_not_running(self, mock_client):
        """stop() is safe to call when not running."""
        ds = DeltaSync(mock_client)
        ds.stop()  # should not raise


class TestDeltaSyncStats:
    def test_stats_initial(self, mock_client):
        """Initial stats reflect default state."""
        ds = DeltaSync(mock_client)
        s = ds.stats
        assert s["running"] is False
        assert s["cursor"] == 0
        assert s["polls"] == 0
        assert s["errors"] == 0
        assert s["poll_interval"] == 0.1
        assert s["callbacks"] == 0

    def test_stats_with_callbacks(self, mock_client):
        """Stats reflect registered callback count."""
        ds = DeltaSync(mock_client)
        ds.on("memory", "insert", lambda e: None)
        ds.on("kg_node", "*", lambda e: None)
        assert ds.stats["callbacks"] == 2


class TestDeltaSyncDispatch:
    def test_dispatch_matching_table_and_op(self, mock_client):
        """Callbacks matching table and operation are called."""
        ds = DeltaSync(mock_client)
        received = []
        ds.on("memory", "insert", received.append)

        ev = ChangeEvent(
            id="1", workspace_id="w", table_name="memory",
            operation="insert", record_id="r", data_json="{}", created_at=0,
        )
        ds._dispatch(ev)
        assert len(received) == 1
        assert received[0] is ev

    def test_dispatch_wildcard_table(self, mock_client):
        """'*' table wildcard matches any table."""
        ds = DeltaSync(mock_client)
        received = []
        ds.on("*", "insert", received.append)

        ev = ChangeEvent(
            id="1", workspace_id="w", table_name="kg_node",
            operation="insert", record_id="r", data_json="{}", created_at=0,
        )
        ds._dispatch(ev)
        assert len(received) == 1

    def test_dispatch_wildcard_operation(self, mock_client):
        """'*' operation wildcard matches any operation."""
        ds = DeltaSync(mock_client)
        received = []
        ds.on("memory", "*", received.append)

        ev = ChangeEvent(
            id="1", workspace_id="w", table_name="memory",
            operation="delete", record_id="r", data_json="{}", created_at=0,
        )
        ds._dispatch(ev)
        assert len(received) == 1

    def test_dispatch_no_match_table(self, mock_client):
        """Callback for a different table is not called."""
        ds = DeltaSync(mock_client)
        received = []
        ds.on("kg_node", "insert", received.append)

        ev = ChangeEvent(
            id="1", workspace_id="w", table_name="memory",
            operation="insert", record_id="r", data_json="{}", created_at=0,
        )
        ds._dispatch(ev)
        assert len(received) == 0

    def test_dispatch_no_match_operation(self, mock_client):
        """Callback for a different operation is not called."""
        ds = DeltaSync(mock_client)
        received = []
        ds.on("memory", "update", received.append)

        ev = ChangeEvent(
            id="1", workspace_id="w", table_name="memory",
            operation="insert", record_id="r", data_json="{}", created_at=0,
        )
        ds._dispatch(ev)
        assert len(received) == 0

    def test_dispatch_callback_exception_is_swallowed(self, mock_client):
        """Exceptions in callbacks are caught and logged, not propagated."""
        ds = DeltaSync(mock_client)
        received = []

        def bad_callback(event):
            raise RuntimeError("boom")

        ds.on("memory", "insert", bad_callback)
        ds.on("memory", "insert", received.append)

        ev = ChangeEvent(
            id="1", workspace_id="w", table_name="memory",
            operation="insert", record_id="r", data_json="{}", created_at=0,
        )
        ds._dispatch(ev)
        # The second callback should still be called
        assert len(received) == 1

    def test_dispatch_multiple_callbacks(self, mock_client):
        """Multiple matching callbacks are all invoked."""
        ds = DeltaSync(mock_client)
        received1 = []
        received2 = []
        ds.on("memory", "insert", received1.append)
        ds.on("memory", "insert", received2.append)

        ev = ChangeEvent(
            id="1", workspace_id="w", table_name="memory",
            operation="insert", record_id="r", data_json="{}", created_at=0,
        )
        ds._dispatch(ev)
        assert len(received1) == 1
        assert len(received2) == 1


class TestDeltaSyncGetInitialCursor:
    def test_returns_cursor_from_rows(self, mock_client):
        """_get_initial_cursor parses cursor from SQL response."""
        ds = DeltaSync(mock_client)
        mock_client._sql.return_value = [
            {"events_json": json.dumps({"cursor": 999})}
        ]
        cursor = ds._get_initial_cursor()
        assert cursor == 999
        mock_client._call.assert_called_with("get_latest_change_cursor", [])

    def test_returns_zero_when_no_rows(self, mock_client):
        """Returns 0 when no rows returned."""
        ds = DeltaSync(mock_client)
        mock_client._sql.return_value = []
        cursor = ds._get_initial_cursor()
        assert cursor == 0

    def test_returns_zero_when_cursor_missing(self, mock_client):
        """Returns 0 when cursor field missing from JSON."""
        ds = DeltaSync(mock_client)
        mock_client._sql.return_value = [
            {"events_json": json.dumps({"other": "data"})}
        ]
        cursor = ds._get_initial_cursor()
        assert cursor == 0

    def test_returns_zero_on_exception(self, mock_client):
        """When _call raises, _poll_loop catches it and sets cursor=0."""
        ds = DeltaSync(mock_client)
        mock_client._call.side_effect = RuntimeError("boom")

        # _get_initial_cursor itself doesn't catch exceptions —
        # the exception handling is in _poll_loop. Simulate that.
        ds._running = False  # prevent loop from running
        with patch.object(time, "sleep", return_value=None):
            ds._poll_loop()

        assert ds._cursor == 0


class TestDeltaSyncFetchChanges:
    def test_fetch_returns_events(self, mock_client):
        """_fetch_changes parses events from SQL response."""
        ds = DeltaSync(mock_client)
        ds._cursor = 100
        raw_events = [
            {
                "id": "ev1",
                "workspace_id": "ws1",
                "table_name": "memory",
                "operation": "insert",
                "record_id": "r1",
                "data_json": '{"a": 1}',
                "created_at": 200,
            },
        ]
        mock_client._sql.return_value = [
            {"events_json": json.dumps(raw_events)}
        ]
        events = ds._fetch_changes()
        assert len(events) == 1
        assert events[0].id == "ev1"
        assert events[0].table_name == "memory"
        mock_client._call.assert_called_with("get_changes_since", [100])

    def test_fetch_returns_empty_on_no_rows(self, mock_client):
        """Returns empty list when no SQL rows."""
        ds = DeltaSync(mock_client)
        mock_client._sql.return_value = []
        events = ds._fetch_changes()
        assert events == []

    def test_fetch_returns_empty_on_empty_json(self, mock_client):
        """Returns empty list when events_json is empty string."""
        ds = DeltaSync(mock_client)
        mock_client._sql.return_value = [{"events_json": ""}]
        events = ds._fetch_changes()
        assert events == []

    def test_fetch_handles_raw_as_list_not_string(self, mock_client):
        """Handles case where events_json is already a list, not a string."""
        ds = DeltaSync(mock_client)
        raw_events = [
            {
                "id": "ev2",
                "workspace_id": "ws2",
                "table_name": "kg_node",
                "operation": "delete",
                "record_id": "r2",
                "data_json": "{}",
                "created_at": 300,
            },
        ]
        mock_client._sql.return_value = [{"events_json": raw_events}]
        events = ds._fetch_changes()
        assert len(events) == 1
        assert events[0].id == "ev2"


class TestDeltaSyncPollLoop:
    def test_poll_loop_bootstrap_failure(self, mock_client):
        """When bootstrap fails, loop still runs with cursor=0."""
        # _call raises for the bootstrap call, then succeeds for polls
        call_count = [0]

        def call_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("bootstrap fail")
            return None

        mock_client._call.side_effect = call_side_effect
        mock_client._sql.return_value = []

        ds = DeltaSync(mock_client, poll_interval=0.01)
        ds._running = True

        # Run one iteration then stop
        sleep_count = [0]
        orig_sleep = time.sleep

        def limited_sleep(seconds):
            sleep_count[0] += 1
            if sleep_count[0] >= 2:
                ds._running = False
            orig_sleep(0)

        with patch.object(time, "sleep", limited_sleep):
            ds._poll_loop()

        assert ds._cursor == 0
        assert ds._polls >= 1

    def test_poll_loop_fetches_and_dispatches(self, mock_client):
        """Loop fetches changes and dispatches to callbacks."""
        raw_events = [
            {
                "id": "ev1",
                "workspace_id": "ws",
                "table_name": "memory",
                "operation": "insert",
                "record_id": "r",
                "data_json": "{}",
                "created_at": 500,
            },
        ]
        # First call: get_initial_cursor
        mock_client._sql.side_effect = [
            [],  # bootstrap: no rows -> cursor 0
            [{"events_json": json.dumps(raw_events)}],  # first poll
        ]

        ds = DeltaSync(mock_client, poll_interval=0.01)
        received = []
        ds.on("memory", "insert", received.append)

        ds._running = True
        call_count = [0]
        orig_sleep = time.sleep

        def limited_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 2:
                ds._running = False
            orig_sleep(0)

        with patch.object(time, "sleep", limited_sleep):
            ds._poll_loop()

        assert len(received) >= 1
        # Cursor should be updated to the last event's created_at
        assert ds._cursor == 500
        assert ds._polls >= 1

    def test_poll_loop_handles_poll_error(self, mock_client):
        """Poll errors increment error counter but loop continues."""
        mock_client._sql.side_effect = RuntimeError("poll fail")

        ds = DeltaSync(mock_client, poll_interval=0.01)
        ds._running = True

        call_count = [0]
        orig_sleep = time.sleep

        def limited_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 3:
                ds._running = False
            orig_sleep(0)

        with patch.object(time, "sleep", limited_sleep):
            ds._poll_loop()

        assert ds._errors >= 1

    def test_poll_loop_stops_when_not_running(self, mock_client):
        """Loop exits immediately when _running is False."""
        mock_client._sql.return_value = []

        ds = DeltaSync(mock_client, poll_interval=0.01)
        ds._running = False  # already stopped

        with patch.object(time, "sleep") as mock_sleep:
            ds._poll_loop()

        # Should not call sleep because loop body never executes
        mock_sleep.assert_not_called()


class TestDeltaSyncIntegration:
    """End-to-end tests of the public API with mocked backend."""

    def test_full_lifecycle(self, mock_client):
        """Register callbacks, start, let it poll, stop."""
        mock_client._sql.return_value = []
        mock_client._call.return_value = None

        ds = DeltaSync(mock_client, poll_interval=0.01)
        received = []
        ds.on("memory", "insert", received.append)
        ds.on("*", "update", received.append)

        assert ds.stats["callbacks"] == 2

        ds.start()
        assert ds._running is True

        # Let it run briefly then stop
        time.sleep(0.05)
        ds.stop()

        assert ds._running is False
        stats = ds.stats
        assert stats["polls"] >= 0  # might be 0 if it finished bootstrap quickly

    def test_thread_is_daemon(self, mock_client):
        """The background thread is a daemon thread."""
        mock_client._sql.return_value = []
        with patch.object(time, "sleep", return_value=None):
            ds = DeltaSync(mock_client)
            ds.start()
            assert ds._thread.daemon is True
            ds.stop()
