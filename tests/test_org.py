"""Tests for server/mcp/tools/org.py - Organization MCP tools."""
import pytest
from server.mcp.tools.org import org_sync


class TestOrgModule:
    """Test suite for org.py - verify all expected exports exist."""

    def test_org_sync_exists(self):
        """org_sync should be callable."""
        assert callable(org_sync)
