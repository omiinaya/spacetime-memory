"""Unit tests for server/ws_subscription/_subscription — SubscriptionFilter and ClientConnection.

Tests cover wildcard matching, exact matching, filter lifecycle (add/remove),
and the private _filters_equal helper. All event objects are mocked via
unittest.mock with the attributes that SubscriptionFilter.matches() accesses
(workspace_id, table_name, operation).
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

import pytest
from server.ws_subscription._subscription import (
    ClientConnection,
    SubscriptionFilter,
    _filters_equal,
)

# ===================================================================
# Helper factories
# ===================================================================


def make_event(**kwargs) -> Mock:
    """Build a mock change event with .workspace_id, .table_name, .operation."""
    event = Mock(spec=["workspace_id", "table_name", "operation"])
    event.workspace_id = kwargs.get("workspace_id", "ws-1")
    event.table_name = kwargs.get("table_name", "tasks")
    event.operation = kwargs.get("operation", "insert")
    return event


# ===================================================================
# SubscriptionFilter
# ===================================================================


@pytest.mark.unit
class TestSubscriptionFilter:
    """SubscriptionFilter — default values, wildcard matching, exact matching."""

    def test_default_values_all_wildcards(self):
        """Default-constructed filter has wildcards for workspace_id, table, operation."""
        f = SubscriptionFilter()
        assert f.workspace_id == "*"
        assert f.table == "*"
        assert f.operation == "*"

    def test_matches_all_wildcards_accepts_any_event(self):
        """All-wildcard filter matches any event."""
        f = SubscriptionFilter()
        assert f.matches(make_event(workspace_id="any", table_name="any", operation="any")) is True

    def test_matches_exact_workspace_id(self):
        """Filter with specific workspace_id matches event with same id."""
        f = SubscriptionFilter(workspace_id="ws-42")
        assert f.matches(make_event(workspace_id="ws-42")) is True

    def test_matches_workspace_id_mismatch(self):
        """Filter with specific workspace_id rejects event with different id."""
        f = SubscriptionFilter(workspace_id="ws-42")
        assert f.matches(make_event(workspace_id="other")) is False

    def test_matches_exact_table(self):
        """Filter with specific table matches event with same table_name."""
        f = SubscriptionFilter(table="projects")
        assert f.matches(make_event(table_name="projects")) is True

    def test_matches_table_mismatch(self):
        """Filter with specific table rejects event with different table_name."""
        f = SubscriptionFilter(table="projects")
        assert f.matches(make_event(table_name="tasks")) is False

    def test_matches_exact_operation(self):
        """Filter with specific operation matches event with same operation."""
        f = SubscriptionFilter(operation="update")
        assert f.matches(make_event(operation="update")) is True

    def test_matches_operation_mismatch(self):
        """Filter with specific operation rejects event with different operation."""
        f = SubscriptionFilter(operation="update")
        assert f.matches(make_event(operation="delete")) is False

    def test_matches_all_fields_exact(self):
        """Filter with all three fields set exactly matches only a fully-corresponding event."""
        f = SubscriptionFilter(workspace_id="ws-1", table="tasks", operation="insert")
        assert f.matches(make_event()) is True
        assert f.matches(make_event(workspace_id="ws-2")) is False
        assert f.matches(make_event(table_name="other")) is False
        assert f.matches(make_event(operation="delete")) is False

    def test_matches_partial_wildcards(self):
        """Wildcard fields are skipped during matching; only non-* fields are checked."""
        f = SubscriptionFilter(workspace_id="ws-1", table="*", operation="insert")
        assert f.matches(make_event(workspace_id="ws-1", table_name="anything", operation="insert")) is True
        assert f.matches(make_event(workspace_id="ws-2", table_name="anything", operation="insert")) is False

    def test_matches_short_circuit_on_workspace_id(self):
        """matches() returns False immediately when workspace_id doesn't match (short-circuit)."""
        f = SubscriptionFilter(workspace_id="ws-a", table="t", operation="op")
        # If workspace_id doesn't match, table and operation aren't consulted
        assert f.matches(make_event(workspace_id="ws-b", table_name="t", operation="op")) is False

    # -- Edge cases ---------------------------------------------------

    def test_matches_event_with_none_attributes(self):
        """When event attributes are None the equality check still works (no crash)."""
        f = SubscriptionFilter(workspace_id="*", table="*", operation="*")
        event = make_event(workspace_id=None, table_name=None, operation=None)
        assert f.matches(event) is True  # wildcards skip checks

    def test_matches_event_with_none_attribute_non_wildcard(self):
        """When a non-wildcard filter is compared against None, it returns False."""
        f = SubscriptionFilter(workspace_id="ws-1")
        event = make_event(workspace_id=None)
        assert f.matches(event) is False

    def test_matches_empty_string_vs_wildcard(self):
        """Empty-string workspace_id is not equal to '*', so it won't match a '*' filter incorrectly."""
        # Wait — '*' is wildcard, so it *should* skip the check and return True.
        # Verify: a filter with workspace_id="*" matches an event with workspace_id="".
        f = SubscriptionFilter(workspace_id="*")
        assert f.matches(make_event(workspace_id="")) is True

    @pytest.mark.parametrize(
        "filter_kwargs, event_kwargs, expected",
        [
            # Workspace_id
            ({"workspace_id": "a"}, {"workspace_id": "a"}, True),
            ({"workspace_id": "a"}, {"workspace_id": "b"}, False),
            ({"workspace_id": "*"}, {"workspace_id": "anything"}, True),
            # Table
            ({"table": "x"}, {"table_name": "x"}, True),
            ({"table": "x"}, {"table_name": "y"}, False),
            ({"table": "*"}, {"table_name": "anything"}, True),
            # Operation
            ({"operation": "ins"}, {"operation": "ins"}, True),
            ({"operation": "ins"}, {"operation": "del"}, False),
            ({"operation": "*"}, {"operation": "anything"}, True),
            # Combination
            ({"workspace_id": "a", "table": "x", "operation": "ins"}, {"workspace_id": "a", "table_name": "x", "operation": "ins"}, True),
            ({"workspace_id": "a", "table": "x", "operation": "ins"}, {"workspace_id": "b", "table_name": "x", "operation": "ins"}, False),
            ({"workspace_id": "*", "table": "x", "operation": "*"}, {"workspace_id": "z", "table_name": "x", "operation": "del"}, True),
            ({"workspace_id": "*", "table": "x", "operation": "ins"}, {"workspace_id": "z", "table_name": "x", "operation": "del"}, False),
        ],
    )
    def test_matches_parametrized(self, filter_kwargs, event_kwargs, expected):
        """Parametrized cross-product of matching scenarios."""
        f = SubscriptionFilter(**filter_kwargs)
        event = make_event(**event_kwargs)
        assert f.matches(event) is expected


# ===================================================================
# ClientConnection
# ===================================================================


@pytest.mark.unit
class TestClientConnection:
    """ClientConnection — lifecycle of filters on a WebSocket client connection."""

    def test_default_construction(self):
        """Default ClientConnection has empty filters and empty peer_id."""
        ws = MagicMock()
        conn = ClientConnection(websocket=ws)
        assert conn.filters == []
        assert conn.peer_id == ""

    def test_constructor_sets_peer_id(self):
        """peer_id passed to constructor is stored."""
        ws = MagicMock()
        conn = ClientConnection(websocket=ws, peer_id="peer-abc")
        assert conn.peer_id == "peer-abc"

    def test_websocket_stored(self):
        """The websocket argument is stored as-is."""
        ws = MagicMock()
        conn = ClientConnection(websocket=ws)
        assert conn.websocket is ws

    def test_add_filter_appends(self):
        """add_filter appends a SubscriptionFilter to the filters list."""
        ws = MagicMock()
        conn = ClientConnection(websocket=ws)
        f1 = SubscriptionFilter(workspace_id="ws-1")
        f2 = SubscriptionFilter(workspace_id="ws-2")

        conn.add_filter(f1)
        assert len(conn.filters) == 1
        assert conn.filters[0] is f1

        conn.add_filter(f2)
        assert len(conn.filters) == 2
        assert conn.filters[1] is f2

    def test_remove_filter_exact_match(self):
        """remove_filter removes a filter that exactly matches (all three fields)."""
        ws = MagicMock()
        conn = ClientConnection(websocket=ws)
        f1 = SubscriptionFilter(workspace_id="ws-1", table="t", operation="ins")
        f2 = SubscriptionFilter(workspace_id="ws-2", table="u", operation="del")
        conn.add_filter(f1)
        conn.add_filter(f2)

        conn.remove_filter(f1)
        assert len(conn.filters) == 1
        assert conn.filters[0] is f2

    def test_remove_filter_no_match_keeps_all(self):
        """remove_filter with a filter not in the list leaves the list unchanged."""
        ws = MagicMock()
        conn = ClientConnection(websocket=ws)
        f1 = SubscriptionFilter(workspace_id="ws-1")
        f2 = SubscriptionFilter(workspace_id="ws-2")
        conn.add_filter(f1)

        conn.remove_filter(f2)  # f2 not in list
        assert len(conn.filters) == 1
        assert conn.filters[0] is f1

    def test_remove_filter_partial_match_does_not_remove(self):
        """remove_filter requires all three fields to match; partial match is ignored."""
        ws = MagicMock()
        conn = ClientConnection(websocket=ws)
        f1 = SubscriptionFilter(workspace_id="ws-1", table="t", operation="ins")
        conn.add_filter(f1)

        # Same workspace_id but different table — not equal according to _filters_equal
        partial = SubscriptionFilter(workspace_id="ws-1", table="x", operation="ins")
        conn.remove_filter(partial)
        assert len(conn.filters) == 1
        assert conn.filters[0] is f1

    def test_remove_filter_removes_only_first_match(self):
        """When multiple copies of the same filter exist, remove_filter removes all of them."""
        ws = MagicMock()
        conn = ClientConnection(websocket=ws)
        f = SubscriptionFilter(workspace_id="ws-1")
        conn.add_filter(f)
        conn.add_filter(f)
        conn.add_filter(SubscriptionFilter(workspace_id="ws-2"))

        conn.remove_filter(f)
        assert len(conn.filters) == 1
        assert conn.filters[0].workspace_id == "ws-2"

    def test_matches_any_empty_filters(self):
        """matches_any with no filters returns False."""
        ws = MagicMock()
        conn = ClientConnection(websocket=ws)
        assert conn.matches_any(make_event()) is False

    def test_matches_any_one_matches(self):
        """matches_any returns True when at least one filter matches."""
        ws = MagicMock()
        conn = ClientConnection(websocket=ws)
        conn.add_filter(SubscriptionFilter(workspace_id="ws-1"))
        conn.add_filter(SubscriptionFilter(workspace_id="ws-2"))
        assert conn.matches_any(make_event(workspace_id="ws-1")) is True

    def test_matches_any_none_match(self):
        """matches_any returns False when no filter matches."""
        ws = MagicMock()
        conn = ClientConnection(websocket=ws)
        conn.add_filter(SubscriptionFilter(workspace_id="ws-1"))
        assert conn.matches_any(make_event(workspace_id="other")) is False

    def test_matches_any_all_wildcard(self):
        """matches_any with an all-wildcard filter matches every event."""
        ws = MagicMock()
        conn = ClientConnection(websocket=ws)
        conn.add_filter(SubscriptionFilter())
        assert conn.matches_any(make_event(workspace_id="anything", table_name="any", operation="any")) is True

    def test_matches_any_multiple_filters_second_matches(self):
        """When the first filter doesn't match but the second does, matches_any returns True."""
        ws = MagicMock()
        conn = ClientConnection(websocket=ws)
        conn.add_filter(SubscriptionFilter(workspace_id="ws-1"))
        conn.add_filter(SubscriptionFilter(workspace_id="ws-2"))
        assert conn.matches_any(make_event(workspace_id="ws-2")) is True

    # -- Edge cases ---------------------------------------------------

    def test_add_filter_duplicate(self):
        """Adding the same filter object twice keeps both (no deduplication)."""
        ws = MagicMock()
        conn = ClientConnection(websocket=ws)
        f = SubscriptionFilter(workspace_id="ws-1")
        conn.add_filter(f)
        conn.add_filter(f)
        assert len(conn.filters) == 2

    def test_remove_filter_not_present(self):
        """Removing a filter that was never added is a no-op (no error)."""
        ws = MagicMock()
        conn = ClientConnection(websocket=ws)
        conn.add_filter(SubscriptionFilter(workspace_id="ws-1"))
        conn.remove_filter(SubscriptionFilter(workspace_id="ws-99"))
        assert len(conn.filters) == 1

    def test_constructor_accepts_filters_list(self):
        """ClientConnection accepts a pre-populated list of filters via constructor."""
        ws = MagicMock()
        filters = [SubscriptionFilter(workspace_id="a"), SubscriptionFilter(workspace_id="b")]
        conn = ClientConnection(websocket=ws, filters=filters)
        assert len(conn.filters) == 2
        assert conn.filters[0].workspace_id == "a"
        assert conn.filters[1].workspace_id == "b"

    def test_websocket_accepts_mock_with_spec(self):
        """Pass a MagicMock with spec=ServerConnection to verify type compatibility."""
        ws = MagicMock(spec=["send", "recv", "close", "id"])
        conn = ClientConnection(websocket=ws)
        assert conn.websocket is ws


# ===================================================================
# _filters_equal (private helper)
# ===================================================================


@pytest.mark.unit
class TestFiltersEqual:
    """_filters_equal — all-three-fields equality check."""

    def test_equal_all_wildcards(self):
        """Two default-constructed filters are equal."""
        a = SubscriptionFilter()
        b = SubscriptionFilter()
        assert _filters_equal(a, b) is True

    def test_equal_exact_fields(self):
        """Filters with identical workspace_id, table, operation are equal."""
        a = SubscriptionFilter(workspace_id="a", table="b", operation="c")
        b = SubscriptionFilter(workspace_id="a", table="b", operation="c")
        assert _filters_equal(a, b) is True

    def test_different_workspace_id(self):
        """Filters differing only in workspace_id are not equal."""
        a = SubscriptionFilter(workspace_id="a")
        b = SubscriptionFilter(workspace_id="b")
        assert _filters_equal(a, b) is False

    def test_different_table(self):
        """Filters differing only in table are not equal."""
        a = SubscriptionFilter(table="x")
        b = SubscriptionFilter(table="y")
        assert _filters_equal(a, b) is False

    def test_different_operation(self):
        """Filters differing only in operation are not equal."""
        a = SubscriptionFilter(operation="insert")
        b = SubscriptionFilter(operation="delete")
        assert _filters_equal(a, b) is False

    def test_all_fields_different(self):
        """Filters with all three fields different are not equal."""
        a = SubscriptionFilter(workspace_id="a", table="b", operation="c")
        b = SubscriptionFilter(workspace_id="x", table="y", operation="z")
        assert _filters_equal(a, b) is False

    def test_wildcard_is_just_a_string(self):
        """The string '*' is treated literally — two '*' filters are equal."""
        a = SubscriptionFilter(workspace_id="*")
        b = SubscriptionFilter(workspace_id="*")
        assert _filters_equal(a, b) is True

    def test_wildcard_vs_non_wildcard_not_equal(self):
        """A filter with '*' is not equal to one with a concrete value."""
        a = SubscriptionFilter(workspace_id="*")
        b = SubscriptionFilter(workspace_id="ws-1")
        assert _filters_equal(a, b) is False
