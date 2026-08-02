"""Unit tests for server/ws_subscription/_handler.py.

Tests _decode_row, event_to_dict, StdbSubscriptionClient constructor,
_extract_workspace_id, and _merge_update_pairs.
All tests use mocking — no live STDB or WebSocket server needed.
"""

from __future__ import annotations

import asyncio
import base64
import json

# ---------------------------------------------------------------------------
# Add repo root to sys.path (same pattern as conftest.py and
# test_ws_subscription_server.py)
# ---------------------------------------------------------------------------
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from server.ws_subscription._handler import (
    StdbSubscriptionClient,
    _decode_row,
    event_to_dict,
)

from spacetime_memory.delta_sync import ChangeEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def asyncio_run(coro):
    """Run an async coroutine synchronously for testing.

    Handles both the case where we're already inside a running event loop
    (e.g. pytest-asyncio) and the case where we aren't.
    """
    try:
        asyncio.get_running_loop()
        # Already in a running loop — spawn a separate thread with its own loop
        import threading

        def _run():
            r = asyncio.run(coro)
            if r is not None:
                result.append(r)

        result: list = []
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=5)
        return result[0] if result else None
    except RuntimeError:
        # No running loop
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# _decode_row
# ---------------------------------------------------------------------------


class TestDecodeRow:
    """_decode_row converts STDB row data values to JSON strings.

    Covers: base64-encoded string, dict, bytes, plain string,
    invalid base64 (contains '!').
    """

    def test_base64_encoded(self):
        """Base64-encoded JSON string is decoded."""
        data = {"key": "value", "nested": [1, 2, 3]}
        encoded = base64.b64encode(json.dumps(data).encode()).decode()
        result = _decode_row(encoded)
        assert json.loads(result) == data

    def test_dict_input(self):
        """Dict input is serialised to JSON string."""
        result = _decode_row({"key": "value", "num": 42})
        assert json.loads(result) == {"key": "value", "num": 42}

    def test_bytes_input(self):
        """Bytes input is decoded as UTF-8."""
        result = _decode_row(b'{"from_bytes": true}')
        assert result == '{"from_bytes": true}'

    def test_plain_string(self):
        """Plain string that is not valid base64 is returned as-is."""
        result = _decode_row("plain text")
        assert result == "plain text"

    def test_invalid_base64_contains_exclamation(self):
        """String with '!' is not valid base64 with validate=True — returned as-is."""
        result = _decode_row("!!!invalid base64!!!")
        assert result == "!!!invalid base64!!!"

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert _decode_row("") == ""

    def test_empty_dict(self):
        """Empty dict returns '{}'."""
        assert _decode_row({}) == "{}"

    def test_empty_bytes(self):
        """Empty bytes returns empty string."""
        assert _decode_row(b"") == ""

    def test_non_base64_characters_returned_as_is(self):
        """A string that looks like base64 but contains invalid chars is
        returned as-is when b64decode(validate=True) raises."""
        result = _decode_row("abc!!!def")
        assert result == "abc!!!def"

    def test_valid_base64_but_not_json(self):
        """Valid base64 that decodes to non-JSON text is still returned."""
        raw_text = "just some text"
        encoded = base64.b64encode(raw_text.encode()).decode()
        result = _decode_row(encoded)
        assert result == raw_text

    def test_integer_input_falls_through(self):
        """Non-str, non-dict, non-bytes input is passed through str()."""
        result = _decode_row(42)
        assert result == "42"

    def test_list_input_falls_through(self):
        """List input (not handled specially) is passed through str()."""
        result = _decode_row([1, 2, 3])
        assert result == "[1, 2, 3]"

    def test_none_input_falls_through(self):
        """None is passed through str()."""
        result = _decode_row(None)
        assert result == "None"


# ---------------------------------------------------------------------------
# event_to_dict
# ---------------------------------------------------------------------------


class TestEventToDict:
    """event_to_dict converts a ChangeEvent dataclass to a plain dict."""

    def test_basic_conversion(self):
        """All fields are mapped correctly."""
        ev = ChangeEvent(
            id="ev-1",
            workspace_id="ws-123",
            table_name="memory",
            operation="insert",
            record_id="rec-abc",
            data_json='{"key": "val"}',
            created_at=1000,
        )
        d = event_to_dict(ev)
        assert d == {
            "id": "ev-1",
            "workspace_id": "ws-123",
            "table_name": "memory",
            "operation": "insert",
            "record_id": "rec-abc",
            "data_json": '{"key": "val"}',
            "created_at": 1000,
        }

    def test_empty_data_json(self):
        """Empty data_json is preserved."""
        ev = ChangeEvent(
            id="ev-2",
            workspace_id="ws-1",
            table_name="kg_node",
            operation="delete",
            record_id="node-1",
            data_json="{}",
            created_at=0,
        )
        d = event_to_dict(ev)
        assert d["data_json"] == "{}"

    def test_zero_created_at(self):
        """created_at of 0 is preserved."""
        ev = ChangeEvent(
            id="ev-3",
            workspace_id="ws-1",
            table_name="profile",
            operation="update",
            record_id="p-1",
            data_json="{}",
            created_at=0,
        )
        d = event_to_dict(ev)
        assert d["created_at"] == 0


# ---------------------------------------------------------------------------
# _extract_workspace_id
# ---------------------------------------------------------------------------


class TestExtractWorkspaceId:
    """_extract_workspace_id extracts workspace_id from a JSON data string.

    Covers: valid JSON with workspace_id, empty JSON, malformed JSON,
    missing workspace_id, empty workspace_id, numeric workspace_id.
    """

    def test_with_valid_workspace_id(self):
        result = StdbSubscriptionClient._extract_workspace_id(
            '{"workspace_id": "ws-123", "key": "val"}'
        )
        assert result == "ws-123"

    def test_missing_workspace_id(self):
        result = StdbSubscriptionClient._extract_workspace_id(
            '{"key": "val", "other": "data"}'
        )
        assert result == "*"

    def test_empty_json_object(self):
        assert StdbSubscriptionClient._extract_workspace_id("{}") == "*"

    def test_empty_string(self):
        assert StdbSubscriptionClient._extract_workspace_id("") == "*"

    def test_empty_workspace_id_value(self):
        result = StdbSubscriptionClient._extract_workspace_id(
            '{"workspace_id": "", "key": "val"}'
        )
        assert result == "*"

    def test_null_workspace_id(self):
        result = StdbSubscriptionClient._extract_workspace_id(
            '{"workspace_id": null, "key": "val"}'
        )
        assert result == "*"

    def test_numeric_workspace_id(self):
        """Numeric workspace_id is converted to string."""
        result = StdbSubscriptionClient._extract_workspace_id(
            '{"workspace_id": 42, "key": "val"}'
        )
        assert result == "42"

    def test_non_dict_json_array(self):
        """JSON array (not a dict) returns '*'."""
        result = StdbSubscriptionClient._extract_workspace_id('["a", "b"]')
        assert result == "*"

    def test_malformed_json(self):
        """Malformed JSON returns '*'."""
        result = StdbSubscriptionClient._extract_workspace_id("not json")
        assert result == "*"

    def test_none_input(self):
        """None input returns '*' (fails json.loads gracefully)."""
        result = StdbSubscriptionClient._extract_workspace_id(None)  # type: ignore[arg-type]
        assert result == "*"


# ---------------------------------------------------------------------------
# _merge_update_pairs
# ---------------------------------------------------------------------------


class TestMergeUpdatePairs:
    """_merge_update_pairs merges adjacent delete+insert pairs into updates.

    Covers: adjacent delete+insert for same record -> update,
    adjacent delete+insert for different records -> kept separate,
    single event, empty list, non-adjacent events.
    """

    def _make_event(self, id: str, table: str, op: str, record_id: str, **kw):
        return ChangeEvent(
            id=id,
            table_name=table,
            operation=op,
            record_id=record_id,
            workspace_id=kw.pop("workspace_id", "ws-1"),
            data_json=kw.pop("data_json", '{"d": 1}'),
            created_at=kw.pop("created_at", 100),
            **kw,
        )

    def test_empty_list(self):
        assert StdbSubscriptionClient._merge_update_pairs([]) == []

    def test_single_insert(self):
        events = [self._make_event("1", "memory", "insert", "rec-1")]
        result = StdbSubscriptionClient._merge_update_pairs(events)
        assert len(result) == 1
        assert result[0].operation == "insert"
        assert result[0].id == "1"

    def test_single_delete(self):
        events = [self._make_event("1", "memory", "delete", "rec-1")]
        result = StdbSubscriptionClient._merge_update_pairs(events)
        assert len(result) == 1
        assert result[0].operation == "delete"

    def test_adjacent_delete_insert_merged(self):
        """Adjacent delete+insert for same record and table -> update."""
        events = [
            self._make_event("1", "memory", "delete", "rec-1", data_json='{"old": 1}', created_at=100),
            self._make_event("2", "memory", "insert", "rec-1", data_json='{"val": 2}', created_at=101),
        ]
        result = StdbSubscriptionClient._merge_update_pairs(events)
        assert len(result) == 1
        assert result[0].operation == "update"
        assert result[0].record_id == "rec-1"
        assert result[0].table_name == "memory"
        # Should use the insert event's data_json and id
        assert json.loads(result[0].data_json) == {"val": 2}
        assert result[0].id == "2"

    def test_adjacent_different_records_not_merged(self):
        """Adjacent delete+insert for different records -> kept separate."""
        events = [
            self._make_event("1", "memory", "delete", "rec-1"),
            self._make_event("2", "memory", "insert", "rec-2"),
        ]
        result = StdbSubscriptionClient._merge_update_pairs(events)
        assert len(result) == 2
        assert result[0].operation == "delete"
        assert result[1].operation == "insert"

    def test_adjacent_different_tables_not_merged(self):
        """Adjacent delete+insert for different tables -> kept separate."""
        events = [
            self._make_event("1", "memory", "delete", "rec-1"),
            self._make_event("2", "kg_node", "insert", "rec-1"),
        ]
        result = StdbSubscriptionClient._merge_update_pairs(events)
        assert len(result) == 2
        assert result[0].operation == "delete"
        assert result[1].operation == "insert"

    def test_non_adjacent_delete_insert_not_merged(self):
        """Delete followed later by same-record insert (not adjacent) -> not merged."""
        events = [
            self._make_event("1", "memory", "delete", "rec-1"),
            self._make_event("2", "memory", "insert", "rec-2"),
            self._make_event("3", "memory", "insert", "rec-1"),
        ]
        result = StdbSubscriptionClient._merge_update_pairs(events)
        assert len(result) == 3
        assert result[0].operation == "delete"
        assert result[1].operation == "insert"
        assert result[2].operation == "insert"

    def test_adjacent_insert_delete_not_merged(self):
        """Insert then delete (reverse order) is NOT merged."""
        events = [
            self._make_event("1", "memory", "insert", "rec-1"),
            self._make_event("2", "memory", "delete", "rec-1"),
        ]
        result = StdbSubscriptionClient._merge_update_pairs(events)
        assert len(result) == 2
        assert result[0].operation == "insert"
        assert result[1].operation == "delete"

    def test_multiple_merged_pairs(self):
        """Multiple adjacent delete+insert pairs for different records."""
        events = [
            self._make_event("1", "memory", "delete", "rec-1", created_at=100),
            self._make_event("2", "memory", "insert", "rec-1", created_at=101),
            self._make_event("3", "kg_node", "delete", "node-1", created_at=102),
            self._make_event("4", "kg_node", "insert", "node-1", created_at=103),
        ]
        result = StdbSubscriptionClient._merge_update_pairs(events)
        assert len(result) == 2
        assert result[0].operation == "update"
        assert result[0].record_id == "rec-1"
        assert result[0].table_name == "memory"
        assert result[1].operation == "update"
        assert result[1].record_id == "node-1"
        assert result[1].table_name == "kg_node"

    def test_mixed_merged_and_single(self):
        """Merge a pair but keep a trailing single event."""
        events = [
            self._make_event("1", "memory", "delete", "rec-1"),
            self._make_event("2", "memory", "insert", "rec-1"),
            self._make_event("3", "memory", "insert", "rec-2"),
        ]
        result = StdbSubscriptionClient._merge_update_pairs(events)
        assert len(result) == 2
        assert result[0].operation == "update"
        assert result[0].record_id == "rec-1"
        assert result[1].operation == "insert"
        assert result[1].record_id == "rec-2"

    def test_merge_with_leading_unmatched(self):
        """Leading event that doesn't merge, followed by a mergable pair."""
        events = [
            self._make_event("1", "memory", "insert", "rec-1"),
            self._make_event("2", "memory", "delete", "rec-2"),
            self._make_event("3", "memory", "insert", "rec-2"),
        ]
        result = StdbSubscriptionClient._merge_update_pairs(events)
        assert len(result) == 2
        assert result[0].operation == "insert"
        assert result[1].operation == "update"
        assert result[1].record_id == "rec-2"


# ---------------------------------------------------------------------------
# StdbSubscriptionClient — constructor
# ---------------------------------------------------------------------------


class TestStdbSubscriptionClientInit:
    """StdbSubscriptionClient constructor stores params correctly."""

    def test_default_params(self):
        client = StdbSubscriptionClient()
        assert client._on_changes is None
        assert client._stdb_uri is None
        assert client._stdb_host == "127.0.0.1"
        assert client._stdb_port == 3001
        assert client._stdb_database == ""
        assert client._poll_interval == 0.1
        assert client._push_mode is False
        assert client._connected is False
        assert client._running is False
        assert client._task is None
        assert client._ws is None
        assert client._http_client is None
        assert client._cursor == 0

    def test_custom_params(self):
        async def cb(events):
            pass

        client = StdbSubscriptionClient(
            on_changes=cb,
            stdb_uri="ws://custom:9000",
            stdb_host="10.0.0.1",
            stdb_port=5000,
            stdb_database="test-db",
            poll_interval=0.5,
        )
        assert client._on_changes is cb
        assert client._stdb_uri == "ws://custom:9000"
        assert client._stdb_host == "10.0.0.1"
        assert client._stdb_port == 5000
        assert client._stdb_database == "test-db"
        assert client._poll_interval == 0.5
        assert client._push_mode is True

    def test_push_mode_with_empty_uri(self):
        """Empty stdb_uri produces push_mode=False."""
        client = StdbSubscriptionClient(stdb_uri="")
        assert client._push_mode is False
        assert client._stdb_uri == ""

    def test_push_mode_with_none_uri(self):
        """None stdb_uri produces push_mode=False."""
        client = StdbSubscriptionClient(stdb_uri=None)
        assert client._push_mode is False

    def test_subscribe_queries_contains_all_content_tables(self):
        client = StdbSubscriptionClient()
        expected_tables = {
            "memory", "kg_node", "kg_edge", "note", "profile", "document",
        }
        for q in client._subscribe_queries:
            table = q.replace("SELECT * FROM ", "")
            assert table in expected_tables, f"Unexpected table in queries: {table}"
            expected_tables.discard(table)
        assert len(expected_tables) == 0, f"Missing tables: {expected_tables}"


# ---------------------------------------------------------------------------
# StdbSubscriptionClient — static methods
# ---------------------------------------------------------------------------


class TestStdbSubscriptionClientStatic:
    """StdbSubscriptionClient._extract_workspace_id and _merge_update_pairs
    are static methods that work on the class, not an instance.
    """

    def test_extract_workspace_id_is_callable(self):
        assert callable(StdbSubscriptionClient._extract_workspace_id)

    def test_merge_update_pairs_is_callable(self):
        assert callable(StdbSubscriptionClient._merge_update_pairs)

    def test_extract_workspace_id_returns_string(self):
        result = StdbSubscriptionClient._extract_workspace_id(
            '{"workspace_id": "abc"}'
        )
        assert isinstance(result, str)

    def test_merge_update_pairs_returns_list(self):
        result = StdbSubscriptionClient._merge_update_pairs([])
        assert isinstance(result, list)
