"""Example logger plugin for spacetime-memory.

Logs all memory operations and connector events to the console
with timestamps and coloured output when possible.
"""

from __future__ import annotations

import datetime
import sys

from spacetime_memory.plugin_manager import SpacetimePlugin


class ExampleLoggerPlugin(SpacetimePlugin):
    """Logs memory operations to stdout/stderr."""

    name = "example_logger"
    version = "1.0.0"
    description = "Logs all memory operations and connector events to the console"

    def on_load(self, client) -> None:
        """Print a startup banner."""
        self._client = client
        print(
            f"[example_logger] Plugin loaded — logging all memory operations.",
            file=sys.stderr,
        )

    def on_unload(self) -> None:
        """Print a shutdown message."""
        print(
            f"[example_logger] Plugin unloaded.",
            file=sys.stderr,
        )

    def on_memory_stored(self, memory) -> None:
        """Log stored memory details."""
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        mid = memory.get("id", "?") if isinstance(memory, dict) else "?"
        content = (
            memory.get("content", "")[:120]
            if isinstance(memory, dict)
            else str(memory)[:120]
        )
        print(
            f"[example_logger] {ts} MEMORY STORED  id={mid}  content={content!r}",
            file=sys.stderr,
        )

    def on_memory_retrieved(self, memory) -> None:
        """Log retrieved memory details."""
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        mid = memory.get("id", "?") if isinstance(memory, dict) else "?"
        content = (
            memory.get("content", "")[:120]
            if isinstance(memory, dict)
            else str(memory)[:120]
        )
        print(
            f"[example_logger] {ts} MEMORY RETRIEVED  id={mid}  content={content!r}",
            file=sys.stderr,
        )

    def on_connector_event(self, event) -> None:
        """Log connector event details."""
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        ev_type = type(event).__name__
        content = (
            event.content[:120]
            if hasattr(event, "content")
            else str(event)[:120]
        )
        print(
            f"[example_logger] {ts} CONNECTOR EVENT  type={ev_type}  content={content!r}",
            file=sys.stderr,
        )
