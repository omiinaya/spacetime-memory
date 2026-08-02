"""Unit tests for STDB subscription server components.

Tests the StdbSubscriptionClient, _merge_update_pairs, _decode_row,
event_to_dict, webhook delivery, and SubscriptionManager.
All tests use monkey-patching/mocking — no live STDB or WebSocket server needed.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, Mock

# ---------------------------------------------------------------------------
# _decode_row
# ---------------------------------------------------------------------------


class TestDecodeRow:
    """_decode_row converts STDB row data to JSON strings."""

    def test_base64_encoded(self):
        from server.ws_subscription._handler import _decode_row

        data = {"key": "value"}
        encoded = base64.b64encode(json.dumps(data).encode()).decode()
        result = _decode_row(encoded)
        assert json.loads(result) == data

    def test_dict_input(self):
        from server.ws_subscription._handler import _decode_row

        result = _decode_row({"key": "value"})
        assert json.loads(result) == {"key": "value"}

    def test_plain_string(self):
        from server.ws_subscription._handler import _decode_row

        result = _decode_row("plain text")
        assert result == "plain text"

    def test_empty_string(self):
        from server.ws_subscription._handler import _decode_row

        assert _decode_row("") == ""

    def test_invalid_base64(self):
        from server.ws_subscription._handler import _decode_row

        # Not valid base64 but handled gracefully
        result = _decode_row("!!!")
        assert result == "!!!"


# ---------------------------------------------------------------------------
# event_to_dict
# ---------------------------------------------------------------------------


class TestEventToDict:
    """event_to_dict converts ChangeEvent to plain dict."""

    def test_basic_conversion(self):
        from server.ws_subscription.main import event_to_dict

        from spacetime_memory.delta_sync import ChangeEvent

        ev = ChangeEvent(
            id="ev-1",
            workspace_id="ws-1",
            table_name="memory",
            operation="insert",
            record_id="rec-1",
            data_json='{"key": "val"}',
            created_at=1000,
        )
        d = event_to_dict(ev)
        assert d["id"] == "ev-1"
        assert d["workspace_id"] == "ws-1"
        assert d["table_name"] == "memory"
        assert d["operation"] == "insert"
        assert d["record_id"] == "rec-1"
        assert d["data_json"] == '{"key": "val"}'
        assert d["created_at"] == 1000


# ---------------------------------------------------------------------------
# _merge_update_pairs
# ---------------------------------------------------------------------------


class TestMergeUpdatePairs:
    """_merge_update_pairs groups delete+insert pairs into updates."""

    def test_plain_insert(self):
        from server.ws_subscription.main import StdbSubscriptionClient

        from spacetime_memory.delta_sync import ChangeEvent

        events = [
            ChangeEvent(id="1", workspace_id="ws-1", table_name="memory",
                        operation="insert", record_id="rec-1",
                        data_json='{"val": 1}', created_at=100),
        ]
        result = StdbSubscriptionClient._merge_update_pairs(events)
        assert len(result) == 1
        assert result[0].operation == "insert"

    def test_plain_delete(self):
        from server.ws_subscription.main import StdbSubscriptionClient

        from spacetime_memory.delta_sync import ChangeEvent

        events = [
            ChangeEvent(id="1", workspace_id="ws-1", table_name="memory",
                        operation="delete", record_id="rec-1",
                        data_json="{}", created_at=100),
        ]
        result = StdbSubscriptionClient._merge_update_pairs(events)
        assert len(result) == 1
        assert result[0].operation == "delete"

    def test_delete_insert_merged_to_update(self):
        from server.ws_subscription.main import StdbSubscriptionClient

        from spacetime_memory.delta_sync import ChangeEvent

        events = [
            ChangeEvent(id="1", workspace_id="ws-1", table_name="memory",
                        operation="delete", record_id="rec-1",
                        data_json='{"old": 1}', created_at=100),
            ChangeEvent(id="2", workspace_id="ws-1", table_name="memory",
                        operation="insert", record_id="rec-1",
                        data_json='{"val": 2}', created_at=101),
        ]
        result = StdbSubscriptionClient._merge_update_pairs(events)
        assert len(result) == 1
        assert result[0].operation == "update"
        assert result[0].record_id == "rec-1"
        assert json.loads(result[0].data_json) == {"val": 2}

    def test_multiple_tables_no_merge_cross_table(self):
        from server.ws_subscription.main import StdbSubscriptionClient

        from spacetime_memory.delta_sync import ChangeEvent

        events = [
            ChangeEvent(id="1", workspace_id="ws-1", table_name="memory",
                        operation="delete", record_id="rec-1",
                        data_json="{}", created_at=100),
            ChangeEvent(id="2", workspace_id="ws-1", table_name="kg_node",
                        operation="insert", record_id="rec-1",
                        data_json='{"label": "test"}', created_at=101),
        ]
        result = StdbSubscriptionClient._merge_update_pairs(events)
        assert len(result) == 2

    def test_multiple_updates(self):
        from server.ws_subscription.main import StdbSubscriptionClient

        from spacetime_memory.delta_sync import ChangeEvent

        events = [
            ChangeEvent(id="1", workspace_id="ws-1", table_name="memory",
                        operation="delete", record_id="rec-1",
                        data_json="{}", created_at=100),
            ChangeEvent(id="2", workspace_id="ws-1", table_name="memory",
                        operation="insert", record_id="rec-1",
                        data_json='{"val": 2}', created_at=101),
            ChangeEvent(id="3", workspace_id="ws-1", table_name="kg_node",
                        operation="delete", record_id="node-1",
                        data_json="{}", created_at=102),
            ChangeEvent(id="4", workspace_id="ws-1", table_name="kg_node",
                        operation="insert", record_id="node-1",
                        data_json='{"label": "new"}', created_at=103),
        ]
        result = StdbSubscriptionClient._merge_update_pairs(events)
        assert len(result) == 2
        assert result[0].operation == "update"
        assert result[1].operation == "update"

    def test_empty_list(self):
        from server.ws_subscription.main import StdbSubscriptionClient

        assert StdbSubscriptionClient._merge_update_pairs([]) == []


# ---------------------------------------------------------------------------
# StdbSubscriptionClient
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# _extract_workspace_id
# ---------------------------------------------------------------------------


class TestExtractWorkspaceId:
    """_extract_workspace_id extracts workspace_id from row JSON data."""

    def test_with_valid_workspace_id(self):
        from server.ws_subscription.main import StdbSubscriptionClient

        result = StdbSubscriptionClient._extract_workspace_id(
            '{"workspace_id": "ws-123", "key": "val"}'
        )
        assert result == "ws-123"

    def test_without_workspace_id(self):
        from server.ws_subscription.main import StdbSubscriptionClient

        result = StdbSubscriptionClient._extract_workspace_id(
            '{"key": "val", "other": "data"}'
        )
        assert result == "*"

    def test_empty_object(self):
        from server.ws_subscription.main import StdbSubscriptionClient

        assert StdbSubscriptionClient._extract_workspace_id("{}") == "*"

    def test_empty_string(self):
        from server.ws_subscription.main import StdbSubscriptionClient

        assert StdbSubscriptionClient._extract_workspace_id("") == "*"

    def test_empty_workspace_id(self):
        from server.ws_subscription.main import StdbSubscriptionClient

        result = StdbSubscriptionClient._extract_workspace_id(
            '{"workspace_id": "", "key": "val"}'
        )
        assert result == "*"

    def test_non_dict_json(self):
        from server.ws_subscription.main import StdbSubscriptionClient

        result = StdbSubscriptionClient._extract_workspace_id('["a", "b"]')
        assert result == "*"

    def test_invalid_json(self):
        from server.ws_subscription.main import StdbSubscriptionClient

        result = StdbSubscriptionClient._extract_workspace_id("not json")
        assert result == "*"

    def test_numeric_workspace_id(self):
        from server.ws_subscription.main import StdbSubscriptionClient

        result = StdbSubscriptionClient._extract_workspace_id(
            '{"workspace_id": 42, "key": "val"}'
        )
        assert result == "42"

class TestStdbSubscriptionClient:
    """StdbSubscriptionClient lifecycle and message handling."""

    def test_initial_state(self):
        from server.ws_subscription.main import StdbSubscriptionClient

        client = StdbSubscriptionClient()
        assert client._connected is False
        assert client._running is False
        assert client._task is None
        assert client._ws is None

    def test_start_stop(self):
        from server.ws_subscription.main import StdbSubscriptionClient

        client = StdbSubscriptionClient()
        # Start creates a task but will fail to connect (no STDB running)
        # We just verify it doesn't crash
        asyncio_run(client.start())
        assert client._running is True

        client._running = False
        client.stop()
        # Should not raise
        assert client._connected is False

    def test_on_changes_called(self):
        """_handle_transaction calls on_changes callback."""
        from server.ws_subscription.main import StdbSubscriptionClient

        received = []

        async def on_changes(events):
            received.extend(events)

        client = StdbSubscriptionClient(on_changes=on_changes)

        # Simulate a TransactionUpdate with a table update
        tx = {
            "subscription_update": {
                "table_updates": [
                    {
                        "table_name": "memory",
                        "table_row_operations": [
                            {
                                "op": "insert",
                                "row_pk": "rec-1",
                                "row": base64.b64encode(
                                    json.dumps({"key": "val", "workspace_id": "ws-1"}).encode()
                                ).decode(),
                            }
                        ],
                    }
                ]
            }
        }

        asyncio_run(client._handle_transaction(tx))
        assert len(received) >= 1
        assert received[0].table_name == "memory"
        assert received[0].operation == "insert"
        assert received[0].record_id == "rec-1"

    def test_handle_transaction_empty(self):
        """_handle_transaction with no table_updates does not call callback."""
        from server.ws_subscription.main import StdbSubscriptionClient

        called = False

        def on_changes(events):
            nonlocal called
            called = True

        client = StdbSubscriptionClient(on_changes=on_changes)
        asyncio_run(client._handle_transaction({}))
        assert called is False

    def test_handle_transaction_no_matching_tables(self):
        """_handle_transaction with non-content tables is skipped."""
        from server.ws_subscription.main import StdbSubscriptionClient

        called = False

        def on_changes(events):
            nonlocal called
            called = True

        client = StdbSubscriptionClient(on_changes=on_changes)
        tx = {
            "subscription_update": {
                "table_updates": [
                    {
                        "table_name": "unknown_table",
                        "table_row_operations": [
                            {"op": "insert", "row_pk": "1", "row": "{}"}
                        ],
                    }
                ]
            }
        }

        asyncio_run(client._handle_transaction(tx))
        assert called is False

    def test_handle_identity_message(self):
        """IdentityToken messages are handled silently."""
        from server.ws_subscription.main import StdbSubscriptionClient

        called = False

        def on_changes(events):
            nonlocal called
            called = True

        client = StdbSubscriptionClient(on_changes=on_changes)
        asyncio_run(client._handle_message(
            json.dumps({"IdentityToken": {"token": "abc", "identity": "xyz", "address": "addr"}})
        ))
        assert called is False

    def test_handle_subscription_update(self):
        """SubscriptionUpdate (initial data) is handled silently."""
        from server.ws_subscription.main import StdbSubscriptionClient

        called = False

        def on_changes(events):
            nonlocal called
            called = True

        client = StdbSubscriptionClient(on_changes=on_changes)
        asyncio_run(client._handle_message(
            json.dumps({"SubscriptionUpdate": {"table_updates": []}})
        ))
        assert called is False

    def test_handle_invalid_json(self):
        from server.ws_subscription.main import StdbSubscriptionClient

        called = False

        def on_changes(events):
            nonlocal called
            called = True

        client = StdbSubscriptionClient(on_changes=on_changes)
        asyncio_run(client._handle_message("not valid json"))
        assert called is False


# ---------------------------------------------------------------------------
# SubscriptionFilter matching
# ---------------------------------------------------------------------------


class TestSubscriptionFilterMatching:
    """SubscriptionFilter matches ChangeEvent correctly."""

    def test_exact_match(self):
        from server.ws_subscription.main import SubscriptionFilter

        from spacetime_memory.delta_sync import ChangeEvent

        f = SubscriptionFilter(workspace_id="ws-1", table="memory", operation="insert")
        event = ChangeEvent(id="1", workspace_id="ws-1", table_name="memory",
                            operation="insert", record_id="r1", data_json="{}", created_at=1)
        assert f.matches(event)

    def test_wildcard_workspace(self):
        from server.ws_subscription.main import SubscriptionFilter

        from spacetime_memory.delta_sync import ChangeEvent

        f = SubscriptionFilter(workspace_id="*", table="memory", operation="insert")
        event = ChangeEvent(id="1", workspace_id="ws-1", table_name="memory",
                            operation="insert", record_id="r1", data_json="{}", created_at=1)
        assert f.matches(event)

    def test_no_match_workspace(self):
        from server.ws_subscription.main import SubscriptionFilter

        from spacetime_memory.delta_sync import ChangeEvent

        f = SubscriptionFilter(workspace_id="ws-1", table="memory", operation="insert")
        event = ChangeEvent(id="1", workspace_id="ws-2", table_name="memory",
                            operation="insert", record_id="r1", data_json="{}", created_at=1)
        assert not f.matches(event)


# ---------------------------------------------------------------------------
# SubscriptionManager (mocked)
# ---------------------------------------------------------------------------


class TestManagedSubscription:
    """ManagedSubscription dataclass."""

    def test_from_dict(self):
        from spacetime_memory.ws_subscription import ManagedSubscription

        d = {
            "id": "sub-1",
            "workspace_id": "ws-1",
            "name": "test-sub",
            "query": "SELECT * FROM memory",
            "callback_url": "http://example.com/webhook",
            "created_by": "peer-1",
            "is_active": True,
            "created_at": "1000",
            "updated_at": "2000",
        }
        sub = ManagedSubscription.from_dict(d)
        assert sub.id == "sub-1"
        assert sub.workspace_id == "ws-1"
        assert sub.name == "test-sub"
        assert sub.query == "SELECT * FROM memory"
        assert sub.callback_url == "http://example.com/webhook"
        assert sub.is_active is True
        assert sub.created_at == 1000
        assert sub.updated_at == 2000

    def test_from_dict_empty(self):
        from spacetime_memory.ws_subscription import ManagedSubscription

        sub = ManagedSubscription.from_dict({})
        assert sub.id == ""
        assert sub.is_active is False


class TestSubscriptionManager:
    """SubscriptionManager calls STDB reducers correctly."""

    def test_create(self):
        from spacetime_memory.ws_subscription import SubscriptionManager

        mock_client = Mock()
        mock_client._sql.return_value = [
            {
                "id": "sub-1",
                "workspace_id": "ws-1",
                "name": "test-sub",
                "query": "SELECT * FROM memory",
                "callback_url": "",
                "created_by": "peer-1",
                "is_active": True,
                "created_at": 1000,
                "updated_at": 1000,
            }
        ]

        mgr = SubscriptionManager(mock_client)
        sub = mgr.create(
            workspace_id="ws-1",
            name="test-sub",
            query="SELECT * FROM memory",
        )

        mock_client._call.assert_called_once_with(
            "create_subscription", ["ws-1", "test-sub", "SELECT * FROM memory", ""]
        )
        assert sub.id == "sub-1"
        assert sub.name == "test-sub"

    def test_delete(self):
        from spacetime_memory.ws_subscription import SubscriptionManager

        mock_client = Mock()
        mgr = SubscriptionManager(mock_client)
        mgr.delete("sub-1")
        mock_client._call.assert_called_once_with("delete_subscription", ["sub-1"])

    def test_toggle(self):
        from spacetime_memory.ws_subscription import SubscriptionManager

        mock_client = Mock()
        mgr = SubscriptionManager(mock_client)
        mgr.toggle("sub-1", False)
        mock_client._call.assert_called_once_with("toggle_subscription", ["sub-1", False])

    def test_list(self):
        from spacetime_memory.ws_subscription import SubscriptionManager

        mock_client = Mock()
        mock_client._sql.return_value = [
            {
                "id": "sub-1",
                "workspace_id": "ws-1",
                "name": "test-sub",
                "query": "SELECT *",
                "callback_url": "",
                "created_by": "peer-1",
                "is_active": True,
                "created_at": 1000,
                "updated_at": 1000,
            }
        ]

        mgr = SubscriptionManager(mock_client)
        subs = mgr.list("ws-1")
        assert len(subs) == 1
        assert subs[0].id == "sub-1"

    def test_list_all(self):
        from spacetime_memory.ws_subscription import SubscriptionManager

        mock_client = Mock()
        mock_client._sql.return_value = [
            {
                "id": "sub-1",
                "workspace_id": "ws-1",
                "name": "test",
                "query": "SELECT *",
                "callback_url": "",
                "created_by": "peer-1",
                "is_active": True,
                "created_at": 1000,
                "updated_at": 1000,
            }
        ]

        mgr = SubscriptionManager(mock_client)
        subs = mgr.list_all()
        assert len(subs) == 1


# ---------------------------------------------------------------------------
# SubscriptionFilter additional edge cases
# ---------------------------------------------------------------------------


class TestSubscriptionFilterExtra:
    """Additional SubscriptionFilter edge cases (wildcards, mismatches)."""

    def test_wildcard_table(self):
        from server.ws_subscription.main import SubscriptionFilter

        from spacetime_memory.delta_sync import ChangeEvent

        f = SubscriptionFilter(workspace_id="ws-1", table="*", operation="insert")
        event = ChangeEvent(id="1", workspace_id="ws-1", table_name="memory",
                            operation="insert", record_id="r1", data_json="{}", created_at=1)
        assert f.matches(event)

    def test_wildcard_operation(self):
        from server.ws_subscription.main import SubscriptionFilter

        from spacetime_memory.delta_sync import ChangeEvent

        f = SubscriptionFilter(workspace_id="ws-1", table="memory", operation="*")
        event = ChangeEvent(id="1", workspace_id="ws-1", table_name="memory",
                            operation="delete", record_id="r1", data_json="{}", created_at=1)
        assert f.matches(event)

    def test_all_wildcards(self):
        from server.ws_subscription.main import SubscriptionFilter

        from spacetime_memory.delta_sync import ChangeEvent

        f = SubscriptionFilter()
        event = ChangeEvent(id="1", workspace_id="any", table_name="any_table",
                            operation="update", record_id="r1", data_json="{}", created_at=1)
        assert f.matches(event)

    def test_no_match_table(self):
        from server.ws_subscription.main import SubscriptionFilter

        from spacetime_memory.delta_sync import ChangeEvent

        f = SubscriptionFilter(workspace_id="ws-1", table="memory", operation="*")
        event = ChangeEvent(id="1", workspace_id="ws-1", table_name="kg_node",
                            operation="insert", record_id="r1", data_json="{}", created_at=1)
        assert not f.matches(event)

    def test_no_match_operation(self):
        from server.ws_subscription.main import SubscriptionFilter

        from spacetime_memory.delta_sync import ChangeEvent

        f = SubscriptionFilter(workspace_id="ws-1", table="*", operation="insert")
        event = ChangeEvent(id="1", workspace_id="ws-1", table_name="memory",
                            operation="delete", record_id="r1", data_json="{}", created_at=1)
        assert not f.matches(event)

    def test_default_constructor(self):
        """Default filter matches everything."""
        from server.ws_subscription.main import SubscriptionFilter

        f = SubscriptionFilter()
        assert f.workspace_id == "*"
        assert f.table == "*"
        assert f.operation == "*"


# ---------------------------------------------------------------------------
# _filters_equal
# ---------------------------------------------------------------------------


class TestFiltersEqual:
    """_filters_equal compares two SubscriptionFilters for equality."""

    def test_identical_filters(self):
        from server.ws_subscription.main import SubscriptionFilter, _filters_equal

        a = SubscriptionFilter(workspace_id="ws-1", table="memory", operation="insert")
        b = SubscriptionFilter(workspace_id="ws-1", table="memory", operation="insert")
        assert _filters_equal(a, b)

    def test_different_workspace(self):
        from server.ws_subscription.main import SubscriptionFilter, _filters_equal

        a = SubscriptionFilter(workspace_id="ws-1", table="memory", operation="insert")
        b = SubscriptionFilter(workspace_id="ws-2", table="memory", operation="insert")
        assert not _filters_equal(a, b)

    def test_different_table(self):
        from server.ws_subscription.main import SubscriptionFilter, _filters_equal

        a = SubscriptionFilter(workspace_id="ws-1", table="memory", operation="insert")
        b = SubscriptionFilter(workspace_id="ws-1", table="kg_node", operation="insert")
        assert not _filters_equal(a, b)

    def test_different_operation(self):
        from server.ws_subscription.main import SubscriptionFilter, _filters_equal

        a = SubscriptionFilter(workspace_id="ws-1", table="memory", operation="insert")
        b = SubscriptionFilter(workspace_id="ws-1", table="memory", operation="delete")
        assert not _filters_equal(a, b)

    def test_defaults_are_equal(self):
        from server.ws_subscription.main import SubscriptionFilter, _filters_equal

        assert _filters_equal(SubscriptionFilter(), SubscriptionFilter())


# ---------------------------------------------------------------------------
# ClientConnection
# ---------------------------------------------------------------------------


class TestClientConnection:
    """ClientConnection manages filters for a single WebSocket client."""

    def test_add_filter(self):
        from server.ws_subscription.main import ClientConnection, SubscriptionFilter

        conn = ClientConnection(websocket=MagicMock())
        f = SubscriptionFilter(workspace_id="ws-1", table="memory", operation="insert")
        conn.add_filter(f)
        assert len(conn.filters) == 1
        assert conn.filters[0] == f

    def test_remove_filter(self):
        from server.ws_subscription.main import ClientConnection, SubscriptionFilter

        conn = ClientConnection(websocket=MagicMock())
        conn.add_filter(SubscriptionFilter(workspace_id="ws-1", table="memory", operation="insert"))
        conn.add_filter(SubscriptionFilter(workspace_id="ws-2", table="*", operation="*"))
        assert len(conn.filters) == 2

        conn.remove_filter(SubscriptionFilter(workspace_id="ws-1", table="memory", operation="insert"))
        assert len(conn.filters) == 1
        assert conn.filters[0].workspace_id == "ws-2"

    def test_remove_non_existent_filter_is_safe(self):
        from server.ws_subscription.main import ClientConnection, SubscriptionFilter

        conn = ClientConnection(websocket=MagicMock())
        conn.add_filter(SubscriptionFilter(workspace_id="ws-1", table="memory", operation="insert"))
        conn.remove_filter(SubscriptionFilter(workspace_id="nonexistent", table="*", operation="*"))
        assert len(conn.filters) == 1  # unchanged

    def test_matches_any(self):
        from server.ws_subscription.main import ClientConnection, SubscriptionFilter

        from spacetime_memory.delta_sync import ChangeEvent

        conn = ClientConnection(websocket=MagicMock())
        conn.add_filter(SubscriptionFilter(workspace_id="ws-1", table="memory", operation="insert"))

        event = ChangeEvent(id="1", workspace_id="ws-1", table_name="memory",
                            operation="insert", record_id="r1", data_json="{}", created_at=1)
        assert conn.matches_any(event)

    def test_matches_any_no_match(self):
        from server.ws_subscription.main import ClientConnection, SubscriptionFilter

        from spacetime_memory.delta_sync import ChangeEvent

        conn = ClientConnection(websocket=MagicMock())
        conn.add_filter(SubscriptionFilter(workspace_id="ws-1", table="memory", operation="insert"))

        event = ChangeEvent(id="1", workspace_id="ws-2", table_name="memory",
                            operation="insert", record_id="r1", data_json="{}", created_at=1)
        assert not conn.matches_any(event)

    def test_matches_any_empty_filters(self):
        from server.ws_subscription.main import ClientConnection

        from spacetime_memory.delta_sync import ChangeEvent

        conn = ClientConnection(websocket=MagicMock())
        event = ChangeEvent(id="1", workspace_id="ws-1", table_name="memory",
                            operation="insert", record_id="r1", data_json="{}", created_at=1)
        assert not conn.matches_any(event)

    def test_peer_id_default(self):
        from server.ws_subscription.main import ClientConnection

        conn = ClientConnection(websocket=MagicMock())
        assert conn.peer_id == ""


# ---------------------------------------------------------------------------
# SubscriptionServer
# ---------------------------------------------------------------------------


class TestSubscriptionServer:
    """SubscriptionServer lifecycle and message handling."""

    def test_initial_state(self):
        from server.ws_subscription.main import SubscriptionServer

        server = SubscriptionServer()
        assert server._clients == {}
        assert server._server is None
        assert server._stdb_subscription is None

    def test_handle_subscribe_adds_filter(self):
        from unittest.mock import AsyncMock

        from server.ws_subscription.main import ClientConnection, SubscriptionServer

        server = SubscriptionServer()
        conn = ClientConnection(websocket=MagicMock())
        conn.websocket.send = AsyncMock()

        asyncio_run(server._handle_subscribe(conn, {"workspace_id": "ws-1", "table": "memory", "operation": "insert"}))
        assert len(conn.filters) == 1
        assert conn.filters[0].workspace_id == "ws-1"
        assert conn.filters[0].table == "memory"
        assert conn.filters[0].operation == "insert"
        conn.websocket.send.assert_called_once()

    def test_handle_subscribe_with_defaults(self):
        from unittest.mock import AsyncMock

        from server.ws_subscription.main import ClientConnection, SubscriptionServer

        server = SubscriptionServer()
        conn = ClientConnection(websocket=MagicMock())
        conn.websocket.send = AsyncMock()

        asyncio_run(server._handle_subscribe(conn, {}))
        assert len(conn.filters) == 1
        assert conn.filters[0].workspace_id == "*"
        assert conn.filters[0].table == "*"
        assert conn.filters[0].operation == "*"

    def test_handle_unsubscribe_removes_filter(self):
        from unittest.mock import AsyncMock

        from server.ws_subscription.main import (
            ClientConnection,
            SubscriptionFilter,
            SubscriptionServer,
        )

        server = SubscriptionServer()
        conn = ClientConnection(websocket=MagicMock())
        conn.websocket.send = AsyncMock()
        conn.add_filter(SubscriptionFilter(workspace_id="ws-1", table="memory", operation="insert"))
        conn.add_filter(SubscriptionFilter(workspace_id="ws-2", table="*", operation="*"))

        asyncio_run(server._handle_unsubscribe(conn, {"workspace_id": "ws-1", "table": "memory", "operation": "insert"}))
        assert len(conn.filters) == 1
        assert conn.filters[0].workspace_id == "ws-2"

    def test_handle_message_subscribe(self):
        from unittest.mock import AsyncMock

        from server.ws_subscription.main import ClientConnection, SubscriptionServer

        server = SubscriptionServer()
        websocket = MagicMock()
        websocket.send = AsyncMock()
        conn = ClientConnection(websocket=websocket)
        server._clients[str(id(websocket))] = conn

        asyncio_run(server._handle_message(conn, '{"type": "subscribe", "workspace_id": "ws-1", "table": "memory", "operation": "insert"}'))
        assert len(conn.filters) == 1
        sent = websocket.send.call_args[0][0]
        assert '"type": "subscribed"' in sent

    def test_handle_message_unsubscribe(self):
        from unittest.mock import AsyncMock

        from server.ws_subscription.main import (
            ClientConnection,
            SubscriptionFilter,
            SubscriptionServer,
        )

        server = SubscriptionServer()
        websocket = MagicMock()
        websocket.send = AsyncMock()
        conn = ClientConnection(websocket=websocket)
        conn.add_filter(SubscriptionFilter(workspace_id="ws-1", table="memory", operation="insert"))

        asyncio_run(server._handle_message(conn, '{"type": "unsubscribe", "workspace_id": "ws-1", "table": "memory", "operation": "insert"}'))
        assert len(conn.filters) == 0
        sent = websocket.send.call_args[0][0]
        assert '"type": "unsubscribed"' in sent

    def test_handle_message_ping(self):
        from unittest.mock import AsyncMock

        from server.ws_subscription.main import ClientConnection, SubscriptionServer

        server = SubscriptionServer()
        websocket = MagicMock()
        websocket.send = AsyncMock()
        conn = ClientConnection(websocket=websocket)

        asyncio_run(server._handle_message(conn, '{"type": "ping"}'))
        sent = websocket.send.call_args[0][0]
        assert '"type": "pong"' in sent

    def test_handle_message_unknown_type(self):
        from unittest.mock import AsyncMock

        from server.ws_subscription.main import ClientConnection, SubscriptionServer

        server = SubscriptionServer()
        websocket = MagicMock()
        websocket.send = AsyncMock()
        conn = ClientConnection(websocket=websocket)

        asyncio_run(server._handle_message(conn, '{"type": "unknown"}'))
        sent = websocket.send.call_args[0][0]
        assert '"type": "error"' in sent
        assert "Unknown message type" in sent

    def test_handle_message_invalid_json(self):
        from unittest.mock import AsyncMock

        from server.ws_subscription.main import ClientConnection, SubscriptionServer

        server = SubscriptionServer()
        websocket = MagicMock()
        websocket.send = AsyncMock()
        conn = ClientConnection(websocket=websocket)

        asyncio_run(server._handle_message(conn, "not json"))
        sent = websocket.send.call_args[0][0]
        assert '"type": "error"' in sent
        assert "Invalid JSON" in sent

    def test_send_does_not_raise_on_closed(self):
        from server.ws_subscription.main import ClientConnection, SubscriptionServer
        from websockets.exceptions import ConnectionClosed

        server = SubscriptionServer()
        websocket = MagicMock()
        # _send catches websockets.exceptions.ConnectionClosed, so raise that
        websocket.send.side_effect = ConnectionClosed(None, None)
        conn = ClientConnection(websocket=websocket)

        # Should not raise
        asyncio_run(server._send(conn, {"type": "test"}))

    def test_fanout_cleans_disconnected(self):
        from unittest.mock import AsyncMock

        from server.ws_subscription.main import (
            ClientConnection,
            SubscriptionFilter,
            SubscriptionServer,
        )
        from websockets.exceptions import ConnectionClosed

        from spacetime_memory.delta_sync import ChangeEvent

        server = SubscriptionServer()
        websocket = MagicMock()
        websocket.send = AsyncMock()
        websocket.send.side_effect = ConnectionClosed(None, None)
        conn = ClientConnection(websocket=websocket)
        conn.add_filter(SubscriptionFilter(workspace_id="*", table="*", operation="*"))
        server._clients["conn-1"] = conn

        event = ChangeEvent(id="1", workspace_id="ws-1", table_name="memory",
                            operation="insert", record_id="r1", data_json="{}", created_at=1)

        asyncio_run(server._fanout(event))
        # Disconnected client should be removed
        assert "conn-1" not in server._clients

    def test_fanout_skips_non_matching_client(self):
        from unittest.mock import AsyncMock

        from server.ws_subscription.main import (
            ClientConnection,
            SubscriptionFilter,
            SubscriptionServer,
        )

        from spacetime_memory.delta_sync import ChangeEvent

        server = SubscriptionServer()
        websocket = MagicMock()
        websocket.send = AsyncMock()
        conn = ClientConnection(websocket=websocket)
        conn.add_filter(SubscriptionFilter(workspace_id="ws-1", table="memory", operation="*"))
        server._clients["conn-1"] = conn

        event = ChangeEvent(id="1", workspace_id="ws-2", table_name="memory",
                            operation="insert", record_id="r1", data_json="{}", created_at=1)

        asyncio_run(server._fanout(event))
        websocket.send.assert_not_called()

    def test_on_stdb_events_routes_to_fanout(self):
        from unittest.mock import AsyncMock

        from server.ws_subscription.main import (
            ClientConnection,
            SubscriptionFilter,
            SubscriptionServer,
        )

        from spacetime_memory.delta_sync import ChangeEvent

        server = SubscriptionServer()
        websocket = MagicMock()
        websocket.send = AsyncMock()
        conn = ClientConnection(websocket=websocket)
        conn.add_filter(SubscriptionFilter(workspace_id="ws-1", table="*", operation="*"))
        server._clients["conn-1"] = conn

        events = [
            ChangeEvent(id="1", workspace_id="ws-1", table_name="memory",
                        operation="insert", record_id="r1", data_json="{}", created_at=1),
        ]

        asyncio_run(server._on_stdb_events(events))
        websocket.send.assert_called_once()


# ---------------------------------------------------------------------------
# event_to_dict — edge cases with special values
# ---------------------------------------------------------------------------


class TestEventToDictEdgeCases:
    """event_to_dict handles edge cases like bytes, None, special chars."""

    def test_hex_id(self):
        from server.ws_subscription.main import event_to_dict

        from spacetime_memory.delta_sync import ChangeEvent

        ev = ChangeEvent(
            id="0xdeadbeef",
            workspace_id="ws-1",
            table_name="memory",
            operation="update",
            record_id="rec-1",
            data_json='{"hex": true}',
            created_at=1234567890,
        )
        d = event_to_dict(ev)
        assert d["id"] == "0xdeadbeef"
        assert d["created_at"] == 1234567890

    def test_long_workspace_id(self):
        from server.ws_subscription.main import event_to_dict

        from spacetime_memory.delta_sync import ChangeEvent

        ev = ChangeEvent(
            id="ev-2",
            workspace_id="ws-" + "a" * 100,
            table_name="kg_node",
            operation="delete",
            record_id="node-99",
            data_json="[1,2,3]",
            created_at=42,
        )
        d = event_to_dict(ev)
        assert d["workspace_id"] == "ws-" + "a" * 100
        assert d["table_name"] == "kg_node"
        assert d["operation"] == "delete"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def asyncio_run(coro):
    """Run an async coroutine synchronously for testing."""
    import asyncio
    try:
        asyncio.get_running_loop()
        # We're already in a running loop — create a new task and run it
        import threading
        result = []

        async def _run():
            r = await coro
            result.append(r)

        t = threading.Thread(target=lambda: asyncio.run(coro))
        t.start()
        t.join(timeout=5)
    except RuntimeError:
        # No running loop
        return asyncio.run(coro)
