"""Tests for context tree feature (QMD parity)."""

import json
import pytest
from unittest.mock import MagicMock


class TestContextTree:
    """Context tree — set/get context on workspaces and memories."""

    def test_set_workspace_context(self, mock_client):
        """set_workspace_context calls reducer with correct args."""
        mock_client._call("set_workspace_context", ["ws-1", "Project docs about auth"])
        mock_client._call.assert_called_with(
            "set_workspace_context", ["ws-1", "Project docs about auth"]
        )

    def test_set_memory_context(self, mock_client):
        """set_memory_context calls reducer with correct args."""
        mock_client._call("set_memory_context", ["mem-1", "This memory describes the login flow"])
        mock_client._call.assert_called_with(
            "set_memory_context", ["mem-1", "This memory describes the login flow"]
        )

    def test_context_in_search_results(self, mock_client):
        """Search results include context_json from hybrid_result."""
        ctx = json.dumps(
            {
                "workspace_context": "Auth module docs",
                "memory_context": "Login flow details",
            }
        )
        mock_client._sql.return_value = [
            {
                "entity_id": "mem-1",
                "entity_type": "memory",
                "score": 0.95,
                "query_hash": "abc123",
                "workspace_id": "ws-1",
                "context_json": ctx,
            }
        ]
        mock_client._embed.return_value = [0.1] * 384
        mock_client._query.return_value = [{"id": "mem-1", "content": "login content"}]

        results = mock_client.search("ws-1", "login", limit=10)
        assert len(results) == 1
        assert "context_json" in results[0]
        parsed = json.loads(results[0]["context_json"])
        assert parsed["workspace_context"] == "Auth module docs"
        assert parsed["memory_context"] == "Login flow details"


@pytest.fixture
def mock_client():
    """Client with mocked HTTP layer."""
    from spacetime_memory import Client

    c = Client.__new__(Client)
    c._http = MagicMock()
    c._http.get.return_value = MagicMock(status_code=200)
    c._http.post.return_value = MagicMock(status_code=200, json=lambda: [])
    c.database = "test"
    c._identity_token = "test-token"
    c._identity_established = True
    c._call = MagicMock(return_value={"status": "ok"})
    c._sql = MagicMock(return_value=[])
    c._query = MagicMock(return_value=[])
    c._embed = MagicMock(return_value=[0.1] * 384)
    c._query_cache = None
    c._binary_cache = {}
    c._circuit_open_until = 0.0
    c._consecutive_failures = 0
    c._circuit_breaker_threshold = 5
    c._circuit_breaker_reset_secs = 30.0
    c.max_retries = 3
    c.plugin_manager = None
    c.event_bus = None
    c.embedder_url = "http://localhost:9090"
    c.tantivy_url = "http://localhost:9100"
    return c
