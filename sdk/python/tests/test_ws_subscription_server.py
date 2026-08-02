"""Unit tests for server.ws_subscription.main — WebSocket subscription server.

All tests use mocking — no real WebSocket server or STDB connection needed.
Covers: SubscriptionFilter, ClientConnection, _filters_equal, event_to_dict,
_decode_row, SubscriptionServer lifecycle & message handling, and
StdbSubscriptionClient construction & static helpers.
"""

from __future__ import annotations

import asyncio
import json

# Add repo root to sys.path (same pattern as conftest.py)
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import websockets.exceptions

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from server.ws_subscription._handler import (
    _STDB_CONTENT_TABLES,
    StdbSubscriptionClient,
    _decode_row,
    event_to_dict,
)
from server.ws_subscription._subscription import (
    ClientConnection,
    SubscriptionFilter,
    _filters_equal,
)
from server.ws_subscription.main import (
    SubscriptionServer,
    start_server,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_event():
    """Create a ChangeEvent via the server module's own import path."""
    from spacetime_memory.delta_sync import ChangeEvent

    return ChangeEvent(
        id="ev-1",
        workspace_id="ws-1",
        table_name="memory",
        operation="insert",
        record_id="rec-1",
        data_json='{"key": "val"}',
        created_at=1000,
    )


@pytest.fixture
def mock_websocket():
    """A mock WebSocket ServerConnection with async send."""
    ws = MagicMock()
    ws.send = AsyncMock()
    ws.close = AsyncMock()
    ws.remote_address = ("127.0.0.1", 54321)
    return ws


@pytest.fixture
def subscription_server():
    """A SubscriptionServer with no real WS or STDB connections."""
    return SubscriptionServer()


# ---------------------------------------------------------------------------
# SubscriptionFilter
# ---------------------------------------------------------------------------


class TestSubscriptionFilter:
    """SubscriptionFilter dataclass and matches() method."""

    def test_matches_exact(self, sample_event):
        f = SubscriptionFilter(workspace_id="ws-1", table="memory", operation="insert")
        assert f.matches(sample_event)

    def test_matches_wildcard_workspace(self, sample_event):
        f = SubscriptionFilter(workspace_id="*", table="memory", operation="insert")
        assert f.matches(sample_event)

    def test_matches_wildcard_table(self, sample_event):
        f = SubscriptionFilter(workspace_id="ws-1", table="*", operation="insert")
        assert f.matches(sample_event)

    def test_matches_wildcard_operation(self, sample_event):
        f = SubscriptionFilter(workspace_id="ws-1", table="memory", operation="*")
        assert f.matches(sample_event)

    def test_matches_all_wildcard(self, sample_event):
        f = SubscriptionFilter()
        assert f.matches(sample_event)

    def test_no_match_workspace(self, sample_event):
        f = SubscriptionFilter(workspace_id="ws-2")
        assert not f.matches(sample_event)

    def test_no_match_table(self, sample_event):
        f = SubscriptionFilter(table="kg_node")
        assert not f.matches(sample_event)

    def test_no_match_operation(self, sample_event):
        f = SubscriptionFilter(operation="delete")
        assert not f.matches(sample_event)

    def test_default_constructor_all_wildcard(self):
        f = SubscriptionFilter()
        assert f.workspace_id == "*"
        assert f.table == "*"
        assert f.operation == "*"

    def test_empty_workspace_id_handled(self):
        from spacetime_memory.delta_sync import ChangeEvent

        ev = ChangeEvent(
            id="e", workspace_id="real-ws", table_name="m",
            operation="i", record_id="r", data_json="{}", created_at=1,
        )
        f = SubscriptionFilter(workspace_id="*")
        assert f.matches(ev)

        f2 = SubscriptionFilter(workspace_id="real-ws")
        assert f2.matches(ev)

    def test_custom_filter_fields(self):
        f = SubscriptionFilter(workspace_id="abc", table="note", operation="update")
        assert f.workspace_id == "abc"
        assert f.table == "note"
        assert f.operation == "update"

    def test_matches_workspace_wildcard(self, sample_event):
        """A filter with workspace_id='*' matches any event workspace."""
        f = SubscriptionFilter(workspace_id="*")
        assert f.matches(sample_event)


# ---------------------------------------------------------------------------
# _filters_equal
# ---------------------------------------------------------------------------


class TestFiltersEqual:
    """_filters_equal compares all three fields for equality."""

    def test_equal(self):
        a = SubscriptionFilter("ws-1", "memory", "insert")
        b = SubscriptionFilter("ws-1", "memory", "insert")
        assert _filters_equal(a, b)

    def test_different_workspace(self):
        a = SubscriptionFilter("ws-1", "memory", "insert")
        b = SubscriptionFilter("ws-2", "memory", "insert")
        assert not _filters_equal(a, b)

    def test_different_table(self):
        a = SubscriptionFilter("ws-1", "memory", "insert")
        b = SubscriptionFilter("ws-1", "kg_node", "insert")
        assert not _filters_equal(a, b)

    def test_different_operation(self):
        a = SubscriptionFilter("ws-1", "memory", "insert")
        b = SubscriptionFilter("ws-1", "memory", "delete")
        assert not _filters_equal(a, b)

    def test_all_wildcard_compare(self):
        a = SubscriptionFilter()
        b = SubscriptionFilter()
        assert _filters_equal(a, b)

    def test_wildcard_vs_explicit(self):
        a = SubscriptionFilter("*", "*", "*")
        b = SubscriptionFilter()
        assert _filters_equal(a, b)

    def test_same_filter_different_objects(self):
        assert _filters_equal(
            SubscriptionFilter("a", "b", "c"),
            SubscriptionFilter("a", "b", "c"),
        )


# ---------------------------------------------------------------------------
# ClientConnection
# ---------------------------------------------------------------------------


class TestClientConnection:
    """ClientConnection dataclass and filter management."""

    def test_add_filter(self, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        f = SubscriptionFilter("ws-1", "memory", "insert")
        conn.add_filter(f)
        assert len(conn.filters) == 1
        assert conn.filters[0] is f

    def test_add_multiple_filters(self, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        conn.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        conn.add_filter(SubscriptionFilter("ws-1", "kg_node", "delete"))
        assert len(conn.filters) == 2

    def test_remove_filter_by_value(self, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        f = SubscriptionFilter("ws-1", "memory", "insert")
        conn.add_filter(f)
        conn.remove_filter(f)
        assert len(conn.filters) == 0

    def test_remove_filter_partial_match(self, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        conn.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        conn.add_filter(SubscriptionFilter("ws-1", "kg_node", "insert"))
        conn.remove_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        assert len(conn.filters) == 1
        assert conn.filters[0].table == "kg_node"

    def test_remove_filter_nonexistent(self, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        conn.add_filter(SubscriptionFilter("ws-1"))
        conn.remove_filter(SubscriptionFilter("ws-2"))
        assert len(conn.filters) == 1

    def test_remove_from_empty(self, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        conn.remove_filter(SubscriptionFilter("ws-1"))
        assert len(conn.filters) == 0

    def test_matches_any(self, sample_event, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        conn.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        assert conn.matches_any(sample_event)

    def test_matches_any_no_filters(self, sample_event, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        assert not conn.matches_any(sample_event)

    def test_matches_any_second_filter_wins(self, sample_event, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        conn.add_filter(SubscriptionFilter("ws-1", "kg_node", "insert"))
        conn.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        assert conn.matches_any(sample_event)

    def test_matches_any_no_match(self, sample_event, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        conn.add_filter(SubscriptionFilter("ws-2", "memory", "insert"))
        assert not conn.matches_any(sample_event)

    def test_default_peer_id(self, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        assert conn.peer_id == ""

    def test_custom_peer_id(self, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket, peer_id="peer-1")
        assert conn.peer_id == "peer-1"

    def test_initial_filters_empty(self, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        assert conn.filters == []

    def test_websocket_stored(self, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        assert conn.websocket is mock_websocket

    def test_matches_any_respects_all_filter_fields(self, mock_websocket):
        from spacetime_memory.delta_sync import ChangeEvent

        ev = ChangeEvent(
            id="e", workspace_id="ws-1", table_name="memory",
            operation="insert", record_id="r", data_json="{}", created_at=1,
        )
        conn = ClientConnection(websocket=mock_websocket)
        conn.add_filter(SubscriptionFilter("ws-1", "note", "insert"))
        assert not conn.matches_any(ev)


# ---------------------------------------------------------------------------
# event_to_dict
# ---------------------------------------------------------------------------


class TestEventToDict:
    """event_to_dict converts ChangeEvent to a plain dict."""

    def test_basic_conversion(self, sample_event):
        d = event_to_dict(sample_event)
        assert d["id"] == "ev-1"
        assert d["workspace_id"] == "ws-1"
        assert d["table_name"] == "memory"
        assert d["operation"] == "insert"
        assert d["record_id"] == "rec-1"
        assert d["data_json"] == '{"key": "val"}'
        assert d["created_at"] == 1000

    def test_all_expected_keys(self, sample_event):
        d = event_to_dict(sample_event)
        expected = {"id", "workspace_id", "table_name", "operation",
                    "record_id", "data_json", "created_at"}
        assert set(d.keys()) == expected

    def test_empty_fields(self):
        from spacetime_memory.delta_sync import ChangeEvent

        ev = ChangeEvent(
            id="", workspace_id="", table_name="",
            operation="", record_id="", data_json="{}", created_at=0,
        )
        d = event_to_dict(ev)
        assert d["id"] == ""
        assert d["workspace_id"] == ""
        assert d["created_at"] == 0

    def test_data_json_preserved(self):
        from spacetime_memory.delta_sync import ChangeEvent

        complex_json = '{"nested": {"a": [1, 2, 3]}, "flag": true}'
        ev = ChangeEvent(
            id="e1", workspace_id="w", table_name="m",
            operation="u", record_id="r", data_json=complex_json, created_at=42,
        )
        d = event_to_dict(ev)
        assert d["data_json"] == complex_json


# ---------------------------------------------------------------------------
# _decode_row
# ---------------------------------------------------------------------------


class TestDecodeRow:
    """_decode_row converts STDB row data (str, dict, bytes) to JSON strings."""

    def test_dict_input(self):
        result = _decode_row({"key": "val", "nested": {"a": 1}})
        parsed = json.loads(result)
        assert parsed["key"] == "val"
        assert parsed["nested"]["a"] == 1

    def test_plain_string(self):
        result = _decode_row("hello world")
        assert result == "hello world"

    def test_json_string(self):
        result = _decode_row('{"key": "val"}')
        assert result == '{"key": "val"}'

    def test_base64_encoded_json(self):
        import base64

        original = '{"key": "val"}'
        encoded = base64.b64encode(original.encode()).decode()
        result = _decode_row(encoded)
        assert result == original

    def test_invalid_base64_preserves_string(self):
        result = _decode_row("hello!world")
        assert result == "hello!world"

    def test_bytes_input(self):
        result = _decode_row(b"some bytes")
        assert result == "some bytes"

    def test_bytes_utf8(self):
        result = _decode_row("caf\u00e9".encode("utf-8"))
        assert result == "caf\u00e9"

    def test_empty_string(self):
        result = _decode_row("")
        assert result == ""

    def test_empty_dict(self):
        result = _decode_row({})
        assert result == "{}"

    def test_none_input(self):
        result = _decode_row(None)
        assert result == "None"

    def test_int_input(self):
        result = _decode_row(42)
        assert result == "42"

    def test_float_input(self):
        result = _decode_row(3.14)
        assert result == "3.14"

    def test_list_input(self):
        result = _decode_row([1, 2, 3])
        assert result == "[1, 2, 3]"

    def test_bool_input(self):
        result = _decode_row(True)
        assert result == "True"

    def test_base64_without_validate_flag(self):
        import base64

        original = '{"key": "val"}'
        encoded = base64.b64encode(original.encode()).decode()
        encoded_no_pad = encoded.rstrip("=")
        result = _decode_row(encoded_no_pad)
        assert result == original or result == encoded_no_pad


# ---------------------------------------------------------------------------
# SubscriptionServer lifecycle (mocked)
# ---------------------------------------------------------------------------


class TestSubscriptionServerLifecycle:
    """SubscriptionServer start/stop lifecycle."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_initial_state(self, subscription_server):
        assert subscription_server._clients == {}
        assert subscription_server._server is None
        assert subscription_server._stdb_subscription is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_creates_server(self, subscription_server):
        mock_server = MagicMock()
        mock_server.close = MagicMock()
        mock_server.wait_closed = AsyncMock()
        mock_serve = AsyncMock(return_value=mock_server)
        with patch("server.ws_subscription.main.websockets.serve", mock_serve):
            await subscription_server.start(host="127.0.0.1", port=9999)

            assert subscription_server._server is not None
            assert subscription_server._stdb_subscription is not None
            assert subscription_server._stdb_subscription._running is True
            mock_serve.assert_called_once()

            await subscription_server.stop()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_cleans_up(self, subscription_server):
        mock_server = MagicMock()
        mock_server.close = MagicMock()
        mock_server.wait_closed = AsyncMock()
        mock_serve = AsyncMock(return_value=mock_server)
        with patch("server.ws_subscription.main.websockets.serve", mock_serve):
            await subscription_server.start(host="127.0.0.1", port=9999)

            mock_ws = MagicMock()
            mock_ws.close = AsyncMock()
            conn = ClientConnection(websocket=mock_ws)
            subscription_server._clients["test-conn"] = conn

            await subscription_server.stop()

            assert len(subscription_server._clients) == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_without_start(self, subscription_server):
        await subscription_server.stop()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_closes_all_clients(self, subscription_server):
        subscription_server._clients["c1"] = ClientConnection(
            websocket=MagicMock(close=AsyncMock(side_effect=ConnectionError("gone")))
        )
        subscription_server._clients["c2"] = ClientConnection(
            websocket=MagicMock(close=AsyncMock())
        )

        await subscription_server.stop()
        assert len(subscription_server._clients) == 0


# ---------------------------------------------------------------------------
# SubscriptionServer message handling (mocked)
# ---------------------------------------------------------------------------


class TestSubscriptionServerMessageHandling:
    """SubscriptionServer incoming message routing."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_subscribe(self, subscription_server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        msg = {
            "type": "subscribe",
            "workspace_id": "ws-1",
            "table": "memory",
            "operation": "insert",
        }
        await subscription_server._handle_subscribe(conn, msg)
        assert len(conn.filters) == 1
        assert conn.filters[0].workspace_id == "ws-1"
        assert conn.filters[0].table == "memory"
        assert conn.filters[0].operation == "insert"
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "subscribed"
        assert sent["count"] == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_subscribe_wildcard_defaults(self, subscription_server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await subscription_server._handle_subscribe(conn, {"type": "subscribe"})
        assert len(conn.filters) == 1
        assert conn.filters[0].workspace_id == "*"
        assert conn.filters[0].table == "*"
        assert conn.filters[0].operation == "*"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_unsubscribe(self, subscription_server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        f = SubscriptionFilter("ws-1", "memory", "insert")
        conn.add_filter(f)
        msg = {
            "type": "unsubscribe",
            "workspace_id": "ws-1",
            "table": "memory",
            "operation": "insert",
        }
        await subscription_server._handle_unsubscribe(conn, msg)
        assert len(conn.filters) == 0
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "unsubscribed"
        assert sent["count"] == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_unsubscribe_partial(self, subscription_server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        conn.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        conn.add_filter(SubscriptionFilter("ws-1", "kg_node", "update"))
        # Remove the memory/insert filter with exact match
        await subscription_server._handle_unsubscribe(
            conn, {"type": "unsubscribe", "workspace_id": "ws-1", "table": "memory", "operation": "insert"}
        )
        assert len(conn.filters) == 1
        assert conn.filters[0].table == "kg_node"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_ping(self, subscription_server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await subscription_server._handle_message(conn, '{"type": "ping"}')
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "pong"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_unknown_type(self, subscription_server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await subscription_server._handle_message(conn, '{"type": "unknown"}')
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "error"
        assert "Unknown message type" in sent["message"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_invalid_json(self, subscription_server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await subscription_server._handle_message(conn, "not valid json")
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "error"
        assert "Invalid JSON" in sent["message"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_empty_string(self, subscription_server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await subscription_server._handle_message(conn, "")
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "error"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_message_type_not_string(self, subscription_server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await subscription_server._handle_message(conn, '{"type": 123}')
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "error"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_message_missing_type(self, subscription_server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await subscription_server._handle_message(conn, '{"hello": "world"}')
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "error"


# ---------------------------------------------------------------------------
# SubscriptionServer fan-out logic (mocked)
# ---------------------------------------------------------------------------


class TestSubscriptionServerFanout:
    """SubscriptionServer._fanout delivers events to matching clients."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fanout_to_matching_client(self, sample_event, subscription_server):
        mock_ws = MagicMock()
        mock_ws.send = AsyncMock()
        conn = ClientConnection(websocket=mock_ws)
        conn.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        subscription_server._clients["conn-1"] = conn

        await subscription_server._fanout(sample_event)

        mock_ws.send.assert_called_once()
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent["type"] == "change"
        assert sent["event"]["id"] == "ev-1"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fanout_skips_non_matching(self, sample_event, subscription_server):
        mock_ws = MagicMock()
        mock_ws.send = AsyncMock()
        conn = ClientConnection(websocket=mock_ws)
        conn.add_filter(SubscriptionFilter("ws-2", "memory", "insert"))
        subscription_server._clients["conn-1"] = conn

        await subscription_server._fanout(sample_event)
        mock_ws.send.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fanout_multiple_clients(self, sample_event, subscription_server):
        mock_ws1 = MagicMock()
        mock_ws1.send = AsyncMock()
        mock_ws2 = MagicMock()
        mock_ws2.send = AsyncMock()
        conn1 = ClientConnection(websocket=mock_ws1)
        conn1.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        conn2 = ClientConnection(websocket=mock_ws2)
        conn2.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        subscription_server._clients["c1"] = conn1
        subscription_server._clients["c2"] = conn2

        await subscription_server._fanout(sample_event)
        mock_ws1.send.assert_called_once()
        mock_ws2.send.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fanout_disconnected_client_removed(self, sample_event, subscription_server):
        mock_ws = MagicMock()
        mock_ws.send = AsyncMock(side_effect=websockets.exceptions.ConnectionClosed(None, None))
        conn = ClientConnection(websocket=mock_ws)
        conn.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        subscription_server._clients["conn-1"] = conn

        await subscription_server._fanout(sample_event)
        assert "conn-1" not in subscription_server._clients

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fanout_no_clients(self, sample_event, subscription_server):
        await subscription_server._fanout(sample_event)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fanout_partial_disconnect(self, sample_event, subscription_server):
        mock_ws1 = MagicMock()
        mock_ws1.send = AsyncMock(side_effect=websockets.exceptions.ConnectionClosed(None, None))
        mock_ws2 = MagicMock()
        mock_ws2.send = AsyncMock()
        conn1 = ClientConnection(websocket=mock_ws1)
        conn1.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        conn2 = ClientConnection(websocket=mock_ws2)
        conn2.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        subscription_server._clients["c1"] = conn1
        subscription_server._clients["c2"] = conn2

        await subscription_server._fanout(sample_event)
        assert "c1" not in subscription_server._clients
        assert "c2" in subscription_server._clients
        mock_ws2.send.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_on_stdb_events(self, sample_event, subscription_server):
        with patch.object(subscription_server, "_fanout", AsyncMock()) as mock_fanout:
            await subscription_server._on_stdb_events([sample_event])
            mock_fanout.assert_called_once_with(sample_event)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_on_stdb_events_multiple(self, subscription_server):
        from spacetime_memory.delta_sync import ChangeEvent

        ev1 = ChangeEvent(
            id="e1", workspace_id="w", table_name="m",
            operation="i", record_id="r", data_json="{}", created_at=1,
        )
        ev2 = ChangeEvent(
            id="e2", workspace_id="w", table_name="m",
            operation="i", record_id="r", data_json="{}", created_at=2,
        )
        with patch.object(subscription_server, "_fanout", AsyncMock()) as mock_fanout:
            await subscription_server._on_stdb_events([ev1, ev2])
            assert mock_fanout.call_count == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_on_stdb_events_empty(self, subscription_server):
        with patch.object(subscription_server, "_fanout", AsyncMock()) as mock_fanout:
            await subscription_server._on_stdb_events([])
            mock_fanout.assert_not_called()


# ---------------------------------------------------------------------------
# SubscriptionServer _send helper
# ---------------------------------------------------------------------------


class TestSubscriptionServerSend:
    """SubscriptionServer._send helper."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_json(self, subscription_server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await subscription_server._send(conn, {"type": "test", "value": 42})
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "test"
        assert sent["value"] == 42

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_connection_closed(self, subscription_server):
        mock_ws = MagicMock()
        mock_ws.send = AsyncMock(side_effect=websockets.exceptions.ConnectionClosed(None, None))
        conn = ClientConnection(websocket=mock_ws)
        await subscription_server._send(conn, {"type": "test"})

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_handles_non_serializable(self, subscription_server, mock_websocket):
        from datetime import datetime

        now = datetime(2026, 6, 1, 12, 0, 0)
        conn = ClientConnection(websocket=mock_websocket)
        await subscription_server._send(conn, {"type": "test", "time": now})
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["time"] == "2026-06-01 12:00:00"


# ---------------------------------------------------------------------------
# StdbSubscriptionClient construction
# ---------------------------------------------------------------------------


class TestStdbSubscriptionClientConstruction:
    """StdbSubscriptionClient constructor and mode selection."""

    def test_default_constructor(self):
        client = StdbSubscriptionClient()
        assert client._push_mode is False
        assert client._connected is False
        assert client._running is False
        assert client._task is None
        assert client._stdb_uri is None

    def test_push_mode_with_uri(self):
        client = StdbSubscriptionClient(stdb_uri="ws://127.0.0.1:3001/v1/database/test")
        assert client._push_mode is True
        assert client._stdb_uri == "ws://127.0.0.1:3001/v1/database/test"

    def test_push_mode_empty_uri_disabled(self):
        client = StdbSubscriptionClient(stdb_uri="")
        assert client._push_mode is False

    def test_custom_host_port(self):
        client = StdbSubscriptionClient(stdb_host="10.0.0.1", stdb_port=4242)
        assert client._stdb_host == "10.0.0.1"
        assert client._stdb_port == 4242

    def test_custom_poll_interval(self):
        client = StdbSubscriptionClient(poll_interval=5.0)
        assert client._poll_interval == 5.0

    def test_content_tables_constant(self):
        expected = {"memory", "kg_node", "kg_edge", "note", "profile", "document"}
        assert _STDB_CONTENT_TABLES == expected

    def test_subscribe_queries_includes_all_tables(self):
        client = StdbSubscriptionClient()
        for t in _STDB_CONTENT_TABLES:
            assert f"SELECT * FROM {t}" in client._subscribe_queries

    def test_subscribe_queries_sorted(self):
        client = StdbSubscriptionClient()
        assert client._subscribe_queries == sorted(client._subscribe_queries)

    def test_on_changes_callback(self):
        cb = MagicMock()
        client = StdbSubscriptionClient(on_changes=cb)
        assert client._on_changes is cb

    def test_on_changes_none(self):
        client = StdbSubscriptionClient()
        assert client._on_changes is None


# ---------------------------------------------------------------------------
# StdbSubscriptionClient lifecycle (mocked)
# ---------------------------------------------------------------------------


class TestStdbSubscriptionClientLifecycle:
    """StdbSubscriptionClient start/stop lifecycle."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_poll_mode(self):
        client = StdbSubscriptionClient()
        await client.start()
        assert client._running is True
        assert client._task is not None
        assert client._task.get_name() == "stdb-sub-poll"
        client.stop()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_push_mode(self):
        client = StdbSubscriptionClient(stdb_uri="ws://localhost:3001/ws")
        await client.start()
        assert client._running is True
        assert client._task.get_name() == "stdb-sub-push"
        client.stop()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        client = StdbSubscriptionClient()
        await client.start()
        task = client._task
        await client.start()
        assert client._task is task
        client.stop()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        client = StdbSubscriptionClient()
        await client.start()
        task = client._task
        client.stop()
        # Yield to let cancellation propagate
        await asyncio.sleep(0)
        assert client._running is False
        assert client._task is None
        assert task.cancelled()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        client = StdbSubscriptionClient()
        client.stop()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_resets_state(self):
        client = StdbSubscriptionClient()
        await client.start()
        client._connected = True
        client.stop()
        assert client._connected is False
        assert client._running is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_reset_cursor_on_start(self):
        client = StdbSubscriptionClient()
        client._cursor = 999
        await client.start()
        assert client._cursor == 0
        client.stop()


# ---------------------------------------------------------------------------
# StdbSubscriptionClient static helpers
# ---------------------------------------------------------------------------


class TestStdbSubscriptionClientMerge:
    """StdbSubscriptionClient._merge_update_pairs merges delete+insert pairs."""

    def test_empty_list(self):
        result = StdbSubscriptionClient._merge_update_pairs([])
        assert result == []

    def test_single_event(self):
        from spacetime_memory.delta_sync import ChangeEvent

        ev = ChangeEvent(
            id="e1", workspace_id="w", table_name="m", operation="insert",
            record_id="r", data_json="{}", created_at=1,
        )
        result = StdbSubscriptionClient._merge_update_pairs([ev])
        assert len(result) == 1
        assert result[0].operation == "insert"
        assert result[0].id == "e1"

    def test_merge_delete_insert_same_record(self):
        from spacetime_memory.delta_sync import ChangeEvent

        ev1 = ChangeEvent(
            id="e1", workspace_id="w", table_name="m", operation="delete",
            record_id="r", data_json="{}", created_at=1,
        )
        ev2 = ChangeEvent(
            id="e2", workspace_id="w", table_name="m", operation="insert",
            record_id="r", data_json='{"key": "new"}', created_at=2,
        )
        result = StdbSubscriptionClient._merge_update_pairs([ev1, ev2])
        assert len(result) == 1
        assert result[0].operation == "update"
        assert result[0].id == "e2"
        assert result[0].record_id == "r"
        assert result[0].data_json == '{"key": "new"}'

    def test_no_merge_different_records(self):
        from spacetime_memory.delta_sync import ChangeEvent

        ev1 = ChangeEvent(
            id="e1", workspace_id="w", table_name="m", operation="delete",
            record_id="r1", data_json="{}", created_at=1,
        )
        ev2 = ChangeEvent(
            id="e2", workspace_id="w", table_name="m", operation="insert",
            record_id="r2", data_json="{}", created_at=2,
        )
        result = StdbSubscriptionClient._merge_update_pairs([ev1, ev2])
        assert len(result) == 2
        assert result[0].operation == "delete"
        assert result[1].operation == "insert"

    def test_merge_consecutive_pairs(self):
        from spacetime_memory.delta_sync import ChangeEvent

        ev1 = ChangeEvent(
            id="e1", workspace_id="w", table_name="m", operation="delete",
            record_id="r1", data_json="{}", created_at=1,
        )
        ev2 = ChangeEvent(
            id="e2", workspace_id="w", table_name="m", operation="insert",
            record_id="r1", data_json="{}", created_at=2,
        )
        ev3 = ChangeEvent(
            id="e3", workspace_id="w", table_name="m", operation="delete",
            record_id="r2", data_json="{}", created_at=3,
        )
        ev4 = ChangeEvent(
            id="e4", workspace_id="w", table_name="m", operation="insert",
            record_id="r2", data_json="{}", created_at=4,
        )
        result = StdbSubscriptionClient._merge_update_pairs([ev1, ev2, ev3, ev4])
        assert len(result) == 2
        assert result[0].operation == "update"
        assert result[1].operation == "update"

    def test_no_merge_different_tables(self):
        from spacetime_memory.delta_sync import ChangeEvent

        ev1 = ChangeEvent(
            id="e1", workspace_id="w", table_name="memory", operation="delete",
            record_id="r", data_json="{}", created_at=1,
        )
        ev2 = ChangeEvent(
            id="e2", workspace_id="w", table_name="kg_node", operation="insert",
            record_id="r", data_json="{}", created_at=2,
        )
        result = StdbSubscriptionClient._merge_update_pairs([ev1, ev2])
        assert len(result) == 2

    def test_merge_odd_number_of_events(self):
        from spacetime_memory.delta_sync import ChangeEvent

        ev1 = ChangeEvent(
            id="e1", workspace_id="w", table_name="m", operation="delete",
            record_id="r1", data_json="{}", created_at=1,
        )
        ev2 = ChangeEvent(
            id="e2", workspace_id="w", table_name="m", operation="insert",
            record_id="r1", data_json="{}", created_at=2,
        )
        ev3 = ChangeEvent(
            id="e3", workspace_id="w", table_name="m", operation="delete",
            record_id="r2", data_json="{}", created_at=3,
        )
        result = StdbSubscriptionClient._merge_update_pairs([ev1, ev2, ev3])
        assert len(result) == 2
        assert result[0].operation == "update"
        assert result[1].operation == "delete"

    def test_no_merge_when_delete_not_followed_by_insert(self):
        from spacetime_memory.delta_sync import ChangeEvent

        ev1 = ChangeEvent(
            id="e1", workspace_id="w", table_name="m", operation="insert",
            record_id="r", data_json="{}", created_at=1,
        )
        ev2 = ChangeEvent(
            id="e2", workspace_id="w", table_name="m", operation="delete",
            record_id="r", data_json="{}", created_at=2,
        )
        result = StdbSubscriptionClient._merge_update_pairs([ev1, ev2])
        assert len(result) == 2
        assert result[0].operation == "insert"
        assert result[1].operation == "delete"


class TestStdbSubscriptionClientExtractWorkspaceId:
    """StdbSubscriptionClient._extract_workspace_id parses workspace IDs."""

    def test_extract_from_json(self):
        ws = StdbSubscriptionClient._extract_workspace_id('{"workspace_id": "ws-1"}')
        assert ws == "ws-1"

    def test_extract_nested_data(self):
        ws = StdbSubscriptionClient._extract_workspace_id(
            '{"id": 1, "workspace_id": "ws-42", "content": "hello"}'
        )
        assert ws == "ws-42"

    def test_empty_json(self):
        ws = StdbSubscriptionClient._extract_workspace_id("")
        assert ws == "*"

    def test_no_workspace_id_field(self):
        ws = StdbSubscriptionClient._extract_workspace_id('{"name": "test"}')
        assert ws == "*"

    def test_empty_workspace_id_value(self):
        ws = StdbSubscriptionClient._extract_workspace_id('{"workspace_id": ""}')
        assert ws == "*"

    def test_invalid_json(self):
        ws = StdbSubscriptionClient._extract_workspace_id("not json")
        assert ws == "*"

    def test_null_workspace_id(self):
        ws = StdbSubscriptionClient._extract_workspace_id('{"workspace_id": null}')
        assert ws == "*"

    def test_numeric_workspace_id(self):
        ws = StdbSubscriptionClient._extract_workspace_id('{"workspace_id": 123}')
        assert ws == "123"

    def test_extract_with_extra_whitespace(self):
        ws = StdbSubscriptionClient._extract_workspace_id(
            '  {"workspace_id": "ws-99"}  '
        )
        assert ws == "ws-99"

    def test_empty_object(self):
        ws = StdbSubscriptionClient._extract_workspace_id("{}")
        assert ws == "*"


# ---------------------------------------------------------------------------
# start_server convenience function
# ---------------------------------------------------------------------------


class TestStartServer:
    """start_server() convenience function."""

    def test_start_server_importable(self):
        from server.ws_subscription.main import start_server
        assert callable(start_server)

    def test_subscription_server_import(self):
        from server.ws_subscription.main import SubscriptionServer, start_server
        assert SubscriptionServer is not None
        assert callable(start_server)


# ---------------------------------------------------------------------------
# StdbSubscriptionClient message handling
# ---------------------------------------------------------------------------


class TestStdbSubscriptionClientHandleMessage:
    """StdbSubscriptionClient._handle_message routes raw WS messages."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_invalid_json_returns_early(self):
        cb = AsyncMock()
        client = StdbSubscriptionClient(on_changes=cb)
        await client._handle_message("not valid json")
        cb.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_identity_token_returns_early(self):
        cb = AsyncMock()
        client = StdbSubscriptionClient(on_changes=cb)
        await client._handle_message('{"IdentityToken": {"token": "abc"}}')
        cb.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_subscription_update_returns_early(self):
        cb = AsyncMock()
        client = StdbSubscriptionClient(on_changes=cb)
        await client._handle_message('{"SubscriptionUpdate": {}}')
        cb.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_transaction_update_simple(self):
        """Top-level subscription_update with table_updates."""
        cb = AsyncMock()
        client = StdbSubscriptionClient(on_changes=cb)
        msg = json.dumps({
            "subscription_update": {
                "table_updates": [
                    {
                        "table_name": "memory",
                        "table_row_operations": [
                            {
                                "op": "insert",
                                "row_pk": "rec-1",
                                "row": '{"workspace_id": "ws-1", "content": "hello"}',
                            }
                        ],
                    }
                ]
            }
        })
        await client._handle_message(msg)
        cb.assert_called_once()
        events = cb.call_args[0][0]
        assert len(events) == 1
        assert events[0].operation == "insert"
        assert events[0].table_name == "memory"
        assert events[0].record_id == "rec-1"
        assert events[0].workspace_id == "ws-1"
        assert "hello" in events[0].data_json

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_subscription_update_top_level_ignored(self):
        """SubscriptionUpdate at the top level is silently ignored (initial data)."""
        cb = AsyncMock()
        client = StdbSubscriptionClient(on_changes=cb)
        msg = json.dumps({
            "SubscriptionUpdate": {
                "subscription_update": {
                    "table_updates": [
                        {
                            "table_name": "note",
                            "table_row_operations": [
                                {
                                    "op": "delete",
                                    "row_pk": "rec-2",
                                    "row": '{"workspace_id": "ws-1"}',
                                }
                            ],
                        }
                    ]
                }
            }
        })
        await client._handle_message(msg)
        # SubscriptionUpdate is treated as initial data and discarded
        cb.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ignores_non_content_tables(self):
        """Rows from tables not in _STDB_CONTENT_TABLES are filtered out."""
        cb = AsyncMock()
        client = StdbSubscriptionClient(on_changes=cb)
        msg = json.dumps({
            "subscription_update": {
                "table_updates": [
                    {
                        "table_name": "non_content_table",
                        "table_row_operations": [
                            {"op": "insert", "row_pk": "r1", "row": "{}"}
                        ],
                    }
                ]
            }
        })
        await client._handle_message(msg)
        cb.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mixed_content_and_non_content_tables(self):
        """Content tables produce events; non-content tables are skipped."""
        cb = AsyncMock()
        client = StdbSubscriptionClient(on_changes=cb)
        msg = json.dumps({
            "subscription_update": {
                "table_updates": [
                    {
                        "table_name": "profile",
                        "table_row_operations": [
                            {"op": "insert", "row_pk": "p1", "row": '{"workspace_id": "w1"}'}
                        ],
                    },
                    {
                        "table_name": "unknown_table",
                        "table_row_operations": [
                            {"op": "insert", "row_pk": "x1", "row": "{}"}
                        ],
                    },
                ]
            }
        })
        await client._handle_message(msg)
        cb.assert_called_once()
        events = cb.call_args[0][0]
        assert len(events) == 1
        assert events[0].table_name == "profile"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_empty_table_row_operations(self):
        """No row operations means no events are produced."""
        cb = AsyncMock()
        client = StdbSubscriptionClient(on_changes=cb)
        msg = json.dumps({
            "subscription_update": {
                "table_updates": [
                    {
                        "table_name": "memory",
                        "table_row_operations": [],
                    }
                ]
            }
        })
        await client._handle_message(msg)
        cb.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_default_workspace_id_for_empty_row(self):
        """When the row data is '{}', workspace_id defaults to '*'."""
        cb = AsyncMock()
        client = StdbSubscriptionClient(on_changes=cb)
        msg = json.dumps({
            "subscription_update": {
                "table_updates": [
                    {
                        "table_name": "memory",
                        "table_row_operations": [
                            {"op": "insert", "row_pk": "r1", "row": "{}"}
                        ],
                    }
                ]
            }
        })
        await client._handle_message(msg)
        cb.assert_called_once()
        events = cb.call_args[0][0]
        assert events[0].workspace_id == "*"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_merge_adjacent_delete_insert(self):
        """Adjacent delete+insert on same record is merged into 'update'."""
        cb = AsyncMock()
        client = StdbSubscriptionClient(on_changes=cb)
        msg = json.dumps({
            "subscription_update": {
                "table_updates": [
                    {
                        "table_name": "memory",
                        "table_row_operations": [
                            {
                                "op": "delete",
                                "row_pk": "rec-1",
                                "row": '{"workspace_id": "ws-1"}',
                            },
                            {
                                "op": "insert",
                                "row_pk": "rec-1",
                                "row": '{"workspace_id": "ws-1", "content": "updated"}',
                            },
                        ],
                    }
                ]
            }
        })
        await client._handle_message(msg)
        cb.assert_called_once()
        events = cb.call_args[0][0]
        assert len(events) == 1
        assert events[0].operation == "update"
        assert events[0].record_id == "rec-1"
        assert "updated" in events[0].data_json

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_row_data_as_dict(self):
        """Row may be a dict, not a JSON string -- _decode_row handles it."""
        cb = AsyncMock()
        client = StdbSubscriptionClient(on_changes=cb)
        msg = json.dumps({
            "subscription_update": {
                "table_updates": [
                    {
                        "table_name": "memory",
                        "table_row_operations": [
                            {
                                "op": "insert",
                                "row_pk": "r1",
                                "row": {"workspace_id": "ws-1", "content": "hello"},
                            }
                        ],
                    }
                ]
            }
        })
        await client._handle_message(msg)
        cb.assert_called_once()
        events = cb.call_args[0][0]
        assert events[0].workspace_id == "ws-1"


# ---------------------------------------------------------------------------
# StdbSubscriptionClient._handle_transaction (direct tests)
# ---------------------------------------------------------------------------


class TestStdbSubscriptionClientHandleTransaction:
    """StdbSubscriptionClient._handle_transaction processes tx payloads."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_on_changes_returns_early(self):
        client = StdbSubscriptionClient()
        result = await client._handle_transaction(
            {"table_updates": [{"table_name": "memory", "table_row_operations": []}]}
        )
        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_table_updates_returns_early(self):
        cb = AsyncMock()
        client = StdbSubscriptionClient(on_changes=cb)
        await client._handle_transaction({"subscription_update": {}})
        cb.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_missing_table_updates_key(self):
        """Transaction with no table_updates key at all should be harmless."""
        cb = AsyncMock()
        client = StdbSubscriptionClient(on_changes=cb)
        await client._handle_transaction({"subscription_update": {"no_updates": True}})
        cb.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_multiple_tables(self):
        """Events from multiple content tables are all collected."""
        cb = AsyncMock()
        client = StdbSubscriptionClient(on_changes=cb)
        tx = {
            "table_updates": [
                {
                    "table_name": "memory",
                    "table_row_operations": [
                        {"op": "insert", "row_pk": "r1", "row": "{}"}
                    ],
                },
                {
                    "table_name": "kg_node",
                    "table_row_operations": [
                        {"op": "delete", "row_pk": "r2", "row": "{}"}
                    ],
                },
            ]
        }
        await client._handle_transaction(tx)
        cb.assert_called_once()
        events = cb.call_args[0][0]
        assert len(events) == 2
        assert events[0].table_name == "memory"
        assert events[1].table_name == "kg_node"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_workspace_id_extracted_from_row_data(self):
        """workspace_id should be extracted from the row JSON data."""
        cb = AsyncMock()
        client = StdbSubscriptionClient(on_changes=cb)
        tx = {
            "table_updates": [
                {
                    "table_name": "memory",
                    "table_row_operations": [
                        {
                            "op": "insert",
                            "row_pk": "r1",
                            "row": '{"workspace_id": "my-ws", "content": "test"}',
                        }
                    ],
                }
            ]
        }
        await client._handle_transaction(tx)
        cb.assert_called_once()
        events = cb.call_args[0][0]
        assert events[0].workspace_id == "my-ws"


# ---------------------------------------------------------------------------
# StdbSubscriptionClient._bootstrap_cursor
# ---------------------------------------------------------------------------


class TestStdbSubscriptionClientBootstrapCursor:
    """StdbSubscriptionClient._bootstrap_cursor with mocked HTTP client."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_rows(self):
        client = StdbSubscriptionClient()
        client._http_client = MagicMock()
        client._http_client._call = MagicMock()
        client._http_client._sql = MagicMock(return_value=[])
        cursor = await client._bootstrap_cursor()
        assert cursor == 0
        client._http_client._call.assert_called_once_with(
            "get_latest_change_cursor", []
        )
        client._http_client._sql.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_parses_cursor_from_string_events_json(self):
        client = StdbSubscriptionClient()
        client._http_client = MagicMock()
        client._http_client._call = MagicMock()
        client._http_client._sql = MagicMock(
            return_value=[{"events_json": '{"cursor": 42}'}]
        )
        cursor = await client._bootstrap_cursor()
        assert cursor == 42

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_parses_cursor_from_dict_events_json(self):
        client = StdbSubscriptionClient()
        client._http_client = MagicMock()
        client._http_client._call = MagicMock()
        client._http_client._sql = MagicMock(
            return_value=[{"events_json": {"cursor": 100}}]
        )
        cursor = await client._bootstrap_cursor()
        assert cursor == 100

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_zero_on_missing_cursor_key(self):
        client = StdbSubscriptionClient()
        client._http_client = MagicMock()
        client._http_client._call = MagicMock()
        client._http_client._sql = MagicMock(
            return_value=[{"events_json": '{"no_cursor": 0}'}]
        )
        cursor = await client._bootstrap_cursor()
        assert cursor == 0


# ---------------------------------------------------------------------------
# StdbSubscriptionClient._fetch_changes
# ---------------------------------------------------------------------------


class TestStdbSubscriptionClientFetchChanges:
    """StdbSubscriptionClient._fetch_changes with mocked HTTP client."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_rows(self):
        client = StdbSubscriptionClient()
        client._cursor = 0
        client._http_client = MagicMock()
        client._http_client._call = MagicMock()
        client._http_client._sql_param = MagicMock(return_value=[])
        events = await client._fetch_changes()
        assert events == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_events_json_empty(self):
        client = StdbSubscriptionClient()
        client._cursor = 0
        client._http_client = MagicMock()
        client._http_client._call = MagicMock()
        client._http_client._sql_param = MagicMock(
            return_value=[{"events_json": ""}]
        )
        events = await client._fetch_changes()
        assert events == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_events_json_missing(self):
        client = StdbSubscriptionClient()
        client._cursor = 0
        client._http_client = MagicMock()
        client._http_client._call = MagicMock()
        client._http_client._sql_param = MagicMock(
            return_value=[{"no_events": True}]
        )
        events = await client._fetch_changes()
        assert events == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_parses_events_from_string_json(self):
        client = StdbSubscriptionClient()
        client._cursor = 0
        client._http_client = MagicMock()
        client._http_client._call = MagicMock()
        event_dict = {
            "id": "ev-1",
            "workspace_id": "ws-1",
            "table_name": "memory",
            "operation": "insert",
            "record_id": "rec-1",
            "data_json": "{}",
            "created_at": 100,
        }
        client._http_client._sql_param = MagicMock(
            return_value=[{"events_json": json.dumps([event_dict])}]
        )
        events = await client._fetch_changes()
        assert len(events) == 1
        assert events[0].id == "ev-1"
        assert events[0].table_name == "memory"
        assert events[0].operation == "insert"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_parses_events_from_dict_json(self):
        """When events_json is already a dict (not a string)."""
        client = StdbSubscriptionClient()
        client._cursor = 0
        client._http_client = MagicMock()
        client._http_client._call = MagicMock()
        event_dict = {
            "id": "ev-2",
            "workspace_id": "ws-2",
            "table_name": "note",
            "operation": "delete",
            "record_id": "rec-2",
            "data_json": "{}",
            "created_at": 200,
        }
        client._http_client._sql_param = MagicMock(
            return_value=[{"events_json": [event_dict]}]
        )
        events = await client._fetch_changes()
        assert len(events) == 1
        assert events[0].id == "ev-2"
        assert events[0].table_name == "note"
        assert events[0].operation == "delete"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_passes_current_cursor(self):
        client = StdbSubscriptionClient()
        client._cursor = 42
        client._http_client = MagicMock()
        client._http_client._call = MagicMock()
        client._http_client._sql_param = MagicMock(return_value=[])
        await client._fetch_changes()
        client._http_client._call.assert_called_once_with(
            "get_changes_since", [42]
        )
        # Verify the SQL uses the cursor parameter
        call_kwargs = client._http_client._sql_param.call_args
        assert 42 in call_kwargs[0] or call_kwargs[0][1] == 42


# ---------------------------------------------------------------------------
# start_server convenience function -- behaviour
# ---------------------------------------------------------------------------


class TestStartServerBehavior:
    """start_server() creates a SubscriptionServer and manages lifecycle."""

    # Shared helper: a fake asyncio.run that patches create_future to
    # return a cancelled future, so the "await create_future()" in
    # start_server._run() resolves immediately.
    @staticmethod
    def _make_fake_asyncio_run():
        def fake_asyncio_run(coro, *args, **kwargs):
            loop = None
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                orig_create = loop.create_future

                def _cancelled_future():
                    f = orig_create()
                    f.cancel()
                    return f

                loop.create_future = _cancelled_future
                loop.run_until_complete(coro)
            finally:
                if loop is not None:
                    loop.close()
                    asyncio.set_event_loop(None)

        return fake_asyncio_run

    @pytest.mark.unit
    def test_creates_server_and_starts(self):
        """Verify start_server creates a SubscriptionServer and calls start/stop."""
        mock_server = MagicMock(spec=SubscriptionServer)
        mock_server.start = AsyncMock()
        mock_server.stop = AsyncMock()

        with patch(
            "server.ws_subscription.main.SubscriptionServer",
            return_value=mock_server,
        ) as mock_cls, patch(
            "server.ws_subscription.main.asyncio.run",
            self._make_fake_asyncio_run(),
        ):
            start_server()

        mock_cls.assert_called_once()
        mock_server.start.assert_awaited_once()
        mock_server.stop.assert_awaited_once()

    @pytest.mark.unit
    def test_creates_server_with_custom_host_port(self):
        """start_server accepts host/port but does NOT forward them to
        SubscriptionServer.start() (a current code behavior quirk)."""
        mock_server = MagicMock(spec=SubscriptionServer)
        mock_server.start = AsyncMock()
        mock_server.stop = AsyncMock()

        with patch(
            "server.ws_subscription.main.SubscriptionServer",
            return_value=mock_server,
        ) as mock_cls, patch(
            "server.ws_subscription.main.asyncio.run",
            self._make_fake_asyncio_run(),
        ):
            start_server(host="0.0.0.0", port=8765)

        mock_cls.assert_called_once()
        # start() is called without arguments (the defaults from WS_HOST/WS_PORT)
        mock_server.start.assert_awaited_once_with()

    @pytest.mark.unit
    def test_default_call(self):
        """start_server() uses default WS_HOST and WS_PORT when called bare."""
        mock_server = MagicMock(spec=SubscriptionServer)
        mock_server.start = AsyncMock()
        mock_server.stop = AsyncMock()

        with patch(
            "server.ws_subscription.main.SubscriptionServer",
            return_value=mock_server,
        ) as mock_cls, patch(
            "server.ws_subscription.main.asyncio.run",
            self._make_fake_asyncio_run(),
        ):
            start_server()

        mock_cls.assert_called_once()
        mock_server.start.assert_awaited_once()

    @pytest.mark.unit
    def test_start_server_signature(self):
        """Check that start_server accepts the expected parameters."""
        import inspect

        sig = inspect.signature(start_server)
        assert "host" in sig.parameters
        assert "port" in sig.parameters
        # Default values should be present
        assert sig.parameters["host"].default is not inspect.Parameter.empty
        assert sig.parameters["port"].default is not inspect.Parameter.empty
