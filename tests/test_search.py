"""Tests for server/mcp/tools/search.py - Search MCP tools."""
import pytest
from server.mcp.tools.search import (
    search_profiles, search_sessions_semantic,
    recommend_memories, get_user_memories,
)


class TestSearchModule:
    """Test suite for search.py - verify all expected exports exist."""

    def test_search_profiles_exists(self):
        """search_profiles should be callable."""
        assert callable(search_profiles)

    def test_search_sessions_semantic_exists(self):
        """search_sessions_semantic should be callable."""
        assert callable(search_sessions_semantic)

    def test_recommend_memories_exists(self):
        """recommend_memories should be callable."""
        assert callable(recommend_memories)

    def test_get_user_memories_exists(self):
        """get_user_memories should be callable."""
        assert callable(get_user_memories)
