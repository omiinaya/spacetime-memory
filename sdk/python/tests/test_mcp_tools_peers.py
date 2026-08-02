"""Tests for server/mcp/tools/peers.py MCP tools.

Patches ``server.mcp.tools.app.get_client`` to verify delegation.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    """Patch ``server.mcp.tools.peers.get_client`` to return a MagicMock."""
    with patch("server.mcp.tools.peers.get_client") as mock_fn:
        instance = MagicMock()
        mock_fn.return_value = instance
        yield instance


@pytest.mark.unit
class TestListPeers:
    """Tests for ``list_peers``."""

    def test_without_workspace(self, mock_client):
        from server.mcp.tools.peers import list_peers

        mock_client.list_peers.return_value = [
            {"peer_id": "p1", "profile": {"name": "Alice"}},
        ]
        result = list_peers()
        mock_client.list_peers.assert_called_once_with(None)
        assert result == [{"peer_id": "p1", "profile": {"name": "Alice"}}]

    def test_with_workspace(self, mock_client):
        from server.mcp.tools.peers import list_peers

        mock_client.list_peers.return_value = []
        result = list_peers(workspace_id="ws-1")
        mock_client.list_peers.assert_called_once_with("ws-1")
        assert result == []

    def test_error_propagates(self, mock_client):
        """Client connection error propagates to caller."""
        from server.mcp.tools.peers import list_peers

        mock_client.list_peers.side_effect = ConnectionError("DB down")
        with pytest.raises(ConnectionError, match="DB down"):
            list_peers()

    def test_missing_profile(self, mock_client):
        """Listing peers whose profile dict is missing or incomplete."""
        from server.mcp.tools.peers import list_peers

        mock_client.list_peers.return_value = [
            {"peer_id": "p2"},
            {"peer_id": "p3", "profile": {}},
        ]
        result = list_peers()
        assert result[0].get("profile") is None
        assert result[1]["profile"] == {}
        assert len(result) == 2

    def test_multiple_peers(self, mock_client):
        """Multiple peers returned correctly."""
        from server.mcp.tools.peers import list_peers

        mock_client.list_peers.return_value = [
            {"peer_id": "p1", "profile": {"name": "Alice"}},
            {"peer_id": "p2", "profile": {"name": "Bob"}},
            {"peer_id": "p3", "profile": {"name": "Carol"}},
        ]
        result = list_peers(workspace_id="ws-2")
        mock_client.list_peers.assert_called_once_with("ws-2")
        assert len(result) == 3
        assert result[-1]["peer_id"] == "p3"


@pytest.mark.unit
class TestGetPeerSessions:
    """Tests for ``get_peer_sessions``."""

    def test_returns_list(self, mock_client):
        from server.mcp.tools.peers import get_peer_sessions

        mock_client.get_peer_sessions.return_value = [
            {"session_id": "s1", "messages": 5},
        ]
        result = get_peer_sessions(peer_id="p1")
        mock_client.get_peer_sessions.assert_called_once_with("p1")
        assert result[0]["session_id"] == "s1"

    def test_empty(self, mock_client):
        from server.mcp.tools.peers import get_peer_sessions

        mock_client.get_peer_sessions.return_value = []
        result = get_peer_sessions(peer_id="unknown")
        assert result == []

    def test_error_propagates(self, mock_client):
        """Client raises on invalid peer ID."""
        from server.mcp.tools.peers import get_peer_sessions

        mock_client.get_peer_sessions.side_effect = ValueError("peer not found")
        with pytest.raises(ValueError, match="peer not found"):
            get_peer_sessions(peer_id="nonexistent")

    def test_multiple_sessions(self, mock_client):
        """Multiple sessions returned correctly."""
        from server.mcp.tools.peers import get_peer_sessions

        mock_client.get_peer_sessions.return_value = [
            {"session_id": "s1", "messages": 5},
            {"session_id": "s2", "messages": 12},
        ]
        result = get_peer_sessions(peer_id="p1")
        assert len(result) == 2
        assert result[-1]["session_id"] == "s2"

    def test_missing_fields(self, mock_client):
        """Session dicts with missing keys do not crash."""
        from server.mcp.tools.peers import get_peer_sessions

        mock_client.get_peer_sessions.return_value = [
            {"session_id": "s1"},
            {},
        ]
        result = get_peer_sessions(peer_id="p1")
        assert result[0].get("session_id") == "s1"
        assert result[1] == {}


@pytest.mark.unit
class TestGetSessionMessages:
    """Tests for ``get_session_messages``."""

    def test_returns_list(self, mock_client):
        from server.mcp.tools.peers import get_session_messages

        mock_client.get_session_messages.return_value = [
            {"message_id": "m1", "content": "Hello"},
        ]
        result = get_session_messages(session_id="s1")
        mock_client.get_session_messages.assert_called_once_with("s1")
        assert result[0]["message_id"] == "m1"

    def test_empty(self, mock_client):
        from server.mcp.tools.peers import get_session_messages

        mock_client.get_session_messages.return_value = []
        result = get_session_messages(session_id="empty")
        assert result == []

    def test_error_propagates(self, mock_client):
        """Client connection error propagates."""
        from server.mcp.tools.peers import get_session_messages

        mock_client.get_session_messages.side_effect = RuntimeError("timeout")
        with pytest.raises(RuntimeError, match="timeout"):
            get_session_messages(session_id="bad")

    def test_multiple_messages(self, mock_client):
        """Multiple messages returned correctly."""
        from server.mcp.tools.peers import get_session_messages

        mock_client.get_session_messages.return_value = [
            {"message_id": "m1", "content": "Hello"},
            {"message_id": "m2", "content": "World"},
        ]
        result = get_session_messages(session_id="s1")
        assert len(result) == 2
        assert result[0]["message_id"] == "m1"
        assert result[1]["content"] == "World"

    def test_missing_content_field(self, mock_client):
        """Messages with missing content field do not crash."""
        from server.mcp.tools.peers import get_session_messages

        mock_client.get_session_messages.return_value = [
            {"message_id": "m1"},
        ]
        result = get_session_messages(session_id="s1")
        assert "content" not in result[0]
