"""Tests for server/mcp/tools/peers.py - Peer management MCP tools."""
import pytest
from server.mcp.tools.peers import (
    list_peers, get_peer_sessions, get_session_messages,
)


class TestPeersModule:
    """Test suite for peers.py - verify all expected exports exist."""

    def test_list_peers_exists(self):
        """list_peers should be callable."""
        assert callable(list_peers)

    def test_get_peer_sessions_exists(self):
        """get_peer_sessions should be callable."""
        assert callable(get_peer_sessions)

    def test_get_session_messages_exists(self):
        """get_session_messages should be callable."""
        assert callable(get_session_messages)
