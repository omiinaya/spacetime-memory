"""Tests for server/mcp/tools/space.py - Space access MCP tools."""
import pytest
from server.mcp.tools.space import (
    grant_space_access, revoke_space_access, list_space_members,
)


class TestSpaceModule:
    """Test suite for space.py - verify all expected exports exist."""

    def test_grant_space_access_exists(self):
        """grant_space_access should be callable."""
        assert callable(grant_space_access)

    def test_revoke_space_access_exists(self):
        """revoke_space_access should be callable."""
        assert callable(revoke_space_access)

    def test_list_space_members_exists(self):
        """list_space_members should be callable."""
        assert callable(list_space_members)
