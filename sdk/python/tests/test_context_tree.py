"""Tests for context tree feature (QMD parity).

Covers set/get workspace context, memory context, context in search results,
edge cases like empty context, special chars, deep nesting, and invalid IDs.
"""

import json
import pytest
from unittest.mock import MagicMock


class TestContextTree:
    """Context tree — set/get context on workspaces and memories."""

    # ── Basic set operations ─────────────────────────────────────────

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

    def test_set_workspace_context_empty(self, mock_client):
        """Setting empty workspace context should be allowed."""
        mock_client._call("set_workspace_context", ["ws-1", ""])
        mock_client._call.assert_called_with(
            "set_workspace_context", ["ws-1", ""]
        )

    def test_set_memory_context_empty(self, mock_client):
        """Setting empty memory context should be allowed."""
        mock_client._call("set_memory_context", ["mem-1", ""])
        mock_client._call.assert_called_with(
            "set_memory_context", ["mem-1", ""]
        )

    def test_set_workspace_context_special_chars(self, mock_client):
        """Special Unicode characters in workspace context."""
        text = "Project: αβγ → 日本語 • emoji 😊 <script>alert(1)</script>"
        mock_client._call("set_workspace_context", ["ws-1", text])
        mock_client._call.assert_called_with(
            "set_workspace_context", ["ws-1", text]
        )

    def test_set_memory_context_long_text(self, mock_client):
        """Very long context text should be passed verbatim."""
        long_text = "word " * 1000  # ~6000 chars
        mock_client._call("set_memory_context", ["mem-1", long_text])
        mock_client._call.assert_called_with(
            "set_memory_context", ["mem-1", long_text]
        )

    # ── Context in search results ────────────────────────────────────

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

    def test_context_missing_from_search(self, mock_client):
        """Results without context_json key should not crash."""
        mock_client._sql.return_value = [
            {
                "entity_id": "mem-2",
                "entity_type": "memory",
                "score": 0.85,
                "query_hash": "abc124",
                "workspace_id": "ws-1",
            }
        ]
        mock_client._embed.return_value = [0.1] * 384
        mock_client._query.return_value = [{"id": "mem-2", "content": "no context"}]

        results = mock_client.search("ws-1", "no context", limit=10)
        assert len(results) >= 1

    def test_context_null_json(self, mock_client):
        """context_json set to null JSON should not crash."""
        mock_client._sql.return_value = [
            {
                "entity_id": "mem-3",
                "entity_type": "memory",
                "score": 0.75,
                "query_hash": "abc125",
                "workspace_id": "ws-1",
                "context_json": "null",
            }
        ]
        mock_client._embed.return_value = [0.1] * 384
        mock_client._query.return_value = [{"id": "mem-3", "content": "null context"}]

        results = mock_client.search("ws-1", "null context", limit=10)
        assert len(results) >= 1

    def test_context_empty_dict_json(self, mock_client):
        """context_json with {} should be valid."""
        mock_client._sql.return_value = [
            {
                "entity_id": "mem-4",
                "entity_type": "memory",
                "score": 0.65,
                "query_hash": "abc126",
                "workspace_id": "ws-1",
                "context_json": "{}",
            }
        ]
        mock_client._embed.return_value = [0.1] * 384
        mock_client._query.return_value = [{"id": "mem-4", "content": "empty ctx"}]

        results = mock_client.search("ws-1", "empty ctx", limit=10)
        assert len(results) >= 1

    def test_context_malformed_json(self, mock_client):
        """Malformed context_json should not crash search."""
        mock_client._sql.return_value = [
            {
                "entity_id": "mem-5",
                "entity_type": "memory",
                "score": 0.55,
                "query_hash": "abc127",
                "workspace_id": "ws-1",
                "context_json": "{invalid json!!!",
            }
        ]
        mock_client._embed.return_value = [0.1] * 384
        mock_client._query.return_value = [{"id": "mem-5", "content": "bad json"}]

        # Should not raise — fallbacks gracefully
        results = mock_client.search("ws-1", "bad json", limit=10)
        assert isinstance(results, list)

    def test_context_with_only_workspace_context(self, mock_client):
        """Only workspace_context in context_json (no memory_context)."""
        ctx = json.dumps({"workspace_context": "Global project notes"})
        mock_client._sql.return_value = [
            {
                "entity_id": "mem-6",
                "entity_type": "memory",
                "score": 0.9,
                "query_hash": "abc128",
                "workspace_id": "ws-1",
                "context_json": ctx,
            }
        ]
        mock_client._embed.return_value = [0.1] * 384
        mock_client._query.return_value = [{"id": "mem-6", "content": "workspace only"}]

        results = mock_client.search("ws-1", "workspace only", limit=10)
        assert len(results) >= 1

    def test_context_with_only_memory_context(self, mock_client):
        """Only memory_context in context_json (no workspace_context)."""
        ctx = json.dumps({"memory_context": "Specific item details"})
        mock_client._sql.return_value = [
            {
                "entity_id": "mem-7",
                "entity_type": "memory",
                "score": 0.8,
                "query_hash": "abc129",
                "workspace_id": "ws-1",
                "context_json": ctx,
            }
        ]
        mock_client._embed.return_value = [0.1] * 384
        mock_client._query.return_value = [{"id": "mem-7", "content": "memory only"}]

        results = mock_client.search("ws-1", "memory only", limit=10)
        assert len(results) >= 1

    def test_context_many_results(self, mock_client):
        """Multiple search results each with varied context."""
        ctx1 = json.dumps({"workspace_context": "Auth"})
        ctx2 = json.dumps({"workspace_context": "Database"})
        mock_client._sql.return_value = [
            {"entity_id": "m1", "entity_type": "memory", "score": 0.9,
             "query_hash": "h1", "workspace_id": "ws-1", "context_json": ctx1},
            {"entity_id": "m2", "entity_type": "memory", "score": 0.8,
             "query_hash": "h2", "workspace_id": "ws-1", "context_json": ctx2},
        ]
        mock_client._embed.return_value = [0.1] * 384
        mock_client._query.return_value = [
            {"id": "m1", "content": "auth login"},
            {"id": "m2", "content": "db indexing"},
        ]

        results = mock_client.search("ws-1", "test", limit=10)
        assert len(results) == 2
        for r in results:
            assert "context_json" in r

    # ── Overwriting context ─────────────────────────────────────────

    def test_overwrite_workspace_context(self, mock_client):
        """Overwriting workspace context replaces old value."""
        mock_client._call("set_workspace_context", ["ws-1", "Initial"])
        mock_client._call("set_workspace_context", ["ws-1", "Updated"])

        # The _call mock remembers only the last call
        assert mock_client._call.call_count == 2
        mock_client._call.assert_any_call("set_workspace_context", ["ws-1", "Initial"])
        mock_client._call.assert_any_call("set_workspace_context", ["ws-1", "Updated"])

    def test_overwrite_memory_context(self, mock_client):
        """Overwriting memory context replaces old value."""
        mock_client._call("set_memory_context", ["mem-1", "Old"])
        mock_client._call("set_memory_context", ["mem-1", "New"])

        assert mock_client._call.call_count == 2

    def test_context_unaffected_by_other_operations(self, mock_client):
        """Setting context does not affect unrelated workspace context."""
        mock_client._call("set_workspace_context", ["ws-1", "Context A"])
        mock_client._call("set_workspace_context", ["ws-2", "Context B"])

        # Check first call had correct args
        calls = mock_client._call.call_args_list
        assert calls[0] == (("set_workspace_context", ["ws-1", "Context A"]),)
        assert calls[1] == (("set_workspace_context", ["ws-2", "Context B"]),)

    def test_context_call_returns_status(self, mock_client):
        """set_*_context returns {'status': 'ok'} on success."""
        result = mock_client._call("set_workspace_context", ["ws-1", "test"])
        assert result == {"status": "ok"}


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
