"""Tests for server/mcp/tools/profiles.py - Profile MCP tools."""
import pytest
from server.mcp.tools.profiles import (
    add_fact, delete_fact, add_profile_fact,
    get_peer_reputation, add_dynamic_context, expire_memories,
)


class TestProfilesModule:
    """Test suite for profiles.py - verify all expected exports exist."""

    def test_add_fact_exists(self):
        assert callable(add_fact)

    def test_delete_fact_exists(self):
        assert callable(delete_fact)

    def test_add_profile_fact_exists(self):
        assert callable(add_profile_fact)

    def test_get_peer_reputation_exists(self):
        assert callable(get_peer_reputation)

    def test_add_dynamic_context_exists(self):
        assert callable(add_dynamic_context)

    def test_expire_memories_exists(self):
        assert callable(expire_memories)
