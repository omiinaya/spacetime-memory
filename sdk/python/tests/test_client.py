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
    """_embed() method — Rust ONNX sidecar."""

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
