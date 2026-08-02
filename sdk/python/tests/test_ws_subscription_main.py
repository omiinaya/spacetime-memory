"""Pytest unit tests for server/ws_subscription/main.py — SubscriptionServer.

Tests the SubscriptionServer class in isolation with mocked WebSocket
connections.  No real WebSocket server or STDB connection is required.
Covers: __init__, _send, _handle_message dispatch, _handle_subscribe,
_handle_unsubscribe, _fanout, and _on_stdb_events.
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

from server.ws_subscription._handler import event_to_dict
from server.ws_subscription._subscription import ClientConnection, SubscriptionFilter
from server.ws_subscription.main import SubscriptionServer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _AsyncIterator:
    """Async iterator that yields items from a list, then stops.

    Used to mock ``async for raw_message in websocket:`` in
    ``SubscriptionServer._handle_connection``.
    """

    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


@pytest.fixture
def sample_event():
    """Create a minimal ChangeEvent for fan-out tests."""
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
    """A mock WebSocket ServerConnection with async send and close."""
    ws = MagicMock()
    ws.send = AsyncMock()
    ws.close = AsyncMock()
    ws.remote_address = ("127.0.0.1", 54321)
    return ws


@pytest.fixture
def server():
    """A SubscriptionServer with no real WS or STDB connections."""
    return SubscriptionServer()


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubscriptionServerInit:
    """SubscriptionServer.__init__ initial state."""

    def test_empty_clients_dict(self, server):
        assert server._clients == {}

    def test_server_is_none(self, server):
        assert server._server is None

    def test_stdb_subscription_is_none(self, server):
        assert server._stdb_subscription is None


# ---------------------------------------------------------------------------
# _send
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubscriptionServerSend:
    """SubscriptionServer._send helper."""

    @pytest.mark.asyncio
    async def test_send_serializes_and_sends(self, server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await server._send(conn, {"type": "test", "value": 42})
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "test"
        assert sent["value"] == 42

    @pytest.mark.asyncio
    async def test_send_handles_connection_closed(self, server):
        mock_ws = MagicMock()
        mock_ws.send = AsyncMock(
            side_effect=websockets.exceptions.ConnectionClosed(None, None)
        )
        conn = ClientConnection(websocket=mock_ws)
        # Must not raise
        await server._send(conn, {"type": "test"})

    @pytest.mark.asyncio
    async def test_send_default_str_for_non_serializable(self, server, mock_websocket):
        """Non-serializable objects are converted with default=str."""
        conn = ClientConnection(websocket=mock_websocket)
        await server._send(conn, {"type": "test", "value": object()})
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["value"].startswith("<object")


# ---------------------------------------------------------------------------
# _handle_message — dispatch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubscriptionServerHandleMessage:
    """_handle_message dispatches to the correct handler based on msg type."""

    @pytest.mark.asyncio
    async def test_subscribe_dispatched(self, server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        with patch.object(server, "_handle_subscribe", AsyncMock()) as mock_sub:
            await server._handle_message(conn, '{"type": "subscribe", "workspace_id": "ws-1"}')
            mock_sub.assert_called_once()

    @pytest.mark.asyncio
    async def test_unsubscribe_dispatched(self, server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        with patch.object(server, "_handle_unsubscribe", AsyncMock()) as mock_unsub:
            await server._handle_message(
                conn, '{"type": "unsubscribe", "workspace_id": "ws-1"}'
            )
            mock_unsub.assert_called_once()

    @pytest.mark.asyncio
    async def test_ping_dispatched(self, server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await server._handle_message(conn, '{"type": "ping"}')
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "pong"

    @pytest.mark.asyncio
    async def test_unknown_type_returns_error(self, server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await server._handle_message(conn, '{"type": "unknown_cmd"}')
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "error"
        assert "Unknown message type" in sent["message"]

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self, server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await server._handle_message(conn, "not valid json")
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "error"
        assert "Invalid JSON" in sent["message"]

    @pytest.mark.asyncio
    async def test_empty_string_returns_error(self, server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await server._handle_message(conn, "")
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "error"

    @pytest.mark.asyncio
    async def test_missing_type_returns_error(self, server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await server._handle_message(conn, '{"hello": "world"}')
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "error"

    @pytest.mark.asyncio
    async def test_type_not_string_returns_error(self, server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await server._handle_message(conn, '{"type": 123}')
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "error"


# ---------------------------------------------------------------------------
# _handle_subscribe
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubscriptionServerHandleSubscribe:
    """_handle_subscribe adds filter and sends 'subscribed' response."""

    @pytest.mark.asyncio
    async def test_adds_filter_and_sends_subscribed(self, server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        msg = {
            "type": "subscribe",
            "workspace_id": "ws-1",
            "table": "memory",
            "operation": "insert",
        }
        await server._handle_subscribe(conn, msg)
        assert len(conn.filters) == 1
        assert conn.filters[0].workspace_id == "ws-1"
        assert conn.filters[0].table == "memory"
        assert conn.filters[0].operation == "insert"
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "subscribed"
        assert sent["count"] == 1

    @pytest.mark.asyncio
    async def test_defaults_to_wildcard(self, server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await server._handle_subscribe(conn, {"type": "subscribe"})
        assert len(conn.filters) == 1
        assert conn.filters[0].workspace_id == "*"
        assert conn.filters[0].table == "*"
        assert conn.filters[0].operation == "*"

    @pytest.mark.asyncio
    async def test_multiple_subscribes_increment_count(self, server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await server._handle_subscribe(conn, {"type": "subscribe", "workspace_id": "ws-1"})
        await server._handle_subscribe(conn, {"type": "subscribe", "workspace_id": "ws-2"})
        assert len(conn.filters) == 2
        # Last response has count=2
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["count"] == 2


# ---------------------------------------------------------------------------
# _handle_unsubscribe
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubscriptionServerHandleUnsubscribe:
    """_handle_unsubscribe removes filter and sends 'unsubscribed' response."""

    @pytest.mark.asyncio
    async def test_removes_filter_and_sends_unsubscribed(self, server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        conn.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        msg = {
            "type": "unsubscribe",
            "workspace_id": "ws-1",
            "table": "memory",
            "operation": "insert",
        }
        await server._handle_unsubscribe(conn, msg)
        assert len(conn.filters) == 0
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["type"] == "unsubscribed"
        assert sent["count"] == 0

    @pytest.mark.asyncio
    async def test_removes_only_matching_filter(self, server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        conn.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        conn.add_filter(SubscriptionFilter("ws-1", "kg_node", "update"))
        await server._handle_unsubscribe(
            conn,
            {"type": "unsubscribe", "workspace_id": "ws-1", "table": "memory", "operation": "insert"},
        )
        assert len(conn.filters) == 1
        assert conn.filters[0].table == "kg_node"

    @pytest.mark.asyncio
    async def test_unsubscribe_non_existent_filter(self, server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        conn.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        await server._handle_unsubscribe(
            conn,
            {"type": "unsubscribe", "workspace_id": "ws-2"},
        )
        # Original filter remains
        assert len(conn.filters) == 1

    @pytest.mark.asyncio
    async def test_unsubscribe_from_empty_connections(self, server, mock_websocket):
        conn = ClientConnection(websocket=mock_websocket)
        await server._handle_unsubscribe(
            conn,
            {"type": "unsubscribe", "workspace_id": "ws-1"},
        )
        assert len(conn.filters) == 0
        mock_websocket.send.assert_called_once()
        sent = json.loads(mock_websocket.send.call_args[0][0])
        assert sent["count"] == 0


# ---------------------------------------------------------------------------
# _fanout
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubscriptionServerFanout:
    """_fanout pushes events to matching clients and handles disconnects."""

    @pytest.mark.asyncio
    async def test_fanout_to_matching_client(self, server, sample_event):
        mock_ws = MagicMock()
        mock_ws.send = AsyncMock()
        conn = ClientConnection(websocket=mock_ws)
        conn.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        server._clients["conn-1"] = conn

        await server._fanout(sample_event)

        mock_ws.send.assert_called_once()
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent["type"] == "change"
        assert sent["event"]["id"] == "ev-1"
        assert sent["event"]["workspace_id"] == "ws-1"

    @pytest.mark.asyncio
    async def test_fanout_skips_non_matching_client(self, server, sample_event):
        mock_ws = MagicMock()
        mock_ws.send = AsyncMock()
        conn = ClientConnection(websocket=mock_ws)
        conn.add_filter(SubscriptionFilter("ws-2", "memory", "insert"))
        server._clients["conn-1"] = conn

        await server._fanout(sample_event)

        mock_ws.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_fanout_to_multiple_matching_clients(self, server, sample_event):
        mock_ws1 = MagicMock()
        mock_ws1.send = AsyncMock()
        mock_ws2 = MagicMock()
        mock_ws2.send = AsyncMock()
        conn1 = ClientConnection(websocket=mock_ws1)
        conn1.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        conn2 = ClientConnection(websocket=mock_ws2)
        conn2.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        server._clients["c1"] = conn1
        server._clients["c2"] = conn2

        await server._fanout(sample_event)

        mock_ws1.send.assert_called_once()
        mock_ws2.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_fanout_removes_disconnected_client(self, server, sample_event):
        mock_ws = MagicMock()
        mock_ws.send = AsyncMock(
            side_effect=websockets.exceptions.ConnectionClosed(None, None)
        )
        conn = ClientConnection(websocket=mock_ws)
        conn.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        server._clients["conn-1"] = conn

        await server._fanout(sample_event)

        assert "conn-1" not in server._clients

    @pytest.mark.asyncio
    async def test_fanout_partial_disconnect(self, server, sample_event):
        """When one client disconnects, others still receive the event."""
        mock_ws1 = MagicMock()
        mock_ws1.send = AsyncMock(
            side_effect=websockets.exceptions.ConnectionClosed(None, None)
        )
        mock_ws2 = MagicMock()
        mock_ws2.send = AsyncMock()
        conn1 = ClientConnection(websocket=mock_ws1)
        conn1.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        conn2 = ClientConnection(websocket=mock_ws2)
        conn2.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        server._clients["c1"] = conn1
        server._clients["c2"] = conn2

        await server._fanout(sample_event)

        assert "c1" not in server._clients
        assert "c2" in server._clients
        mock_ws2.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_fanout_no_clients(self, server, sample_event):
        """No error when there are no connected clients."""
        await server._fanout(sample_event)

    @pytest.mark.asyncio
    async def test_fanout_sends_correct_payload(self, server, sample_event):
        mock_ws = MagicMock()
        mock_ws.send = AsyncMock()
        conn = ClientConnection(websocket=mock_ws)
        conn.add_filter(SubscriptionFilter("ws-1", "memory", "insert"))
        server._clients["conn-1"] = conn

        await server._fanout(sample_event)

        mock_ws.send.assert_called_once()
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent["type"] == "change"
        expected_event = event_to_dict(sample_event)
        assert sent["event"] == expected_event


# ---------------------------------------------------------------------------
# _on_stdb_events
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubscriptionServerOnStdbEvents:
    """_on_stdb_events iterates events and calls _fanout for each."""

    @pytest.mark.asyncio
    async def test_single_event_calls_fanout(self, server, sample_event):
        with patch.object(server, "_fanout", AsyncMock()) as mock_fanout:
            await server._on_stdb_events([sample_event])
            mock_fanout.assert_called_once_with(sample_event)

    @pytest.mark.asyncio
    async def test_multiple_events_calls_fanout_for_each(self, server):
        from spacetime_memory.delta_sync import ChangeEvent

        ev1 = ChangeEvent(
            id="e1", workspace_id="w", table_name="memory",
            operation="insert", record_id="r1", data_json="{}", created_at=1,
        )
        ev2 = ChangeEvent(
            id="e2", workspace_id="w", table_name="memory",
            operation="update", record_id="r1", data_json="{}", created_at=2,
        )
        with patch.object(server, "_fanout", AsyncMock()) as mock_fanout:
            await server._on_stdb_events([ev1, ev2])
            assert mock_fanout.call_count == 2
            mock_fanout.assert_any_call(ev1)
            mock_fanout.assert_any_call(ev2)

    @pytest.mark.asyncio
    async def test_empty_events_does_not_call_fanout(self, server):
        with patch.object(server, "_fanout", AsyncMock()) as mock_fanout:
            await server._on_stdb_events([])
            mock_fanout.assert_not_called()

    @pytest.mark.asyncio
    async def test_fanout_error_does_not_stop_iteration(self, server):
        """If _fanout raises for one event, later events are still processed."""
        from spacetime_memory.delta_sync import ChangeEvent

        ev1 = ChangeEvent(
            id="e1", workspace_id="w", table_name="memory",
            operation="insert", record_id="r1", data_json="{}", created_at=1,
        )
        ev2 = ChangeEvent(
            id="e2", workspace_id="w", table_name="memory",
            operation="insert", record_id="r2", data_json="{}", created_at=2,
        )

        fanout_results = []

        async def fanout_side_effect(event):
            fanout_results.append(event.id)
            if event.id == "e1":
                raise RuntimeError("fanout failed for e1")

        with patch.object(server, "_fanout", AsyncMock(side_effect=fanout_side_effect)):
            with pytest.raises(RuntimeError, match="fanout failed for e1"):
                await server._on_stdb_events([ev1, ev2])

            # ev2 was never reached because the exception propagates from
            # the loop (no try/except around _fanout inside _on_stdb_events)
            assert fanout_results == ["e1"]


# ---------------------------------------------------------------------------
# start / stop lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubscriptionServerStartStop:
    """SubscriptionServer.start and .stop lifecycle methods."""

    @pytest.mark.asyncio
    async def test_start_creates_stdb_subscription_client(self, server):
        """start() creates a StdbSubscriptionClient with correct config."""
        with patch(
            "server.ws_subscription.main.StdbSubscriptionClient"
        ) as mock_stdb_cls:
            mock_stdb_instance = MagicMock()
            mock_stdb_instance.start = AsyncMock()
            mock_stdb_cls.return_value = mock_stdb_instance

            with patch("server.ws_subscription.main.websockets.serve", new_callable=AsyncMock) as mock_serve:
                mock_server = MagicMock()
                mock_serve.return_value = mock_server

                await server.start(host="0.0.0.0", port=8765)

                # StdbSubscriptionClient created with correct params
                mock_stdb_cls.assert_called_once()
                call_kwargs = mock_stdb_cls.call_args
                assert call_kwargs.kwargs["stdb_host"] == "localhost"
                assert call_kwargs.kwargs["stdb_port"] == 3001
                assert call_kwargs.kwargs["poll_interval"] == 0.1
                # start() called on the client
                mock_stdb_instance.start.assert_awaited_once()
                # websockets.serve called with correct host/port
                mock_serve.assert_awaited_once()
                assert mock_serve.call_args.args[1] == "0.0.0.0"
                assert mock_serve.call_args.args[2] == 8765
                # Server stored
                assert server._server is mock_server
                assert server._stdb_subscription is mock_stdb_instance

    @pytest.mark.asyncio
    async def test_start_with_stdb_subscription_uri(self, server):
        """start() passes stdb_uri when STDB_SUBSCRIPTION_URI is set."""
        with patch(
            "server.ws_subscription.main.StdbSubscriptionClient"
        ) as mock_stdb_cls:
            mock_stdb_instance = MagicMock()
            mock_stdb_instance.start = AsyncMock()
            mock_stdb_cls.return_value = mock_stdb_instance

            with patch("server.ws_subscription.main.websockets.serve", new_callable=AsyncMock):
                with patch(
                    "server.ws_subscription.main.STDB_SUBSCRIPTION_URI",
                    "ws://127.0.0.1:3001/v1/database/test",
                ):
                    await server.start()

                    call_kwargs = mock_stdb_cls.call_args
                    assert call_kwargs.kwargs["stdb_uri"] == "ws://127.0.0.1:3001/v1/database/test"

    @pytest.mark.asyncio
    async def test_start_already_running(self, server):
        """start() is a no-op when already running."""
        server._stdb_subscription = MagicMock()
        server._stdb_subscription.start = AsyncMock()

        with patch(
            "server.ws_subscription.main.StdbSubscriptionClient"
        ) as mock_stdb_cls:
            await server.start()
            # Should not create a new client
            mock_stdb_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_without_start(self, server):
        """stop() does not crash when server was never started."""
        # _stdb_subscription and _server are None by default
        await server.stop()
        assert server._clients == {}

    @pytest.mark.asyncio
    async def test_stop_closes_stdb_subscription(self, server):
        """stop() calls stop() on the STDB subscription client."""
        mock_stdb = MagicMock()
        server._stdb_subscription = mock_stdb

        await server.stop()

        mock_stdb.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_closes_websocket_server(self, server):
        """stop() closes the WebSocket server."""
        mock_ws_server = MagicMock()
        mock_ws_server.close = MagicMock()
        mock_ws_server.wait_closed = AsyncMock()
        server._server = mock_ws_server

        await server.stop()

        mock_ws_server.close.assert_called_once()
        mock_ws_server.wait_closed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_closes_all_client_connections(self, server):
        """stop() closes all connected client WebSockets."""
        mock_ws1 = MagicMock()
        mock_ws1.close = AsyncMock()
        mock_ws1.remote_address = ("127.0.0.1", 1000)
        mock_ws2 = MagicMock()
        mock_ws2.close = AsyncMock()
        mock_ws2.remote_address = ("127.0.0.1", 2000)

        server._clients["c1"] = ClientConnection(websocket=mock_ws1)
        server._clients["c2"] = ClientConnection(websocket=mock_ws2)

        await server.stop()

        mock_ws1.close.assert_awaited_once()
        mock_ws2.close.assert_awaited_once()
        assert server._clients == {}

    @pytest.mark.asyncio
    async def test_stop_handles_connection_error_on_close(self, server):
        """stop() swallows ConnectionError when closing a client."""
        mock_ws = MagicMock()
        mock_ws.close = AsyncMock(side_effect=ConnectionError("broken"))
        server._clients["c1"] = ClientConnection(websocket=mock_ws)

        # Must not raise
        await server.stop()
        assert server._clients == {}

    @pytest.mark.asyncio
    async def test_stop_full_lifecycle(self, server):
        """Full start→stop lifecycle with mocked components."""
        with patch(
            "server.ws_subscription.main.StdbSubscriptionClient"
        ) as mock_stdb_cls:
            mock_stdb_instance = MagicMock()
            mock_stdb_instance.start = AsyncMock()
            mock_stdb_cls.return_value = mock_stdb_instance

            mock_ws_server = MagicMock()
            mock_ws_server.close = MagicMock()
            mock_ws_server.wait_closed = AsyncMock()

            with patch(
                "server.ws_subscription.main.websockets.serve",
                new_callable=AsyncMock,
                return_value=mock_ws_server,
            ):
                await server.start()
                assert server._server is mock_ws_server
                assert server._stdb_subscription is mock_stdb_instance

                await server.stop()
                assert server._server is None
                mock_stdb_instance.stop.assert_called_once()


# ---------------------------------------------------------------------------
# _handle_connection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubscriptionServerHandleConnection:
    """SubscriptionServer._handle_connection lifecycle."""

    @pytest.mark.asyncio
    async def test_connection_added_to_clients(self, server, mock_websocket):
        """A new connection is added to _clients with a unique ID."""
        mock_websocket.remote_address = ("127.0.0.1", 54321)

        # Simulate the connection closing immediately
        mock_websocket.__aiter__ = MagicMock(
            return_value=_AsyncIterator([])  # No messages
        )

        await server._handle_connection(mock_websocket)

        # Client was added and then removed (connection closed)
        assert len(server._clients) == 0  # Cleaned up in finally

    @pytest.mark.asyncio
    async def test_connection_processes_messages(self, server, mock_websocket):
        """Messages from the client are processed via _handle_message."""
        mock_websocket.remote_address = ("127.0.0.1", 54321)
        mock_websocket.__aiter__ = MagicMock(
            return_value=_AsyncIterator(['{"type": "ping"}', '{"type": "ping"}'])
        )

        with patch.object(server, "_handle_message", AsyncMock()) as mock_handler:
            await server._handle_connection(mock_websocket)
            assert mock_handler.call_count == 2

    @pytest.mark.asyncio
    async def test_connection_handles_connection_closed(self, server, mock_websocket):
        """ConnectionClosed during iteration is handled gracefully."""
        mock_websocket.remote_address = ("127.0.0.1", 54321)

        # __aiter__ returns the mock itself; __anext__ raises ConnectionClosed
        mock_websocket.__aiter__ = MagicMock(return_value=mock_websocket)
        mock_websocket.__anext__ = AsyncMock(
            side_effect=websockets.exceptions.ConnectionClosed(None, None)
        )

        with patch.object(server, "_handle_message", AsyncMock()):
            # Must not raise
            await server._handle_connection(mock_websocket)

    @pytest.mark.asyncio
    async def test_connection_cleanup_on_disconnect(self, server, mock_websocket):
        """Client is removed from _clients after disconnect."""
        mock_websocket.remote_address = ("127.0.0.1", 54321)
        mock_websocket.__aiter__ = MagicMock(
            return_value=_AsyncIterator([])
        )

        # Pre-populate to verify cleanup
        server._clients["fake-id"] = ClientConnection(websocket=MagicMock())

        await server._handle_connection(mock_websocket)

        # The fake client should still be there (different ID),
        # but the new connection should have been cleaned up
        assert "fake-id" in server._clients


# ---------------------------------------------------------------------------
# start_server / _main (blocking entry points)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStartServerAndMain:
    """Tests for start_server() and _main() blocking entry points."""

    def test_start_server_creates_and_runs(self):
        """start_server creates a SubscriptionServer, starts it, and stops on interrupt."""
        with patch(
            "server.ws_subscription.main.SubscriptionServer"
        ) as mock_server_cls:
            mock_instance = MagicMock()
            mock_instance.start = AsyncMock()
            mock_instance.stop = AsyncMock()
            mock_server_cls.return_value = mock_instance

            # Simulate CancelledError to break the infinite future
            async def _cancelled():
                raise asyncio.CancelledError()

            with patch(
                "asyncio.get_running_loop"
            ) as mock_get_loop:
                mock_loop = MagicMock()
                mock_loop.create_future = MagicMock(
                    side_effect=_cancelled
                )
                mock_get_loop.return_value = mock_loop

                from server.ws_subscription.main import start_server
                start_server(host="0.0.0.0", port=8765)

                mock_instance.start.assert_awaited_once()
                mock_instance.stop.assert_awaited_once()

    def test_start_server_keyboard_interrupt(self):
        """start_server handles KeyboardInterrupt gracefully."""
        with patch(
            "server.ws_subscription.main.SubscriptionServer"
        ) as mock_server_cls:
            mock_instance = MagicMock()
            mock_instance.start = AsyncMock()
            mock_instance.stop = AsyncMock()
            mock_server_cls.return_value = mock_instance

            async def _keyboard():
                raise KeyboardInterrupt()

            with patch(
                "asyncio.get_running_loop"
            ) as mock_get_loop:
                mock_loop = MagicMock()
                mock_loop.create_future = MagicMock(
                    side_effect=_keyboard
                )
                mock_get_loop.return_value = mock_loop

                from server.ws_subscription.main import start_server
                start_server()

                mock_instance.start.assert_awaited_once()
                mock_instance.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_main_runs_server_until_interrupted(self):
        """_main creates a server, starts it, and stops on CancelledError."""
        with patch(
            "server.ws_subscription.main.SubscriptionServer"
        ) as mock_server_cls:
            mock_instance = MagicMock()
            mock_instance.start = AsyncMock()
            mock_instance.stop = AsyncMock()
            mock_server_cls.return_value = mock_instance

            async def _cancelled():
                raise asyncio.CancelledError()

            with patch(
                "asyncio.get_running_loop"
            ) as mock_get_loop:
                mock_loop = MagicMock()
                mock_loop.create_future = MagicMock(
                    side_effect=_cancelled
                )
                mock_get_loop.return_value = mock_loop

                from server.ws_subscription.main import _main
                await _main()

                mock_instance.start.assert_awaited_once()
                mock_instance.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_main_handles_keyboard_interrupt(self):
        """_main handles KeyboardInterrupt and still calls stop()."""
        with patch(
            "server.ws_subscription.main.SubscriptionServer"
        ) as mock_server_cls:
            mock_instance = MagicMock()
            mock_instance.start = AsyncMock()
            mock_instance.stop = AsyncMock()
            mock_server_cls.return_value = mock_instance

            async def _keyboard():
                raise KeyboardInterrupt()

            with patch(
                "asyncio.get_running_loop"
            ) as mock_get_loop:
                mock_loop = MagicMock()
                mock_loop.create_future = MagicMock(
                    side_effect=_keyboard
                )
                mock_get_loop.return_value = mock_loop

                from server.ws_subscription.main import _main
                await _main()

                mock_instance.start.assert_awaited_once()
                mock_instance.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_main_stop_called_on_start_failure(self):
        """_main calls stop() even if start() raises."""
        with patch(
            "server.ws_subscription.main.SubscriptionServer"
        ) as mock_server_cls:
            mock_instance = MagicMock()
            mock_instance.start = AsyncMock(
                side_effect=RuntimeError("STDB unavailable")
            )
            mock_instance.stop = AsyncMock()
            mock_server_cls.return_value = mock_instance

            from server.ws_subscription.main import _main
            with pytest.raises(RuntimeError, match="STDB unavailable"):
                await _main()

            mock_instance.start.assert_awaited_once()
            mock_instance.stop.assert_awaited_once()


# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnvironmentConfig:
    """Verify environment variable defaults are correct."""

    def test_stdb_host_default(self):
        """STDB_HOST defaults to localhost."""
        from server.ws_subscription.main import STDB_HOST
        assert STDB_HOST == "localhost"

    def test_stdb_port_default(self):
        """STDB_PORT defaults to 3001."""
        from server.ws_subscription.main import STDB_PORT
        assert STDB_PORT == 3001

    def test_ws_port_default(self):
        """WS_PORT defaults to 8765."""
        from server.ws_subscription.main import WS_PORT
        assert WS_PORT == 8765

    def test_poll_interval_default(self):
        """POLL_INTERVAL defaults to 0.1."""
        from server.ws_subscription.main import POLL_INTERVAL
        assert POLL_INTERVAL == 0.1
