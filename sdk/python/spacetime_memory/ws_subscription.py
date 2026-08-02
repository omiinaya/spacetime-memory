"""
WebSocket subscription client for spacetime-memory.

Connects to the WebSocket subscription server for real-time memory
update notifications.  Complements the polling-based ``DeltaSync``
with a push-based WebSocket subscription model.

Usage::

    from spacetime_memory import Client
    from spacetime_memory.ws_subscription import WsSubscription

    client = Client(...)
    ws = WsSubscription(client, uri="ws://127.0.0.1:8765")

    # Register callbacks
    ws.on("memory", "insert", lambda event: print(f"New memory: {event}"))
    ws.on("kg_node", "*", lambda event: print(f"Graph change: {event}"))

    # Connect (starts background reader thread)
    ws.connect()

    # Later...
    ws.disconnect()
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Default WebSocket subscription server URI
_DEFAULT_WS_URI = "ws://127.0.0.1:8765"


@dataclass
class ChangeEvent:
    """A single change event received via WebSocket (same shape as DeltaSync)."""

    id: str
    workspace_id: str
    table_name: str
    operation: str  # "insert", "update", "delete"
    record_id: str
    data_json: str
    created_at: int

    @property
    def data(self) -> dict[str, Any]:
        """Deserialized record data."""
        return json.loads(self.data_json) if isinstance(self.data_json, str) else self.data_json

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChangeEvent:
        return cls(
            id=d.get("id", ""),
            workspace_id=d.get("workspace_id", ""),
            table_name=d.get("table_name", ""),
            operation=d.get("operation", ""),
            record_id=d.get("record_id", ""),
            data_json=d.get("data_json", "{}"),
            created_at=int(d.get("created_at", 0)),
        )


class WsSubscription:
    """WebSocket subscription client for real-time memory updates.

    Connects to the spacetime-memory WebSocket subscription server
    and dispatches change events to registered callbacks.

    Args:
        client: A ``Client`` instance (used for auth context, optional).
        uri: WebSocket server URI (default: ``ws://127.0.0.1:8765``).
        auto_reconnect: Automatically reconnect on disconnect (default: True).
        reconnect_delay: Seconds to wait before reconnecting (default: 5).
    """

    def __init__(
        self,
        client: Any = None,
        uri: str = _DEFAULT_WS_URI,
        auto_reconnect: bool = True,
        reconnect_delay: float = 5.0,
    ):
        self._client = client
        self._uri = uri
        self._auto_reconnect = auto_reconnect
        self._reconnect_delay = reconnect_delay
        self._callbacks: dict[tuple[str, str], list[tuple[object, Callable[[Any], None]]]] = {}
        self._connected = False
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._messages_sent: int = 0
        self._errors: int = 0
        self._outbox: list[dict[str, Any]] = []
        self._outbox_lock = threading.Lock()

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def connect(self) -> None:
        """Connect to the WebSocket server and start the reader thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="ws-subscription",
            daemon=True,
        )
        self._thread.start()
        logger.info("WsSubscription connecting to %s", self._uri)

    def disconnect(self) -> None:
        """Disconnect and stop the reader thread."""
        self._running = False
        self._connected = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("WsSubscription disconnected")

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "connected": self._connected,
            "running": self._running,
            "uri": self._uri,
            "callbacks": sum(len(v) for v in self._callbacks.values()),
            "messages_sent": self._messages_sent,
            "errors": self._errors,
        }

    def on(
        self,
        table: str = "*",
        operation: str = "*",
        callback: Callable[[Any], None] | None = None,
    ) -> object:
        """Register a callback for change events.

        Args:
            table: Table name (``"memory"``, ``"kg_node"``, etc., or ``"*"``).
            operation: Operation (``"insert"``, ``"update"``, ``"delete"``, or ``"*"``).
            callback: Callable receiving a ``ChangeEvent``.

        Returns:
            A token that can be passed to ``off()`` to unregister.
        """
        if callback is None:
            raise ValueError("callback is required")
        token = object()
        with self._lock:
            key = (table, operation)
            if key not in self._callbacks:
                self._callbacks[key] = []
            self._callbacks[key].append((token, callback))
        return token

    def off(self, token: object) -> None:
        """Unregister a callback by its token."""
        with self._lock:
            for key in list(self._callbacks.keys()):
                self._callbacks[key] = [
                    (t, cb) for t, cb in self._callbacks[key] if t is not token
                ]
                if not self._callbacks[key]:
                    del self._callbacks[key]

    def subscribe(
        self,
        workspace_id: str = "*",
        table: str = "*",
        operation: str = "*",
    ) -> None:
        """Send a subscribe message to the server.

        The server will push matching change events to this client.
        """
        if not self._connected:
            logger.warning("Cannot subscribe — not connected")
            return
        self._send_message({
            "type": "subscribe",
            "workspace_id": workspace_id,
            "table": table,
            "operation": operation,
        })

    def unsubscribe(
        self,
        workspace_id: str = "*",
        table: str = "*",
        operation: str = "*",
    ) -> None:
        """Remove a subscription filter from the server."""
        if not self._connected:
            return
        self._send_message({
            "type": "unsubscribe",
            "workspace_id": workspace_id,
            "table": table,
            "operation": operation,
        })

    # -------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Main loop — connects and reads messages."""
        import websockets.sync.client as ws_client

        while self._running:
            try:
                with ws_client.connect(self._uri) as ws:
                    self._connected = True
                    logger.info("Connected to WebSocket subscription server: %s", self._uri)

                    # Subscribe to all changes by default
                    ws.send(json.dumps({"type": "subscribe", "workspace_id": "*", "table": "*", "operation": "*"}))
                    self._messages_sent += 1

                    while self._running:
                        # Drain outbox
                        with self._outbox_lock:
                            outgoing = list(self._outbox)
                            self._outbox.clear()
                        for msg in outgoing:
                            ws.send(json.dumps(msg))
                            self._messages_sent += 1

                        raw = ws.recv()
                        if raw is None:
                            break
                        self._handle_raw(raw)

            except Exception as e:
                self._errors += 1
                logger.debug("WsSubscription connection error: %s", e)
            finally:
                self._connected = False

            if not self._auto_reconnect or not self._running:
                break

            logger.debug("Reconnecting in %.1fs...", self._reconnect_delay)
            threading.Event().wait(self._reconnect_delay)

    def _handle_raw(self, raw: str | bytes) -> None:
        """Parse and dispatch an incoming WebSocket message."""
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            msg = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug("Invalid message from server: %s", e)
            return

        msg_type = msg.get("type", "")

        if msg_type == "change":
            event = ChangeEvent.from_dict(msg.get("event", {}))
            self._dispatch(event)
        elif msg_type == "error":
            logger.warning("Server error: %s", msg.get("message", ""))
        elif msg_type == "subscribed":
            logger.debug("Subscribed to change events (count=%d)", msg.get("count", 0))
        elif msg_type == "pong":
            pass  # keepalive response — nothing to do

    def _send_message(self, msg: dict[str, Any]) -> None:
        """Queue a message to be sent on the reader thread."""
        with self._outbox_lock:
            self._outbox.append(msg)

    def _dispatch(self, event: ChangeEvent) -> None:
        """Dispatch a single event to all matching callbacks."""
        with self._lock:
            matched: list[Callable[[Any], None]] = []
            for (table, operation), cbs in self._callbacks.items():
                if table == "*" or table == event.table_name:
                    if operation == "*" or operation == event.operation:
                        for _, cb in cbs:
                            matched.append(cb)

        for cb in matched:
            try:
                cb(event)
            except Exception as e:
                logger.exception("WsSubscription callback error: %s", e)


# ---------------------------------------------------------------------------
# SQL quoting helper
# ---------------------------------------------------------------------------


def _q(value: str) -> str:
    """Quote a string literal for safe SQL injection into STDB queries.

    STDB does not support parameterized queries, so we escape manually.
    """
    return "'" + value.replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# ManagedSubscription — tracked subscription record
# ---------------------------------------------------------------------------


@dataclass
class ManagedSubscription:
    """A subscription record managed in the STDB ``subscriptions`` table.

    Attributes match the STDB table schema for round-trip fidelity.
    """

    id: str = ""
    workspace_id: str = ""
    name: str = ""
    query: str = ""
    callback_url: str = ""
    created_by: str = ""
    is_active: bool = True
    created_at: int = 0
    updated_at: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ManagedSubscription:
        """Create from a raw STDB row dict."""
        return cls(
            id=d.get("id", ""),
            workspace_id=d.get("workspace_id", ""),
            name=d.get("name", ""),
            query=d.get("query", ""),
            callback_url=d.get("callback_url", ""),
            created_by=d.get("created_by", ""),
            is_active=bool(d.get("is_active", False)),
            created_at=int(d.get("created_at", 0)),
            updated_at=int(d.get("updated_at", 0)),
        )


# ---------------------------------------------------------------------------
# SubscriptionManager — CRUD for managed subscriptions via STDB reducers
# ---------------------------------------------------------------------------


class SubscriptionManager:
    """Manages subscription lifecycle through the STDB reducer interface.

    Wraps STDB reducers (``create_subscription``, ``delete_subscription``,
    ``toggle_subscription``, ``list_subscriptions``) and provides Pythonic
    methods for CRUD operations.

    Args:
        client: A ``Client`` instance with ``_call`` and ``_sql`` methods.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def create(
        self,
        workspace_id: str,
        name: str,
        query: str,
        callback_url: str = "",
    ) -> ManagedSubscription:
        """Create a new subscription via the STDB reducer."""
        self._client._call("create_subscription", [workspace_id, name, query, callback_url])

        # Fetch the newly created subscription
        rows = self._client._sql(
            f"SELECT * FROM subscriptions WHERE name = {_q(name)} AND workspace_id = {_q(workspace_id)}"
        )
        if rows:
            return ManagedSubscription.from_dict(rows[0])
        raise RuntimeError(f"Failed to create subscription '{name}'")

    def delete(self, sub_id: str) -> None:
        """Delete a subscription by ID."""
        self._client._call("delete_subscription", [sub_id])

    def toggle(self, sub_id: str, is_active: bool) -> None:
        """Enable or disable a subscription."""
        self._client._call("toggle_subscription", [sub_id, is_active])

    def list(self, workspace_id: str) -> list[ManagedSubscription]:
        """List subscriptions for a workspace."""
        rows = self._client._sql(
            f"SELECT * FROM subscriptions WHERE workspace_id = {_q(workspace_id)}"
        )
        return [ManagedSubscription.from_dict(r) for r in rows]

    def list_all(self) -> list[ManagedSubscription]:
        """List all subscriptions across all workspaces."""
        rows = self._client._sql("SELECT * FROM subscriptions")
        return [ManagedSubscription.from_dict(r) for r in rows]
