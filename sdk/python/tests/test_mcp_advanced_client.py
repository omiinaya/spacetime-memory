"""Tests for MCP tools — split from test_mcp_advanced.py."""

import pytest

pytest.skip("requires MCP server runtime (server/mcp/)", allow_module_level=True)

# ── TestRequireApiKeyAsync ────────────────────────────────────────────────────────

class TestRequireApiKeyAsync:
    """Tests for the async wrapper of require_api_key."""

    def test_no_key_set_passes_through(self, monkeypatch):
        """When MCP_API_KEY is empty, decorator passes through without auth."""
        import asyncio

        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "")

        from server.mcp.main import require_api_key

        async def sample_fn(arg1: str) -> str:
            return f"result: {arg1}"

        wrapped = require_api_key(sample_fn)
        result = asyncio.run(wrapped("hello"))
        assert result == "result: hello"

    def test_with_valid_bearer_token_via_args(self, monkeypatch):
        """MCP_API_KEY set + valid Bearer token in args context passes."""
        import asyncio
        from unittest.mock import MagicMock

        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key-123")

        from server.mcp.main import require_api_key

        async def sample_fn(ctx, arg1: str) -> str:
            return f"ok: {arg1}"

        wrapped = require_api_key(sample_fn)
        ctx = MagicMock()
        ctx.request = MagicMock()
        ctx.request.headers = {"authorization": "Bearer test-key-123"}

        result = asyncio.run(wrapped(ctx, "hello"))
        assert result == "ok: hello"

    def test_with_invalid_bearer_token_via_args(self, monkeypatch):
        """MCP_API_KEY set + invalid Bearer token raises PermissionError."""
        import asyncio
        from unittest.mock import MagicMock

        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key-123")

        from server.mcp.main import require_api_key

        async def sample_fn(ctx, arg1: str) -> str:
            return f"ok: {arg1}"

        wrapped = require_api_key(sample_fn)
        ctx = MagicMock()
        ctx.request = MagicMock()
        ctx.request.headers = {"authorization": "Bearer wrong-key"}

        import pytest
        with pytest.raises(PermissionError, match="Unauthorized"):
            asyncio.run(wrapped(ctx, "hello"))

    def test_with_no_request_context_stdio(self, monkeypatch):
        """MCP_API_KEY set but no request context (stdio) passes through."""
        import asyncio

        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key-123")

        from server.mcp.main import require_api_key

        async def sample_fn() -> str:
            return "stdio result"

        wrapped = require_api_key(sample_fn)
        result = asyncio.run(wrapped())
        assert result == "stdio result"

    def test_with_context_via_kwargs(self, monkeypatch):
        """MCP_API_KEY set + context via kwargs (ctx=...) passes."""
        import asyncio
        from unittest.mock import MagicMock

        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key-456")

        from server.mcp.main import require_api_key

        async def sample_fn(ctx) -> str:
            return "ok via kwargs"

        wrapped = require_api_key(sample_fn)
        ctx = MagicMock()
        ctx.request = MagicMock()
        ctx.request.headers = {"authorization": "Bearer test-key-456"}

        result = asyncio.run(wrapped(ctx=ctx))
        assert result == "ok via kwargs"

    def test_with_async_function_detection(self, monkeypatch):
        """require_api_key returns the async_wrapper for coroutine functions."""
        import asyncio

        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "")

        from server.mcp.main import require_api_key

        async def async_fn() -> str:
            return "async"

        wrapped = require_api_key(async_fn)
        result = asyncio.run(wrapped())
        assert result == "async"



# ── TestGetClient ────────────────────────────────────────────────────────

class TestGetClient:
    """Tests for the get_client() singleton."""

    def test_first_call_creates_client(self, monkeypatch):
        """First call to get_client should create a Client."""
        monkeypatch.setattr("server.mcp.main._client", None)
        from server.mcp.main import get_client

        client = get_client()
        from spacetime_memory import Client

        assert isinstance(client, Client)

    def test_second_call_returns_cached(self, monkeypatch):
        """Second call returns cached client (same object)."""
        monkeypatch.setattr("server.mcp.main._client", None)
        from server.mcp.main import get_client

        c1 = get_client()
        c2 = get_client()
        assert c1 is c2

    def test_get_client_global_reset(self, monkeypatch):
        """After resetting _client to None, get_client creates new instance."""
        monkeypatch.setattr("server.mcp.main._client", None)
        from server.mcp.main import get_client

        c1 = get_client()
        monkeypatch.setattr("server.mcp.main._client", None)
        c2 = get_client()
        assert c1 is not c2


# ── _embed / _embed_batch ─────────────────────────────────────────────────



# ── TestEmbed ────────────────────────────────────────────────────────

class TestEmbed:
    """Tests for _embed and _embed_batch convenience wrappers."""

    def test_embed_calls_client(self, mock_mcp_client):
        from server.mcp.main import _embed

        mock_mcp_client._embed.return_value = [0.1, 0.2, 0.3]
        result = _embed("hello world")
        assert result == [0.1, 0.2, 0.3]
        mock_mcp_client._embed.assert_called_once_with("hello world")

    def test_embed_batch_calls_client(self, mock_mcp_client):
        from server.mcp.main import _embed_batch

        mock_mcp_client._embed_batch.return_value = [[0.1], [0.2]]
        result = _embed_batch(["text1", "text2"])
        assert result == [[0.1], [0.2]]
        mock_mcp_client._embed_batch.assert_called_once_with(["text1", "text2"])

    def test_embed_empty_string(self, mock_mcp_client):
        from server.mcp.main import _embed

        mock_mcp_client._embed.return_value = []
        result = _embed("")
        assert result == []

    def test_embed_batch_empty_list(self, mock_mcp_client):
        from server.mcp.main import _embed_batch

        mock_mcp_client._embed_batch.return_value = []
        result = _embed_batch([])
        assert result == []


# ── Workspace tools ───────────────────────────────────────────────────────



# ── TestGetClientSingleton ────────────────────────────────────────────────────────

class TestGetClientSingleton:
    """Tests for the get_client() singleton."""

    def teardown_method(self):
        """Reset the global _client between tests."""
        import server.mcp.main as mcp_main

        mcp_main._client = None

    def test_creates_client_on_first_call(self):
        from server.mcp.main import get_client

        client = get_client()
        assert client is not None
        assert client.host == "localhost"

    def test_returns_cached_client(self):
        from server.mcp.main import get_client

        c1 = get_client()
        c2 = get_client()
        assert c1 is c2

    def test_client_has_expected_attrs(self):
        from server.mcp.main import get_client

        client = get_client()
        assert hasattr(client, "store")
        assert hasattr(client, "search")
        assert hasattr(client, "_call")

    def test_teardown_resets(self):
        import server.mcp.main as mcp_main

        mcp_main._client = "fake"
        from server.mcp.main import get_client

        c1 = get_client()
        mcp_main._client = None
        c2 = get_client()
        assert c1 is not c2


# ── _embed and _embed_batch ─────────────────────────────────────────────────



# ── TestEmbedHelpers ────────────────────────────────────────────────────────

class TestEmbedHelpers:
    """Tests for the _embed and _embed_batch convenience functions."""

    def test_embed_calls_client(self, mock_mcp_client):
        from server.mcp.main import _embed

        mock_mcp_client._embed.return_value = [0.1, 0.2, 0.3]
        result = _embed("test text")
        assert result == [0.1, 0.2, 0.3]
        mock_mcp_client._embed.assert_called_once_with("test text")

    def test_embed_batch_calls_client(self, mock_mcp_client):
        from server.mcp.main import _embed_batch

        mock_mcp_client._embed_batch.return_value = [[0.1], [0.2]]
        result = _embed_batch(["a", "b"])
        assert result == [[0.1], [0.2]]
        mock_mcp_client._embed_batch.assert_called_once_with(["a", "b"])


# ── create_workspace (uses get_client directly) ────────────────────────────



