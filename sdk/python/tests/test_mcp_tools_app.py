"""Tests for server/mcp/tools/app.py — shared MCP server state.

Covers ``get_client``, ``require_api_key``, ``_embed``, and ``_embed_batch``.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestGetClient:
    """Tests for the ``get_client`` singleton factory."""

    def _reset_cache(self):
        """Reset the module-level ``_client`` cache."""
        import server.mcp.tools.app as app_mod

        app_mod._client = None

    @patch("server.mcp.tools.app.Client")
    def test_get_client_creates_new_client(self, mock_client_class):
        """get_client() creates a new Client instance on first call."""
        self._reset_cache()

        from server.mcp.tools.app import get_client

        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        result = get_client()

        mock_client_class.assert_called_once()
        assert result is mock_instance

    @patch("server.mcp.tools.app.Client")
    def test_get_client_caches_and_reuses_client(self, mock_client_class):
        """get_client() returns the same Client instance on repeated calls."""
        self._reset_cache()

        from server.mcp.tools.app import get_client

        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        first = get_client()
        second = get_client()

        mock_client_class.assert_called_once()  # only created once
        assert first is second
        assert first is mock_instance

    @patch("server.mcp.tools.app.Client")
    def test_get_client_passes_config_from_env(self, mock_client_class):
        """get_client() passes module-level config to the Client constructor."""
        self._reset_cache()

        from server.mcp.tools.app import (
            DB,
            EMBEDDER_URL,
            HOST,
            PORT,
            TANTIVY_URL,
            get_client,
        )

        mock_client_class.return_value = MagicMock()

        get_client()

        mock_client_class.assert_called_once_with(
            host=HOST,
            port=PORT,
            database=DB,
            embedder_url=EMBEDDER_URL,
            tantivy_url=TANTIVY_URL,
        )

    @patch("server.mcp.tools.app.Client")
    def test_get_client_cache_hit_returns_same_instance(self, mock_client_class):
        """get_client() returns same instance when _client is already set."""
        import server.mcp.tools.app as app_mod

        # Pre-set the cache directly
        cached = MagicMock(spec=object)
        app_mod._client = cached

        from server.mcp.tools.app import get_client

        result = get_client()
        mock_client_class.assert_not_called()  # constructor NOT called
        assert result is cached

    @patch("server.mcp.tools.app.Client")
    def test_get_client_raises_on_constructor_failure(self, mock_client_class):
        """get_client() propagates exception when Client constructor fails."""
        self._reset_cache()

        from server.mcp.tools.app import get_client

        mock_client_class.side_effect = ConnectionError("Cannot connect")

        with pytest.raises(ConnectionError, match="Cannot connect"):
            get_client()

        mock_client_class.assert_called_once()
        # Cache should still be None after failure
        import server.mcp.tools.app as app_mod

        assert app_mod._client is None

    @patch("server.mcp.tools.app.Client")
    def test_get_client_resets_cache_after_failure(self, mock_client_class):
        """get_client() allows retry after a construction failure."""
        self._reset_cache()

        from server.mcp.tools.app import get_client

        # First call fails
        mock_client_class.side_effect = RuntimeError("First fail")
        with pytest.raises(RuntimeError):
            get_client()

        # Second call succeeds
        mock_instance = MagicMock()
        mock_client_class.side_effect = None
        mock_client_class.return_value = mock_instance

        result = get_client()
        assert result is mock_instance
        assert mock_client_class.call_count == 2


@pytest.mark.unit
class TestRequireApiKey:
    """Tests for the ``require_api_key`` decorator."""

    @pytest.fixture(autouse=True)
    def _ensure_no_key(self):
        """Ensure MCP_API_KEY is empty before each test in this class."""
        import server.mcp.tools.app as app_mod

        app_mod.MCP_API_KEY = ""
        yield

    def test_passthrough_when_no_key_configured(self):
        """Decorator passes through when MCP_API_KEY is empty."""
        from server.mcp.tools.app import require_api_key

        mock_func = MagicMock(return_value="ok")
        decorated = require_api_key(mock_func)

        result = decorated("arg1", kwarg="val")

        mock_func.assert_called_once_with("arg1", kwarg="val")
        assert result == "ok"

    def test_passthrough_when_no_request_context(self):
        """Decorator passes through when no request object is found in args."""
        import server.mcp.tools.app as app_mod

        app_mod.MCP_API_KEY = "test-key-123"

        from server.mcp.tools.app import require_api_key

        mock_func = MagicMock(return_value="ok")
        decorated = require_api_key(mock_func)

        result = decorated("plain_arg")

        mock_func.assert_called_once_with("plain_arg")
        assert result == "ok"

    def test_passthrough_on_context_with_valid_auth(self):
        """Decorator passes through when Authorization header matches."""
        import server.mcp.tools.app as app_mod

        app_mod.MCP_API_KEY = "secret"

        from server.mcp.tools.app import require_api_key

        # Simulate a FastMCP context object with a request that has valid auth
        mock_req = MagicMock()
        mock_req.headers = {"authorization": "Bearer secret"}

        mock_ctx = MagicMock()
        mock_ctx.request = mock_req

        mock_func = MagicMock(return_value="ok")
        decorated = require_api_key(mock_func)

        result = decorated(mock_ctx)

        mock_func.assert_called_once_with(mock_ctx)
        assert result == "ok"

    def test_raises_on_context_with_invalid_auth(self):
        """Decorator raises PermissionError when Authorization header is wrong."""
        import server.mcp.tools.app as app_mod

        app_mod.MCP_API_KEY = "secret"

        from server.mcp.tools.app import require_api_key

        mock_req = MagicMock()
        mock_req.headers = {"authorization": "Bearer wrong-key"}

        mock_ctx = MagicMock()
        mock_ctx.request = mock_req

        mock_func = MagicMock(return_value="ok")
        decorated = require_api_key(mock_func)

        with pytest.raises(PermissionError, match="Unauthorized"):
            decorated(mock_ctx)

        mock_func.assert_not_called()

    def test_extracts_auth_from_kwargs_context(self):
        """Decorator checks kwargs for context-like names (ctx, context, request)."""
        import server.mcp.tools.app as app_mod

        app_mod.MCP_API_KEY = "mykey"

        from server.mcp.tools.app import require_api_key

        mock_req = MagicMock()
        mock_req.headers = {"authorization": "Bearer mykey"}

        mock_ctx = MagicMock()
        mock_ctx.request = mock_req

        mock_func = MagicMock(return_value="ok")
        decorated = require_api_key(mock_func)

        result = decorated(other_arg=42, ctx=mock_ctx)

        mock_func.assert_called_once_with(other_arg=42, ctx=mock_ctx)
        assert result == "ok"

    def test_missing_auth_header_on_requests(self):
        """Decorator raises when request context exists but no auth header is set."""
        import server.mcp.tools.app as app_mod

        app_mod.MCP_API_KEY = "mykey"

        from server.mcp.tools.app import require_api_key

        # Request has no authorization header at all
        mock_req = MagicMock()
        mock_req.headers = {}

        mock_ctx = MagicMock()
        mock_ctx.request = mock_req

        mock_func = MagicMock(return_value="ok")
        decorated = require_api_key(mock_func)

        with pytest.raises(PermissionError, match="Unauthorized"):
            decorated(mock_ctx)

        mock_func.assert_not_called()

    def test_scope_based_headers_fallback(self):
        """Decorator falls back to 'scope' dict when request has no 'headers' attr."""
        import server.mcp.tools.app as app_mod

        app_mod.MCP_API_KEY = "mykey"

        from server.mcp.tools.app import require_api_key

        # Request has scope instead of headers (Starlette/ASGI style)
        mock_req = MagicMock()
        # Remove headers attr to force scope fallback
        del mock_req.headers
        mock_req.scope = {"authorization": "Bearer mykey"}

        mock_ctx = MagicMock()
        mock_ctx.request = mock_req

        mock_func = MagicMock(return_value="ok")
        decorated = require_api_key(mock_func)

        result = decorated(mock_ctx)

        mock_func.assert_called_once_with(mock_ctx)
        assert result == "ok"

    def test_case_insensitive_header_lookup(self):
        """Decorator checks both 'authorization' and 'Authorization' keys."""
        import server.mcp.tools.app as app_mod

        app_mod.MCP_API_KEY = "mykey"

        from server.mcp.tools.app import require_api_key

        # Capitalized key
        mock_req = MagicMock()
        mock_req.headers = {"Authorization": "Bearer mykey"}

        mock_ctx = MagicMock()
        mock_ctx.request = mock_req

        mock_func = MagicMock(return_value="ok")
        decorated = require_api_key(mock_func)

        result = decorated(mock_ctx)

        mock_func.assert_called_once_with(mock_ctx)
        assert result == "ok"

    def test_async_function_wrapper(self):
        """Decorator returns async wrapper for coroutine functions."""
        import asyncio

        import server.mcp.tools.app as app_mod

        app_mod.MCP_API_KEY = ""

        from server.mcp.tools.app import require_api_key

        async def async_func(*args, **kwargs):
            return "async-result"

        decorated = require_api_key(async_func)

        # Should be a coroutine function wrapper
        assert asyncio.iscoroutinefunction(decorated)

        result = asyncio.run(decorated())
        assert result == "async-result"


@pytest.mark.unit
class TestEmbedHelpers:
    """Tests for the _embed and _embed_batch helper functions."""

    @patch("server.mcp.tools.app.get_client")
    def test_embed_calls_client_embed(self, mock_get_client):
        """_embed delegates to get_client()._embed."""
        mock_client = MagicMock()
        mock_client._embed.return_value = [0.1, 0.2, 0.3]
        mock_get_client.return_value = mock_client

        from server.mcp.tools.app import _embed

        result = _embed("hello world")

        mock_client._embed.assert_called_once_with("hello world")
        assert result == [0.1, 0.2, 0.3]

    @patch("server.mcp.tools.app.get_client")
    def test_embed_batch_calls_client_embed_batch(self, mock_get_client):
        """_embed_batch delegates to get_client()._embed_batch."""
        mock_client = MagicMock()
        mock_client._embed_batch.return_value = [[0.1], [0.2]]
        mock_get_client.return_value = mock_client

        from server.mcp.tools.app import _embed_batch

        result = _embed_batch(["a", "b"])

        mock_client._embed_batch.assert_called_once_with(["a", "b"])
        assert result == [[0.1], [0.2]]

    @patch("server.mcp.tools.app.get_client")
    def test_embed_empty_string(self, mock_get_client):
        """_embed handles empty string gracefully."""
        mock_client = MagicMock()
        mock_client._embed.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.app import _embed

        result = _embed("")

        mock_client._embed.assert_called_once_with("")
        assert result == []

    @patch("server.mcp.tools.app.get_client")
    def test_embed_batch_empty_list(self, mock_get_client):
        """_embed_batch handles empty list gracefully."""
        mock_client = MagicMock()
        mock_client._embed_batch.return_value = []
        mock_get_client.return_value = mock_client

        from server.mcp.tools.app import _embed_batch

        result = _embed_batch([])

        mock_client._embed_batch.assert_called_once_with([])
        assert result == []

    @patch("server.mcp.tools.app.get_client")
    def test_embed_propagates_client_error(self, mock_get_client):
        """_embed propagates exceptions from get_client()._embed."""
        mock_client = MagicMock()
        mock_client._embed.side_effect = RuntimeError("Embedding failed")
        mock_get_client.return_value = mock_client

        from server.mcp.tools.app import _embed

        with pytest.raises(RuntimeError, match="Embedding failed"):
            _embed("fail")

        mock_client._embed.assert_called_once_with("fail")

    @patch("server.mcp.tools.app.get_client")
    def test_embed_batch_propagates_client_error(self, mock_get_client):
        """_embed_batch propagates exceptions from get_client()._embed_batch."""
        mock_client = MagicMock()
        mock_client._embed_batch.side_effect = ValueError("Invalid input")
        mock_get_client.return_value = mock_client

        from server.mcp.tools.app import _embed_batch

        with pytest.raises(ValueError, match="Invalid input"):
            _embed_batch(["bad"])

        mock_client._embed_batch.assert_called_once_with(["bad"])
