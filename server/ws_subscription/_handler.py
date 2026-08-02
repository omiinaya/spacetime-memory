"""STDB change-detection client and utility functions for ws_subscription."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets

from spacetime_memory import Client
from spacetime_memory.delta_sync import ChangeEvent

logger = logging.getLogger("ws_subscription")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STDB_CONTENT_TABLES = frozenset({
    "memory", "kg_node", "kg_edge", "note", "profile", "document",
})


# ---------------------------------------------------------------------------
# _decode_row — convert STDB row data to JSON strings
# ---------------------------------------------------------------------------


def _decode_row(data: Any) -> str:
    """Convert an STDB row data value to a JSON string.

    Handles three cases:
    1. Base64-encoded string — decode and return as-is
    2. Dict — re-serialize as JSON
    3. Plain string — return unchanged
    """
    if isinstance(data, str):
        # Try base64 decode with validation to reject
        # non-base64 characters like '!' which b64decode otherwise
        # silently ignores, producing empty bytes.
        try:
            import base64
            import binascii
            decoded = base64.b64decode(data, validate=True).decode("utf-8")
            return decoded
        except (ValueError, binascii.Error):
            return data
    if isinstance(data, dict):
        return json.dumps(data)
    if isinstance(data, bytes):
        return data.decode("utf-8")
    return str(data)


# ---------------------------------------------------------------------------
# event_to_dict — convert a ChangeEvent to a plain dict
# ---------------------------------------------------------------------------


def event_to_dict(event: ChangeEvent) -> dict[str, Any]:
    """Convert a ChangeEvent dataclass to a plain dict."""
    return {
        "id": event.id,
        "workspace_id": event.workspace_id,
        "table_name": event.table_name,
        "operation": event.operation,
        "record_id": event.record_id,
        "data_json": event.data_json,
        "created_at": event.created_at,
    }


# ---------------------------------------------------------------------------
# StdbSubscriptionClient — WebSocket client for STDB subscription updates
# ---------------------------------------------------------------------------


class StdbSubscriptionClient:
    """WebSocket client that connects to the STDB subscription endpoint.

    Receives TransactionUpdate messages via WebSocket and dispatches
    change events to registered callbacks.  Complements the polling-based
    ``DeltaSync`` with a push-based model.

    Args:
        uri: WebSocket server URI.
        on_changes: Optional callback receiving a list of ``ChangeEvent``.
    """

    def __init__(
        self,
        on_changes: Any | None = None,
        stdb_uri: str | None = None,
        stdb_host: str = "127.0.0.1",
        stdb_port: int = 3001,
        stdb_database: str = "",
        poll_interval: float = 0.1,
    ) -> None:
        self._stdb_uri = stdb_uri
        self._on_changes = on_changes
        self._stdb_host = stdb_host
        self._stdb_port = stdb_port
        self._stdb_database = stdb_database
        self._poll_interval = poll_interval
        self._push_mode = stdb_uri is not None and stdb_uri != ""
        self._connected = False
        self._running = False
        self._task: asyncio.Task | None = None
        self._ws: Any = None
        self._http_client: Any = None
        self._cursor: int = 0
        self._subscribe_queries = [
            f"SELECT * FROM {t}"
            for t in sorted(_STDB_CONTENT_TABLES)
        ]

    async def start(self) -> None:
        """Start the change-detection loop."""
        if self._running:
            return
        self._running = True
        self._connected = False
        self._http_client = None
        self._cursor = 0

        if self._push_mode:
            self._task = asyncio.create_task(self._run_push(), name="stdb-sub-push")
        else:
            self._task = asyncio.create_task(self._run_poll(), name="stdb-sub-poll")

    def stop(self) -> None:
        """Disconnect and stop the loop."""
        self._running = False
        self._connected = False
        if self._task:
            self._task.cancel()
            self._task = None
        self._http_client = None

    # ------------------------------------------------------------------
    # Push mode -- STDB native WebSocket subscription
    # ------------------------------------------------------------------

    async def _run_push(self) -> None:
        """Push mode: connect to STDB WS endpoint and receive TransactionUpdates."""
        try:
            async with websockets.connect(self._stdb_uri) as ws:
                self._ws = ws
                self._connected = True
                logger.info(
                    "Connected to STDB subscription endpoint: %s",
                    self._stdb_uri,
                )

                # Wait for IdentityToken
                identity = await asyncio.wait_for(ws.recv(), timeout=10)
                logger.debug("Received IdentityToken from STDB")

                # Send subscribe queries for all content tables
                subscribe_payload: list[dict[str, Any]] = [
                    {"subscribe": {"query_strings": self._subscribe_queries}}
                ]
                await ws.send(json.dumps(subscribe_payload))
                logger.info(
                    "Subscribed to %d tables via STDB WS",
                    len(self._subscribe_queries),
                )

                # Read SubscriptionUpdate (initial data snapshot -- discard)
                try:
                    initial = await asyncio.wait_for(ws.recv(), timeout=10)
                    logger.debug("Received SubscriptionUpdate (initial data, discarded)")
                except asyncio.TimeoutError:
                    logger.debug("No SubscriptionUpdate received")

                # Read TransactionUpdates (ongoing changes)
                async for raw in ws:
                    await self._handle_message(raw)

        except asyncio.CancelledError:
            pass
        except websockets.ConnectionClosed:
            logger.warning("STDB subscription WebSocket closed")
        except OSError as e:
            logger.warning("STDB subscription WebSocket connection failed: %s", e)
        except Exception as e:
            logger.debug("STDB subscription push error: %s", e)
        finally:
            self._connected = False
            self._ws = None
            # Auto-reconnect in poll mode if push fails
            if self._running and self._push_mode:
                logger.info(
                    "STDB WS unavailable, falling back to poll mode "
                    "(reconnect in %.1fs)",
                    self._poll_interval,
                )
                self._push_mode = False
                self._task = asyncio.create_task(
                    self._run_poll(), name="stdb-sub-poll"
                )

    # ------------------------------------------------------------------
    # Poll mode -- HTTP-based change polling (fallback)
    # ------------------------------------------------------------------

    async def _run_poll(self) -> None:
        """Poll mode: periodically poll STDB for change events."""
        # Lazy-init HTTP client (avoid STDB connection in tests)
        if self._http_client is None:
            self._http_client = Client(
                host=self._stdb_host,
                port=self._stdb_port,
                database=self._stdb_database,
            )

        # Bootstrap cursor
        try:
            self._cursor = await self._bootstrap_cursor()
        except Exception as e:
            logger.warning("Bootstrap cursor failed, starting at 0: %s", e)

        while self._running:
            try:
                await asyncio.sleep(self._poll_interval)
                events = await self._fetch_changes()
                if events:
                    for event in events:
                        self._cursor = max(self._cursor, event.created_at)
                    if self._on_changes:
                        merged = StdbSubscriptionClient._merge_update_pairs(events)
                        await self._on_changes(merged)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Poll error: %s", e)

    async def _bootstrap_cursor(self) -> int:
        """Get the initial change cursor from STDB."""
        assert self._http_client is not None
        self._http_client._call("get_latest_change_cursor", [])
        rows = self._http_client._sql(
            "SELECT events_json FROM change_event_result "
            "WHERE since_cursor = 0 ORDER BY created_at DESC LIMIT 1"
        )
        if rows:
            data = json.loads(rows[0]["events_json"]) if isinstance(rows[0]["events_json"], str) else rows[0]["events_json"]
            return int(data.get("cursor", 0))
        return 0

    async def _fetch_changes(self) -> list[ChangeEvent]:
        """Fetch change events since the current cursor."""
        from spacetime_memory.delta_sync import ChangeEvent

        assert self._http_client is not None
        self._http_client._call("get_changes_since", [self._cursor])
        rows = self._http_client._sql_param(
            "SELECT events_json FROM change_event_result "
            "WHERE since_cursor = ? ORDER BY created_at DESC LIMIT 1",
            self._cursor,
        )
        if not rows:
            return []
        raw = rows[0].get("events_json", "[]")
        if not raw:
            return []
        raw_list = json.loads(raw) if isinstance(raw, str) else raw
        return [ChangeEvent.from_dict(e) for e in raw_list]

    # ------------------------------------------------------------------
    # Message handling (push mode)
    # ------------------------------------------------------------------

    async def _handle_message(self, raw: str) -> None:
        """Parse an incoming WebSocket message."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        # Handle IdentityToken messages
        if "IdentityToken" in msg:
            return

        # Handle SubscriptionUpdate (initial data sync)
        if "SubscriptionUpdate" in msg:
            return

        # Handle TransactionUpdate (ongoing changes)
        if isinstance(msg, dict) and "subscription_update" in msg.get("SubscriptionUpdate", msg):
            tx_update = msg.get("SubscriptionUpdate", msg)
            if "subscription_update" in tx_update:
                tx_update = tx_update["subscription_update"]
            await self._handle_transaction(tx_update)
        elif "subscription_update" in msg or "table_updates" in msg.get("subscription_update", {}):
            await self._handle_transaction(msg)

    async def _handle_transaction(self, tx: dict[str, Any]) -> None:
        """Process a TransactionUpdate payload.

        Extracts change events from table_updates and fires the
        on_changes callback with merged events.
        """
        if self._on_changes is None:
            return

        # Unwrap subscription_update envelope if present (STDB protocol sends
        # TransactionUpdate with a "subscription_update" wrapper key)
        if "subscription_update" in tx:
            tx = tx["subscription_update"]

        table_updates = tx.get("table_updates", [])
        if not table_updates:
            return

        from spacetime_memory.delta_sync import ChangeEvent

        events: list[ChangeEvent] = []
        for table_update in table_updates:
            table_name = table_update.get("table_name", "")
            if table_name not in _STDB_CONTENT_TABLES:
                continue

            for row_op in table_update.get("table_row_operations", []):
                op = row_op.get("op", "")
                row_pk = row_op.get("row_pk", "")
                row_data = row_op.get("row", "{}")
                data_str = _decode_row(row_data) if isinstance(row_data, (str, dict, bytes)) else str(row_data)
                # Extract workspace_id from decoded row data
                workspace_id = self._extract_workspace_id(data_str)

                event = ChangeEvent(
                    id=f"{table_name}:{row_pk}:{op}",
                    workspace_id=workspace_id,
                    table_name=table_name,
                    operation=op,
                    record_id=row_pk,
                    data_json=data_str,
                    created_at=0,
                )
                events.append(event)

        if events:
            merged = self._merge_update_pairs(events)
            await self._on_changes(merged)

    @staticmethod
    def _extract_workspace_id(data_json: str) -> str:
        """Extract workspace_id from a row's JSON data string."""
        if not data_json or data_json == "{}":
            return "*"
        try:
            data = json.loads(data_json)
            if isinstance(data, dict):
                ws = data.get("workspace_id")
                if ws is not None and ws != "":
                    return str(ws)
        except (json.JSONDecodeError, TypeError):
            pass
        return "*"

    @staticmethod
    def _merge_update_pairs(events: list[Any]) -> list[Any]:
        """Merge adjacent delete+insert pairs for the same record into updates.

        STDB often emits a delete followed by an insert when a row is updated.
        This method collapses those pairs into a single 'update' event.
        """
        if not events:
            return []
        if len(events) == 1:
            return events

        result: list[Any] = []
        skip: set[int] = set()

        for i in range(len(events) - 1):
            if i in skip:
                continue
            curr = events[i]
            nxt = events[i + 1]

            if (
                curr.operation == "delete"
                and nxt.operation == "insert"
                and curr.record_id == nxt.record_id
                and curr.table_name == nxt.table_name
            ):
                # Merge into a single update event
                from spacetime_memory.delta_sync import ChangeEvent
                merged = ChangeEvent(
                    id=nxt.id,
                    workspace_id=nxt.workspace_id,
                    table_name=nxt.table_name,
                    operation="update",
                    record_id=nxt.record_id,
                    data_json=nxt.data_json,
                    created_at=nxt.created_at,
                )
                result.append(merged)
                skip.add(i)
                skip.add(i + 1)
            else:
                result.append(curr)

        # Last item
        if len(events) - 1 not in skip:
            result.append(events[-1])

        return result
