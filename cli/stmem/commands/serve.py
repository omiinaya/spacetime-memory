"""MCP server"""

from __future__ import annotations

import json
import os
import sys

import click


from .. import root as _root
from ..root import (
    cli,
)

# ===================================================================
# serve — MCP server
# ===================================================================


@cli.command(name="serve")
@click.option("--transport", default="stdio",
              type=click.Choice(["stdio", "sse"]),
              help="MCP transport protocol (default: stdio)")
@click.option("--host", default=None, help="SSE listen host (default: SPACETIMEDB_HOST)")
@click.option("--port", default=None, type=int, help="SSE listen port (default: 8100)")
@click.option("--api-key", default=None, help="API key for SSE auth (default: MCP_API_KEY env)")
def serve(transport: str, host: str | None, port: int | None, api_key: str | None) -> None:
    """Start the MCP (Model Context Protocol) server.

    By default runs on stdio transport for local agent integration.
    Use ``--transport sse`` for HTTP/SSE mode.
    """
    host_val = host or os.environ.get("SPACETIMEDB_HOST", "localhost")
    port_val = port if port is not None else int(os.environ.get("SPACETIMEDB_PORT", "3001"))
    db_val = os.environ.get("SPACETIMEDB_DB", "spacetime-memory")
    embedder_url = os.environ.get("EMBEDDER_URL", "http://localhost:9090")

    os.environ.setdefault("SPACETIMEDB_HOST", host_val)
    os.environ.setdefault("SPACETIMEDB_PORT", str(port_val))
    os.environ.setdefault("SPACETIMEDB_DB", db_val)
    os.environ.setdefault("EMBEDDER_URL", embedder_url)
    if api_key:
        os.environ["MCP_API_KEY"] = api_key

    listen_host = os.environ.get("MCP_HOST", "0.0.0.0")
    listen_port = int(os.environ.get("MCP_PORT", "8100"))

    if transport == "sse":
        _root.console.print(f"MCP SSE server starting on http://{listen_host}:{listen_port} ...")
        _root.console.print(f"  DB: {host_val}:{port_val}/{db_val}")
        _root.console.print(f"  Embedder: {embedder_url}")
        _root.console.print(f"  Auth: {'enabled' if os.environ.get('MCP_API_KEY') else 'disabled'}")
    else:
        _root.console.print("MCP stdio server starting ...", highlight=False)

    try:
        from server.mcp.main import run
        run(
            transport=transport,
            host=listen_host if transport == "sse" else None,
            port=listen_port if transport == "sse" else None,
        )
    except ImportError as e:
        _root.console.print(f"[red]Error:[/red] Cannot start MCP server — missing dependencies: {e}")
        _root.console.print("  pip install spacetime-memory[mcp]")
        sys.exit(1)
    except (OSError, json.JSONDecodeError) as e:
        _root.console.print(f"[red]Error:[/red] MCP server failed: {e}")
        sys.exit(1)
