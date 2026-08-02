#!/usr/bin/env python3
"""
WebSocket subscription server for spacetime-memory.

Accepts WebSocket connections, lets clients subscribe to real-time
memory updates (change events), and pushes matching changes as they
occur.  The server polls the STDB ``change_event`` table internally
and fans out events to connected clients whose subscription filters
match (workspace, table, operation).

Message Protocol
----------------
All messages are JSON dicts with a ``type`` field.

**Client → Server:**

``{"type": "subscribe", "workspace_id": "...", "table": "...", "operation": "..."}``
    Subscribe to change events.  Each field is optional — omit to match
    all.  ``table`` can be ``"memory"``, ``"kg_node"``, ``"kg_edge"``,
    ``"note"``, ``"profile"``, ``"document"`` or ``"*"``.
    ``operation`` can be ``"insert"``, ``"update"``, ``"delete"`` or ``"*"``.

``{"type": "unsubscribe", "workspace_id": "...", "table": "...", "operation": "..."}``
    Remove a previously registered subscription filter.  If a field is
    omitted it's treated as a wildcard (same semantics as subscribe).

``{"type": "ping"}``
    Keepalive — server replies with ``{"type": "pong"}``.

**Server → Client:**

``{"type": "change", "event": {...}}``
    A change event matching the client's subscriptions.  The ``event``
    object has the same shape as a ``ChangeEvent`` record (id,
    workspace_id, table_name, operation, record_id, data_json, created_at).

``{"type": "error", "message": "..."}``
    An error occurred (e.g. invalid message).

``{"type": "pong"}``
    Reply to a client ``ping``.

``{"type": "subscribed", "count": N}``
    Confirmation after a subscribe — ``count`` is the number of active
    subscription filters for this connection.

Usage
-----
Start the server::

    python -m server.ws_subscription.main

Environment variables:
    STDB_HOST        — SpacetimeDB host (default: localhost)
    STDB_PORT        — SpacetimeDB HTTP port (default: 3001)
    STDB_DB          — SpacetimeDB database hash (default from SDK)
    WS_HOST          — WebSocket bind address (default: 0.0.0.0)
    WS_PORT          — WebSocket listen port (default: 8765)
    POLL_INTERVAL    — Change-poll interval in seconds (default: 0.1)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

import websockets
from websockets.asyncio.server import ServerConnection

# ---------------------------------------------------------------------------
# Add the SDK to the path — the server sits next to the SDK in the monorepo
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_SDK = os.path.abspath(os.path.join(_HERE, "..", "..", "sdk", "python"))
if _SDK not in sys.path:
    sys.path.insert(0, _SDK)

from spacetime_memory.delta_sync import ChangeEvent  # noqa: E402

from ._handler import StdbSubscriptionClient, event_to_dict  # noqa: E402
from ._subscription import ClientConnection, SubscriptionFilter, _filters_equal  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ws_subscription")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

STDB_HOST = os.environ.get("STDB_HOST", "localhost")
STDB_PORT = int(os.environ.get("STDB_PORT", "3001"))
STDB_DB = os.environ.get("STDB_DB", "")
WS_HOST = os.environ.get("WS_HOST", "0.0.0.0")
WS_PORT = int(os.environ.get("WS_PORT", "8765"))
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "0.1"))  # seconds
# STDB native WebSocket subscription URI -- when set, SubscriptionServer uses
# push-based STDB subscriptions instead of polling.  Format:
#   ws://<host>:<port>/v1/database/<db>
# Leave empty to use polling fallback.
STDB_SUBSCRIPTION_URI = os.environ.get("STDB_SUBSCRIPTION_URI", "")

# ---------------------------------------------------------------------------
# Subscription server
# ---------------------------------------------------------------------------


class SubscriptionServer:
    """WebSocket server that fans out STDB change events to subscribers.

    Delegates change detection to ``StdbSubscriptionClient``, which uses
    push-based STDB subscriptions when available, falling back to polling.
    """

    def __init__(self) -> None:
        self._clients: dict[str, ClientConnection] = {}
        self._server: websockets.WebSocketServer | None = None
        # StdbSubscriptionClient -- detects STDB changes (push or poll mode)
        self._stdb_subscription: StdbSubscriptionClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, host: str = WS_HOST, port: int = WS_PORT) -> None:
        """Start the WebSocket server and the STDB change-detection client."""
        if self._stdb_subscription is not None:
            return  # Already started
        # Start the STDB change-detection client (push or poll mode)
        self._stdb_subscription = StdbSubscriptionClient(
            on_changes=self._on_stdb_events,
            stdb_uri=STDB_SUBSCRIPTION_URI or None,
            stdb_host=STDB_HOST,
            stdb_port=STDB_PORT,
            stdb_database=STDB_DB,
            poll_interval=POLL_INTERVAL,
        )
        await self._stdb_subscription.start()

        # Start the WebSocket server for external clients
        self._server = await websockets.serve(
            self._handle_connection,
            host,
            port,
            ping_interval=30,
            ping_timeout=10,
        )
        logger.info("WebSocket subscription server listening on ws://%s:%s", host, port)

    async def stop(self) -> None:
        """Gracefully shut down the server and STDB change-detection client."""
        if self._stdb_subscription:
            self._stdb_subscription.stop()

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Close all client connections
        for conn in list(self._clients.values()):
            try:
                await conn.websocket.close(1001, "Server shutting down")
            except ConnectionError:
                pass
        self._clients.clear()
        logger.info("WebSocket subscription server stopped")

    # ------------------------------------------------------------------
    # Client connection handling
    # ------------------------------------------------------------------

    async def _handle_connection(self, websocket: ServerConnection) -> None:
        """Handle a new WebSocket connection."""
        conn_id = str(id(websocket))
        conn = ClientConnection(websocket=websocket)
        self._clients[conn_id] = conn

        logger.info(
            "Client connected: %s (total: %d)",
            websocket.remote_address,
            len(self._clients),
        )

        try:
            async for raw_message in websocket:
                await self._handle_message(conn, raw_message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.pop(conn_id, None)
            logger.info(
                "Client disconnected: %s (total: %d)",
                websocket.remote_address,
                len(self._clients),
            )

    async def _handle_message(self, conn: ClientConnection, raw: str) -> None:
        """Parse and handle an incoming JSON message from a client."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as e:
            await self._send(conn, {"type": "error", "message": f"Invalid JSON: {e}"})
            return

        msg_type = msg.get("type", "")

        if msg_type == "subscribe":
            await self._handle_subscribe(conn, msg)
        elif msg_type == "unsubscribe":
            await self._handle_unsubscribe(conn, msg)
        elif msg_type == "ping":
            await self._send(conn, {"type": "pong"})
        else:
            await self._send(conn, {"type": "error", "message": f"Unknown message type: {msg_type}"})

    async def _handle_subscribe(self, conn: ClientConnection, msg: dict[str, Any]) -> None:
        """Handle a subscribe message from a client."""
        f = SubscriptionFilter(
            workspace_id=msg.get("workspace_id", "*"),
            table=msg.get("table", "*"),
            operation=msg.get("operation", "*"),
        )
        conn.add_filter(f)
        await self._send(conn, {"type": "subscribed", "count": len(conn.filters)})

    async def _handle_unsubscribe(self, conn: ClientConnection, msg: dict[str, Any]) -> None:
        """Handle an unsubscribe message from a client."""
        f = SubscriptionFilter(
            workspace_id=msg.get("workspace_id", "*"),
            table=msg.get("table", "*"),
            operation=msg.get("operation", "*"),
        )
        conn.remove_filter(f)
        await self._send(conn, {"type": "unsubscribed", "count": len(conn.filters)})

    @staticmethod
    async def _send(conn: ClientConnection, msg: dict[str, Any]) -> None:
        """Send a JSON message to a connected client."""
        try:
            await conn.websocket.send(json.dumps(msg, default=str))
        except websockets.exceptions.ConnectionClosed:
            pass

    # ------------------------------------------------------------------
    # STDB change event handler -- fed by StdbSubscriptionClient
    # ------------------------------------------------------------------

    async def _on_stdb_events(self, events: list[ChangeEvent]) -> None:
        """Called by StdbSubscriptionClient when new change events arrive.

        Fans out each event to matching connected WebSocket clients.
        """
        for event in events:
            await self._fanout(event)

    async def _fanout(self, event: ChangeEvent) -> None:
        """Push a change event to all matching connected clients."""
        payload = {"type": "change", "event": event_to_dict(event)}
        disconnected: list[str] = []
        for conn_id, conn in self._clients.items():
            if conn.matches_any(event):
                try:
                    await conn.websocket.send(json.dumps(payload, default=str))
                except websockets.exceptions.ConnectionClosed:
                    disconnected.append(conn_id)

        # Clean up disconnected clients
        for conn_id in disconnected:
            self._clients.pop(conn_id, None)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _main() -> None:
    """Run the WebSocket subscription server."""
    server = SubscriptionServer()
    try:
        await server.start()
        # Keep running until interrupted
        await asyncio.get_running_loop().create_future()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down...")
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(_main())


def start_server(
    host: str = WS_HOST,
    port: int = WS_PORT,
) -> None:
    """Start the WebSocket subscription server (blocking).

    Convenience function for programmatic use.  Starts the server and
    runs until interrupted.

    Usage::

        from server.ws_subscription.main import start_server
        start_server(host="0.0.0.0", port=8765)
    """
    _server = SubscriptionServer()

    async def _run() -> None:
        await _server.start()
        try:
            await asyncio.get_running_loop().create_future()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await _server.stop()

    asyncio.run(_run())
