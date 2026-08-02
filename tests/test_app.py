"""Tests for server/mcp/tools/app.py - MCP server app configuration."""
import pytest
from server.mcp.tools.app import (
    HOST, PORT, MCP_API_KEY,
    EMBEDDER_URL, TANTIVY_URL,
)


class TestAppConfig:
    """Test suite for app.py configuration constants."""

    def test_host_configured(self):
        """HOST should be a non-empty string."""
        assert isinstance(HOST, str)
        assert len(HOST) > 0

    def test_port_is_integer(self):
        """PORT should be a positive integer value (may be string type)."""
        assert str(PORT).isdigit()
        assert int(PORT) > 0

    def test_api_key_configured(self):
        """MCP_API_KEY should be a string (may be empty in dev config)."""
        assert isinstance(MCP_API_KEY, str)

    def test_embedder_url_configured(self):
        """EMBEDDER_URL should be a valid URL."""
        assert isinstance(EMBEDDER_URL, str)
        assert EMBEDDER_URL.startswith("http")

    def test_tantivy_url_configured(self):
        """TANTIVY_URL should be a valid URL."""
        assert isinstance(TANTIVY_URL, str)
        assert TANTIVY_URL.startswith("http")
