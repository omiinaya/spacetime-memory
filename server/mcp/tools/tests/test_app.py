"""Tests for server/mcp/tools/app.py — shared MCP server state + auth decorator.

These tests exercise the pure logic (require_api_key decorator, env defaults)
without needing a live SpacetimeDB instance. The client is only constructed
lazily via get_client() and is not touched here.
"""
import asyncio

import pytest

from server.mcp.tools import app


class FakeRequestMeta:
    """Minimal object exposing .request with a headers dict (HTTP transport)."""

    def __init__(self, headers: dict):
        self.request = _Req(headers)


class _Req:
    def __init__(self, headers: dict):
        self.headers = headers


@pytest.fixture(autouse=True)
def _reset_api_key():
    """Each test controls MCP_API_KEY explicitly via the module global."""
    prev = app.MCP_API_KEY
    app.MCP_API_KEY = ""
    yield
    app.MCP_API_KEY = prev


# ---------------------------------------------------------------------------
# require_api_key — no key configured
# ---------------------------------------------------------------------------


def test_no_key_allows_through_sync():
    app.MCP_API_KEY = ""

    @app.require_api_key
    def target(x: int) -> int:
        return x * 2

    assert target(21) == 42


def test_no_key_allows_through_async():
    app.MCP_API_KEY = ""

    @app.require_api_key
    async def target(x: int) -> int:
        return x * 2

    assert asyncio.run(target(21)) == 42


# ---------------------------------------------------------------------------
# require_api_key — key configured
# ---------------------------------------------------------------------------


def test_key_configured_stdio_no_context_passes():
    """stdio transport has no request context → auth does not apply."""
    app.MCP_API_KEY = "sekret"

    @app.require_api_key
    def target() -> str:
        return "ok"

    assert target() == "ok"


def test_key_configured_bad_header_raises_sync():
    app.MCP_API_KEY = "sekret"

    @app.require_api_key
    def target(ctx=None) -> str:  # noqa: ARG001
        return "ok"

    with pytest.raises(PermissionError, match="Unauthorized"):
        target(ctx=FakeRequestMeta({"authorization": "Bearer wrong"}))


def test_key_configured_good_header_passes_sync():
    app.MCP_API_KEY = "sekret"

    @app.require_api_key
    def target(ctx=None) -> str:  # noqa: ARG001
        return "ok"

    assert target(ctx=FakeRequestMeta({"authorization": "Bearer sekret"})) == "ok"


def test_key_configured_good_header_capitalized_passes_sync():
    app.MCP_API_KEY = "sekret"

    @app.require_api_key
    def target(ctx=None) -> str:  # noqa: ARG001
        return "ok"

    assert target(ctx=FakeRequestMeta({"Authorization": "Bearer sekret"})) == "ok"


def test_key_configured_bad_header_raises_async():
    app.MCP_API_KEY = "sekret"

    @app.require_api_key
    async def target(ctx=None) -> str:  # noqa: ARG001
        return "ok"

    with pytest.raises(PermissionError, match="Unauthorized"):
        asyncio.run(target(ctx=FakeRequestMeta({"authorization": "Bearer nope"})))


def test_key_configured_good_header_passes_async():
    app.MCP_API_KEY = "sekret"

    @app.require_api_key
    async def target(ctx=None) -> str:  # noqa: ARG001
        return "ok"

    assert asyncio.run(target(ctx=FakeRequestMeta({"authorization": "Bearer sekret"}))) == "ok"


def test_ctx_kwarg_context_checked():
    """Context passed via kwarg (ctx=) with a request object is honored."""
    app.MCP_API_KEY = "sekret"

    @app.require_api_key
    def target(ctx=None) -> str:  # noqa: ARG001
        return "ok"

    with pytest.raises(PermissionError, match="Unauthorized"):
        target(ctx=FakeRequestMeta({"authorization": "Bearer bad"}))


# ---------------------------------------------------------------------------
# Env defaults (no .env / env vars set)
# ---------------------------------------------------------------------------


def test_env_defaults(monkeypatch):
    for var in ("SPACETIMEDB_HOST", "SPACETIMEDB_PORT", "SPACETIMEDB_DB",
                "EMBEDDER_URL", "TANTIVY_URL", "MCP_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", "/tmp/nonexistent-home-for-test")
    import importlib
    mod = importlib.import_module("server.mcp.tools.app")
    assert mod.HOST == "localhost"
    assert mod.PORT == "3001"
    assert mod.DB == "spacetime-memory"
    assert mod.EMBEDDER_URL == "http://localhost:4000"
    assert mod.TANTIVY_URL == "http://localhost:9091"
    assert mod.MCP_API_KEY == ""


# ---------------------------------------------------------------------------
# Registry sanity — app.py is the shared hub
# ---------------------------------------------------------------------------


def test_mcp_instance_is_fastmcp():
    assert app.mcp is not None
    # The FastMCP name identifies the server
    assert getattr(app.mcp, "name", None) == "spacetime-memory"
