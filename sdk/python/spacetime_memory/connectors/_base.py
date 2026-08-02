"""Sync connector base class for spacetime-memory.

``connectors._base`` defines the **base class** for all sync connectors
— classes that actively *poll* external data sources and persist events
as memories or KG nodes.

The base class is ``SyncConnector`` (not ``Connector``).  The old
``Connector`` name is kept as a backward-compatible alias but is deprecated
— new code should use ``SyncConnector`` to make the polling intent unambiguous.

This is *not* a **parity adapter**.  Parity adapters live in
``spacetime_memory.sdks`` (Mem0, Zep, Graphiti, Honcho, LangChain, Hindsight)
and provide drop-in API compatibility without polling.  The ``connectors``
package is for sync connectors only; if you want parity adapters, look in
``sdks/`` instead.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._types import Event

import httpx

logger = logging.getLogger(__name__)


# ── SyncConnector base ──────────────────────────────────────────────


class SyncConnector(ABC):
    """Base class for all spacetime-memory **sync connectors**.

    A sync connector actively polls an external data source and persists
    results as memories or KG nodes.  This is distinct from a **parity
    adapter** (``spacetime_memory.sdks``, e.g. Mem0, Zep, Graphiti),
    which provides API compatibility without polling.

    Subclasses must implement ``poll()``, which should yield ``Event``
    objects.  The framework calls ``on_event()`` to persist each event
    as either a memory or a KG node.

    Production features (built into the base class):

    *   **Logging** — each connector gets a ``self._log`` logger named
        ``connector.<ClassName>``.  Call ``self._log.info()``,
        ``self._log.warning()``, ``self._log.error()`` instead of
        ``print()``.
    *   **Retry with backoff** — call
        ``self._retry_client_call(client, \"get\", url, ...)`` instead of
        ``client.get(url, ...)`` to get automatic exponential backoff
        with jitter on transient HTTP errors.
    *   **Persistent cursors** — each connector has a JSON cursor file
        at ``~/.spacetime-memory/connectors/<ClassName>_cursor.json``.
        Use ``self._cursor`` to read/write state that survives restarts.
    *   **Health reporting** — ``self.last_status()`` returns the
        connector's current health.  ``ConnectorRegistry.get_health()``
        aggregates health for all registered connectors.
    """

    def __init__(self, *, cursor_dir: str | None = None) -> None:
        # ── Logging ────────────────────────────────────────────────
        self._log = logging.getLogger(f"connector.{type(self).__name__}")

        # ── Health tracking ────────────────────────────────────────
        self._last_poll_time: float = 0.0
        self._error_count: int = 0
        self._last_status: str = "ok"

        # ── Persistent cursor store ────────────────────────────────
        self._cursor_dir = cursor_dir or os.path.expanduser("~/.spacetime-memory/connectors")
        os.makedirs(self._cursor_dir, exist_ok=True)
        self._cursor_file = os.path.join(self._cursor_dir, f"{type(self).__name__}_cursor.json")
        self._cursor: dict[str, Any] = {}
        self._load_cursor()

    # ── Cursor persistence ──────────────────────────────────────────

    def _load_cursor(self) -> None:
        """Restore cursor state from the JSON file on disk."""
        if os.path.exists(self._cursor_file):
            try:
                with open(self._cursor_file, "r") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._cursor = data
                        self._log.info(
                            "Loaded cursor from %s (%d keys)",
                            self._cursor_file,
                            len(self._cursor),
                        )
                    else:
                        self._cursor = {}
            except (json.JSONDecodeError, OSError) as e:
                self._log.warning(
                    "Failed to load cursor from %s: %s",
                    self._cursor_file,
                    e,
                )
                self._cursor = {}
        else:
            self._cursor = {}

    def _save_cursor(self) -> None:
        """Persist cursor state to the JSON file on disk."""
        try:
            with open(self._cursor_file, "w") as f:
                json.dump(self._cursor, f, indent=2)
        except OSError as e:
            self._log.warning(
                "Failed to save cursor to %s: %s",
                self._cursor_file,
                e,
            )

    # ── Retry with exponential backoff + jitter ─────────────────────

    def _retry_client_call(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        *,
        max_retries: int = 3,
        base_delay: float = 1.0,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make an HTTP call with retry on transient errors.

        Retries on ``httpx.RequestError`` (connection errors, timeouts)
        with exponential backoff ``base_delay * 2^attempt`` plus random
        jitter (0–100 ms) to avoid thundering-herd effects.

        Does **not** retry on HTTP 4xx status codes — those are treated
        as client errors that should be handled by the caller.

        Args:
            client: An ``httpx.Client`` instance.
            method: HTTP method name (``\"get\"``, ``\"post\"``, etc.).
            url: Request URL.
            max_retries: Maximum number of attempts (default 3).
            base_delay: Initial delay in seconds (default 1.0).
            **kwargs: Extra arguments forwarded to ``client.method()``.

        Returns:
            The ``httpx.Response`` from the successful attempt.

        Raises:
            httpx.RequestError: If all retries are exhausted.
        """
        for attempt in range(max_retries):
            try:
                resp = getattr(client, method)(url, **kwargs)
                # Raise-for-status is NOT called automatically — the
                # caller inspects resp.status_code for their own logic.
                # We only retry on transport-level errors here.
                return resp
            except httpx.RequestError as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt) + random.uniform(0, 0.1)
                    self._log.warning(
                        "%s %s failed (attempt %d/%d): %s. Retrying in %.2fs …",
                        method.upper(),
                        url,
                        attempt + 1,
                        max_retries,
                        e,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    self._log.error(
                        "%s %s failed after %d retries: %s",
                        method.upper(),
                        url,
                        max_retries,
                        e,
                    )
                    raise

        # Keep the type-checker happy — loop always returns or raises above.
        raise RuntimeError("unreachable")

    # ── Health reporting ────────────────────────────────────────────

    def last_status(self) -> dict[str, Any]:
        """Return the connector's current health status.

        Returns:
            A dict with keys ``status`` (``\"ok\"`` | ``\"error\"``),
            ``last_poll`` (Unix timestamp or ``0.0`` if never polled),
            and ``errors_since_last_ok`` (integer count).
        """
        return {
            "status": self._last_status,
            "last_poll": self._last_poll_time,
            "errors_since_last_ok": self._error_count,
        }

    # ── Abstract interface ──────────────────────────────────────────

    @abstractmethod
    def poll(self) -> list[Event]:
        """Fetch new data from the external source.

        Returns a list of ``Event`` objects.  The framework calls
        ``on_event()`` for each one.  Call repeatedly to get new data.
        """
        ...

    def on_event(self, event: Event, client: Any) -> None:
        """Default handler: store the event's content as a memory.

        Override to customise (e.g. create KG nodes instead).
        Always called from within the run loop.
        """
        client.store(
            workspace_id=event.workspace_id,
            content=event.content,
            summary=event.summary or event.content[:200],
            memory_type=event.memory_type or "experience",
            peer_id=event.peer_id or "connector",
            source_session_id=event.session_id or "",
        )

    def run(
        self,
        client: Any,
        *,
        interval_secs: int = 300,
        max_per_tick: int = 10,
        stop_after: int | None = None,
    ) -> None:
        """Continuous poll loop.

        Args:
            client: A ``spacetime_memory.Client`` instance.
            interval_secs: Seconds between polls.
            max_per_tick: Max events to process per poll.
            stop_after: If set, run this many ticks then return.
        """
        ticks = 0
        while stop_after is None or ticks < stop_after:
            self._last_poll_time = time.time()
            try:
                events = self.poll()[:max_per_tick]
                for ev in events:
                    try:
                        self.on_event(ev, client)
                    except Exception as e:
                        self._log.error("Event handler error: %s", e)
                        self._error_count += 1
                if events:
                    self._log.info("Polled %d events", len(events))
                self._last_status = "ok"
            except Exception as e:
                self._log.error("Poll error: %s", e)
                self._last_status = "error"
                self._error_count += 1

            ticks += 1
            if stop_after is not None and ticks >= stop_after:
                break
            time.sleep(interval_secs)

        self._save_cursor()


# ── Backward-compatible alias ──────────────────────────────────────

Connector = SyncConnector
"""Deprecated alias for :class:`SyncConnector`.

Use ``SyncConnector`` in new code to make the sync-polling intent clear.
"""
