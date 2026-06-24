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
