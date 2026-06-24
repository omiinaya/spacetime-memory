"""Tests for the SDK Client."""

import json
import pytest
import httpx
from unittest.mock import Mock
from spacetime_memory import Client
from tests.conftest import make_sql_response


class TestClientInit:
    """Client construction and configuration."""

    def test_init_defaults(self):
        """Client can be initialized with explicit args."""
        client = Client(host="localhost", port="3001", database="test-db")
        assert client.host == "localhost"
        assert client.port == "3001"
        assert client.database == "test-db"

    def test_init_env_overrides(self, monkeypatch):
        """Client reads env vars when no constructor args given."""
        monkeypatch.setenv("SPACETIMEDB_HOST", "myhost")
        monkeypatch.setenv("SPACETIMEDB_PORT", "9999")
        monkeypatch.setenv("SPACETIMEDB_DB", "my-db")
        client = Client()
        assert client.host == "myhost"
        assert client.port == "9999"
        assert client.database == "my-db"

    def test_init_port_from_int(self):
        """port can be passed as an int."""
        client = Client(host="h", port=4000, database="d")
        assert client.port == "4000"

    def test_init_default_database(self):
        """Default database is the production hash when no env/arg."""
        client = Client(host="h", port="1")
        # length-64 hex string from the code
        assert len(client.database) == 64
        assert all(c in "0123456789abcdef" for c in client.database)


class TestClientSql:
    """_sql() method — wraps SpacetimeDB SQL API."""

    def test_sql_query(self, mock_http_client):
        """_sql() sends POST to /v1/database/{db}/sql with the query content."""
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text=json.dumps([]),
        )

        mock_http_client._sql("SELECT * FROM workspace")

        mock_http_client._http.post.assert_called_once()
        args, kwargs = mock_http_client._http.post.call_args
        assert "/v1/database/test-db/sql" in args[0]
        assert kwargs["content"] == "SELECT * FROM workspace"

    def test_sql_parses_response(self, mock_http_client):
        """_sql() parses SpacetimeDB wire‑format into a list of dicts."""
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response([{"id": "1", "name": "alice"}]),
        )

        rows = mock_http_client._sql("SELECT * FROM peer")

        assert len(rows) == 1
        assert rows[0]["id"] == "1"
        assert rows[0]["name"] == "alice"

    def test_sql_error_raises(self, mock_http_client):
        """_sql() raises RuntimeError on HTTP >= 400."""
        mock_http_client._http.post.return_value = Mock(
            status_code=400,
            text="Bad request",
        )

        with pytest.raises(RuntimeError, match=r"error"):
            mock_http_client._sql("SELECT bad SQL")

    def test_sql_empty_response(self, mock_http_client):
        """_sql() returns [] when the response is an empty string."""
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text="",
        )

        rows = mock_http_client._sql("SELECT * FROM empty")
        assert rows == []


class TestClientReducer:
    """_call() method — wraps SpacetimeDB reducer endpoint."""

    def test_reducer_call(self, mock_http_client):
        """_call() sends POST to /v1/database/{db}/call/{reducer}."""
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text="{}",
        )

        result = mock_http_client._call(
            "store_memory",
            ["ws", "peer", "", "experience", "hello", "", "[]", 0.8, "", ""],
        )

        assert result["status"] == "ok"
        mock_http_client._http.post.assert_called_once()
        args, kwargs = mock_http_client._http.post.call_args
        assert "/v1/database/test-db/call/store_memory" in args[0]

    def test_reducer_error_raises(self, mock_http_client):
        """_call() raises RuntimeError on HTTP >= 400."""
        mock_http_client._http.post.return_value = Mock(
            status_code=500,
            text="Internal server error",
        )

        with pytest.raises(RuntimeError, match="Request failed after"):
            mock_http_client._call("bad_reducer", [])


class TestClientEmbed:
    """_embed() method — proxy → NVIDIA NIM bge-m3."""

    def test_embed_success(self, mock_http_client, monkeypatch):
        """_embed() returns a valid embedding vector."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        embed_response = Mock(status_code=200)
        embed_response.json.return_value = {
            "data": [{"embedding": [0.1, 0.2, 0.3]}],
        }
        mock_http_client._http.post.return_value = embed_response

        result = mock_http_client._embed("hello world")
        assert result == [0.1, 0.2, 0.3]

    def test_embed_error_returns_empty(self, mock_http_client, monkeypatch):
        """_embed() returns [] on connection error."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        import httpx
        mock_http_client._http.post.side_effect = httpx.ConnectError("Connection refused")

        result = mock_http_client._embed("hello")
        assert result == []

    def test_embed_http_error_returns_empty(self, mock_http_client, monkeypatch):
        """_embed() returns [] when the proxy returns HTTP >= 400."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        mock_resp = Mock(status_code=503)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Service Unavailable", request=Mock(), response=mock_resp
        )
        mock_http_client._http.post.return_value = mock_resp

        result = mock_http_client._embed("hello")
        assert result == []


class TestClientWorkspace:
    """High-level workspace methods."""

    def test_create_workspace(self, mock_http_client):
        """create_workspace calls the create_workspace reducer."""
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text="{}",
        )

        result = mock_http_client.create_workspace("test-ws")

        assert result["status"] == "ok"
        mock_http_client._http.post.assert_called_once()
        args, kwargs = mock_http_client._http.post.call_args
        assert "/v1/database/test-db/call/create_workspace" in args[0]

    def test_list_workspaces(self, mock_http_client):
        """list_workspaces returns correct data via _query()."""
        # Mock the SQL endpoint to return query_result table data
        # (the _query() method internally queries query_result after calling the reducer)
        mock_http_client._http.post.return_value = Mock(
            status_code=200,
            text=make_sql_response([
                {"id": "1", "name": "ws-one"},
                {"id": "2", "name": "ws-two"},
            ]),
        )

        workspaces = mock_http_client.list_workspaces()

        assert len(workspaces) == 2
        assert workspaces[0]["name"] == "ws-one"
        assert workspaces[1]["name"] == "ws-two"


class TestRequestRetry:
    """_request_with_retry — retry logic and circuit breaker."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._http = Mock()
        return c

    def test_server_error_retries(self, client):
        """HTTP 502 is retried, then succeeds on retry."""
        client._http.post.side_effect = [
            Mock(status_code=502),
            Mock(status_code=200),
        ]
        resp = client._request_with_retry("POST", "http://test/call/x")
        assert resp.status_code == 200
        assert client._consecutive_failures == 0
        assert client._circuit_open_until == 0.0

    def test_connect_error_retries(self, client):
        """httpx.ConnectError is retried."""
        client._http.post.side_effect = [
            httpx.ConnectError("refused"),
            Mock(status_code=200),
        ]
        resp = client._request_with_retry("POST", "http://test/call/x")
        assert resp.status_code == 200

    def test_client_error_not_retried(self, client):
        """HTTP 400 is NOT retried — returned immediately."""
        client._http.post.return_value = Mock(status_code=400)
        resp = client._request_with_retry("POST", "http://test/call/x")
        assert resp.status_code == 400
        # Only one call (no retries)
        assert client._http.post.call_count == 1

    def test_http_530_not_retried(self, client):
        """HTTP 530 (application error) is NOT retried."""
        client._http.post.return_value = Mock(status_code=530)
        resp = client._request_with_retry("POST", "http://test/call/x")
        assert resp.status_code == 530
        assert client._http.post.call_count == 1

    def test_all_retries_exhausted(self, client):
        """After max_retries+1 attempts, circuit breaker trips."""
        client.max_retries = 2
        client._circuit_breaker_threshold = 2
        client._consecutive_failures = 1  # one prior failure

        client._http.post.return_value = Mock(status_code=502)
        with pytest.raises(RuntimeError, match="Request failed after"):
            client._request_with_retry("POST", "http://test/call/x")

        # Circuit should be tripped (consecutive_failures=2 >= threshold=2)
        assert client._consecutive_failures == 2
        assert client._circuit_open_until > 0

    def test_circuit_breaker_open(self, client):
        """When circuit is open, fails fast without attempting request."""
        import time
        client._circuit_open_until = time.time() + 60  # open for 60s
        client._consecutive_failures = 5

        with pytest.raises(RuntimeError, match="circuit breaker is open"):
            client._request_with_retry("POST", "http://test/call/x")

        # No HTTP call was made
        client._http.post.assert_not_called()

    def test_circuit_resets_on_success(self, client):
        """A successful request after failures resets the circuit."""
        client._consecutive_failures = 3
        client._circuit_open_until = 0.0

        # Server error, then success
        client._http.post.side_effect = [
            Mock(status_code=502),
            Mock(status_code=200),
        ]
        resp = client._request_with_retry("POST", "http://test/call/x")
        assert resp.status_code == 200
        assert client._consecutive_failures == 0
        assert client._circuit_open_until == 0.0

    def test_get_method_routing(self, client):
        """GET method routes to _http.get."""
        client._http.get.return_value = Mock(status_code=200)
        resp = client._request_with_retry("GET", "http://test/health")
        assert resp.status_code == 200
        client._http.get.assert_called_once()

    def test_other_method_routing(self, client):
        """Non-POST/GET methods route to _http.request."""
        client._http.request.return_value = Mock(status_code=200)
        resp = client._request_with_retry("PUT", "http://test/resource")
        assert resp.status_code == 200
        client._http.request.assert_called_once_with("PUT", "http://test/resource")


class TestErrorMapping:
    """_map_reducer_error and _map_sql_error."""

    @pytest.fixture
    def client(self):
        return Client(host="localhost", port="3001", database="test-db")

    def test_map_reducer_error_known(self, client):
        """Known reducer errors are mapped to friendly messages."""
        msg = client._map_reducer_error("not found: memory abc-123")
        assert "Record not found" in msg
        assert "raw:" in msg

    def test_map_reducer_error_unknown(self, client):
        """Unknown reducer errors get generic message."""
        msg = client._map_reducer_error("Something went wrong")
        assert msg.startswith("Reducer error:")

    def test_map_sql_error_known(self, client):
        """Known SQL errors are mapped with friendly message + raw."""
        msg = client._map_sql_error("syntax error near SELECT")
        assert "SQL syntax error" in msg
        assert "raw:" in msg

    def test_map_sql_error_unknown(self, client):
        """Unknown SQL errors get generic prefix."""
        msg = client._map_sql_error("random database problem")
        assert msg.startswith("Database error:")

    def test_map_sql_error_truncates(self, client):
        """Long error messages are truncated to 300 chars."""
        long_error = "x" * 500
        msg = client._map_sql_error(long_error)
        assert len(msg) < 500


# ── Glob / wildcard memory search ──────────────────────────────


class TestGlobGet:
    """Unit tests for client.glob_get()."""

    @pytest.fixture
    def client(self):
        return Client(host="localhost", port="3001", database="test-db")

    def test_glob_matches_content(self, client: Client):
        """Glob pattern matches memory content field."""
        client._query = lambda *a, **kw: [
            {"id": "a", "content": "hello world"},
            {"id": "b", "content": "goodbye"},
        ]
        results = client.glob_get("ws1", "hello*", field="content")
        assert len(results) == 1
        assert results[0]["id"] == "a"

    def test_glob_case_insensitive(self, client: Client):
        """Case-insensitive matching."""
        client._query = lambda *a, **kw: [
            {"id": "a", "content": "HELLO WORLD"},
        ]
        results = client.glob_get("ws1", "hello*", field="content")
        assert len(results) == 1

    def test_glob_no_matches(self, client: Client):
        """No matches returns empty list."""
        client._query = lambda *a, **kw: [
            {"id": "a", "content": "hello"},
        ]
        results = client.glob_get("ws1", "xyz*", field="content")
        assert results == []

    def test_glob_custom_field(self, client: Client):
        """Match against a custom field (summary)."""
        client._query = lambda *a, **kw: [
            {"id": "a", "content": "stuff", "summary": "Important note"},
            {"id": "b", "content": "stuff", "summary": "random"},
        ]
        results = client.glob_get("ws1", "Important*", field="summary")
        assert len(results) == 1
        assert results[0]["id"] == "a"

    def test_glob_honours_limit(self, client: Client):
        """Honours the limit parameter."""
        client._query = lambda *a, **kw: [
            {"id": f"item{i}", "content": f"item{i}"} for i in range(10)
        ]
        results = client.glob_get("ws1", "item*", field="id", limit=3)
        assert len(results) == 3

    def test_glob_default_field_is_id(self, client: Client):
        """Default field is 'id'."""
        client._query = lambda *a, **kw: [
            {"id": "user-1", "content": "stuff"},
            {"id": "admin-2", "content": "other"},
        ]
        results = client.glob_get("ws1", "user-*")
        assert len(results) == 1
        assert results[0]["id"] == "user-1"


# ── Backup ───────────────────────────────────────────────────────


class TestBackup:
    """Unit tests for client.backup()."""

    @pytest.fixture
    def client(self):
        return Client(host="localhost", port="3001", database="test-db")

    def test_backup_writes_json(self, client: Client):
        """Backup creates a JSON file with table data."""
        import tempfile

        client._query = lambda *a, **kw: [
            {"id": "ws1", "name": "default"},
        ]

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            out_path = tf.name
        try:
            result = client.backup(output_path=out_path)
            assert result["status"] == "ok"
            assert result["path"] == out_path
            assert result["total_rows"] > 0

            with open(out_path) as f:
                data = json.load(f)
            assert data["version"] == "0.3.0"
            assert "tables" in data
        finally:
            import os
            os.unlink(out_path)

    def test_backup_default_path(self, client: Client):
        """Backup with default path uses today's date."""
        import datetime
        client._query = lambda *a, **kw: []

        result = client.backup()
        assert result["status"] == "ok"
        date = datetime.date.today().isoformat()
        assert date in result["path"]
        import os
        os.unlink(result["path"])

    def test_backup_runtime_error_skipped(self, client: Client):
        """Tables that raise RuntimeError are skipped."""
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise RuntimeError("no such table")
            return []

        client._query = side_effect
        result = client.backup(output_path="/tmp/test_backup_skip.json")
        assert result["status"] == "ok"

    def test_backup_plugin_dispatch(self, client: Client):
        """Backup dispatches to plugin_manager if set."""
        client._query = lambda *a, **kw: [
            {"id": "ws1", "name": "default"},
        ]
        pm = Mock()
        client.plugin_manager = pm

        result = client.backup(output_path="/tmp/test_backup_plugin.json")
        assert result["status"] == "ok"
        pm.dispatch_export.assert_called_once()
        import os
        os.unlink(result["path"])


# ── Store with veracity tier ────────────────────────────────────────────


class TestStoreVeracity:
    """store() veracity tier handling (lines 786-791)."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value={"status": "ok"})
        c._embed = Mock(return_value=[])  # empty → skip post-store indexing
        c._emit_event = Mock()
        c._query_cache = None
        c.plugin_manager = None
        return c

    def test_store_with_veracity_tier(self, client):
        """store with veracity_tier='stated' computes compound confidence."""
        result = client.store("ws1", content="hello", veracity_tier="stated", veracity_sources=2)
        assert result["status"] == "ok"
        client._call.assert_called()
        args_list = client._call.call_args[0][1]
        # confidence is index 7 in the reducer args list
        confidence = args_list[7]
        # "stated" tier has base ~0.9, compounded with 2 sources
        assert confidence > 0.8

    def test_store_unknown_tier_skips_compound(self, client):
        """store with veracity_tier='unknown' keeps default confidence."""
        result = client.store("ws1", content="hello", veracity_tier="unknown")
        assert result["status"] == "ok"
        args_list = client._call.call_args[0][1]
        confidence = args_list[7]
        assert confidence == 0.8  # default

    def test_store_invalid_tier_falls_back(self, client):
        """Invalid veracity tier string → ValueError caught, default used."""
        result = client.store("ws1", content="hello", veracity_tier="bogus_tier")
        assert result["status"] == "ok"
        args_list = client._call.call_args[0][1]
        confidence = args_list[7]
        assert confidence == 0.8  # default, ValueError caught


# ── Store with plugin manager ──────────────────────────────────────────


class TestStorePluginDispatch:
    """store() plugin manager dispatch (line 801)."""

    def test_store_dispatches_to_plugin_manager(self):
        """When plugin_manager is set, dispatch_store is called."""
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value={"status": "ok"})
        c._embed = Mock(return_value=[])  # empty → skip post-store indexing
        c._emit_event = Mock()
        c._query_cache = None

        pm = Mock()
        pm.dispatch_store.return_value = ("modified content", {"extra": True})
        c.plugin_manager = pm

        result = c.store("ws1", content="hello")
        assert result["status"] == "ok"
        pm.dispatch_store.assert_called_once()
        assert pm.dispatch_store.call_args[0][0] == "hello"


# ── Batch store response parsing ───────────────────────────────────────


class TestStoreBatchResponse:
    """store_batch() response parsing (lines 973-978)."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value=[{"status": "ok"}])
        c._embed_batch = Mock(return_value=[[0.1] * 1024, [0.2] * 1024])
        c._embed = Mock(return_value=[[0.1] * 1024])
        c._query = Mock(return_value=[])
        c._tantivy_index = Mock()
        c._extract_and_store_entities = Mock()
        c._binary_cache = {}
        c._emit_event = Mock()
        # Mock the entire _http attribute
        c._http = Mock()
        return c

    def test_batch_store_with_embeddings_response(self, client):
        """Batch store parses 'embeddings' key from LLM embedder response."""
        mock_resp = Mock(status_code=200)
        mock_resp.json.return_value = {"embeddings": [[0.1] * 1024, [0.2] * 1024]}
        client._http.post.return_value = mock_resp

        items = [
            {"content": "a", "memory_type": "experience"},
            {"content": "b", "memory_type": "experience"},
        ]
        result = client.store_batch("ws1", items)
        assert isinstance(result, list)

    def test_batch_single_embedding_fallback(self, client):
        """Batch store handles 'embedding' (singular) response key."""
        mock_resp = Mock(status_code=200)
        mock_resp.json.return_value = {"embedding": [0.5] * 1024}
        client._http.post.return_value = mock_resp

        items = [
            {"content": "single", "memory_type": "experience"},
        ]
        result = client.store_batch("ws1", items)
        assert isinstance(result, list)


# ── LLM rerank rate-limit handling ─────────────────────────────────────


class TestLLMRerankRateLimit:
    """llm_rerank() rate-limit retry (lines 3027-3045)."""

    def test_rate_limit_retry_then_success(self):
        """Rate-limited → retries → succeeds."""
        import httpx
        from spacetime_memory.client import llm_rerank

        call_count = [0]

        def mock_post(*args, **kwargs):
            call_count[0] += 1
            resp = Mock(spec=httpx.Response)
            if call_count[0] < 3:
                resp.status_code = 429
                resp.request = Mock()
            else:
                resp.status_code = 200
                resp.json.return_value = {
                    "choices": [{"message": {"content": '[{"index":0,"score":9.0}]'}}]
                }
                resp.request = Mock()
            return resp

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("httpx.post", mock_post)
            mp.setattr("time.sleep", lambda s: None)
            results = llm_rerank(
                "query", [{"id": "a", "content": "x"}], api_key="sk-test"
            )
            assert len(results) >= 1
            assert results[0]["score"] == pytest.approx(0.9)

    def test_rate_limit_exhausted_falls_back(self):
        """All retries rate-limited → falls back to original results."""
        from spacetime_memory.client import llm_rerank

        resp_429 = Mock()
        resp_429.status_code = 429
        resp_429.request = Mock()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("httpx.post", Mock(return_value=resp_429))
            mp.setattr("time.sleep", lambda s: None)
            original = [{"id": "a", "content": "x", "score": 0.5}]
            results = llm_rerank(
                "query", original, api_key="sk-test"
            )
            # Falls back to original results
            assert results == original

    def test_reasoning_model_fallback(self):
        """Reasoning models put output in reasoning_content, not content."""
        import httpx
        from spacetime_memory.client import llm_rerank

        resp = Mock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [{"message": {
                "content": "",
                "reasoning_content": '[{"index":0,"score":8.8}]',
            }}]
        }
        resp.request = Mock()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("httpx.post", Mock(return_value=resp))
            results = llm_rerank(
                "query", [{"id": "r1", "content": "reasoning test"}], api_key="sk-test"
            )
            assert len(results) >= 1
            assert results[0]["score"] == pytest.approx(0.88)
