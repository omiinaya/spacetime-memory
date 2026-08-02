"""Deep integration tests for client.py — Advanced module.

Includes: ParseRerankJson, ParseSqlResponse, ProfilesWithPeers,
MemoryRetrieval, FuzzyGet, GlobGet, UserMemories, Decay, DecayDeep,
PluginDispatch, GraphTraversalDeep, GraphStatsDeep, AdminDeep,
GraphNeighborsDeep, QueryHash, ParseRerankJsonDeep,
ParseRerankJsonFinal, DeleteMemoryDeep, UpdateMemoryDeep,
GetterMethods, ClientUnitCoverage, SearchWithFilters,
SearchSessionsSemantic, Recommend, TestDecay,
SearchWithFiltersUnit, ConfigAndReputation, KgStats, MemoryStats,
DirectoryOps, NoteEmbedOps, NoteBacklinks, SessionListing,
ListProfiles, ApiKeyCreate, FuzzyGetEdgeCases, MemoryHistory,
BatchEmbedError, CreateNodeEmbed, RerankerErrorHandling,
QueryCacheInvalidation, TantivyAndHealthCheck, RestoreManifest,
and standalone functions.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import httpx
import pytest

from spacetime_memory import Client

pytestmark = [
    pytest.mark.integration,
]


def _unique(prefix: str = "deep") -> str:
    """Return a unique name for test entities."""
    suffix = os.urandom(4).hex()
    return f"{prefix}-{suffix}"


def _make_ws(client: Client) -> str:
    """Helper: create a unique workspace and return its ID."""
    ws_name = _unique("deep-ws")
    result = client.create_workspace(ws_name)
    assert result["status"] == "ok"
    workspaces = client.list_workspaces()
    for w in workspaces:
        if w.get("name") == ws_name:
            return w["id"]
    pytest.fail(f"Workspace '{ws_name}' not found after creation")


def _store_mem(client: Client, ws_id: str, content: str, peer: str = "deep-bot") -> dict:
    """Store a memory and return the result."""
    return client.store(
        workspace_id=ws_id,
        content=content,
        peer_id=peer,
        memory_type="experience",
    )


def _get_first_memory_id(client: Client, ws_id: str) -> str | None:
    """Get the ID of the first memory in a workspace."""
    mems = client.list_memories(workspace_id=ws_id, limit=5)
    return mems[0]["id"] if mems else None
class TestClientUnitCoverage:
    """Unit tests for missed lines in client.py — pure mocking, no backend.

    Part 1 of 4: event emission, identity, retry, circuit breaker, SQL,
    embedding, Tantivy indexing, ping.
    """

    def test_emit_event_with_bus(self):
        """Lines 225-226: _emit_event when event_bus is set."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        mock_bus = MagicMock()
        client.event_bus = mock_bus
        with patch("spacetime_memory.streaming.MemoryEvent") as mock_me:
            client._emit_event("test.event", {"key": "val"}, workspace_id="ws1")
        mock_bus.emit.assert_called_once()
        mock_me.assert_called_once_with(
            event_type="test.event", data={"key": "val"}, workspace_id="ws1"
        )

    def test_emit_event_no_bus(self):
        """_emit_event when event_bus is None (no-op)."""
        client = Client(host="localhost", port="3000", database="test")
        client.event_bus = None
        client._emit_event("test.event", {"key": "val"})  # should not raise

    # ── _ensure_identity (lines 250-252) ──

    def test_ensure_identity_connect_error(self):
        """_ensure_identity catches ConnectError without crashing, and does NOT
        mark identity established (kept unset so the next _call retries the
        handshake once STDB recovers — see b649c95f resilience fix)."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client.token = None
        client._identity_established = False
        mock_http = MagicMock()
        mock_http.get.side_effect = httpx.ConnectError("refused")
        client._http = mock_http
        client._ensure_identity()
        assert client._identity_established is False  # retry on next call

    def test_ensure_identity_timeout(self):
        """_ensure_identity catches TimeoutException without crashing; identity
        stays unset so the handshake retries on the next call."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client.token = None
        client._identity_established = False
        mock_http = MagicMock()
        mock_http.get.side_effect = httpx.TimeoutException("timed out")
        client._http = mock_http
        client._ensure_identity()
        assert client._identity_established is False

    def test_ensure_identity_remote_protocol_error(self):
        """_ensure_identity catches RemoteProtocolError without crashing;
        identity stays unset so the handshake retries on the next call."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client.token = None
        client._identity_established = False
        mock_http = MagicMock()
        mock_http.get.side_effect = httpx.RemoteProtocolError("protocol error")
        client._http = mock_http
        client._ensure_identity()
        assert client._identity_established is False

    # ── _whoami (lines 264-265) ──

    def test_whoami_error_catch(self):
        """Lines 264-265: _whoami catches errors and returns ''."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client._identity_established = True  # skip _ensure_identity
        mock_http = MagicMock()
        mock_http.get.side_effect = httpx.ConnectError("nope")
        client._http = mock_http
        result = client._whoami()
        assert result == ""

    # ── Metrics (lines 277, 281-283) ──

    def test_set_and_get_metrics(self):
        """Lines 277, 281-283: set_metrics_collector and get_metrics."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        assert client.get_metrics() is None  # line 281-282

        mock_collector = MagicMock()
        mock_collector.to_dict.return_value = {"requests": 5}
        client.set_metrics_collector(mock_collector)  # line 277
        result = client.get_metrics()  # line 283
        assert result == {"requests": 5}
        mock_collector.to_dict.assert_called_once()

    # ── from_token_file (lines 300-301) ──

    def test_from_token_file(self):
        """Lines 300-301: from_token_file classmethod."""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jwt", delete=False) as f:
            f.write("test-jwt-token-123\n")  # real trailing newline — strip() must remove it
            token_path = f.name
        try:
            c = Client.from_token_file(token_path, host="h1", port="42", database="db1")
            assert c.token == "test-jwt-token-123"
            assert c.host == "h1"
            assert c.port == "42"
            assert c.database == "db1"
        finally:
            os.unlink(token_path)

    # ── Circuit breaker (line 325) ──

    def test_circuit_breaker_open(self):
        """Line 325: circuit breaker open raises RuntimeError."""
        import time
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client._circuit_open_until = time.time() + 999  # future
        mock_http = MagicMock()
        client._http = mock_http
        with pytest.raises(RuntimeError, match="circuit breaker is open"):
            client._request_with_retry("GET", "http://example.com")

    # ── HTTP method routing (lines 337-340) ──

    def test_request_retry_get_method(self):
        """Line 337-338: GET method routing."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client._circuit_open_until = 0.0
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_http.get.return_value = mock_resp
        client._http = mock_http
        resp = client._request_with_retry("GET", "http://example.com")
        mock_http.get.assert_called_once()
        assert resp.status_code == 200

    def test_request_retry_post_method(self):
        """Line 335-336: POST method routing."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client._circuit_open_until = 0.0
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_http.post.return_value = mock_resp
        client._http = mock_http
        resp = client._request_with_retry("POST", "http://example.com")
        mock_http.post.assert_called_once()
        assert resp.status_code == 200

    def test_request_retry_other_method(self):
        """Line 339-340: OTHER method routing (e.g. PUT)."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client._circuit_open_until = 0.0
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_http.request.return_value = mock_resp
        client._http = mock_http
        resp = client._request_with_retry("PUT", "http://example.com")
        mock_http.request.assert_called_once_with("PUT", "http://example.com")
        assert resp.status_code == 200

    # ── Error catching in retry (lines 350-353) ──

    def test_retry_connect_error(self):
        """Lines 350-351: retry catches ConnectError and raises after max."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client._circuit_open_until = 0.0
        client.max_retries = 1
        mock_http = MagicMock()
        mock_http.get.side_effect = httpx.ConnectError("no connection")
        client._http = mock_http
        with pytest.raises(RuntimeError, match="Request failed"):
            client._request_with_retry("GET", "http://example.com")

    def test_retry_timeout(self):
        """Lines 350-351: retry catches TimeoutException."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client._circuit_open_until = 0.0
        client.max_retries = 0
        mock_http = MagicMock()
        mock_http.get.side_effect = httpx.TimeoutException("timeout")
        client._http = mock_http
        with pytest.raises(RuntimeError, match="Request failed"):
            client._request_with_retry("GET", "http://example.com")

    def test_retry_remote_protocol_error(self):
        """Lines 352-353: retry catches RemoteProtocolError."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client._circuit_open_until = 0.0
        client.max_retries = 0
        mock_http = MagicMock()
        mock_http.get.side_effect = httpx.RemoteProtocolError("protocol")
        client._http = mock_http
        with pytest.raises(RuntimeError, match="Request failed"):
            client._request_with_retry("GET", "http://example.com")

    # ── Circuit breaker trip (lines 365-366) ──

    def test_circuit_breaker_trip(self):
        """Lines 365-366: circuit breaker trips after threshold failures."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client._circuit_open_until = 0.0
        client.max_retries = 0
        client._consecutive_failures = 2  # one below threshold
        client._circuit_breaker_threshold = 3
        client._circuit_breaker_reset_secs = 60
        mock_http = MagicMock()
        mock_http.get.side_effect = httpx.ConnectError("fail")
        client._http = mock_http
        with pytest.raises(RuntimeError, match="Request failed"):
            client._request_with_retry("GET", "http://example.com")
        # After failure, consecutive = 3, which >= threshold = 3 → circuit opens
        assert client._consecutive_failures == 3
        assert client._circuit_open_until > 0

    # ── _sql metrics path (line 391) ──

    def test_sql_with_metrics(self):
        """Line 391: _sql uses metrics collector when set."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client._identity_established = True
        mock_collector = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "[]"
        mock_collector.record.return_value = mock_resp
        client.set_metrics_collector(mock_collector)
        result = client._sql("SELECT 1")
        mock_collector.record.assert_called_once()
        assert result == []

    # ── _sql verbose error (line 398) ──

    def test_sql_verbose_error(self):
        """Line 398: _sql raises verbose RuntimeError."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test", verbose=True)
        client._identity_established = True
        mock_http = MagicMock()
        client._http = mock_http
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "database explosion"
        mock_http.post.return_value = mock_resp
        with pytest.raises(RuntimeError, match="SQL error"):
            client._sql("SELECT * FROM doomed")

    # ── _map_sql_error (line 446) ──

    def test_map_sql_error_with_match(self):
        """Line 446: _map_sql_error finds matching pattern."""
        client = Client(host="localhost", port="3000", database="test")
        result = client._map_sql_error("table 'foo' does not exist")
        assert "Table not found" in result
        assert "raw:" in result

    def test_map_sql_error_no_match(self):
        """_map_sql_error returns generic message on no match."""
        client = Client(host="localhost", port="3000", database="test")
        result = client._map_sql_error("something weird happened")
        assert result.startswith("Database error:")

    # ── _map_reducer_error (line 453) ──

    def test_map_reducer_error_with_match(self):
        """_map_reducer_error finds matching pattern."""
        client = Client(host="localhost", port="3000", database="test")
        result = client._map_reducer_error("not found: memory_id=xyz")
        assert "Record not found" in result

    def test_map_reducer_error_no_match(self):
        """_map_reducer_error returns generic message on no match."""
        client = Client(host="localhost", port="3000", database="test")
        result = client._map_reducer_error("weird reducer failure")
        assert result.startswith("Reducer error:")

    # ── _call metrics (line 469) ──

    def test_call_with_metrics(self):
        """Line 469: _call uses metrics when collector set."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        client._identity_established = True
        mock_collector = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_collector.record.return_value = mock_resp
        client.set_metrics_collector(mock_collector)
        result = client._call("some_reducer", ["arg1"])
        mock_collector.record.assert_called_once()
        assert result == {"status": "ok"}

    # ── _call verbose error (line 476) ──

    def test_call_verbose_error(self):
        """Line 476: _call with verbose=True raises verbose error."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test", verbose=True)
        client._identity_established = True
        mock_http = MagicMock()
        client._http = mock_http
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "reducer kaboom"
        mock_http.post.return_value = mock_resp
        with pytest.raises(RuntimeError, match="Reducer error"):
            client._call("bad_reducer", [])

    # ── _embed_batch empty (lines 553-554) ──

    def test_embed_batch_empty(self):
        """Lines 553-554: _embed_batch with empty list returns []."""
        client = Client(host="localhost", port="3000", database="test")
        result = client._embed_batch([])
        assert result == []

    # ── _tantivy_index (lines 621-634) ──

    def test_tantivy_index_success(self):
        """Lines 621-634: _tantivy_index success path."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_http.post.return_value = mock_resp
        client._http = mock_http
        result = client._tantivy_index("ws1", "mem1", "hello world", "memory")
        assert result is True
        mock_http.post.assert_called_once()

    def test_tantivy_index_error(self):
        """Lines 633-634: _tantivy_index catches ConnectError, returns False."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        mock_http = MagicMock()
        mock_http.post.side_effect = httpx.ConnectError("nope")
        client._http = mock_http
        result = client._tantivy_index("ws1", "mem1", "hello")
        assert result is False

    # ── _tantivy_search (line 658) ──

    def test_tantivy_search_error_status(self):
        """Line 657-658: _tantivy_search on HTTP error status."""
        from unittest.mock import MagicMock

        client = Client(host="localhost", port="3000", database="test")
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_http.post.return_value = mock_resp
        client._http = mock_http
        result = client._tantivy_search("ws1", "query", limit=10)
        assert result == []
