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


# ── Batch store indexing loop ──────────────────────────────────────────


class TestStoreBatchIndexing:
    """store_batch() post-indexing loop (lines 998-1009)."""

    def test_batch_store_indexes_each_item(self):
        """When embeddings are available, each item gets indexed."""
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value=[{"status": "ok"}])
        c._embed_batch = Mock(return_value=[[0.1] * 1024, [0.2] * 1024])
        c._embed = Mock(return_value=[[0.1] * 1024])
        c._query = Mock(return_value=[
            {"id": "mem-1", "created_at": 200},
            {"id": "mem-2", "created_at": 100},
        ])
        c._tantivy_index = Mock()
        c._extract_and_store_entities = Mock()
        c._binary_cache = {}
        c._emit_event = Mock()
        c._http = Mock()

        mock_resp = Mock(status_code=200)
        mock_resp.json.return_value = {"embeddings": [[0.1] * 1024, [0.2] * 1024]}
        c._http.post.return_value = mock_resp

        items = [
            {"content": "first item", "memory_type": "experience"},
            {"content": "second", "memory_type": "experience"},
        ]
        result = c.store_batch("ws1", items)
        assert isinstance(result, list)
        # Should have called index_entity and index_terms for each item
        assert c._call.call_count >= 4  # store_memory_batch + 2× index_entity + 2× index_terms


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


# ── Post-store indexing ────────────────────────────────────────────────


class TestStorePostIndexing:
    """store() post-store indexing path (lines 834-856)."""

    def test_store_indexes_entities_when_embedding_available(self):
        """When _embed returns non-empty, post-store indexing runs."""
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value={"status": "ok"})
        c._embed = Mock(return_value=[0.1] * 1024)  # non-empty → triggers indexing
        c._query = Mock(return_value=[
            {"id": "mem-1", "content": "hello world"},
        ])
        c._tantivy_index = Mock()
        c._extract_and_store_entities = Mock()
        c._binary_cache = {}
        c._emit_event = Mock()
        c._query_cache = None
        c.plugin_manager = None

        result = c.store("ws1", content="hello world")
        assert result["status"] == "ok"
        # Verify indexing calls — check actual call args
        calls = [args[0] for args, _ in c._call.call_args_list]
        assert "index_entity" in calls
        assert "index_terms" in calls
        c._tantivy_index.assert_called_once()
        c._extract_and_store_entities.assert_called_once()

    def test_store_with_tier_L0(self):
        """store with tier='L0' triggers update_memory_tier."""
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value={"status": "ok"})
        c._embed = Mock(return_value=[])  # skip indexing
        c._query = Mock(return_value=[{"id": "mem-1"}])
        c._emit_event = Mock()
        c._query_cache = None
        c.plugin_manager = None

        result = c.store("ws1", content="test", peer_id="user1", tier="L0")
        assert result["status"] == "ok"
        c._call.assert_any_call("update_memory_tier", ["mem-1", "L0"])

    def test_store_binary_compression_error_caught(self):
        """Binary compression error in post-store indexing is caught (lines 841-842)."""
        from unittest.mock import patch

        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value={"status": "ok"})
        c._embed = Mock(return_value=[0.1] * 1024)
        c._query = Mock(return_value=[
            {"id": "mem-1", "content": "hello world"},
        ])
        c._tantivy_index = Mock()
        c._extract_and_store_entities = Mock()
        c._binary_cache = {}
        c._emit_event = Mock()
        c._query_cache = None
        c.plugin_manager = None

        with patch("spacetime_memory.binary_vectors.binarize", side_effect=ValueError("bad")):
            result = c.store("ws1", content="hello world")
            assert result["status"] == "ok"  # store still succeeds


# ── Entity extraction ──────────────────────────────────────────────────


class TestExtractAndStoreEntities:
    """_extract_and_store_entities() (lines 878-913)."""

    def test_llm_extraction_with_entities(self):
        """LLM available → extracts and stores entities."""
        from unittest.mock import patch

        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()

        mock_llm = Mock()
        mock_llm.available = True
        mock_llm.extract_entities_llm.return_value = [
            {"name": "Alice", "entity_type": "person", "aliases": ["Al"], "description": "A person"},
            {"name": "Bob", "entity_type": "person", "aliases": [], "description": "Another"},
        ]

        with patch("spacetime_memory.llm.LLMClient", return_value=mock_llm):
            c._extract_and_store_entities("ws1", "mem-1", "Alice and Bob met")

        # create_entity_link should be called for each entity
        assert c._call.call_count >= 2

    def test_regex_fallback_when_llm_unavailable(self):
        """LLM unavailable → falls back to regex extraction reducer."""
        from unittest.mock import patch

        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()

        mock_llm = Mock()
        mock_llm.available = False

        with patch("spacetime_memory.llm.LLMClient", return_value=mock_llm):
            c._extract_and_store_entities("ws1", "mem-1", "some content")

        c._call.assert_called_with("extract_entities", ["ws1", "some content"])

    def test_entity_link_error_caught(self):
        """RuntimeError in create_entity_link is caught, not propagated."""
        from unittest.mock import patch

        c = Client(host="localhost", port="3001", database="test-db")
        # First call fails, others succeed
        c._call = Mock(side_effect=[RuntimeError("fail"), None, None])

        mock_llm = Mock()
        mock_llm.available = True
        mock_llm.extract_entities_llm.return_value = [
            {"name": "Bad", "entity_type": "concept"},
        ]

        with patch("spacetime_memory.llm.LLMClient", return_value=mock_llm):
            c._extract_and_store_entities("ws1", "mem-1", "Bad entity")

        # Should have tried create_entity_link (failed) and link_entity_to_memory
        assert c._call.call_count >= 2

    def test_link_entity_error_caught(self):
        """RuntimeError in link_entity_to_memory is caught (lines 906-907)."""
        from unittest.mock import patch

        c = Client(host="localhost", port="3001", database="test-db")
        # create_entity_link succeeds, link_entity_to_memory fails
        c._call = Mock(side_effect=[{"status": "ok"}, RuntimeError("link fail")])

        mock_llm = Mock()
        mock_llm.available = True
        mock_llm.extract_entities_llm.return_value = [
            {"name": "Entity", "entity_type": "concept"},
        ]

        with patch("spacetime_memory.llm.LLMClient", return_value=mock_llm):
            c._extract_and_store_entities("ws1", "mem-1", "Entity content")

        assert c._call.call_count == 2  # both called

    def test_regex_fallback_error_caught(self):
        """RuntimeError in extract_entities fallback is caught (lines 912-913)."""
        from unittest.mock import patch

        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(side_effect=RuntimeError("extract fail"))

        mock_llm = Mock()
        mock_llm.available = False  # triggers fallback

        with patch("spacetime_memory.llm.LLMClient", return_value=mock_llm):
            c._extract_and_store_entities("ws1", "mem-1", "content")

        # Called extract_entities (which failed) but no exception propagated
        c._call.assert_called_once_with("extract_entities", ["ws1", "content"])


# ── Entity extraction edge cases ───────────────────────────────────────


class TestExtractEntitiesSkip:
    """Entity extraction skips invalid names."""

    def test_skips_short_names(self):
        """Names <2 chars are skipped."""
        from unittest.mock import patch

        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()

        mock_llm = Mock()
        mock_llm.available = True
        mock_llm.extract_entities_llm.return_value = [
            {"name": "A", "entity_type": "letter"},  # too short
            {"name": "OK", "entity_type": "word"},   # ok
        ]

        with patch("spacetime_memory.llm.LLMClient", return_value=mock_llm):
            c._extract_and_store_entities("ws1", "mem-1", "A and OK")

        # Only "OK" should trigger a call
        # create_entity_link for OK + link_entity_to_memory for OK = 2 calls
        assert c._call.call_count == 2

    def test_skips_empty_names(self):
        """Empty names are skipped."""
        from unittest.mock import patch

        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()

        mock_llm = Mock()
        mock_llm.available = True
        mock_llm.extract_entities_llm.return_value = [
            {"name": "", "entity_type": "empty"},
            {"name": None, "entity_type": "none"},
        ]

        with patch("spacetime_memory.llm.LLMClient", return_value=mock_llm):
            c._extract_and_store_entities("ws1", "mem-1", "nothing useful")

        assert c._call.call_count == 0  # all skipped


# ── Graph traversal ────────────────────────────────────────────────────


class TestGraphTraversal:
    """Graph traversal methods (lines 2573-2583)."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        return c

    def test_graph_bfs(self, client):
        client.graph_bfs("ws1", "node-1", max_depth=3)
        client._call.assert_called_with("graph_bfs", ["ws1", "node-1", 3])

    def test_shortest_path(self, client):
        client.shortest_path("ws1", "src", "tgt", max_hops=4)
        client._call.assert_called_with("shortest_path", ["ws1", "src", "tgt", 4])

    def test_get_neighbors_via_reducer(self, client):
        client.get_neighbors_via_reducer("ws1", "node-1")
        client._call.assert_called_with("get_neighbors", ["ws1", "node-1"])


# ── Pattern detection ──────────────────────────────────────────────────


class TestPatternDetection:
    """detect_memory_patterns() (lines 1432-1440)."""

    def test_detects_patterns(self):
        from unittest.mock import patch

        c = Client(host="localhost", port="3001", database="test-db")
        c._query = Mock(return_value=[
            {"id": "1", "content": "a"},
            {"id": "2", "content": "b"},
        ])

        mock_detect = Mock(return_value={"patterns": [], "clusters": []})
        with patch("spacetime_memory.pattern_detection.detect_patterns", mock_detect):
            result = c.detect_patterns("ws1", limit=10)
            mock_detect.assert_called_once()
            assert isinstance(result, dict)


# ── Batch update memories ──────────────────────────────────────────────


class TestBatchUpdateMemoriesSuccess:
    """batch_update_memories() success path (lines 1758-1769)."""

    def test_batch_update_success(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._query = Mock(return_value=[
            {"id": "m1", "content": "old", "summary": "s", "confidence": 0.5},
        ])
        c.update_memory = Mock(return_value={"status": "ok"})

        result = c.batch_update_memories("ws1", ["m1"], {"content": "new"})
        c.update_memory.assert_called_once_with("m1", "new", "s", 0.5)
        assert result["status"] == "ok"

    def test_batch_update_missing_memory(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._query = Mock(return_value=[])  # memory not found
        c.update_memory = Mock()

        result = c.batch_update_memories("ws1", ["missing"], {"content": "new"})
        c.update_memory.assert_not_called()
        assert result["status"] == "partial"
        assert "not found" in result["errors"][0]

    def test_batch_update_exception(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._query = Mock(side_effect=RuntimeError("boom"))

        result = c.batch_update_memories("ws1", ["m1"], {"content": "new"})
        assert result["status"] == "partial"
        assert result["errors"]


# ── Profile stubs ──────────────────────────────────────────────────────


class TestProfileStubs:
    """Simple profile delegation methods (lines 2294, 2298, 2320-2328)."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        return c

    def test_add_profile_fact(self, client):
        client.add_profile_fact("peer-1", "likes coffee")
        client._call.assert_called_with("add_profile_fact", ["peer-1", "likes coffee"])

    def test_add_dynamic_context(self, client):
        client.add_dynamic_context("peer-1", "just woke up")
        client._call.assert_called_with("add_dynamic_context", ["peer-1", "just woke up"])

    def test_search_profiles(self, client):
        """search_profiles filters client-side by static_facts_json."""
        client.list_profiles = Mock(return_value=[
            {"peer_id": "p1", "static_facts_json": "likes coffee"},
            {"peer_id": "p2", "static_facts_json": "prefers tea"},
        ])
        results = client.search_profiles("ws1", "coffee")
        assert len(results) == 1
        assert results[0]["peer_id"] == "p1"


# ── Tour stubs ─────────────────────────────────────────────────────────


class TestTourStubs:
    """Simple tour delegation methods (lines 2591, 2595, 2599)."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        return c

    def test_create_tour(self, client):
        client.create_tour("ws1", "My Tour", "A nice tour")
        client._call.assert_called_with("create_tour", ["ws1", "My Tour", "A nice tour"])

    def test_add_tour_stop(self, client):
        client.add_tour_stop("tour-1", "node-1", "Stop 1", "desc")
        client._call.assert_called_with("add_tour_stop", ["tour-1", "node-1", "Stop 1", "desc"])

    def test_delete_tour(self, client):
        client.delete_tour("tour-1")
        client._call.assert_called_with("delete_tour", ["tour-1"])


# ── Entity link stubs ──────────────────────────────────────────────────


class TestEntityLinkStubs:
    """Simple entity-link delegation methods (lines 2613, 2619, 2623)."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        return c

    def test_create_entity_link(self, client):
        client.create_entity_link("ws1", "Alice", "person", "Alice in Wonderland")
        client._call.assert_called_with("create_entity_link", [
            "ws1", "Alice", "[]", "person", "Alice in Wonderland",
        ])

    def test_add_alias(self, client):
        client.add_alias("link-1", "Alias")
        client._call.assert_called_with("add_alias", ["link-1", "Alias"])

    def test_resolve_entity(self, client):
        client.resolve_entity("ws1", "Alice")
        client._call.assert_called_with("resolve_entity", ["ws1", "Alice"])


# ── get_context_chain ──────────────────────────────────────────────────


class TestGetContextChain:
    """get_context_chain() method (lines 1615-1632)."""

    def test_returns_context(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._query = Mock(side_effect=[
            [{"id": "mem-1", "workspace_id": "ws1", "context": "mem context"}],
            [{"id": "ws1", "context": "ws context"}],
        ])
        result = c.get_context_chain("mem-1")
        assert result["memory_context"] == "mem context"
        assert result["workspace_context"] == "ws context"

    def test_memory_not_found_returns_empty(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._query = Mock(return_value=[])
        result = c.get_context_chain("nonexistent")
        assert result["workspace_context"] == ""
        assert result["memory_context"] == ""

    def test_no_workspace_context(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._query = Mock(side_effect=[
            [{"id": "mem-1", "workspace_id": "ws1", "context": "mem ctx"}],
            [],  # workspace lookup returns empty
        ])
        result = c.get_context_chain("mem-1")
        assert result["memory_context"] == "mem ctx"
        assert result["workspace_context"] == ""


# ── _whoami ────────────────────────────────────────────────────────────


class TestWhoami:
    """_whoami() method (line 266)."""

    def test_returns_identity_header(self):
        c = Client(host="localhost", port="3001", database="test-db")
        mock_resp = Mock()
        mock_resp.headers.get.return_value = "c200abc123"
        c._ensure_identity = Mock()
        c._http.get = Mock(return_value=mock_resp)
        c._headers = Mock(return_value={})

        ident = c._whoami()
        assert ident == "c200abc123"
        c._http.get.assert_called_once()


# ── Remaining stubs ────────────────────────────────────────────────────


class TestMethodStubs:
    """Remaining delegation stubs (<10 lines each)."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._sql = Mock(return_value=[])
        return c

    def test_get_citations(self, client):
        client.get_citations("ws1", "entity-1", "concept")
        client._call.assert_called_with("get_citations", ["ws1", "entity-1", "concept"])
        client._sql.assert_called_once()

    def test_add_node_citation(self, client):
        client.add_node_citation("ws1", "node-1", "mem-1", "citation desc")
        client._call.assert_called_with("add_node_citation", ["ws1", "node-1", "mem-1", "citation desc"])

    def test_add_edge_citation(self, client):
        client.add_edge_citation("ws1", "src", "tgt", "desc")
        client._call.assert_called_with("add_edge_citation", ["ws1", "src", "tgt", "desc"])

    def test_create_document(self, client):
        client.create_document("ws1", "title", "content", "md", "/path", "url", {"key": "val"})
        client._call.assert_called()

    def test_detect_communities(self, client):
        client.detect_communities("ws1")
        client._call.assert_called_with("detect_communities", ["ws1"])

    def test_seed_communities(self, client):
        client.seed_communities("ws1")
        client._call.assert_called_with("seed_communities", ["ws1"])

    def test_get_edges_with_labels(self, client):
        """get_neighbors resolves node IDs to labels."""
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value=[
            {"source_node_id": "n1", "target_node_id": "n2", "weight": 1.0},
        ])
        # _query side-effect: edges_src, edges_tgt, then node resolutions
        calls = []
        def mock_query(*args, **kw):
            calls.append((args, kw))
            if "source_node_id" in str(kw.get("filter_dict", {})):
                return [{"id": "e1", "source_node_id": "n1", "target_node_id": "n2", "weight": 1.0}]
            if "target_node_id" in str(kw.get("filter_dict", {})):
                return []
            # Node ID resolution — return both labels
            filt = kw.get("filter_dict", {})
            nid = filt.get("id", "")
            return [{"id": nid, "label": f"Label-{nid}"}]
        c._query = mock_query

        edges = c.get_neighbors("n1", "ws1")
        assert len(edges) == 1
        assert edges[0]["source_label"] == "Label-n1"
        assert edges[0]["target_label"] == "Label-n2"

    def test_run_maintenance(self, client):
        client.run_maintenance()
        client._call.assert_called_with("manual_maintenance", [])

    def test_dedup(self, client):
        client.dedup("ws1")
        client._call.assert_called_with("dedup_memories", ["ws1"])

    def test_suggest_merges(self, client):
        client.suggest_merges("ws1", 0.85)
        client._call.assert_called_with("suggest_merges", ["ws1", 0.85])

    def test_get_profile_context(self, client):
        """get_profile_context calls the reducer and reads the result table."""
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._sql = Mock(return_value=[{"peer_id": "p1", "context": "profile data"}])
        result = c.get_profile_context("p1")
        c._call.assert_called_with("get_profile_context", ["p1"])
        assert result["context"] == "profile data"

    def test_get_profile_context_empty(self, client):
        """get_profile_context returns None when no rows."""
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._sql = Mock(return_value=[])
        result = c.get_profile_context("unknown")
        assert result is None


# ── More stubs ─────────────────────────────────────────────────────────


class TestMoreStubs:
    """Remaining one-liner stubs."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])
        return c

    def test_list_memories(self, client):
        client.list_memories("ws1", memory_type="experience")
        client._query.assert_called()

    def test_list_memories_no_filter(self, client):
        client.list_memories("ws1")
        client._query.assert_called()

    def test_set_decay_model_raises_on_bad_model(self):
        c = Client(host="localhost", port="3001", database="test-db")
        with pytest.raises(ValueError, match="model"):
            c.set_decay_model("ws1", "bad_model")

    def test_set_decay_model_linear(self, client):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value={"status": "ok"})
        result = c.set_decay_model("ws1", "linear")
        assert result["status"] == "ok"

    def test_set_decay_model_weibull(self, client):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock(return_value={"status": "ok"})
        result = c.set_decay_model("ws1", "weibull", weibull_shape=0.8, weibull_scale=25.0)
        assert result["status"] == "ok"

    def test_approve_merge(self, client):
        client.approve_merge("sug-1")
        client._call.assert_called_with("approve_merge", ["sug-1"])

    def test_reject_merge(self, client):
        client.reject_merge("sug-1")
        client._call.assert_called_with("reject_merge", ["sug-1"])

    def test_get_node(self, client):
        client.get_node("node-1")
        client._query.assert_called_with("kg_node", filter_dict={"id": "node-1"})

    def test_get_community(self, client):
        client.get_community(42)
        client._query.assert_any_call("kg_community", filter_dict={"id": "42"})
        client._query.assert_any_call("kg_node", filter_dict={"community_id": "42"})


# ── Note CRUD ──────────────────────────────────────────────────────────


class TestNoteCrudStubs:
    """Note CRUD methods (lines 2525, 2531-2548)."""

    @pytest.fixture
    def client(self):
        c = Client(host="localhost", port="3001", database="test-db")
        c._call = Mock()
        c._query = Mock(return_value=[])
        return c

    def test_delete_note(self, client):
        client.delete_note("note-1")
        client._call.assert_called_with("delete_note", ["note-1"])

    def test_list_notes(self, client):
        client.list_notes("ws1")
        client._query.assert_called()

    def test_list_notes_include_inactive(self, client):
        c = Client(host="localhost", port="3001", database="test-db")
        c._query = Mock(return_value=[])
        c.list_notes("ws1", include_inactive=True)
        c._query.assert_called()

    def test_get_note(self, client):
        client.get_note("note-1")
        client._query.assert_called_with("note", filter_dict={"id": "note-1"})

    def test_get_note_by_date(self, client):
        client.get_note_by_date("2026-06-22")
        client._query.assert_called_with("note", filter_dict={
            "note_date": "2026-06-22", "is_active": "true"})

    def test_get_note_by_title(self, client):
        client.get_note_by_title("My Note")
        client._query.assert_called_with("note", filter_dict={
            "title": "My Note", "is_active": "true"})


# ── Multi-region / Failover ────────────────────────────────────────────


class TestMultiRegionFailover:
    """Fallback between multiple STDB hosts."""

    def test_init_single_host_default(self):
        """Client._hosts defaults to [host:port] when SPACETIMEDB_HOSTS is unset."""
        c = Client(host="myhost", port="3001", database="test-db")
        assert c._hosts == ["myhost:3001"]
        assert c.host == "myhost"
        assert c.port == "3001"
        assert c.sql_url == "http://myhost:3001/v1/database/test-db/sql"

    def test_init_multi_hosts_from_env(self, monkeypatch):
        """Client parses SPACETIMEDB_HOSTS into _hosts list."""
        monkeypatch.setenv("SPACETIMEDB_HOSTS", "host1:3001,host2:4000,host3:5000")
        c = Client(database="test-db")
        assert c._hosts == ["host1:3001", "host2:4000", "host3:5000"]
        assert c.host == "host1"
        assert c.port == "3001"

    def test_try_failover_noop_when_single_host(self):
        """_try_failover returns False when only one host is configured."""
        c = Client(host="h", port="1", database="d")
        assert c._try_failover() is False
        assert c.host == "h"

    def test_try_failover_switches_host(self):
        """_try_failover switches to next host in the list."""
        c = Client(host="host1", port="3001", database="test-db")
        c._hosts = ["host1:3001", "host2:4000"]
        c._current_host_index = 0

        assert c._try_failover() is True
        assert c.host == "host2"
        assert c.port == "4000"
        assert c._current_host_index == 1
        # URL rebuild
        assert "host2" in c.sql_url
        assert "4000" in c.reducer_url
        # Circuit breaker reset
        assert c._consecutive_failures == 0
        assert c._circuit_open_until == 0.0

    def test_request_with_retry_failover_on_connect_error(self, monkeypatch):
        """_request_with_retry fails over to next host on ConnectError."""
        monkeypatch.setenv("SPACETIMEDB_HOSTS", "host1:3001,host2:3001")
        monkeypatch.setenv("STMEM_MAX_RETRIES", "1")  # Min retries to speed test
        c = Client(database="test-db")
        # Track which host each call targets
        call_history: list[str] = []

        def mock_post(url, **kw):
            call_history.append(url[:30])  # Just host prefix
            if "host1" in url:
                raise httpx.ConnectError("Connection refused to host1")
            return Mock(status_code=200, text=json.dumps([]))

        c._http.post = mock_post
        c._http.get = Mock(return_value=Mock(status_code=200, headers={}))

        # This should succeed via failover to host2
        resp = c._request_with_retry("POST", c.sql_url, content="test")
        assert resp.status_code == 200
        # Should have switched to host2
        assert c.host == "host2"
        # First calls went to host1, final call to host2
        assert any("host2" in url for url in call_history)

    def test_ensure_identity_tries_all_hosts(self, monkeypatch):
        """_ensure_identity tries all hosts, pins to first responsive one."""
        monkeypatch.setenv("SPACETIMEDB_HOSTS", "dead:3001,alive:4000")
        c = Client(database="test-db")
        c._identity_established = False
        c._identity_token = None

        call_log = []

        def mock_get(url, **kw):
            call_log.append(url)
            if "dead" in url:
                raise httpx.ConnectError("dead host")
            return Mock(status_code=200, headers={
                "spacetime-identity-token": "tok123",
            })

        c._http.get = mock_get

        c._ensure_identity()
        assert c._identity_established is True
        assert c._identity_token == "tok123"
        # Pinned to second host
        assert c.host == "alive"
        assert c.port == "4000"
        assert c._current_host_index == 1
