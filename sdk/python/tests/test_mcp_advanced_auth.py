"""Tests for MCP tools — split from test_mcp_advanced.py."""

import pytest

pytest.skip("requires MCP server runtime (server/mcp/)", allow_module_level=True)

# ── TestRequireApiKey ────────────────────────────────────────────────────────

class TestRequireApiKey:
    """Tests for the require_api_key decorator."""

    def test_no_key_sync_passes_through(self):
        """When MCP_API_KEY is empty (default), sync decorator passes through."""
        from server.mcp.main import require_api_key

        @require_api_key
        def my_tool(arg1, kw1=None):
            return f"{arg1}-{kw1}"

        result = my_tool("hello", kw1="world")
        assert result == "hello-world"

    def test_no_key_async_passes_through(self):
        """When MCP_API_KEY is empty, async decorator passes through."""
        from server.mcp.main import require_api_key

        @require_api_key
        async def my_async_tool():
            return "async_ok"

        import asyncio

        result = asyncio.run(my_async_tool())
        assert result == "async_ok"

    def test_valid_key_via_args(self, monkeypatch):
        """Valid Bearer token via args context."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequest:
            headers = {"authorization": "Bearer test-key"}

        class MockCtx:
            request = MockRequest()

        @require_api_key
        def my_tool(ctx):
            return "authorized"

        result = my_tool(MockCtx())
        assert result == "authorized"

    def test_valid_key_via_kwargs_ctx(self, monkeypatch):
        """Valid Bearer token via ctx kwarg."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequest:
            headers = {"Authorization": "Bearer test-key"}

        class MockCtx:
            request = MockRequest()

        @require_api_key
        def my_tool(ctx=None):
            return "authorized"

        result = my_tool(ctx=MockCtx())
        assert result == "authorized"

    def test_wrong_key_raises_error(self, monkeypatch):
        """Wrong Bearer token raises PermissionError."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequest:
            headers = {"authorization": "Bearer wrong-key"}

        class MockCtx:
            request = MockRequest()

        @require_api_key
        def my_tool(ctx):
            return "should_not_reach"

        import pytest

        with pytest.raises(PermissionError, match="Unauthorized"):
            my_tool(MockCtx())

    def test_no_request_context_stdio(self, monkeypatch):
        """No request context (stdio mode) should pass through even with key set."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        @require_api_key
        def my_tool(arg):
            return arg

        result = my_tool("stdio_value")
        assert result == "stdio_value"

    def test_args_without_request_property(self, monkeypatch):
        """First arg without .request attribute should not match context."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        @require_api_key
        def my_tool(x, y):
            return f"{x}-{y}"

        result = my_tool("a", "b")
        assert result == "a-b"

    def test_async_with_valid_key(self, monkeypatch):
        """Async function with valid key should pass."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequest:
            headers = {"Authorization": "Bearer test-key"}

        class MockCtx:
            request = MockRequest()

        @require_api_key
        async def my_async_tool(ctx):
            return "async_authorized"

        import asyncio

        result = asyncio.run(my_async_tool(MockCtx()))
        assert result == "async_authorized"

    def test_async_wrong_key_raises_error(self, monkeypatch):
        """Async function with wrong key raises PermissionError."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequest:
            headers = {"authorization": "Bearer wrong"}

        class MockCtx:
            request = MockRequest()

        @require_api_key
        async def my_async_tool(ctx):
            return "should_not_reach"

        import asyncio

        import pytest

        with pytest.raises(PermissionError, match="Unauthorized"):
            asyncio.run(my_async_tool(MockCtx()))

    def test_context_via_kwargs_context_key(self, monkeypatch):
        """Valid key via kwargs key 'context'."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequest:
            headers = {"authorization": "Bearer test-key"}

        class MockCtx:
            request = MockRequest()

        @require_api_key
        def my_tool(context=None):
            return "authorized"

        result = my_tool(context=MockCtx())
        assert result == "authorized"

    def test_context_via_kwargs_request_key(self, monkeypatch):
        """Valid key via kwargs key 'request'."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequest:
            headers = {"authorization": "Bearer test-key"}

        class MockRequestObj:
            request = MockRequest()

        @require_api_key
        def my_tool(request=None):
            return "authorized"

        result = my_tool(request=MockRequestObj())
        assert result == "authorized"

    def test_scope_style_headers(self, monkeypatch):
        """When request has 'scope' instead of 'headers'."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequestMeta:
            scope = {"authorization": "Bearer test-key"}

        class MockCtx:
            request = MockRequestMeta()

        @require_api_key
        def my_tool(ctx):
            return "scoped_ok"

        result = my_tool(MockCtx())
        assert result == "scoped_ok"

    def test_non_dict_headers_with_get(self, monkeypatch):
        """When headers has .get() method but is not a dict."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from unittest.mock import MagicMock

        from server.mcp.main import require_api_key

        mock_headers = MagicMock()
        mock_headers.get.return_value = "Bearer test-key"

        class MockRequest:
            headers = mock_headers

        class MockCtx:
            request = MockRequest()

        @require_api_key
        def my_tool(ctx):
            return "ok"

        result = my_tool(MockCtx())
        assert result == "ok"

    def test_async_wrapper_kwargs_ctx_path(self, monkeypatch):
        """Test async_wrapper kwargs path (lines 104-108): first arg has no request,
        but kwargs ctx has request."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequest:
            headers = {"authorization": "Bearer test-key"}

        class MockCtx:
            request = MockRequest()

        @require_api_key
        async def my_tool(some_arg, ctx=None):
            return f"authorized_with_{some_arg}"

        import asyncio

        result = asyncio.run(my_tool("hello", ctx=MockCtx()))
        assert result == "authorized_with_hello"

    def test_async_wrapper_non_dict_headers_with_get(self, monkeypatch):
        """Test async_wrapper non-dict headers with .get() (lines 121-122)."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from unittest.mock import MagicMock

        from server.mcp.main import require_api_key

        mock_headers = MagicMock()
        mock_headers.get.return_value = "Bearer test-key"

        class MockRequest:
            headers = mock_headers

        class MockCtx:
            request = MockRequest()

        @require_api_key
        async def my_tool(ctx):
            return "async_non_dict_ok"

        import asyncio

        result = asyncio.run(my_tool(MockCtx()))
        assert result == "async_non_dict_ok"

    def test_async_wrapper_wrong_key_non_dict_headers(self, monkeypatch):
        """Test async_wrapper with wrong key and non-dict headers."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from unittest.mock import MagicMock

        from server.mcp.main import require_api_key

        mock_headers = MagicMock()
        mock_headers.get.return_value = "Bearer wrong-key"

        class MockRequest:
            headers = mock_headers

        class MockCtx:
            request = MockRequest()

        @require_api_key
        async def my_tool(ctx):
            return "should_not_reach"

        import asyncio

        import pytest

        with pytest.raises(PermissionError, match="Unauthorized"):
            asyncio.run(my_tool(MockCtx()))

    def test_async_wrapper_kwargs_context_key(self, monkeypatch):
        """Test async_wrapper with kwargs key 'context'."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequest:
            headers = {"authorization": "Bearer test-key"}

        class MockCtx:
            request = MockRequest()

        @require_api_key
        async def my_tool(context=None):
            return "context_kwarg_ok"

        import asyncio

        result = asyncio.run(my_tool(context=MockCtx()))
        assert result == "context_kwarg_ok"

    def test_sync_wrapper_kwargs_ctx_path(self, monkeypatch):
        """Test sync_wrapper kwargs path (lines 145-150): first arg has no request,
        but kwargs ctx has request."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from server.mcp.main import require_api_key

        class MockRequest:
            headers = {"authorization": "Bearer test-key"}

        class MockCtx:
            request = MockRequest()

        @require_api_key
        def my_tool(some_arg, ctx=None):
            return f"sync_kwargs_{some_arg}"

        result = my_tool("hello", ctx=MockCtx())
        assert result == "sync_kwargs_hello"

    def test_sync_wrapper_non_dict_headers_with_get(self, monkeypatch):
        """Test sync_wrapper non-dict headers with .get()."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key")
        from unittest.mock import MagicMock

        from server.mcp.main import require_api_key

        mock_headers = MagicMock()
        mock_headers.get.return_value = "Bearer test-key"

        class MockRequest:
            headers = mock_headers

        class MockCtx:
            request = MockRequest()

        @require_api_key
        def my_tool(ctx):
            return "sync_non_dict"

        result = my_tool(MockCtx())
        assert result == "sync_non_dict"


# ── get_client ────────────────────────────────────────────────────────────



# ── TestRequireApiKeySync ────────────────────────────────────────────────────────

class TestRequireApiKeySync:
    """Tests for the sync wrapper of require_api_key."""

    def test_no_key_set_passes_through(self, monkeypatch):
        """When MCP_API_KEY is empty, sync function passes through."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "")

        from server.mcp.main import require_api_key

        def sample_fn(arg1: str) -> str:
            return f"result: {arg1}"

        wrapped = require_api_key(sample_fn)
        result = wrapped("hello")
        assert result == "result: hello"

    def test_with_valid_bearer_token(self, monkeypatch):
        """MCP_API_KEY set + valid Bearer token in args context passes."""
        from unittest.mock import MagicMock

        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key-sync")

        from server.mcp.main import require_api_key

        def sample_fn(ctx) -> str:
            return "sync ok"

        wrapped = require_api_key(sample_fn)
        ctx = MagicMock()
        ctx.request = MagicMock()
        ctx.request.headers = {"authorization": "Bearer test-key-sync"}

        result = wrapped(ctx)
        assert result == "sync ok"

    def test_with_invalid_bearer_token(self, monkeypatch):
        """MCP_API_KEY set + invalid Bearer token raises PermissionError."""
        from unittest.mock import MagicMock

        import pytest

        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key-sync")

        from server.mcp.main import require_api_key

        def sample_fn(ctx) -> str:
            return "sync ok"

        wrapped = require_api_key(sample_fn)
        ctx = MagicMock()
        ctx.request = MagicMock()
        ctx.request.headers = {"authorization": "Bearer wrong"}

        with pytest.raises(PermissionError, match="Unauthorized"):
            wrapped(ctx)

    def test_no_request_context_stdio_sync(self, monkeypatch):
        """MCP_API_KEY set but no request context passes through."""
        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key-sync")

        from server.mcp.main import require_api_key

        def sample_fn() -> str:
            return "sync stdio"

        wrapped = require_api_key(sample_fn)
        result = wrapped()
        assert result == "sync stdio"

    def test_with_starlette_scope_headers(self, monkeypatch):
        """MCP_API_KEY set with Starlette-style scope headers."""
        from unittest.mock import MagicMock

        monkeypatch.setattr("server.mcp.main.MCP_API_KEY", "test-key-scope")

        from server.mcp.main import require_api_key

        def sample_fn(ctx) -> str:
            return "scope ok"

        wrapped = require_api_key(sample_fn)
        ctx = MagicMock()
        ctx.request = MagicMock()
        # request_meta.headers is None, so the decorator falls back to .scope
        ctx.request.headers = None
        ctx.request.scope = {"authorization": "Bearer test-key-scope"}

        result = wrapped(ctx)
        assert result == "scope ok"


# ── get_client singleton ────────────────────────────────────────────────────



