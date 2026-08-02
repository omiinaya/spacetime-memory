"""Tests for server/mcp/tools/admin.py - Admin MCP tools."""
import pytest
from server.mcp.tools.admin import (
    create_api_key, deactivate_api_key, list_api_keys,
    health_check, get_metrics,
)


class TestAdminModule:
    """Test suite for admin.py - verify all expected exports exist."""

    def test_create_api_key_exists(self):
        assert callable(create_api_key)

    def test_deactivate_api_key_exists(self):
        assert callable(deactivate_api_key)

    def test_list_api_keys_exists(self):
        assert callable(list_api_keys)

    def test_health_check_exists(self):
        assert callable(health_check)

    def test_get_metrics_exists(self):
        assert callable(get_metrics)
