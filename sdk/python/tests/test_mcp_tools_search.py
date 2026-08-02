"""Tests for server/mcp/tools/search.py — Search / Recommend MCP tools."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestRecommendMemories:
    """Tests for the ``recommend_memories`` tool."""

    @patch("server.mcp.tools.search.get_client")
    def test_recommend_memories(self, mock_get_client):
        """recommend_memories delegates to get_client().recommend_memories."""
        mock_client = MagicMock()
        expected = [{"id": "mem-1", "urgency": 0.7}]
        mock_client.recommend_memories.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import recommend_memories

        result = recommend_memories(
            workspace_id="ws-1", limit=10, min_urgency=0.3
        )

        mock_client.recommend_memories.assert_called_once_with(
            workspace_id="ws-1", limit=10, min_urgency=0.3
        )
        parsed = json.loads(result)
        assert parsed[0]["id"] == "mem-1"

    @patch("server.mcp.tools.search.get_client")
    def test_recommend_memories_empty_result(self, mock_get_client):
        """recommend_memories returns no-recommendations message when empty."""
        mock_client = MagicMock()
        mock_client.recommend_memories.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import recommend_memories

        result = recommend_memories(workspace_id="ws-1")

        parsed = json.loads(result)
        assert parsed["workspace_id"] == "ws-1"
        assert parsed["recommendations"] == []
        assert "No recommendations found" in parsed["message"]

    @patch("server.mcp.tools.search.get_client")
    def test_recommend_memories_none_result(self, mock_get_client):
        """recommend_memories returns no-recommendations message when None."""
        mock_client = MagicMock()
        mock_client.recommend_memories.return_value = None
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import recommend_memories

        result = recommend_memories(workspace_id="ws-1")

        parsed = json.loads(result)
        assert parsed["recommendations"] == []

    @patch("server.mcp.tools.search.get_client")
    def test_recommend_memories_min_urgency_zero(self, mock_get_client):
        """recommend_memories with min_urgency=0 returns all recommendations."""
        mock_client = MagicMock()
        expected = [{"id": "mem-1", "urgency": 0.0}, {"id": "mem-2", "urgency": 0.1}]
        mock_client.recommend_memories.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import recommend_memories

        result = recommend_memories(
            workspace_id="ws-1", limit=20, min_urgency=0.0
        )
        mock_client.recommend_memories.assert_called_once_with(
            workspace_id="ws-1", limit=20, min_urgency=0.0
        )
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["urgency"] == 0.0

    @patch("server.mcp.tools.search.get_client")
    def test_recommend_memories_propagates_exception(self, mock_get_client):
        """Errors from the client propagate through recommend_memories."""
        mock_client = MagicMock()
        mock_client.recommend_memories.side_effect = RuntimeError("api error")
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import recommend_memories

        with pytest.raises(RuntimeError, match="api error"):
            recommend_memories(workspace_id="ws-1")


@pytest.mark.unit
class TestSearchSessionsSemantic:
    """Tests for the ``search_sessions_semantic`` tool."""

    @patch("server.mcp.tools.search.get_client")
    def test_search_sessions_semantic(self, mock_get_client):
        """search_sessions_semantic delegates to get_client().search_sessions_semantic."""
        mock_client = MagicMock()
        expected = [{"session_id": "s1", "score": 0.9}]
        mock_client.search_sessions_semantic.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import search_sessions_semantic

        result = search_sessions_semantic(query="test query", limit=5)

        mock_client.search_sessions_semantic.assert_called_once_with(
            query="test query", limit=5
        )
        parsed = json.loads(result)
        assert parsed[0]["session_id"] == "s1"

    @patch("server.mcp.tools.search.get_client")
    def test_search_sessions_semantic_empty(self, mock_get_client):
        """search_sessions_semantic returns no-sessions message when empty."""
        mock_client = MagicMock()
        mock_client.search_sessions_semantic.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import search_sessions_semantic

        result = search_sessions_semantic(query="nothing")

        parsed = json.loads(result)
        assert parsed["query"] == "nothing"
        assert parsed["sessions"] == []

    @patch("server.mcp.tools.search.get_client")
    def test_search_sessions_semantic_default_limit(self, mock_get_client):
        """search_sessions_semantic uses default limit=10 when not specified."""
        mock_client = MagicMock()
        mock_client.search_sessions_semantic.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import search_sessions_semantic

        result = search_sessions_semantic(query="default")

        mock_client.search_sessions_semantic.assert_called_once_with(
            query="default", limit=10
        )
        parsed = json.loads(result)
        assert parsed["query"] == "default"

    @patch("server.mcp.tools.search.get_client")
    def test_search_sessions_semantic_none_result(self, mock_get_client):
        """search_sessions_semantic returns empty message when None."""
        mock_client = MagicMock()
        mock_client.search_sessions_semantic.return_value = None
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import search_sessions_semantic

        result = search_sessions_semantic(query="none")
        parsed = json.loads(result)
        assert parsed["sessions"] == []

    @patch("server.mcp.tools.search.get_client")
    def test_search_sessions_semantic_propagates_exception(self, mock_get_client):
        """Errors from the client propagate through search_sessions_semantic."""
        mock_client = MagicMock()
        mock_client.search_sessions_semantic.side_effect = ConnectionError("timeout")
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import search_sessions_semantic

        with pytest.raises(ConnectionError, match="timeout"):
            search_sessions_semantic(query="fail")


@pytest.mark.unit
class TestGetUserMemories:
    """Tests for the ``get_user_memories`` tool."""

    @patch("server.mcp.tools.search.get_client")
    def test_get_user_memories(self, mock_get_client):
        """get_user_memories delegates to get_client().get_user_memories."""
        mock_client = MagicMock()
        expected = [{"memory_id": "m1", "content": "test"}]
        mock_client.get_user_memories.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import get_user_memories

        result = get_user_memories(
            user_scope="user-hash-123", workspace_id="ws-1"
        )

        mock_client.get_user_memories.assert_called_once_with(
            user_scope="user-hash-123", workspace_id="ws-1"
        )
        parsed = json.loads(result)
        assert parsed[0]["memory_id"] == "m1"

    @patch("server.mcp.tools.search.get_client")
    def test_get_user_memories_empty(self, mock_get_client):
        """get_user_memories returns no-memories message when empty."""
        mock_client = MagicMock()
        mock_client.get_user_memories.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import get_user_memories

        result = get_user_memories(
            user_scope="user-hash", workspace_id="ws-1"
        )

        parsed = json.loads(result)
        assert parsed["memories"] == []

    @patch("server.mcp.tools.search.get_client")
    def test_get_user_memories_none_result(self, mock_get_client):
        """get_user_memories returns no-memories message when None."""
        mock_client = MagicMock()
        mock_client.get_user_memories.return_value = None
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import get_user_memories

        result = get_user_memories(
            user_scope="user-hash", workspace_id="ws-1"
        )

        parsed = json.loads(result)
        assert parsed["memories"] == []
        assert parsed["user_scope"] == "user-hash"
        assert parsed["workspace_id"] == "ws-1"

    @patch("server.mcp.tools.search.get_client")
    def test_get_user_memories_propagates_exception(self, mock_get_client):
        """Errors from the client propagate through get_user_memories."""
        mock_client = MagicMock()
        mock_client.get_user_memories.side_effect = PermissionError("access denied")
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import get_user_memories

        with pytest.raises(PermissionError, match="access denied"):
            get_user_memories(user_scope="user", workspace_id="ws-1")


@pytest.mark.unit
class TestSearchProfiles:
    """Tests for the ``search_profiles`` tool."""

    @patch("server.mcp.tools.search.get_client")
    def test_search_profiles(self, mock_get_client):
        """search_profiles delegates to get_client().search_profiles."""
        mock_client = MagicMock()
        expected = [{"profile_id": "p1", "name": "Alice"}]
        mock_client.search_profiles.return_value = expected
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import search_profiles

        result = search_profiles(
            workspace_id="ws-1", query="Alice", limit=20
        )

        mock_client.search_profiles.assert_called_once_with(
            workspace_id="ws-1", query="Alice", limit=20
        )
        parsed = json.loads(result)
        assert parsed[0]["profile_id"] == "p1"

    @patch("server.mcp.tools.search.get_client")
    def test_search_profiles_empty(self, mock_get_client):
        """search_profiles returns no-profiles message when empty."""
        mock_client = MagicMock()
        mock_client.search_profiles.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import search_profiles

        result = search_profiles(
            workspace_id="ws-1", query="nonexistent", limit=10
        )

        parsed = json.loads(result)
        assert parsed["profiles"] == []

    @patch("server.mcp.tools.search.get_client")
    def test_search_profiles_none_result(self, mock_get_client):
        """search_profiles returns no-profiles message when None."""
        mock_client = MagicMock()
        mock_client.search_profiles.return_value = None
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import search_profiles

        result = search_profiles(
            workspace_id="ws-1", query="none", limit=5
        )

        parsed = json.loads(result)
        assert parsed["profiles"] == []
        assert parsed["workspace_id"] == "ws-1"
        assert parsed["query"] == "none"

    @patch("server.mcp.tools.search.get_client")
    def test_search_profiles_default_limit(self, mock_get_client):
        """search_profiles uses default limit=20 when not specified."""
        mock_client = MagicMock()
        mock_client.search_profiles.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import search_profiles

        search_profiles(workspace_id="ws-1", query="test")

        mock_client.search_profiles.assert_called_once_with(
            workspace_id="ws-1", query="test", limit=20
        )

    @patch("server.mcp.tools.search.get_client")
    def test_search_profiles_propagates_exception(self, mock_get_client):
        """Errors from the client propagate through search_profiles."""
        mock_client = MagicMock()
        mock_client.search_profiles.side_effect = ValueError("bad query")
        mock_get_client.return_value = mock_client

        from server.mcp.tools.search import search_profiles

        with pytest.raises(ValueError, match="bad query"):
            search_profiles(workspace_id="ws-1", query="bad")
