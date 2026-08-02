"""Shared MCP server state — mcp instance, auth, client, config.

All domain tool modules import from here.
"""
from __future__ import annotations

import functools
import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from spacetime_memory import Client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Configuration
# ---------------------------------------------------------------------------

HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DB = os.environ.get("SPACETIMEDB_DB", "spacetime-memory")
EMBEDDER_URL = os.environ.get("EMBEDDER_URL", "http://localhost:4000")
TANTIVY_URL = os.environ.get("TANTIVY_URL", "http://localhost:9091")
MCP_API_KEY = os.environ.get("MCP_API_KEY", "")

# Load reranker credentials from Hermes .env (same pattern as eval_harness.py)
_hermes_env = os.path.expanduser("~/.hermes/.env")
if os.path.exists(_hermes_env):
    with open(_hermes_env) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line.startswith("LITELLM_MASTER_KEY="):
                _, _key = _line.split("=", 1)
                os.environ.setdefault("LLM_RERANK_API_KEY", _key.strip().strip('"').strip("'"))
                break
os.environ.setdefault("LLM_RERANK_ENDPOINT", "http://127.0.0.1:4000/v1")
os.environ.setdefault("LLM_RERANK_MODEL", "ds-deepseek-v4-flash")

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

# Auth helpers
# ---------------------------------------------------------------------------

if MCP_API_KEY:
    logger.info(
        "MCP API key authentication is enabled. "
        "Tools will require a valid key for HTTP/SSE transport."
    )

def require_api_key(func):
    """Decorator that enforces MCP_API_KEY on non-stdio transports.

    For HTTP/SSE transport, the FastMCP tool receives request context via
    the ``ctx`` argument.  If ``MCP_API_KEY`` is set, we extract the
    ``Authorization`` header from the request metadata and compare it
    against the configured key.

    For stdio transport (local agent), there are no HTTP headers, so auth
    does not apply — rely on filesystem permissions instead.

    .. note::

        FastMCP passes context as the first positional arg when the tool
        signature includes ``ctx``.  This decorator introspects the
        available context to determine the transport type.
    """

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        # If no key is configured, allow all
        if not MCP_API_KEY:
            return await func(*args, **kwargs)

        # Try to extract the Authorization header from the request context.
        # FastMCP passes the request context in a variety of ways depending
        # on transport.  We do a best-effort check.
        request_meta = None

        # Check if first arg is the FastMCP context object
        for arg in args:
            if hasattr(arg, "request"):
                request_meta = getattr(arg, "request", None)
                break
        if not request_meta:
            # Check kwargs for common context names
            for key in ("ctx", "context", "request"):
                val = kwargs.get(key)
                if val is not None and hasattr(val, "request"):
                    request_meta = getattr(val, "request", None)
                    break

        if request_meta is not None:
            # We have request metadata — check the Authorization header
            headers = getattr(request_meta, "headers", {}) or getattr(
                request_meta, "scope", {}
            )
            # FastMCP / Starlette-style: headers is a dict-like object
            auth_header = ""
            if isinstance(headers, dict):
                auth_header = headers.get("authorization", "") or headers.get(
                    "Authorization", ""
                )
            elif hasattr(headers, "get"):
                auth_header = headers.get("authorization", "") or headers.get(
                    "Authorization", ""
                )

            expected = f"Bearer {MCP_API_KEY}"
            if auth_header != expected:
                raise PermissionError("Unauthorized: invalid or missing API key")

        # If no request context (stdio), auth doesn't apply
        return await func(*args, **kwargs)

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        # If no key is configured, allow all
        if not MCP_API_KEY:
            return func(*args, **kwargs)

        # Try to extract the Authorization header from the request context.
        request_meta = None
        for arg in args:
            if hasattr(arg, "request"):
                request_meta = getattr(arg, "request", None)
                break
        if not request_meta:
            for key in ("ctx", "context", "request"):
                val = kwargs.get(key)
                if val is not None and hasattr(val, "request"):
                    request_meta = getattr(val, "request", None)
                    break

        if request_meta is not None:
            headers = getattr(request_meta, "headers", {}) or getattr(
                request_meta, "scope", {}
            )
            auth_header = ""
            if isinstance(headers, dict):
                auth_header = headers.get("authorization", "") or headers.get(
                    "Authorization", ""
                )
            elif hasattr(headers, "get"):
                auth_header = headers.get("authorization", "") or headers.get(
                    "Authorization", ""
                )

            expected = f"Bearer {MCP_API_KEY}"
            if auth_header != expected:
                raise PermissionError("Unauthorized: invalid or missing API key")

        return func(*args, **kwargs)

    # Return the appropriate wrapper depending on whether the function is async
    import asyncio
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper

# ---------------------------------------------------------------------------
# MCP server + SDK Client
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# MCP server + SDK Client
# ---------------------------------------------------------------------------

mcp = FastMCP("spacetime-memory", log_level="WARNING")

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(
            host=HOST,
            port=PORT,
            database=DB,
            embedder_url=EMBEDDER_URL,
            tantivy_url=TANTIVY_URL,
        )
    return _client


# Embedder helpers (also available via Client, re-exported for convenience)


def _embed(text: str) -> list[float]:
    return get_client()._embed(text)


def _embed_batch(texts: list[str]) -> list[list[float]]:
    return get_client()._embed_batch(texts)
