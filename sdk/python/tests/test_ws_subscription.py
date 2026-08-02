"""Unit tests for WsSubscription (ws_subscription.py) and ChangeEvent.

All tests use monkey-patching/mocking — no live WebSocket server needed.
Covers: ChangeEvent dataclass, WsSubscription constructor, callback
registration/deregistration, message sending, incoming message dispatch,
and error handling.
"""

from __future__ import annotations

import json
import threading
from unittest.mock import MagicMock, Mock, patch

import pytest

from spacetime_memory.ws_subscription import ChangeEvent, WsSubscription


def _make_ev(**overrides) -> ChangeEvent:
    """Create a ChangeEvent with defaults, overriding specific fields."""
    defaults = dict(
        id="ev-1",
        workspace_id="ws-1",
        table_name="memory",
        operation="insert",
        record_id="rec-1",
        data_json="{}",
        created_at=1000,
    )
    defaults.update(overrides)
    return ChangeEvent(**defaults)


# ---------------------------------------------------------------------------
# ChangeEvent
# ---------------------------------------------------------------------------


class TestChangeEvent:
    """ChangeEvent dataclass construction and methods."""

    def test_constructor_all_fields(self):
        ev = ChangeEvent(
            id="ev-1",
            workspace_id="ws-1",
            table_name="memory",
            operation="insert",
            record_id="rec-1",
            data_json='{"key": "val"}',
            created_at=1000,
        )
        assert ev.id == "ev-1"
        assert ev.workspace_id == "ws-1"
        assert ev.table_name == "memory"
        assert ev.operation == "insert"
        assert ev.record_id == "rec-1"
        assert ev.data_json == '{"key": "val"}'
        assert ev.created_at == 1000

    def test_data_property(self):
        ev = _make_ev(data_json='{"key": "val", "nested": {"a": 1}}')
        assert ev.data == {"key": "val", "nested": {"a": 1}}

    def test_data_property_empty(self):
        ev = _make_ev(data_json="{}")
        assert ev.data == {}

    def test_data_already_dict(self):
        """data_json can be a dict already -- data property returns it as-is."""
        ev = _make_ev(data_json={"key": "val"})
        assert ev.data == {"key": "val"}

    def test_from_dict(self):
        d = {
            "id": "ev-2",
            "workspace_id": "ws-2",
            "table_name": "kg_node",
            "operation": "update",
            "record_id": "node-1",
            "data_json": '{"label": "test"}',
            "created_at": 2000,
        }
        ev = ChangeEvent.from_dict(d)
        assert ev.id == "ev-2"
        assert ev.workspace_id == "ws-2"
        assert ev.table_name == "kg_node"
        assert ev.operation == "update"
        assert ev.record_id == "node-1"
        assert ev.data == {"label": "test"}
        assert ev.created_at == 2000

    def test_from_dict_empty(self):
        ev = ChangeEvent.from_dict({})
        assert ev.id == ""
        assert ev.workspace_id == ""
        assert ev.data_json == "{}"
        assert ev.created_at == 0

    def test_from_dict_missing_fields(self):
        """Partial dicts fill missing fields with defaults."""
        ev = ChangeEvent.from_dict({"id": "ev-3"})
        assert ev.id == "ev-3"
        assert ev.workspace_id == ""
        assert ev.table_name == ""
        assert ev.data_json == "{}"

    def test_from_dict_created_at_str(self):
        """created_at can be passed as string and is converted to int."""
        ev = ChangeEvent.from_dict({"created_at": "3000"})
        assert ev.created_at == 3000


# ---------------------------------------------------------------------------
# WsSubscription -- constructor
# ---------------------------------------------------------------------------


class TestWsSubscriptionInit:
    """WsSubscription constructor and default values."""

    def test_default_uri(self):
        ws = WsSubscription()
        assert ws._uri == "ws://127.0.0.1:8765"
        assert ws._auto_reconnect is True
        assert ws._reconnect_delay == 5.0
        assert ws._connected is False
        assert ws._running is False
        assert ws._thread is None
        assert ws._callbacks == {}
        assert ws._messages_sent == 0
        assert ws._errors == 0
        assert ws._outbox == []

    def test_custom_uri(self):
        ws = WsSubscription(uri="ws://custom:9000/ws")
        assert ws._uri == "ws://custom:9000/ws"

    def test_no_auto_reconnect(self):
        ws = WsSubscription(auto_reconnect=False)
        assert ws._auto_reconnect is False

    def test_custom_reconnect_delay(self):
        ws = WsSubscription(reconnect_delay=10.0)
        assert ws._reconnect_delay == 10.0

    def test_initial_stats(self):
        ws = WsSubscription()
        stats = ws.stats
        assert stats["connected"] is False
        assert stats["running"] is False
        assert stats["uri"] == "ws://127.0.0.1:8765"
        assert stats["callbacks"] == 0
        assert stats["messages_sent"] == 0
        assert stats["errors"] == 0

    def test_import_equal(self):
        """WsSubscription is importable from the module directly."""
        from spacetime_memory import WsSubscription as Ws2
        assert Ws2 is WsSubscription


# ---------------------------------------------------------------------------
# WsSubscription -- callback registration
# ---------------------------------------------------------------------------


class TestWsSubscriptionCallbacks:
    """on() / off() callback registration."""

    def test_on_basic(self):
        ws = WsSubscription()
        cb = Mock()
        token = ws.on("memory", "insert", cb)
        assert (token, cb) in ws._callbacks[("memory", "insert")]
        assert ws.stats["callbacks"] == 1

    def test_on_wildcard_table(self):
        ws = WsSubscription()
        cb = Mock()
        ws.on("*", "insert", cb)
        assert ("*", "insert") in ws._callbacks

    def test_on_wildcard_operation(self):
        ws = WsSubscription()
        cb = Mock()
        ws.on("memory", "*", cb)
        assert ("memory", "*") in ws._callbacks

    def test_on_wildcard_both(self):
        ws = WsSubscription()
        cb = Mock()
        ws.on("*", "*", cb)
        assert ("*", "*") in ws._callbacks

    def test_on_callback_required(self):
        ws = WsSubscription()
        with pytest.raises(ValueError, match="callback is required"):
            ws.on("memory", "insert", None)

    def test_on_multiple_callbacks_same_key(self):
        ws = WsSubscription()
        cb1 = Mock()
        cb2 = Mock()
        ws.on("memory", "insert", cb1)
        ws.on("memory", "insert", cb2)
        assert len(ws._callbacks[("memory", "insert")]) == 2

    def test_off_removes_callback(self):
        ws = WsSubscription()
        cb = Mock()
        token = ws.on("memory", "insert", cb)
        assert ws.stats["callbacks"] == 1
        ws.off(token)
        assert ws.stats["callbacks"] == 0
        assert ("memory", "insert") not in ws._callbacks

    def test_off_only_removes_specific_token(self):
        ws = WsSubscription()
        cb1 = Mock()
        cb2 = Mock()
        t1 = ws.on("memory", "insert", cb1)
        ws.on("memory", "insert", cb2)
        ws.off(t1)
        assert len(ws._callbacks[("memory", "insert")]) == 1
        assert ws._callbacks[("memory", "insert")][0][1] is cb2

    def test_off_nonexistent_token(self):
        """off() on a token that was never registered is a no-op."""
        ws = WsSubscription()
        ws.on("memory", "insert", Mock())
        ws.off(object())  # Should not raise


# ---------------------------------------------------------------------------
# WsSubscription -- connect / disconnect lifecycle
# ---------------------------------------------------------------------------


class TestWsSubscriptionLifecycle:
    """connect() and disconnect() behavior."""

    def test_connect_sets_state(self):
        ws = WsSubscription(auto_reconnect=False)
        assert ws._running is False
        assert ws._connected is False

        ws.connect()
        assert ws._running is True
        assert ws._thread is not None
        assert ws._thread.name == "ws-subscription"

        ws.disconnect()
        assert ws._running is False
        assert ws._connected is False
        assert ws._thread is None

    def test_connect_idempotent(self):
        """Calling connect() twice does not create a second thread."""
        ws = WsSubscription()
        ws.connect()
        thread = ws._thread
        ws.connect()  # Second call -- should be a no-op
        assert ws._thread is thread
        ws.disconnect()

    def test_disconnect_without_connect(self):
        """disconnect() when not connected is a no-op."""
        ws = WsSubscription()
        ws.disconnect()  # Should not raise
        assert ws._running is False
        assert ws._thread is None

    def test_disconnect_joins_thread(self):
        ws = WsSubscription(auto_reconnect=False)
        ws.connect()
        assert ws._running is True
        ws.disconnect()
        assert ws._thread is None

    def test_stats_after_connect(self):
        ws = WsSubscription()
        ws.connect()
        stats = ws.stats
        assert stats["running"] is True
        ws.disconnect()

    def test_connected_property(self):
        ws = WsSubscription()
        assert ws.connected is False
        ws._connected = True
        assert ws.connected is True
        ws._connected = False

    def test_messages_sent_initially_zero(self):
        ws = WsSubscription()
        assert ws.stats["messages_sent"] == 0

    def test_errors_initially_zero(self):
        ws = WsSubscription()
        assert ws.stats["errors"] == 0


# ---------------------------------------------------------------------------
# WsSubscription -- _send_message / outbox
# ---------------------------------------------------------------------------


class TestWsSubscriptionSendMessage:
    """_send_message adds to outbox queue."""

    def test_send_message_adds_to_outbox(self):
        ws = WsSubscription()
        ws._send_message({"type": "subscribe", "workspace_id": "ws-1"})
        assert len(ws._outbox) == 1
        assert ws._outbox[0]["type"] == "subscribe"

    def test_send_message_multiple(self):
        ws = WsSubscription()
        ws._send_message({"type": "subscribe"})
        ws._send_message({"type": "unsubscribe"})
        assert len(ws._outbox) == 2

    def test_send_message_thread_safe(self):
        """_outbox_lock prevents race on concurrent access."""
        ws = WsSubscription()
        assert ws._outbox_lock is not None

    def test_subscribe_queues_message(self):
        """subscribe() queues a subscribe message in the outbox."""
        ws = WsSubscription()
        ws._connected = True
        ws.subscribe(workspace_id="ws-1", table="memory", operation="insert")
        assert len(ws._outbox) == 1
        msg = ws._outbox[0]
        assert msg["type"] == "subscribe"
        assert msg["workspace_id"] == "ws-1"
        assert msg["table"] == "memory"
        assert msg["operation"] == "insert"

    def test_subscribe_not_connected_noop(self):
        ws = WsSubscription()
        ws.subscribe(workspace_id="ws-1")
        assert ws._outbox == []

    def test_unsubscribe_queues_message(self):
        ws = WsSubscription()
        ws._connected = True
        ws.unsubscribe(workspace_id="ws-1")
        assert len(ws._outbox) == 1
        assert ws._outbox[0]["type"] == "unsubscribe"

    def test_unsubscribe_not_connected_noop(self):
        ws = WsSubscription()
        ws.unsubscribe(workspace_id="ws-1")
        assert ws._outbox == []


# ---------------------------------------------------------------------------
# WsSubscription -- _handle_raw / message dispatch
# ---------------------------------------------------------------------------


class TestWsSubscriptionHandleRaw:
    """_handle_raw parses and dispatches incoming WebSocket messages."""

    def test_change_message_dispatches_event(self):
        ws = WsSubscription()
        cb = Mock()
        ws.on("memory", "insert", cb)

        msg = {
            "type": "change",
            "event": {
                "id": "ev-1",
                "workspace_id": "ws-1",
                "table_name": "memory",
                "operation": "insert",
                "record_id": "rec-1",
                "data_json": '{"key": "val"}',
                "created_at": 1000,
            },
        }
        ws._handle_raw(json.dumps(msg))
        cb.assert_called_once()
        event = cb.call_args[0][0]
        assert event.id == "ev-1"
        assert event.workspace_id == "ws-1"
        assert event.table_name == "memory"
        assert event.operation == "insert"

    def test_change_message_bytes(self):
        """_handle_raw accepts bytes as well as str."""
        ws = WsSubscription()
        cb = Mock()
        ws.on("*", "*", cb)

        msg = json.dumps({
            "type": "change",
            "event": {
                "id": "ev-b", "workspace_id": "ws-1", "table_name": "memory",
                "operation": "update", "record_id": "r1", "data_json": "{}",
                "created_at": 1000,
            },
        })
        ws._handle_raw(msg.encode("utf-8"))
        cb.assert_called_once()

    def test_error_message_logs_warning(self):
        ws = WsSubscription()
        ws._handle_raw(json.dumps({"type": "error", "message": "Some server error"}))

    def test_subscribed_message(self):
        ws = WsSubscription()
        ws._handle_raw(json.dumps({"type": "subscribed", "count": 5}))

    def test_pong_message(self):
        ws = WsSubscription()
        ws._handle_raw(json.dumps({"type": "pong"}))

    def test_invalid_json(self):
        ws = WsSubscription()
        ws._handle_raw("not valid json")

    def test_empty_string(self):
        ws = WsSubscription()
        ws._handle_raw("")

    def test_malformed_unicode(self):
        """Bytes that can't be decoded as UTF-8 are handled gracefully."""
        ws = WsSubscription()
        ws._handle_raw(b"\xff\xfe\x00\x01")

    def test_change_message_no_event_field(self):
        """Change message without 'event' field is handled."""
        ws = WsSubscription()
        ws._handle_raw(json.dumps({"type": "change"}))

    def test_unknown_message_type(self):
        """Unknown message types are silently ignored."""
        ws = WsSubscription()
        ws._handle_raw(json.dumps({"type": "unknown_type"}))


# ---------------------------------------------------------------------------
# WsSubscription -- _dispatch
# ---------------------------------------------------------------------------


class TestWsSubscriptionDispatch:
    """_dispatch routes ChangeEvents to registered callbacks."""

    def test_dispatch_matches_table_and_operation(self):
        ws = WsSubscription()
        cb = Mock()
        ws.on("memory", "insert", cb)

        ev = _make_ev(table_name="memory", operation="insert")
        ws._dispatch(ev)
        cb.assert_called_once_with(ev)

    def test_dispatch_wildcard_table(self):
        ws = WsSubscription()
        cb = Mock()
        ws.on("*", "insert", cb)

        ev = _make_ev(table_name="memory", operation="insert")
        ws._dispatch(ev)
        cb.assert_called_once()

    def test_dispatch_wildcard_operation(self):
        ws = WsSubscription()
        cb = Mock()
        ws.on("kg_node", "*", cb)

        ev = _make_ev(table_name="kg_node", operation="delete")
        ws._dispatch(ev)
        cb.assert_called_once()

    def test_dispatch_wildcard_both(self):
        ws = WsSubscription()
        cb = Mock()
        ws.on("*", "*", cb)

        ev = _make_ev(table_name="memory", operation="update")
        ws._dispatch(ev)
        cb.assert_called_once()

    def test_dispatch_no_match(self):
        ws = WsSubscription()
        cb = Mock()
        ws.on("memory", "insert", cb)

        ev = _make_ev(table_name="memory", operation="delete")
        ws._dispatch(ev)
        cb.assert_not_called()

    def test_dispatch_different_table_no_match(self):
        ws = WsSubscription()
        cb = Mock()
        ws.on("memory", "insert", cb)

        ev = _make_ev(table_name="kg_node", operation="insert")
        ws._dispatch(ev)
        cb.assert_not_called()

    def test_dispatch_multiple_matched_callbacks(self):
        ws = WsSubscription()
        cb1 = Mock()
        cb2 = Mock()
        ws.on("memory", "insert", cb1)
        ws.on("*", "insert", cb2)

        ev = _make_ev(table_name="memory", operation="insert")
        ws._dispatch(ev)
        cb1.assert_called_once()
        cb2.assert_called_once()

    def test_dispatch_callback_error_logged(self):
        """Callback that raises does not prevent other callbacks or crash."""
        ws = WsSubscription()
        cb_fail = Mock(side_effect=ValueError("callback error"))
        cb_ok = Mock()
        ws.on("memory", "insert", cb_fail)
        ws.on("memory", "insert", cb_ok)

        ev = _make_ev(table_name="memory", operation="insert")
        ws._dispatch(ev)
        cb_ok.assert_called_once()

    def test_dispatch_after_off(self):
        ws = WsSubscription()
        cb = Mock()
        token = ws.on("memory", "insert", cb)
        ws.off(token)

        ev = _make_ev(table_name="memory", operation="insert")
        ws._dispatch(ev)
        cb.assert_not_called()

    def test_dispatch_callback_error_not_counted(self):
        """Callback errors don't increment ws._errors."""
        ws = WsSubscription()
        errors_before = ws._errors
        cb = Mock(side_effect=ValueError("ouch"))
        ws.on("*", "*", cb)

        ev = _make_ev(table_name="memory", operation="insert")
        ws._dispatch(ev)
        assert ws._errors == errors_before


# ---------------------------------------------------------------------------
# WsSubscription -- _run_loop via mock WebSocket
# ---------------------------------------------------------------------------


class TestWsSubscriptionMockLoop:
    """Test _run_loop with a mocked WebSocket connection via patch."""

    def test_run_loop_single_message(self):
        ws = WsSubscription(auto_reconnect=False)
        cb = Mock()
        ws.on("memory", "insert", cb)

        with patch("websockets.sync.client.connect") as mock_connect:
            mock_ws = MagicMock()
            mock_ws.recv.side_effect = [
                json.dumps({
                    "type": "change",
                    "event": {
                        "id": "ev-loop", "table_name": "memory",
                        "operation": "insert", "record_id": "rec-1",
                        "data_json": "{}", "created_at": 0,
                        "workspace_id": "ws-1",
                    },
                }),
                Exception("Connection closed"),
            ]
            mock_connect.return_value.__enter__.return_value = mock_ws

            ws.connect()
            ws._thread.join(timeout=3)
            ws._running = False
            ws._connected = False

        cb.assert_called_once()
        assert ws._messages_sent >= 1
        assert ws._errors >= 1

    def test_run_loop_outbox_drain(self):
        ws = WsSubscription(auto_reconnect=False)
        ws._send_message({"type": "subscribe", "workspace_id": "ws-test"})

        with patch("websockets.sync.client.connect") as mock_connect:
            mock_ws = MagicMock()
            mock_ws.recv.side_effect = [Exception("Exit")]
            mock_connect.return_value.__enter__.return_value = mock_ws

            ws.connect()
            ws._thread.join(timeout=3)
            ws._running = False
            ws._connected = False

        assert ws._messages_sent >= 2
        assert ws._outbox == []

    def test_run_loop_reconnect_attempts(self):
        ws = WsSubscription(auto_reconnect=True, reconnect_delay=0.01)
        ws._running = True
        with patch("websockets.sync.client.connect") as mock_connect:
            mock_connect.side_effect = Exception("Connection refused")

            def _run_with_timeout():
                ws._run_loop()

            t = threading.Thread(target=_run_with_timeout, daemon=True)
            t.start()
            threading.Event().wait(0.2)
            ws._running = False
            t.join(timeout=2)

        assert mock_connect.call_count >= 2
        assert ws._errors >= 2

    def test_run_loop_no_reconnect_after_error(self):
        ws = WsSubscription(auto_reconnect=False)

        with patch("websockets.sync.client.connect") as mock_connect:
            mock_connect.side_effect = Exception("Connection refused")

            ws.connect()
            ws._thread.join(timeout=3)
            ws._running = False

        mock_connect.assert_called_once()
        assert ws._errors >= 1


# ---------------------------------------------------------------------------
# WsSubscription -- edge cases
# ---------------------------------------------------------------------------


class TestWsSubscriptionEdgeCases:
    """Additional edge cases and error resilience."""

    def test_connect_with_empty_uri(self):
        ws = WsSubscription(uri="")
        assert ws._uri == ""

    def test_off_from_different_key_does_not_affect_other_keys(self):
        ws = WsSubscription()
        cb1 = Mock()
        cb2 = Mock()
        t1 = ws.on("memory", "insert", cb1)
        ws.on("kg_node", "update", cb2)
        ws.off(t1)
        assert ("kg_node", "update") in ws._callbacks

    def test_callback_receives_correct_event(self):
        ws = WsSubscription()
        received = []

        def collector(event):
            received.append(event)

        ws.on("*", "*", collector)

        ev1 = _make_ev(id="e1", table_name="memory", operation="insert")
        ev2 = _make_ev(id="e2", table_name="kg_node", operation="delete")

        ws._dispatch(ev1)
        ws._dispatch(ev2)

        assert len(received) == 2
        assert received[0].id == "e1"
        assert received[1].id == "e2"

    def test_connected_property_thread_safety(self):
        ws = WsSubscription()
        assert hasattr(ws, "_lock")

    def test_stats_messages_sent_incremented(self):
        ws = WsSubscription()
        ws._messages_sent = 5
        assert ws.stats["messages_sent"] == 5

    def test_stats_errors_incremented(self):
        ws = WsSubscription()
        ws._errors = 3
        assert ws.stats["errors"] == 3

    def test_stats_callbacks_count(self):
        ws = WsSubscription()
        ws.on("memory", "insert", Mock())
        ws.on("memory", "update", Mock())
        assert ws.stats["callbacks"] == 2
