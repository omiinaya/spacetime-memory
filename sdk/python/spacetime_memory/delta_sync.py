"""Real-time delta sync gateway for spacetime-memory.

Poll the ``change_event`` table at high frequency and dispatch callbacks
to local subscribers.  Supports per-table, per-operation callbacks.

Usage::

    client = Client(...)
    ds = DeltaSync(client, poll_interval=0.1)

    # Register callbacks
    token = ds.on("memory", "insert", lambda event: print(f"New memory: {event}"))
    ds.on("kg_node", "*", lambda event: print(f"Graph change: {event}"))

    # Start polling (background thread)
    ds.start()

    # Later...
    ds.off(token)
    ds.stop()
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ChangeEvent:
    """A single change event from the STDB change_event table."""

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
        return json.loads(self.data_json)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChangeEvent:
        return cls(
            id=d["id"],
            workspace_id=d.get("workspace_id", ""),
            table_name=d.get("table_name", ""),
            operation=d.get("operation", ""),
            record_id=d.get("record_id", ""),
            data_json=d.get("data_json", "{}"),
            created_at=int(d.get("created_at", 0)),
        )


# ---------------------------------------------------------------------------
# DeltaSync
# ---------------------------------------------------------------------------


class DeltaSync:
    """Poll the ``change_event`` table and dispatch callbacks.

    Args:
        client: A ``Client`` instance connected to the STDB module.
        poll_interval: Seconds between polls (default 0.1 = 100ms).
        auto_start: Start polling immediately on init.
    """

    def __init__(
        self,
        client: Any,  # Client, imported lazily to avoid circular dep
        poll_interval: float = 0.1,
        auto_start: bool = False,
    ):
        self._client = client
        self._poll_interval = max(0.01, poll_interval)
        self._cursor: int = 0
        self._callbacks: dict[tuple[str, str], list[tuple[object, Callable[[Any], None]]]] = {}
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._polls: int = 0
        self._errors: int = 0

        if auto_start:
            self.start()

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def on(
        self,
        table: str,
        operation: str = "*",
        callback: Callable[[Any], None] = None,
    ) -> object:
        """Register a callback for change events.

        Args:
            table: Table name (``"memory"``, ``"kg_node"``, ``"kg_edge"``,
                   or ``"*"`` for all tables).
            operation: Operation (``"insert"``, ``"update"``, ``"delete"``,
                      or ``"*"`` for all operations).
            callback: Callable taking a ``ChangeEvent``.

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
                self._callbacks[key] = [(t, cb) for t, cb in self._callbacks[key] if t is not token]
                if not self._callbacks[key]:
                    del self._callbacks[key]

    def start(self) -> None:
        """Start polling in a daemon background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="delta-sync",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "DeltaSync started (interval=%.3fs)",
            self._poll_interval,
        )

    def stop(self) -> None:
        """Stop polling and wait for the thread to exit."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

    @property
    def stats(self) -> dict[str, Any]:
        """Return current polling stats."""
        return {
            "running": self._running,
            "cursor": self._cursor,
            "polls": self._polls,
            "errors": self._errors,
            "poll_interval": self._poll_interval,
            "callbacks": sum(len(v) for v in self._callbacks.values()),
        }

    # -------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------

    def _poll_loop(self) -> None:
        """Main polling loop — runs in background thread."""
        # Bootstrap: get initial cursor
        try:
            self._cursor = self._get_initial_cursor()
        except Exception as e:
            logger.warning("DeltaSync bootstrap failed: %s", e)
            self._cursor = 0

        while self._running:
            try:
                events = self._fetch_changes()
                if events:
                    for event in events:
                        self._dispatch(event)
                    # Update cursor to the last event's timestamp
                    self._cursor = events[-1].created_at
                self._polls += 1
            except Exception as e:
                self._errors += 1
                logger.debug("DeltaSync poll error: %s", e)
            time.sleep(self._poll_interval)

    def _get_initial_cursor(self) -> int:
        """Call ``get_latest_change_cursor`` reducer and return the cursor."""
        client = self._client
        client._call("get_latest_change_cursor", [])
        rows = client._query(
            "change_event_result",
            filter_dict={"since_cursor": 0},
            columns=["events_json"],
        )
        if rows:
            rows.sort(key=lambda r: r.get("created_at", 0) or 0, reverse=True)
            rows = rows[:1]
        if rows:
            data = json.loads(rows[0].get("events_json", "{}"))
            return int(data.get("cursor", 0))
        return 0

    def _fetch_changes(self) -> list[ChangeEvent]:
        """Call ``get_changes_since`` and parse results."""
        client = self._client
        client._call("get_changes_since", [self._cursor])
        rows = client._query(
            "change_event_result",
            filter_dict={"since_cursor": self._cursor},
            columns=["events_json"],
        )
        if rows:
            rows.sort(key=lambda r: r.get("created_at", 0) or 0, reverse=True)
            rows = rows[:1]
        if not rows:
            return []
        raw = rows[0].get("events_json", "[]")
        if not raw:
            return []
        raw_list = json.loads(raw) if isinstance(raw, str) else raw
        return [ChangeEvent.from_dict(e) for e in raw_list]

    def _dispatch(self, event: ChangeEvent) -> None:
        """Dispatch a single event to all matching callbacks."""
        with self._lock:
            # Collect matching callbacks under the lock
            matched: list[Callable[[Any], None]] = []
            for (table, operation), cbs in self._callbacks.items():
                if table == "*" or table == event.table_name:
                    if operation == "*" or operation == event.operation:
                        for _, cb in cbs:
                            matched.append(cb)

        # Dispatch outside the lock to avoid deadlocks
        for cb in matched:
            try:
                cb(event)
            except Exception as e:
                logger.exception("DeltaSync callback error: %s", e)
